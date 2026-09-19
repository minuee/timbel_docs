import BaseService from '../base.service.js';
import memoService from './features/memo.service.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';
import searchService from '../system/search.service.js';
import recycleService from '../system/recycle.service.js';
import { HttpError } from '../../handlers/error.handler.js';
import notePasterUtil from '../../utils/note/paster.util.js';
import attendeesService from './features/attendee.service.js';
import { createResultData } from '../system/drive.service.js';
import contentCaptureService from './contentCapture.service.js';
import recogService, { llmTaskQueue } from '../engine/recog.service.js';
import lifecycleModel from '../../models/lifecycle.model.js';
import { convert, generate, date, notify } from '../../utils/index.js';
import documentComposer from '../../utils/documator/content.exporter.js';
import { getContentsResponseWithIds } from '../feature/calendar.service.js';

// 재요약/재시도 STT는 fastLoadFile이 확장자를 임시파일 postfix로 사용한다. 파일명에 점이 있고
// 오디오 확장자가 없으면(예: 녹음 'A.Biz_w_rec_...') split('.')이 엉뚱한 값을 뱉어 HAIV가
// 'Unsupported File'(E2123)로 거부한다. 유효 오디오 확장자를 보장하기 위해 mimeType/기본값으로 폴백.
const KNOWN_AUDIO_EXT = new Set([
	'flac', 'wav', 'mp3', 'm4a', 'aac', 'ogg', 'oga', 'webm', 'amr', '3gp', 'mp4', 'wma', 'opus',
]);
const MIME_TO_EXT = {
	'audio/flac': 'flac',
	'audio/x-flac': 'flac',
	'audio/wav': 'wav',
	'audio/x-wav': 'wav',
	'audio/wave': 'wav',
	'audio/vnd.wave': 'wav',
	'audio/mpeg': 'mp3',
	'audio/mp3': 'mp3',
	'audio/mp4': 'm4a',
	'audio/x-m4a': 'm4a',
	'audio/aac': 'aac',
	'audio/ogg': 'ogg',
	'audio/webm': 'webm',
	'audio/amr': 'amr',
	'audio/x-ms-wma': 'wma',
};
const resolveAudioExtension = file => {
	const raw = (file?.fileName ?? '').split('.').pop()?.toLowerCase();
	if (raw && KNOWN_AUDIO_EXT.has(raw)) return raw;
	const byMime = MIME_TO_EXT[(file?.mimeType ?? '').toLowerCase()];
	if (byMime) return byMime;
	return 'flac'; // 녹음 기본 포맷
};

class ContentService extends BaseService {
	constructor() {
		super();
		this.notePaster = notePasterUtil;
		this.searchService = searchService;
		this.attendeesService = attendeesService;
		this.documentComposer = documentComposer;
		this.contentCaptureService = contentCaptureService;

		this.ownerRole = this.userModel.Enums.ContentShareRole.OWNER;
		this.downloadType = this.downloadHistoryModel.Enums.DownloadType;
	}

	async getAllContents(pid, email, options) {
		try {
			const { contentFilter } = options;

			// 공유 컨텐츠 조회 필요시
			let sharedContentIds = [];
			const { ALL, SHARED_IN } = Enums.ContentFilter;
			if (contentFilter && [ALL, SHARED_IN].includes(contentFilter)) {
				sharedContentIds = [...(await this.contentModel.getSharedContentIds(email))];
			}

			// 공유받은 컨텐츠 조회시, 사용자의 폴더에 속한 컨텐츠는 제외
			if (contentFilter && contentFilter === Enums.ContentFilter.SHARED_IN) {
				// 사용자의 폴더에 속한 콘텐츠 ID들을 직접 조회
				const myFolderContentIds = await this.contentModel.getMyFolderContentIds(pid);
				const myFolderContentIdSet = new Set(myFolderContentIds);
				sharedContentIds = sharedContentIds.filter(contentId => !myFolderContentIdSet.has(contentId));
			}

			const contents = await this.contentModel.getContents(pid, { ...options, sharedContentIds });

			return await getContentsResponseWithIds(contents, email, pid);
		} catch (err) {
			throw err;
		}
	}

