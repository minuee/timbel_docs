import convert from '../../utils/convert/index.js';
import searchService from '../system/search.service.js';
import generate from '../../utils/generate.util.js';
import attendeeService from './features/attendee.service.js';
import contentModel from '../../models/content.model.js';
import bookmarkModel from '../../models/bookmark.model.js';
import { isAfter, isSame } from '../../utils/date.util.js';
import { HttpError } from '../../handlers/error.handler.js';
import lifecycleModel from '../../models/lifecycle.model.js';
import memoService from './features/memo.service.js';

const allowedKeys = [
	'type',
	'title',
	'isMobile',
	'isRecord',
	'contentId',
	'shareUsers',
	'permission',
	'creatorPID',
	'editedTitle',
	'lastUpdator',
	'clientLanguage',
	'meetingEndTime',
	'linkedContents',
	'meetingStartTime',
	'isTimeChangeNeeded',
];

const isSingleTabs = (tabs, type = 'file') => {
	return tabs.includes(type) && tabs.length === 1;
};

const isEmptyTabs = tabs => {
	return !tabs.length;
};

const isTargetTab = (tabs, target) => {
	return tabs.includes(target);
};

// STT_DONE, RE_SUMMARY_RUNNING 전용
const createResponseDataForSegments = (mongoDBcontent, mariaDBContent) => {
	const { clientLanguage, ...restMongoDBContent } = mongoDBcontent;
	const metaFromMaria = pick(mariaDBContent, allowedKeys);
	// shareUsers, permission, isTimeChangeNeeded 제외
	const meta = { clientLanguage, ...metaFromMaria };
	return { ...restMongoDBContent, meta };
};

const checkTranscribeCompleted = ({ transcribeStatus, fileName, contentId }) => {
	if (!['ERROR', 'CANCEL', 'DONE'].includes(transcribeStatus))
		throw new HttpError(1114, { status: transcribeStatus });

	if (transcribeStatus === 'ERROR' || transcribeStatus === 'CANCEL')
		throw new HttpError(1119, { status: transcribeStatus, fileName, contentId });
};

const checkRecycleContent = ({ isRecycle, isDeleted }) => {
	if (isRecycle && !isDeleted) throw new HttpError(1111);
	if (isDeleted) throw new HttpError(1115);
};

const tabsTransform = (tabs, file, mongoDBcontent, bookmarks, memos) => {
	if (isEmptyTabs(tabs)) {
		mongoDBcontent.file = file;
		mongoDBcontent.bookmarks = bookmarks || [];
		mongoDBcontent.memos = memos || [];
	} else {
		if (isTargetTab(tabs, 'bookmarks')) mongoDBcontent.bookmarks = bookmarks || [];
		if (isTargetTab(tabs, 'file')) mongoDBcontent.file = file;
		if (isTargetTab(tabs, 'memos')) mongoDBcontent.memos = memos || [];
	}
};

const updateMeetingTime = async mariaDBContent => {
	if (!mariaDBContent?.meetingEndTime || !mariaDBContent?.meetingStartTime) {
		const { endTime, startTime } = generate.meetingTime(mariaDBContent);
		mariaDBContent = await contentModel.updateContent(
			{ contentId: mariaDBContent.contentId },
			{ meetingEndTime: endTime, meetingStartTime: startTime }
		);
	}
};

const updateMergedSegments = (mongoDBcontent, file) => {
	if (mongoDBcontent?.mergedSegments?.length === 0) {
		mongoDBcontent.mergedSegments = convert.createMergedSegments({ segments: mongoDBcontent.segments });
		contentModel.updateMergedSegments(file.id, mongoDBcontent.mergedSegments);
	}
};

const transformLinkedContents = async ({ linkedContents = [] }) => {
	const transformedLinkedContents = await Promise.all(
		linkedContents.map(async ({ linkedContent: { editor, isRecycle, isDeleted, ...restLinkedContent } }) => {
			const { contentId } = restLinkedContent;
			if (isRecycle || isDeleted) return null;

			const [{ transcribeResult }, contentLifecycleActions, shareUsers] = await Promise.all([
				await contentModel.findFileByContentId(contentId, getFileIncludeOptions(['segments', 'speakerInfo'])),
				getContentLifecycle(contentId),
				contentModel.getThumbnails([contentId]),
			]);
			const { mergedSegments, speakerInfo } = transcribeResult;

			const lastUpdator = editor.user.profile.nickName;
			return {
				...restLinkedContent,
				lastUpdator,
				speakerInfo,
				shareUsers,
				mergedSegments,
				contentLifecycleActions,
			};
		})
	);
	return transformedLinkedContents;
};

// 구 노트 호환: 신규 요약탭은 aiResult.templateSummary(마크다운)만 렌더한다. 템플릿 도입 이전 노트는
// 이 필드가 없어 요약탭이 비어 보이므로, 레거시 구조화 필드(summary/topics/issues/tasks/summaryTime)로
// 마크다운을 즉석 합성해 채운다(읽기 시점 어댑터, 원본 데이터 미변경). keywords는 KeywordBlock이 별도 렌더.
const legacyItemText = item => (typeof item === 'string' ? item : (item && item.content) || '');
const legacyBullets = (arr = []) =>
	(Array.isArray(arr) ? arr : [])
		.map(legacyItemText)
		.map(t => (t || '').trim())
		.filter(Boolean)
		.map(t => `- ${t}`)
		.join('\n');

