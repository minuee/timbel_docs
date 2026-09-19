import noteService from '../content/features/note.service.js';
import usageModel from '../../models/usage.model.js';
import summarize from '../../utils/summarizer/index.js';
import TranscribeUtil from '../../utils/transcribe.util.js';
import highlightModel from '../../models/highlight.model.js';
import historyModel from '../../models/reSummaryHistory.model.js';
import bookmarkModel from '../../models/bookmark.model.js';
import contentCaptureService from '../content/contentCapture.service.js';

// 재요약 시 재생성되는 AI요약 파생 북마크 key. 전사 기반(segments/mergedSegments/speakerInfo)은 STT 미포함
// 재요약에서 그대로라 보존한다.
const RESUMMARY_STALE_BOOKMARK_KEYS = ['topics', 'keywords', 'summary', 'issues', 'tasks', 'summaryTime'];

export const createNote = (contentId, note = '') => {
	return noteService.createFirstNote(contentId, note);
};

// LLM이 스키마를 어겨 summaryTime 항목에 영어가 아닌(비ASCII, 예: '내용') 키를 넣는 경우 감지/보정.
// 프론트는 summary/issues/tasks 항목의 content 키를 문자열로 가정하므로, 잘못된 키는 크래시를 유발한다.
const NON_ASCII_KEY = /[^\x00-\x7F]/;
const isPlainObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const ITEM_KEYS = ['summary', 'issues', 'tasks'];

// summaryTime[].summary/issues/tasks 항목 중 비ASCII 키를 가진 객체가 하나라도 있으면 스키마 위반
const hasNonAsciiSummaryKey = (summaryTime = []) =>
	summaryTime.some(o =>
		ITEM_KEYS.some(k =>
			(o?.[k] ?? []).some(
				item => isPlainObject(item) && Object.keys(item).some(key => NON_ASCII_KEY.test(key))
			)
		)
	);

// 폴백: 비ASCII 키 제거. 제거로 content가 사라진 항목은 프론트 크래시/빈 줄을 유발하므로 배열에서 드롭.
const isEmptyContent = v => v == null || String(v).trim() === '';
const stripNonAsciiKeys = (summaryTime = []) => {
	const cleanItems = (arr = []) =>
		arr
			.map(item => {
				if (!isPlainObject(item)) return item; // 문자열 형(haiv/openai)은 그대로 유효한 content
				return Object.fromEntries(Object.entries(item).filter(([key]) => !NON_ASCII_KEY.test(key)));
			})
			.filter(item =>
				isPlainObject(item) ? !isEmptyContent(item.content) : !isEmptyContent(item)
			);
	return summaryTime.map(o => ({
		...o,
		summary: cleanItems(o?.summary ?? []),
		issues: cleanItems(o?.issues ?? []),
		tasks: cleanItems(o?.tasks ?? []),
	}));
};

const postSummaryProcess = async (contentId, summarySize, { note = '', aiResult, summaryTime, title }, manager) => {
	await Promise.all([
		createNote(contentId, note),
		manager.contentUpdater(aiResult, title),
		manager.transUpdater({
			aiResult,
			summaryTime,
			summarySize,
			completeAt: new Date(),
			status: 'SUMMARY_DONE',
		}),
	]);

	return Object.keys(aiResult);
};

const finalizeSummaryProcess = async (task, { totalToken }, summarySize, manager) => {
	const { preParams, isCreate, user, isMerge } = task;
	const { contentId } = preParams;
	const promises = [
		usageModel.addUsage(preParams, 'LLM', totalToken),
		highlightModel.clearHighlightByFileId(preParams),
	];
	log.i(`finalizeSummaryProcess : ${contentId} ${summarySize} ${isCreate}`);

	if (!isCreate) promises.push(historyModel.createReSummaryHistory(contentId, user.pid, summarySize));

	// STT 미포함 재요약: 전사는 그대로라 전사 북마크는 보존하고, 재생성된 AI요약 파생 북마크만 정리한다.
	// (요약 성공 후 시점 → 실패 시 유실 없음. STT 포함 재요약은 recogWorker에서 이미 전체 삭제되어 여기선 no-op)
	if (!isCreate && !isMerge && preParams.fileId) {
		promises.push(bookmarkModel.deleteBookmarksByFileIdAndKeys(preParams.fileId, RESUMMARY_STALE_BOOKMARK_KEYS));
	}

	await Promise.all(promises);
	await Promise.all([manager.sendEmail(user, isCreate, isMerge), manager.transUpdater({ status: 'DONE' })]);
};

const summarizeParams = task => {
	const { segmentInfo, preParams, user, isMerge = false } = task;
	const { auth, ticketId, contentId, contentIds } = preParams;
	log.i(`summarizeParams : ${JSON.stringify(user)}`);
	const { company = undefined } = user;
	const {
		config: { summarySize = 'medium', transcribeLang = 'ko', templateId = null },
	} = auth;

	const params = { summarySize, ticketId, lang: transcribeLang, company, user, contentId, templateId, isMerge };

	if (isMerge)
		return {
			memberId: auth.member.id,
			params: { ...params, contentIds },
		};

	return {
		memberId: auth.member.id,
		speakerLength: segmentInfo.speakerInfo?.length,
		params: { ...params, segmentInfo },
	};
};

const llmWorker = async task => {
	const { preParams, user, isCreate = true, isMerge = false } = task;
	const { auth, ticketId, contentId } = preParams;

	log.i(`llmWorker : ${ticketId} start`);
	const { memberId, speakerLength = 0, params } = summarizeParams(task);
	const manager = new TranscribeUtil(preParams, auth, true);
	isMerge ? manager.notify('MERGE_SUMMARY_RUNNING') : manager.notify('LLM-RUNNING');

	if (!isCreate && !isMerge) await manager.transUpdater({ status: 'RE_SUMMARY_RUNNING' });

	const TAG = `[llmWorker : ${ticketId}] PID : [${memberId}]`;
	try {
		log.i(TAG, `Task ${ticketId} started: summarizer OPENAI `);

		let summaryContent = await summarize(params);

		// LLM이 비ASCII 키(예: '내용')를 뱉으면 요약을 1회 재시도하고, 그래도 남으면 해당 키를 제거해 저장.
		if (hasNonAsciiSummaryKey(summaryContent.summaryTime)) {
			log.w(TAG, `Task ${ticketId} summaryTime 비ASCII 키 감지 → 요약 1회 재시도`);
			summaryContent = await summarize(params);
			if (hasNonAsciiSummaryKey(summaryContent.summaryTime)) {
				log.w(TAG, `Task ${ticketId} 재시도 후에도 비ASCII 키 잔존 → 해당 키 제거`);
				summaryContent.summaryTime = stripNonAsciiKeys(summaryContent.summaryTime);
			}
		}

		const aiResultKeys = await postSummaryProcess(contentId, params.summarySize, summaryContent, manager);

		log.i(TAG, `Task ${ticketId} completed: OpenAI summarizer ai : ${JSON.stringify(aiResultKeys)} `);

		await finalizeSummaryProcess(task, summaryContent, params.summarySize, manager);

		await contentCaptureService.createContentCapture('CONTENT', 'CREATE', contentId, memberId, user, speakerLength);

		log.i(TAG, `Task ${ticketId} completed: summarizer OPENAI `);
	} catch (err) {
		log.e(TAG, `Task ${ticketId} failed: ${err.message}`);
		await manager.transUpdater({ status: 'ERROR' });

		await contentCaptureService.createContentCapture('ERROR', 'LLM', contentId, memberId, user, speakerLength);
		throw err;
	}
};

export default llmWorker;