	// 접근 가능한 콘텐츠 조회 및 소유권 정보 반환
	async getAccessibleContentsWithOwnership(contentIds, { email, pid }) {
		// 단일 쿼리로 접근 가능한 콘텐츠만 조회 (내가 생성한 것 + 공유받은 것)
		const { accessibleContents, sharedContentIdSet } = await this.contentModel.getAccessibleContentsByIds(
			contentIds,
			pid,
			email
		);

		// 공유받은 콘텐츠 ID 목록 (소유권 분리를 위해)
		const sharedContentIds = Array.from(sharedContentIdSet);

		// 소유권별로 콘텐츠 ID 분리
		const myOwnContentIds = contentIds.filter(id => !sharedContentIdSet.has(id));

		// 에러 상태 콘텐츠 ID 조회 (이미 조회된 콘텐츠에서 필터링)
		const errorContentIds = accessibleContents
			.filter(content => content.transcribeStatus === 'ERROR')
			.map(content => content.contentId);

		return {
			accessibleContents,
			myOwnContentIds,
			sharedContentIds, // 전체 공유 콘텐츠 ID 목록
			sharedContentIdSet, // Set 객체로 빠른 검색 가능
			errorContentIds, // 에러 상태 콘텐츠 ID 목록
		};
	}

	async getRecycleContents({ member }, take = 0, type = null) {
		try {
			const { id } = member;
			const filterColumns = [
				'workspaceId',
				'creatorId',
				'editorId',
				'isMobile',
				'isRecord',
				'isLocked',
				'saveCount',
				'creator',
				'shareUsers',
			];

			const contents = await this.contentModel.getRecycleContents(id, take, type);
			if (contents === null || contents.length === 0) return [];

			const contentIds = contents.reduce((acc, curr) => {
				acc.push(curr.contentId);
				return acc;
			}, []);

			const files = await this.transcribeResultModel.findSpeakerInfosByContentIds(contentIds);

			return contents.map(content => {
				const { contentId, shareUsers = [], creator } = content;
				const file = files.find(speakerInfo => speakerInfo.contentId === contentId);
				const speakerInfo = file?.transcribeResult?.speakerInfo ?? [];
				const isShared = shareUsers.length > 0;
				const creatorPID = creator.user.pid;

				filterColumns.forEach(column => {
					delete content[column];
				});
				return {
					...content,
					creatorPID,
					isShared,
					speakerInfo,
				};
			});
		} catch (err) {
			throw err;
		}
	}

	// 회의록을 조회 목록에서 제거(deprecated)
	async removeContentFromList(contentId, auth, user) {
		try {
			const { member, permission } = auth;

			const content = await this.contentModel.findContentById(contentId);
			if (content.isRecycle === true) throw new HttpError(1111); // '이미 휴지통으로 이동된 컨텐츠'
			if (!['ERROR', 'CANCEL', 'DONE'].includes(content.transcribeStatus))
				throw new HttpError(1114, { status: content.transcribeStatus });

			if (permission && permission === 'OWNER') {
				await this.contentModel.moveContentToRecycleBin(contentId);
				recycleService.addTask(contentId, auth); // 30일 후 파일 삭제되도록 요청
				await notify.recycleContentEvent(user, [content]);
				await this.contentCaptureService.createContentCapture('CONTENT', 'RECYCLE', contentId, member.id, user);
				return { message: '휴지통 이동 성공', httpCode: 200 };
			} else {
				await this.shareModel.deleteContentShareUser(contentId, user.email);
				return { message: '공유 해제 성공', httpCode: 204 };
			}
		} catch (error) {
			throw error;
		}
	}