const buildLegacyTemplateSummary = (aiResult = {}, summaryTime = []) => {
	const sections = [];
	const push = (heading, body) => {
		if (body && body.trim()) sections.push(`## ${heading}\n${body}`);
	};

	push('핵심 요약', legacyBullets(aiResult.summary));
	push('주제', legacyBullets(aiResult.topics));
	push('이슈', legacyBullets(aiResult.issues));
	push('할 일', legacyBullets(aiResult.tasks));

	if (Array.isArray(summaryTime) && summaryTime.length > 0) {
		const blocks = summaryTime
			.map(item => {
				const topic = (item?.topic || '').trim() || '(제목 없음)';
				const time = (item?.time || '').trim();
				const heading = time ? `${topic} (${time})` : topic;
				const details = legacyBullets(item?.summary);
				return details ? `### ${heading}\n${details}` : '';
			})
			.filter(Boolean)
			.join('\n\n');
		push('주제별 상세 요약', blocks);
	}

	return sections.join('\n\n');
};

const ensureLegacyTemplateSummary = mongoDBcontent => {
	const aiResult = mongoDBcontent?.aiResult;
	if (!aiResult || typeof aiResult !== 'object') return;
	if (aiResult.templateSummary) return; // 신규 템플릿 노트는 그대로 사용
	const markdown = buildLegacyTemplateSummary(aiResult, mongoDBcontent.summaryTime);
	if (markdown) aiResult.templateSummary = markdown;
};

const postProcessResponse = async (mongoDBcontent, mariaDBContent, file) => {
	ensureLegacyTemplateSummary(mongoDBcontent);

	if (mariaDBContent.type === 'MERGED_CONTENT') {
		mariaDBContent.linkedContents = await transformLinkedContents(mariaDBContent);
		return;
	}

	if (mongoDBcontent?.speakerInfo) await attendeeService.matchProfileBySpeakerInfo(mongoDBcontent.speakerInfo);

	updateMergedSegments(mongoDBcontent, file);
	await updateMeetingTime(mariaDBContent);

	if (isAfter(mariaDBContent.updateAt, file.updateAt)) file.updateAt = mariaDBContent.updateAt;
	mongoDBcontent.aiResult.manualTag = mariaDBContent.manualTag;
};

const pick = obj => {
	return allowedKeys.reduce((result, key) => {
		if (key in obj) result[key] = obj[key];
		return result;
	}, {});
};

const createResponseData = (mongoDBcontent, mariaDBContent, permission, shareUsers) => {
	const { clientLanguage, ...restMongoDBContent } = mongoDBcontent;

	const metaFromMaria = pick(mariaDBContent, allowedKeys);
	const meta = {
		shareUsers,
		permission,
		clientLanguage,
		...metaFromMaria,
		isTimeChangeNeeded: isSame(mariaDBContent.meetingStartTime, mariaDBContent.createAt),
	};

	return { ...restMongoDBContent, meta };
};

const getFileIncludeOptions = tabs => {
	const select = { status: true, clientLanguage: true, summarySize: true };

	const tabActions = {
		aiResult: () => {
			select.aiResult = true;
			select.speakerInfo = true;
		},
		speakerInfo: () => {
			select.speakerInfo = true;
		},
		summaryTime: () => {
			select.summaryTime = true;
		},
		segments: () => {
			select.mergedSegments = true;
			// select.segments = true;
		},
	};

	if (tabs.length === 0) {
		Object.values(tabActions).forEach(action => action());
	} else {
		tabs.forEach(tab => {
			if (tabActions[tab]) {
				tabActions[tab]();
			}
		});
	}
	return {
		highlights: true,
		transcribeResult: { select },
	};
};

const getContentLifecycle = async contentId => {
	const result = await lifecycleModel.getContentLifecycle(contentId);
	if (result.length === 0) return [];
	return result.map(item => ({
		type: item.targetType,
		value: item.policyValue,
		unit: item.policyUnit,
	}));
};

const getContentDetail = async ({ pid, permission }, contentId, { source, tabs }) => {
	let {
		transcribeResult,
		highlights = [],
		...file
	} = await contentModel.findFileByContentId(contentId, getFileIncludeOptions(tabs));
	if (!file) throw new HttpError(1122);
	if (isSingleTabs(tabs, 'file')) return { file };

	let [[mariaDBContent, shareUsers], bookmarks, memos, contentLifecycleActions] = await Promise.all([
		contentModel.getContentDetail(contentId),
		bookmarkModel.getBookmarksByContentId(contentId),
		memoService.getMemosByContentId(contentId, pid),
		getContentLifecycle(contentId),
	]);

	if (!transcribeResult || !mariaDBContent) throw new HttpError(1121);
	if (['STT_DONE', 'RE_SUMMARY_RUNNING'].includes(transcribeResult.status)) {
		return createResponseDataForSegments(transcribeResult, mariaDBContent);
	}
	checkTranscribeCompleted(mariaDBContent);
	checkRecycleContent(mariaDBContent);

	if (isSingleTabs(tabs, 'bookmarks')) {
		transcribeResult.bookmarks = bookmarks || [];
		return { bookmarks: transcribeResult.bookmarks };
	}

	if (isSingleTabs(tabs, 'memos')) {
		transcribeResult.memos = memos || [];
		return { memos: transcribeResult.memos };
	}

	if (source === 'search' && !tabs.length) searchService.upsertContentViewedHistoryBySearching(pid, contentId);

	tabsTransform(tabs, file, transcribeResult, bookmarks, memos);
	await postProcessResponse(transcribeResult, mariaDBContent, file);
	return {
		...createResponseData(transcribeResult, mariaDBContent, permission, shareUsers),
		highlights,
		contentLifecycleActions,
	};
};

export default getContentDetail;
