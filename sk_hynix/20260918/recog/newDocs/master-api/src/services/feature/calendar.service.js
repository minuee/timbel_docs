import BaseService from '../base.service.js';
import userModel from '../../models/user.model.js';
import shareModel from '../../models/share.model.js';
import contentModel from '../../models/content.model.js';
import calendarModel from '../../models/calendar.model.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';
import { HttpError } from '../../handlers/error.handler.js';
import { taskQueue, date, transform } from '../../utils/index.js';
import calendarWorker from '../../utils/reminderWorker/calendar.js';
import webcalUtil from '../../utils/integrate/calendar/webcal.util.js';
import transcribeResultModel from '../../models/transcribeResult.model.js';

const summaryDummyData = `### 📌 지난 회의 주요 내용   

 - 에이전트 플로우 개선 방안 논의
- 자연어 처리 앱엔드 프로세스 검토
- QA 자동화 테스트 도입 제안 등
### 📝 내가 남긴 북마크/메모  

 - [북마크] "프로토타입 데모 결과 공유 필요"
- [메모] "QA 자동화 적용 대상 범위 추가 검토"
- [북마크] "다음 회의에서 역할 분담 재확인"`;

const ownerRole = userModel.Enums.ContentShareRole.OWNER;
export const getContentsResponseWithIds = async (contents, email, pid) => {
	const contentIds = contents.map(content => content.contentId);

	const [files, sharedUsers, folders] = await Promise.all([
		transcribeResultModel.findSpeakerInfosByContentIds(contentIds),
		shareModel.getSharedUsers(contentIds),
		userModel.getFolders(pid),
	]);

	/**
	 * 공유자 정보 및 권한 정보 추가
	 */
	let sharedUsersHash = {};
	if (sharedUsers.length > 0) {
		// contentId를 키로 하는 객체 생성
		sharedUsersHash = sharedUsers.reduce((acc, curr) => {
			const { contentId, ...userInfo } = curr;
			if (!acc[contentId]) acc[contentId] = [];
			acc[contentId].push(userInfo);
			return acc;
		}, {});
	}

	return contents.map(content => {
		const shareUsers = sharedUsersHash[content.contentId] || [];
		const userIndex = shareUsers.findIndex(data => data.email === email);
		const userAccessRole = content.creatorPID === pid ? ownerRole : shareUsers[userIndex]?.role;
		const file = files.find(speakerInfo => speakerInfo.contentId === content.contentId);

		// 폴더 이름 결정 로직
		let folderName = '/';
		if (content.creatorPID === pid) {
			// 내가 생성한 콘텐츠
			if (content.transcribeStatus === 'ERROR') {
				folderName = '미완성 회의록';
			} else if (content.folderId) {
				folderName = folders.find(folder => folder.id === content.folderId)?.name ?? '/';
			} else {
				folderName = '내 회의록';
			}
		} else {
			// 공유받은 콘텐츠: SharedUserProfile 뷰에서 folderName 직접 사용
			const userShareInfo = shareUsers.find(data => data.email === email);
			folderName = userShareInfo?.folderName ?? '공유 받은 회의록';
		}

		// shareUsers에서 folderId와 folderName 제외
		const cleanedShareUsers = shareUsers.map(user => {
			const { folderId, folderName, ...userWithoutFolder } = user;
			return userWithoutFolder;
		});

		const speakerInfo = file?.transcribeResult?.speakerInfo ?? [];
		return {
			...content,
			userAccessRole,
			folderName,
			shareUsers: cleanedShareUsers,
			speakerInfo,
		};
	});
};

// deprecated
export const getCalendarContents = async ({ pid, email }, options) => {
	try {
		const { contentFilter } = options;

		let sharedContentIds = [];

		// 공유 컨텐츠 조회 필요시
		const { ALL, SHARED_IN } = Enums.ContentFilter;
		if (contentFilter && [ALL, SHARED_IN].includes(contentFilter)) {
			sharedContentIds = [...(await contentModel.getSharedContentIds(email))];
		}

		const calendarContents = await calendarModel.getCalendarContents(pid, sharedContentIds, options);

		return await getContentsResponseWithIds(calendarContents, email, pid);
	} catch (err) {
		throw err;
	}
};