	// 여러 회의록을 조회 목록에서 동시 제거(휴지통 이동, 공유 해제)
	async removeBulkContentsFromList(contentIds, auth, user) {
		try {
			log.d('[ContentService][removeBulkContentsFromList]', `contentIds : ${this}`);
			const { member } = auth;
			const [myContents, sharedContents] = await Promise.all([
				this.contentModel.findMyOwnContentsByIds(contentIds, user.pid),
				this.shareModel.findSharedContentsToMe(contentIds, user.email),
			]);

			if (myContents.length === 0 && sharedContents.length === 0) {
				throw new HttpError(1908); // '삭제할 컨텐츠가 더 이상 없습니다.'
			}

			myContents.forEach(content => {
				if (!['ERROR', 'CANCEL', 'DONE'].includes(content.transcribeStatus))
					throw new HttpError(1114, { status: content.transcribeStatus });
			});

			// 휴지통 이동
			if (myContents.length > 0) {
				const myContentIds = myContents.map(content => content.contentId);
				await this.contentModel.moveBulkContentsToRecycleBin(myContentIds);
				await notify.recycleContentEvent(user, myContents);
				// 30일 후 파일 삭제되도록 요청
				await Promise.all([
					...myContentIds.map(contentId => recycleService.addTask(contentId, auth)),
					this.contentCaptureService.createManyContentCapture(
						'CONTENT',
						'RECYCLE',
						myContentIds,
						member.id,
						user
					),
				]);
			}

			// 공유 해제
			if (sharedContents.length > 0) {
				const sharedContentIds = sharedContents.map(content => content.contentId);
				await this.shareModel.deleteBulkContentsShareUser(sharedContentIds, user.email);
			}

			return;
		} catch (error) {
			throw error;
		}
	}

	async restoreContent(contentId, auth, user) {
		try {
			const { member } = auth;
			const [content, thumbnail] = await Promise.all([
				this.contentModel.restoreContent(contentId),
				this.contentModel.getThumbnails([contentId]),
			]);

			recycleService.deleteTask(contentId);
			await this.contentCaptureService.createContentCapture('CONTENT', 'RESTORE', contentId, member.id, user);
			return { ...content, shareUsers: thumbnail };
		} catch (error) {
			throw error;
		}
	}

	async truncateContent(contentId, auth, user) {
		try {
			const { member } = auth;

			const result = await this.contentModel.truncateContent(contentId);

			recycleService.addNowDeleteTask([contentId], auth);
			await this.contentCaptureService.createContentCapture('CONTENT', 'TRUNCATE', contentId, member.id, user);
			return result;
		} catch (error) {
			throw error;
		}
	}

	// 휴지통 비우기
	async clearRecyleBin(auth, user) {
		try {
			const { id: creatorId } = auth.member;
			const recycleContents = await this.contentModel.getRecycleContents(creatorId, 0, null);
			if (recycleContents.length === 0) throw new HttpError(400, '휴지통이 이미 비어있습니다.');

			const result = await this.contentModel.clearRecyleBin(creatorId);
			const contentIds = recycleContents.map(content => content.contentId);

			recycleService.addNowDeleteTask(contentIds, auth);
			await this.contentCaptureService.createManyContentCapture(
				'CONTENT',
				'TRUNCATE',
				contentIds,
				creatorId,
				user
			);

			return result;
		} catch (error) {
			throw error;
		}
	}

	// 교정-음성기록 전체 전사 구간 변경
	async changeSegments(contentId, newSegments, { member }, user) {
		try {
			const file = await this.contentModel.findFileByContentId(contentId);
			const oldContent = await this.contentModel.getSegments(file.id);
			const oldSegmentsMap = new Map(oldContent.mergedSegments.map(segment => [segment.segmentId, segment]));

			// 유효성 검사
			const validationErrors = [];
			let hasChanges = false;
			const removingSegmentIndexes = [];

			// 기존 mergedSegments 배열 복사
			const updatedMergedSegments = [...oldContent.mergedSegments];

			for (const [index, { segmentId, text = '' }] of newSegments.entries()) {
				if (segmentId === undefined || segmentId === null) {
					validationErrors.push(`${index}번째 구간: segmentId 필수값입니다.`);
					continue;
				}

				if (typeof segmentId !== 'string' || typeof text !== 'string') {
					validationErrors.push(`${index}번째 구간: segmentId와 text는 string이어야 합니다.`);
					continue;
				}

				const segmentIndex = updatedMergedSegments.findIndex(segment => segment.segmentId === segmentId);
				if (segmentIndex === -1) {
					validationErrors.push(`${index}번째 구간: segmentId(${segmentId})의 기록을 찾을 수 없습니다.`);
					continue;
				}

				const oldSegment = oldSegmentsMap.get(segmentId);
				if (oldSegment.text !== text) {
					updatedMergedSegments[segmentIndex] = { ...oldSegment, text };
					hasChanges = true;
				}
				removingSegmentIndexes.push(segmentIndex);
			}

			if (validationErrors.length > 0) throw new HttpError(400, validationErrors.join(', '));
			if (!hasChanges) throw new HttpError(1172); // '변경 사항이 전혀 없는 요청입니다.'

			// 단일 업데이트 쿼리 실행
			await Promise.all([
				this.contentModel.updateMergedSegments(file.id, updatedMergedSegments),
				this.highlightModel.clearHighlightBySegmentIndexes(file.id, removingSegmentIndexes),
			]);

			await this.contentCaptureService.createContentCapture(
				'CONTENT',
				'UPDATE_SEGMENT',
				contentId,
				member.id,
				user
			);

			return;
		} catch (err) {
			throw err;
		}
	}

	async getThumbnails(contentIds) {
		try {
			return await this.contentModel.getThumbnails(contentIds);
		} catch (err) {
			throw err;
		}
	}

	async updateContentTitle(contentId, title, { member }, user) {
		try {
			if (!title) {
				title = null;
			}

			const result = await this.contentModel.updateContentTitle(contentId, title);
			await this.contentCaptureService.createContentCapture(
				'CONTENT',
				'UPDATE_TITLE',
				contentId,
				member.id,
				user
			);
			return result;
		} catch (err) {
			throw err;
		}
	}

	async updateContentKeywords(contentId, keywords, { member }, user) {
		try {
			const targetKeywords = keywords.filter(keyword => keyword.trim() !== '' && keyword !== null);

			const file = await this.contentModel.findFileByContentId(contentId, { transcribeResult: true });
			if (!file) throw new HttpError(1121);

			const { id, transcribeResult } = file;
			const { ticketId, aiResult = {} } = transcribeResult;
			aiResult.keywords = targetKeywords;

			const where = {
				fileId: id,
				ticket: ticketId,
			};

			const result = await Promise.all([
				this.contentModel.updateContent({ contentId }, { hashTag: targetKeywords }),
				this.transcribeResultModel.updateStatus(where, { aiResult }),
			]);

			if (!result) {
				throw new HttpError(1171);
			}

			await this.contentCaptureService.createContentCapture(
				'CONTENT',
				'UPDATE_KEYWORD',
				contentId,
				member.id,
				user
			);
			return true;
		} catch (err) {
			throw err;
		}
	}

	async reSummaryContent(contentId, auth, user) {
		const file = await this.contentModel.findFileByContentId(contentId, { transcribeResult: true });
		if (!file) throw new HttpError(1121);

		// 관리자 토글: On이면 STT(음성 인식)부터 재수행 후 요약, Off(기본)면 기존 STT 결과로 요약만 재수행.
		const workspaceId = auth?.member?.workspace?.id;
		const includeStt = await this.userModel.getWorkspaceBooleanSetting(workspaceId, 'use_resummary_stt');

		if (includeStt) {
			// STT 포함 재요약: recog 큐로 태우면 STT 완료 후 recogWorker가 LLM 큐로 자동 체이닝한다.
			// 오디오 원본은 스토리지에 남아 있어 recog가 fileKey로 다시 로드한다.
			const extension = resolveAudioExtension(file);
			const params = {
				fileId: file.id,
				fileKey: file.fileKey,
				duration: file.duration,
				contentId,
				fileName: file.fileName,
				extension,
				isCreate: false, // 재요약이므로 생성이 아님(이력/이메일/상태 유지)
			};
			const result = await recogService.addTask(auth, params, user);
			if (!result) throw new HttpError(1127);

			// 메모/북마크 앵커 정리는 STT 성공(세그먼트 재생성) 이후 recogWorker에서 수행한다.
			// (기존엔 큐 적재 직후 삭제해 STT 실패 시 사용자 메모/북마크가 유실됐음)
			return {};
		}

		const { transcribeResult } = file;
		const { speakerInfo, mergedSegments, ticket } = transcribeResult;

		const speakerMap = speakerInfo.reduce((acc, curr) => {
			acc[curr.speakerId] = curr;
			return acc;
		}, {});

		const taskParams = {
			user,
			taskId: ticket,
			isCreate: false,
			segmentInfo: {
				speakerMap,
				speakerInfo,
				mergedSegments,
			},
			preParams: {
				auth,
				contentId,
				fileId: file.id,
				ticketId: ticket,
			},
		};

		const result = await llmTaskQueue.addTask(taskParams);
		if (!result) throw new HttpError(1127);

		await memoService.realDeleteMemosByContentId(contentId);
		return {};
	}