let reminderTaskQueue = null;

const TAG = '[CalendarService]';
class CalendarService extends BaseService {
	constructor() {
		super();
	}
	async getCalendars({ pid }, member, options) {
		try {
			const calendarContents = await this.calendarModel.getCalendars(member, options);
			const contents = calendarContents
				.filter(calendar => calendar.content !== null)
				.map(calendar => {
					const { content } = calendar;
					const { creator, ...contentWithoutCreator } = content;
					const { profile } = creator.user;
					const { pid, nickName, email, thumbnailUrl } = profile;
					return {
						...contentWithoutCreator,
						creatorPID: pid,
						creatorNickName: nickName,
						creatorEmail: email,
						creatorThumbnailUrl: thumbnailUrl,
					};
				});

			const contentsResponse = await getContentsResponseWithIds(contents, member.email, pid);

			const result = transform.transformCalendarWithContentMap(calendarContents, contentsResponse);
			return result;
		} catch (err) {
			throw err;
		}
	}

	async createCalendar({ member }, user, createCalendarDTO) {
		try {
			const { reminderMinutes, attachedContents } = createCalendarDTO;
			if (date.isBeforeMeetingStartDate(reminderMinutes, createCalendarDTO)) throw new HttpError(2110);

			if (attachedContents.length !== 0) {
				const [myContents, sharedContents] = await Promise.all([
					this.contentModel.findMyOwnContentsByIds(attachedContents, user.pid),
					this.shareModel.findSharedContentsToMe(attachedContents, user.email),
				]);

				if (myContents.length + sharedContents.length !== attachedContents.length) throw new HttpError(2109);

				createCalendarDTO.summary = summaryDummyData;
			}

			const calendar = await this.calendarModel.createCalendar(member, createCalendarDTO);
			log.i(TAG, `calendar : ${JSON.stringify(calendar)}`);
			if (reminderMinutes > 0) {
				reminderTaskQueue.addTask(
					{ taskId: `reminder-${calendar.id}`, calendarId: calendar.id, user },
					date.getDelayUntilMinutes(reminderMinutes, createCalendarDTO)
				);
			}

			return calendar;
		} catch (err) {
			throw err;
		}
	}

	async connectWebcal(user, url) {
		try {
			const { pid } = user;

			log.d(TAG, `[connectWebcal] url : ${url}`);
			const provider = await webcalUtil.validateWebcalAndProvider(url);
			if (!provider) {
				throw new HttpError(2103);
			}

			const result = await this.calendarModel.upsertWebcal({ pid }, url, provider);
			if (!result) {
				throw new HttpError(2104);
			}

			const webcales = await this.calendarModel.getWebcales({ pid });
			this.syncIntegrate(user, true, webcales);

			log.d(TAG, `[connectWebcal] webcales : ${JSON.stringify(webcales)}`);

			return webcales;
		} catch (err) {
			throw err;
		}
	}

	async getIntegrateSettings(user) {
		try {
			const { pid } = user;
			const webcales = await this.calendarModel.getWebcales({ pid });
			return webcales;
		} catch (err) {
			throw err;
		}
	}

	async disconnectWebcal(user, provider = '') {
		try {
			await this.calendarModel.disconnectWebcal(user, provider.toUpperCase());

			const webcales = await this.calendarModel.getWebcales(user);
			return webcales;
		} catch (err) {
			log.e(TAG, `[disconnectWebcal] ${err.message}`);
			throw new HttpError(2105);
		}
	}

	async getIntegrateCalendars(user) {
		try {
			const lastSyncWebcal = await this.calendarModel.getLastSyncedWebcale(user);

			const result = await this.calendarModel.getIntegrateCalendars(user);
			return {
				lastSyncedAt: lastSyncWebcal?.lastSyncedAt,
				integrateCalendars: result,
			};
		} catch (err) {
			throw err;
		}
	}