	async updateMeetingTime(contentId, data, { member }, user) {
		const result = await this.contentModel.updateContentMeetingTime(contentId, data);
		if (!result) throw new HttpError(1171);
		await this.contentCaptureService.createContentCapture(
			'CONTENT',
			'UPDATE_MEETINGTIME',
			contentId,
			member.id,
			user
		);
		return result;
	}

	async resetSegments(contentId, { member }, user, options) {
		try {
			const file = await this.contentModel.findFileByContentId(contentId, { transcribeResult: true });
			if (!file) throw new HttpError(1121);
			const { segments, mergedSegments, speakerInfo } = file.transcribeResult;

			options.speakerInfo = speakerInfo;
			options.oldSegmentsMap = new Map(
				mergedSegments.map(({ startTime, segmentId, speakerId }) => [startTime, { segmentId, speakerId }])
			);

			const resetMergedSegment = convert.resetMergedSegments({ segments, options });

			const [result] = await Promise.all([
				this.contentModel.updateMergedSegments(file.id, resetMergedSegment),
				this.highlightModel.clearHighlightByFileId({ fileId: file.id }, 'mergedSegments'),
			]);

			await this.contentCaptureService.createContentCapture(
				'CONTENT',
				'UPDATE_RESET_SEGMENTS',
				contentId,
				member.id,
				user
			);
			return result;
		} catch (err) {
			throw err;
		}
	}

	async exportContentToDocs(auth, user, contentId, { format, includeKeys }) {
		try {
			const selectFields = ['aiResult', 'speakerInfo', 'mergedSegments', 'summaryTime'];

			const includeFields = [];
			if (includeKeys.includes('highlights')) {
				includeFields.push('highlights');
			}
			if (includeKeys.includes('note')) {
				includeFields.push('note');
			}

			let [mongoDBcontent, mariaDBContent, bookmarks] = await Promise.all([
				this.contentModel.getTranscribeResultByContentId(contentId, selectFields, includeFields),
				this.contentModel.findContentById(contentId),
				this.bookmarkModel.getBookmarksByContentId(contentId),
			]);

			const contentData = {
				...mongoDBcontent.transcribeResult,
				highlights: mongoDBcontent.highlights,
				bookmarks,
				note: mongoDBcontent.note,
			};

			const { title, editedTitle, fileName, meetingStartTime, meetingEndTime } = mariaDBContent;
			const metadata = { format, title: editedTitle || title, meetingStartTime, meetingEndTime };

			// 최종 파일 생성
			const result = await documentComposer.execute(metadata, contentData, includeKeys);

			log.i(`[ContentService : exportContentToDocs] Successfully processed:
				requester's pid: ${user.pid}
				contentId: ${contentId}
				format: ${format}
			`);

			const queryDto = {
				contentId,
				type: this.downloadType[`DOCUMENT_${format.toUpperCase()}`],
				size: result.buffer.length,
				workspaceId: auth.member.workspace.id,
				contentTitle: title,
				fileName,
				userName: user.nickName,
				email: user.email,
			};
			this.downloadHistoryModel.createDownloadHistory(queryDto);

			return result;
		} catch (error) {
			console.error('문서 변환 오류:', error);
			throw error;
		}
	}