	async syncIntegrate(user, force, webcales = null) {
		try {
			const result = [];
			log.i(TAG, `[syncIntegrate] force : ${force}`);
			if (!webcales) webcales = await this.calendarModel.getWebcales(user);

			if (!force) {
				let isSynced = true;
				for (const webcal of webcales) {
					if (!webcal.lastSyncedAt) continue;
					if (!date.isAfter(webcal.lastSyncedAt, new Date(Date.now() - 60 * 60 * 1000))) {
						isSynced = false;
						break;
					}
				}
				if (isSynced) return await this.getIntegrateCalendars(user);
			}

			log.i(TAG, `[syncIntegrate] syncing webcales :${webcales.length}`);

			const webcalDataResults = await Promise.allSettled(
				webcales.map(webcal => webcalUtil.getWebcalData(webcal))
			);

			const syncPromises = webcales.map(async (webcal, index) => {
				const dataResult = webcalDataResults[index];

				if (dataResult.status === 'rejected') {
					log.i(TAG, `[syncIntegrate] webcal data get failed: ${webcal.url}`, dataResult.reason?.message);
					return [];
				}

				const data = dataResult.value;
				if (!data || data.length === 0) {
					return [];
				}

				return await this.calendarModel.upsertCalendarIntegrateSync(data, webcal.id);
			});

			const syncResults = await Promise.all(syncPromises);

			syncResults.forEach(syncs => {
				if (syncs && syncs.length > 0) {
					result.push(...syncs);
				}
			});
			await this.calendarModel.updateWebcalLastSyncedAt(webcales);
			const lastSyncWebcal = await this.calendarModel.getLastSyncedWebcale(user);
			return {
				lastSyncedAt: lastSyncWebcal?.lastSyncedAt,
				integrateCalendars: result.sort((a, b) => a.start.getTime() - b.start.getTime()),
			};
		} catch (err) {
			throw err;
		}
	}

	async loadIntegrate({ member }, ids) {
		try {
			const integrateCalendars = await this.calendarModel.getIntegrateCalendarsByIds(ids);
			log.d(TAG, `[loadIntegrate] integrateCalendars : ${JSON.stringify(integrateCalendars)}`);
			if (integrateCalendars.length === 0) {
				throw new HttpError(2106);
			}
			const result = await this.calendarModel.createIntegrateCalendar(member, integrateCalendars);
			log.d(TAG, `[loadIntegrate] result : ${JSON.stringify(result)}`);

			await this.calendarModel.updateIntegrateCalendarSync(ids);

			return {
				count: result.length,
			};
		} catch (err) {
			throw err;
		}
	}

	async deleteCalendar(id) {
		try {
			const calendar = await this.calendarModel.getCalendarById(id);
			if (!calendar) throw new HttpError(2107);

			const { content } = calendar;

			// 회의록 연동 정보 상태 변경
			await this.calendarModel.updateIntegrateCalendarSync([id], false);

			// 회의록이 있으면 해당 회의록을 제거, 또는 공유 제거
			if (content) return [content.contentId];

			// 회의록이 없으면 회의록 제거
			await this.calendarModel.deleteCalendar(id);
			return [];
		} catch (err) {
			throw err;
		}
	}

	async updateCalendar(id, reminderMinutes, user) {
		try {
			const calendar = await this.calendarModel.getCalendarById(id);
			if (!calendar) throw new HttpError(2107);

			if (date.isAfter(Date.now(), calendar.meetingStartDate)) throw new HttpError(2111);
			if (reminderMinutes === calendar.reminderMinutes) return calendar;

			if (calendar.reminderMinutes > 0) {
				await reminderTaskQueue.cancelTask(`reminder-${id}`);
			}

			if (reminderMinutes > 0) {
				if (date.isBeforeMeetingStartDate(reminderMinutes, calendar)) throw new HttpError(2110);

				await reminderTaskQueue.addTask(
					{ taskId: `reminder-${id}`, calendarId: id, user },
					date.getDelayUntilMinutes(reminderMinutes, calendar)
				);
			}

			return await this.calendarModel.updateCalendarReminderMinutes(id, reminderMinutes);
		} catch (err) {
			throw err;
		}
	}
}

process.on('configChanged', () => {
	setTimeout(async () => {
		// 기존 Queue 정리 (메모리 누수 방지)
		if (reminderTaskQueue) {
			await reminderTaskQueue.close();
		}
		reminderTaskQueue = new taskQueue('reminder', calendarWorker, 10);
	}, 500);
});

export default new CalendarService();