	async updateSummaryContent(contentId, { category = '', data = [], removeHighlightIds = [] }) {
		try {
			const file = await this.contentModel.findFileByContentId(contentId, { transcribeResult: true });
			if (!file) throw new HttpError(1121);
			const { id, transcribeResult } = file;
			const { ticketId, status = 'ERROR' } = transcribeResult;
			if (status === 'ERROR') throw new HttpError(1119);
			if (status !== 'DONE') throw new HttpError(1121);

			const where = {
				fileId: id,
				ticket: ticketId,
			};

			const updateData =
				category === 'summaryTime' ?
					{ summaryTime: data }
				:	{
						aiResult: {
							...transcribeResult.aiResult,
							[category]: data,
						},
					};

			Promise.all([
				this.transcribeResultModel.updateStatus(where, updateData),
				this.highlightModel.deleteHighlight(id, removeHighlightIds),
			]);
			return true;
		} catch (err) {
			throw err;
		}
	}

	async mergeContents(contentIds, auth, user) {
		try {
			const contents = await this.contentModel.findContentByIds(contentIds);

			if (contents.length !== contentIds.length) throw new HttpError(1000);

			const contentMeta = {
				title: `회의록 합치기 - ${date.getDateTime(new Date())}`,
				duration: contents.reduce((acc, curr) => acc + curr.duration, 0),
				inputType: 'MERGED_CONTENT',
				isRecord: false,
				isParseDate: false,
				endTime: new Date(),
			};

			const mergedContent = await this.contentModel.createContent(auth, contentMeta, {}, contentIds);

			const { contentId: mergedContentId } = mergedContent;
			const file = await this.contentModel.createFileContent(mergedContentId, contentMeta);
			const taskId = generate.ticketId();
			await this.transcribeResultModel.create(file.id, taskId, auth);
			const taskParams = {
				user,
				taskId,
				isCreate: false,
				isMerge: true,
				preParams: {
					auth,
					contentId: mergedContentId,
					contentIds,
					fileId: file.id,
					ticketId: taskId,
				},
			};
			const result = await llmTaskQueue.addTask(taskParams);
			if (!result) throw new HttpError(1127);

			return createResultData(mergedContent, contentMeta);
		} catch (err) {
			log.i('[ContentService : mergeContents] error : ', err);
			throw err;
		}
	}

	async findContentById(contentId) {
		try {
			return await this.contentModel.findContentById(contentId);
		} catch (err) {
			log.e('[ContentService : findContentById] error : ', err);
			throw err;
		}
	}

	async contentRetry(contentId, auth, user) {
		try {
			const file = await this.contentModel.findFileByContentId(contentId);
			if (!file) throw new HttpError(1122);

			// 보존정책으로 원본 파일이 삭제된 경우 재시도 불가(STT가 원본을 로드 못 해 다시 실패한다).
			// 재요약 버튼이 contentLifecycleActions(FILE) 기준으로 숨겨지는 것과 동일 기준으로 차단.
			// getContentLifecycle은 completedAt!=null(실제 삭제 완료)만 반환한다.
			const lifecycleActions = await lifecycleModel.getContentLifecycle(contentId);
			if (lifecycleActions?.some(action => action.targetType === 'FILE')) throw new HttpError(1128);

			await this.contentModel.updateTranscribeStatus(contentId, 'WAITING');

			// 기존 recogRetry는 큐의 기존 잡을 getJob→retry 하는 방식이라, 잡이 완료 시 제거(removeOnComplete)
			// 되면 대부분 1186('재시도 큐 없음')이 났다. 신규 STT 태스크로 재적재해 항상 동작하도록 변경
			// (engine addTask = transcribeResult upsert + 스테일 잡 정리 포함).
			const extension = resolveAudioExtension(file);
			const params = {
				fileId: file.id,
				fileKey: file.fileKey,
				duration: file.duration,
				contentId,
				fileName: file.fileName,
				extension,
				isCreate: false,
			};
			const result = await recogService.addTask(auth, params, user);
			if (!result) throw new HttpError(1127);
			return true;
		} catch (err) {
			await this.contentModel.updateTranscribeStatus(contentId, 'ERROR');
			throw err;
		}
	}
}

export default new ContentService();
