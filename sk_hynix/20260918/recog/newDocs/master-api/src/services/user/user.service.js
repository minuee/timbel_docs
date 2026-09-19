import BaseService from '../base.service.js';
import usageUtil from '../../utils/usage.util.js';
import contentService from '../content/content.service.js';
import folderUtils from '../../utils/folder.util.js';
import { getSearchRange } from '../../utils/date.util.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';
import { HttpError } from '../../handlers/error.handler.js';
import contactUtils from '../../utils/contact/recycle.util.js';
import contactBulkUtils from '../../utils/contact/bulk.util.js';
import { getContentsResponseWithIds } from '../feature/calendar.service.js';

// 알림 종류/채널 → 워크스페이스 관리자 기본값 설정 키(notification_default.<event>_<channel>) 매핑
const NOTI_EVENT_TOKEN = {
	CONTENT_CREATE: 'create',
	CONTENT_RECYCLE: 'recycle',
	CONTENT_SHARE: 'share',
	CONTENT_RESUMMARY: 'resummary',
	CALENDAR_REMIND: 'calendar',
};
const NOTI_CHANNEL_TOKEN = { EMAIL: 'email', PUSH: 'mobile' };
const notiDefaultKey = (eventType, channel) =>
	`notification_default_${NOTI_CHANNEL_TOKEN[channel]}.${NOTI_EVENT_TOKEN[eventType]}`;

class UserService extends BaseService {
	constructor() {
		super();
	}

	async getMembersFromWorkspace(workspaceId, userPid, keyword) {
		try {
			// 워크스페이스에서 멤버 찾기
			const members = await this.memberModel.getMembersFromWorkspace(workspaceId);
			if (!members.length) return [];

			// 멤버들의 프로필 정보 조회
			const memberPids = members.map(member => member.pid);
			const foundMembers = await this.userModel.getMembersFromWorkspace(memberPids, keyword);
			if (foundMembers.length === 0) return [];

			// 찾은 멤버들을 주소록에서 찾기
			const targetPids = foundMembers.map(member => member.pid);
			const contactsInResults = await this.contactModel.getContactsByTargetPids(userPid, targetPids);

			// 주소록에 있는 pid 추출
			const contactPidSet = new Set(
				contactsInResults.filter(contact => contact.targetUser?.pid).map(contact => contact.targetUser.pid)
			);

			// 주소록에 있는 멤버는 flag 처리
			return foundMembers.map(member => ({
				...member,
				isInContact: contactPidSet.has(member.pid),
			}));
		} catch (err) {
			throw err;
		}
	}

	flattenContact(contact) {
		const { id, targetUser, labels, ...rest } = contact;
		const labelList = labels ? labels.map(({ label }) => label) : [];
		return { id, ...targetUser, ...rest, labels: labelList };
	}

	// 주소록 생성
	async createContact({ pid, email, memo, labelIds }) {
		try {
			const userProfile = await this.userModel.findUserProfileByEmail(email);
			if (!userProfile) throw new HttpError(1303);
			if (userProfile.pid === pid) throw new HttpError(1112);

			const user = await this.contactModel.getUserByEmail(pid, email);
			// 주소록 중복 체크
			if (user) {
				if (user.isRecycle) {
					throw new HttpError(1917); // 휴지통으로 이동된 주소록에 중복된 이메일이 있습니다.
				}
				throw new HttpError(1901);
			}

			const labelInfos = await this.userModel.getContactLabelsByIds(pid, labelIds);
			if (labelInfos.length !== labelIds.length) throw new HttpError(1916); // 존재하지 않는 라벨을 요청했습니다.

			const contact = await this.contactModel.createContact({ pid, email, memo, labelIds });

			return this.flattenContact(contact);
		} catch (err) {
			throw err;
		}
	}

	// 주소록 일괄 등록
	async createBulkContacts(dto) {
		try {
			const { pid, users } = dto;

			if (!users || users.length === 0) {
				return {
					summary: { totalCount: 0, successCount: 0, failedCount: 0 },
					results: [],
					errors: [],
				};
			}

			// 1. 사전 데이터 조회 (한 번에)
			const emails = users.map(user => user.email).filter(Boolean);
			const allLabelNames = new Set();
			users.forEach(user => {
				for (let i = 1; i <= 5; i++) {
					if (user[`label${i}`]) allLabelNames.add(user[`label${i}`]);
				}
			});

			const [userProfiles, existingContacts, userLabels] = await Promise.all([
				emails.length > 0 ? this.userModel.findUserProfileByEmails(emails) : [],
				emails.length > 0 ? this.contactModel.getContactsByEmails(pid, emails) : [],
				allLabelNames.size > 0 ? this.userModel.getContactLabelsByNames(pid, Array.from(allLabelNames)) : [],
			]);

			const validatingDto = { users, pid, userProfiles, existingContacts, userLabels };
			const validatedResult = contactBulkUtils.validateBulkContacts(validatingDto);
			const { results, globalErrors, usersToCreate, labelMap } = validatedResult;

			// 3. 검증 통과한 행만 DB에 저장
			if (usersToCreate.length > 0) {
				await this.contactModel.createBulkContactsWithLabels({ pid, usersToCreate, labelMap });
			}

			const result = contactBulkUtils.buildBulkContactsResponse({ users, usersToCreate, results, globalErrors });
			return result;
		} catch (err) {
			throw err;
		}
	}

	// 주소록 즐겨찾기 상태 변경
	async updateContactFavorite({ pid }, contactIds, isFavorite) {
		try {
			const contacts = await this.contactModel.findContactByIds(pid, contactIds);
			if (contacts.length !== contactIds.length) throw new HttpError(1902);

			await this.contactModel.updateContactFavorite(contactIds, isFavorite);
		} catch (err) {
			throw err;
		}
	}

	// 주소록 휴지통 이동 상태 변경
	async updateContactRecycle(user, contactIds, isRecycle) {
		try {
			const contacts = await this.contactModel.findContactByIds(user.pid, contactIds);
			if (contacts.length !== contactIds.length) throw new HttpError(1902);

			// 이미 요청한 상태값과 동일한 항목은 큐에 중복 등록하지 않도록 제외
			const targetContactIds = contacts
				.filter(contact => contact.isRecycle !== isRecycle)
				.map(contact => contact.id);
			if (targetContactIds.length === 0) return;

			// 변경이 필요한 연락처만 큐에 추가하거나 기존 큐 작업을 취소
			if (isRecycle === true) {
				await Promise.all(
					targetContactIds.map(contactId => contactUtils.addContactRecycleTask(contactId, user))
				);
			} else {
				await Promise.all(targetContactIds.map(contactId => contactUtils.cancelContactRecycleTask(contactId)));
			}

			// 큐 작업이 성공적으로 등록/취소된 항목만 실제 DB 상태를 갱신
			await this.contactModel.updateContactRecycle(targetContactIds, isRecycle);
		} catch (err) {
			throw err;
		}
	}

	// 주소록 다중 삭제
	async deleteContacts({ pid }, contactIds) {
		try {
			// 주소록 존재 여부 체크
			const contacts = await this.contactModel.findContactByIds(pid, contactIds);
			if (contacts.length !== contactIds.length) throw new HttpError(1902);

			// 자신의 pid인지 확인
			const invalidContacts = contacts.filter(contact => contact.pid !== pid);
			if (invalidContacts.length > 0) throw new HttpError(1903);

			// 주소록 다중 삭제
			await this.contactModel.deleteContacts(contactIds);
		} catch (err) {
			throw err;
		}
	}

	// 주소록 목록 조회
	async getContacts({ pid }, options) {
		try {
			const { contacts, _count } = await this.contactModel.getContactsAndCount(pid, options);

			if (contacts.length === 0) return [];

			const result = contacts.map(contact => {
				return this.flattenContact(contact);
			});

			return {
				_count,
				currentPage: options.page,
				lastPage: options.take === 0 ? 0 : Math.ceil(_count / options.take),
				contacts: result,
			};
		} catch (err) {
			throw err;
		}
	}

	// 주소록 삭제(deprecated)
	async deleteContact({ pid }, contactId) {
		try {
			const contact = await this.contactModel.findContactById(pid, contactId);
			if (!contact) throw new HttpError(1902);

			if (contact.pid !== pid) throw new HttpError(1302);

			return await this.contactModel.deleteContact(contactId);
		} catch (err) {
			throw err;
		}
	}

	// 주소록 수정
	async updateContact({ pid }, contactId, { memo, labelIds }) {
		try {
			const contact = await this.contactModel.findContactById(pid, contactId);
			if (!contact) throw new HttpError(1902);

			// 라벨 업데이트가 요청된 경우 유효성 확인 (빈 배열은 모든 라벨 제거이므로 검증 불필요)
			if (labelIds !== undefined && labelIds.length > 0) {
				const validLabels = await this.userModel.getContactLabelsByIds(pid, labelIds);
				if (validLabels.length !== labelIds.length)
					throw new HttpError(1916, '존재하지 않는 라벨이 포함되어 있습니다');
			}

			// 주소록 및 라벨링 업데이트 (memo와 labelIds는 선택적)
			const updatedContact = await this.contactModel.updateContact(contactId, { memo, labelIds });

			return this.flattenContact(updatedContact);
		} catch (err) {
			throw err;
		}
	}

	// 여러 주소록에 라벨링 업데이트
	async updateContactLabelingBatch({ pid }, contactIds, labelIds) {
		try {
			// 주소록 유효성 확인 (존재 여부 및 권한 확인)
			const contacts = await this.contactModel.findContactByIds(pid, contactIds);
			if (contacts.length !== contactIds.length)
				throw new HttpError(1902, '존재하지 않는 주소록이 포함되어 있습니다');

			// 라벨 유효성 확인 (존재 여부 및 권한 확인)
			const validLabels = await this.userModel.getContactLabelsByIds(pid, labelIds);
			if (validLabels.length !== labelIds.length)
				throw new HttpError(1916, '존재하지 않는 라벨이 포함되어 있습니다');

			// 기존 라벨 연결 제거 후 새로운 라벨 연결
			await this.contactModel.updateContactLabelsBatch(contactIds, labelIds);
		} catch (err) {
			throw err;
		}
	}

	// 라벨 생성
	async createContactLabel({ pid }, name, color) {
		try {
			const exists = await this.userModel.checkContactLabelExists(pid, name);
			if (exists) throw new HttpError(1915);

			const label = await this.userModel.createContactLabel({ pid, name, color });
			return label;
		} catch (err) {
			throw err;
		}
	}

	// 라벨 목록 조회
	async getContactLabels({ pid }) {
		try {
			const labels = await this.userModel.getContactLabelsByPid(pid);
			if (!labels) return [];
			return labels;
		} catch (err) {
			throw err;
		}
	}

	// 라벨 삭제
	async deleteContactLabel({ pid }, labelId) {
		try {
			const label = await this.userModel.findContactLabelById(labelId);
			if (!label) throw new HttpError(1916);
			if (label.pid !== pid) throw new HttpError(1302);

			// 해당 라벨과 연결된 주소록의 라벨 연결 해제
			await this.userModel.disconnectLabelFromContacts(labelId);

			// 라벨 삭제
			await this.userModel.deleteContactLabel(labelId);
		} catch (err) {
			throw err;
		}
	}

	// 라벨 수정
	async updateContactLabel({ pid }, labelId, name, color) {
		try {
			const label = await this.userModel.findContactLabelById(labelId);
			if (!label) throw new HttpError(1916);
			if (label.pid !== pid) throw new HttpError(1302);

			// 중복 체크
			const existingLabel = await this.userModel.checkContactLabelExists(pid, name);
			if (existingLabel) throw new HttpError(1915);

			const result = await this.userModel.updateContactLabel(labelId, name, color);

			return result;
		} catch (err) {
			throw err;
		}
	}

	// 주소록 검색
	async searchContacts({ pid }, options) {
		try {
			const contacts = await this.contactModel.searchContacts(pid, options);

			const result = contacts.map(contact => this.flattenContact(contact));

			return {
				_count: contacts.length,
				currentPage: options.page,
				lastPage: options.take === 0 ? 0 : Math.ceil(contacts.length / options.take),
				contacts: result,
			};
		} catch (err) {
			throw err;
		}
	}

	async getUsage(user, { member }, type) {
		console.time('getUsage');
		const { pid, email } = user;
		const { id: memberId } = member;
		const dateRange = getSearchRange(type);

		log.i(`[${pid} ${email}] 기준일 : ${type} ${JSON.stringify(dateRange)}`);

		const isMonthPeriod = type && type.includes('month') && !type.includes('week');

		if (isMonthPeriod) {
			log.i(`[${pid} ${email}] Month 단위 통계 조회 - 최적화 모드 적용`);
		}

		// 회의록 등록 현황 && 녹음 및 업로드 시간 현황
		const [contents, downloadHistory, sharedStats, reSummaryHistory, corpusStats, contactStats] = await Promise.all(
			[
				this.contentModel.getUserContents(pid, dateRange),
				this.downloadHistoryModel.getDownloadHistory(email, dateRange),
				this.contentCaptureModel.getSharedCounts(email, memberId, dateRange),
				this.reSummaryHistoryModel.getReSummaryHistory(pid, dateRange),
				this.corpusModel.getCorpusCount(memberId, dateRange),
				this.contactModel.getContactCount(pid, dateRange),
			]
		);

		// 등록 현황
		const contentStats = usageUtil.getContentsRegistrationStats(contents);

		// 시간대별, 일자별 녹음,업로드 통계
		const statisticsData = usageUtil.getStatisticsByType(contents, type, dateRange, isMonthPeriod);

		// 파일 다운로드 현황
		const downloadStats = usageUtil.getDownloadStats(downloadHistory);

		// 요약 요청 현황
		const reSummaryStats = usageUtil.getReSummaryStats(reSummaryHistory);

		// HitMap 용 데이터
		const statiscsChartData = usageUtil.getStatisticsRecordChartData(contents, type, dateRange, isMonthPeriod);

		console.timeEnd('getUsage');
		return {
			...contentStats,
			statisticsData,
			downloadStats,
			sharedStats,
			reSummaryStats,
			corpusStats,
			contactStats,
			statiscsChartData,
		};
	}

	// 개인 폴더 생성
	async createFolder(user, name) {
		try {
			// 8개 초과인 경우 생성 불가
			const folders = await this.userModel.getFolders(user.pid);
			if (folders.length >= process.env.FOLDER_MAX_COUNT) throw new HttpError(1907); // 더 이상 폴더를 생성할 수 없습니다.

			return await this.userModel.createFolder(user, name);
		} catch (err) {
			throw err;
		}
	}

	// 개인 폴더 목록 조회
	async getFolders(user, workspaceId) {
		try {
			// 워크스페이스 설정: '내 회의록'에 공유받은 회의록 병합 (bo-api KeyName.MERGE_SHARED_INTO_MY_MEETINGS)
			const mergeSharedIntoMy = await this.userModel.getWorkspaceBooleanSetting(
				workspaceId,
				'merge_shared_into_my_meetings'
			);

			// 실제 폴더 조회와 가상 폴더 개수 계산을 병렬로 실행
			const [virtualCounts, result] = await Promise.all([
				this.getVirtualFolderCounts(user),
				this.userModel.getFolders(user.pid),
			]);

			// 1. 가상 폴더 처리 (항상 필요)
			let virtualFolderConfigs = folderUtils
				.getVirtualFolderConfigs()
				.filter(config => config.id !== folderUtils.VIRTUAL_FOLDER.SENT);

			// 설정 ON: '공유 받은 회의록'(received) 폴더를 숨기고 그 개수를 '내 회의록'(success)에 합산
			if (mergeSharedIntoMy) {
				virtualFolderConfigs = virtualFolderConfigs.filter(
					config => config.id !== folderUtils.VIRTUAL_FOLDER.RECEIVED
				);
				virtualCounts.success = (virtualCounts.success || 0) + (virtualCounts.received || 0);
			}

			const virtualFolders = virtualFolderConfigs.map(config => ({
				id: config.id,
				name: config.name,
				_count: virtualCounts[config.id],
			}));

			// 2. 실제 폴더 처리 (있을 때만)
			const realFolders = result?.length > 0 ? await this.processRealFolders(result, user) : [];

			// 가상 폴더 + 실제 폴더 순서로 반환
			return [...virtualFolders, ...realFolders];
		} catch (err) {
			throw err;
		}
	}

	// 실제 폴더 데이터 처리
	async processRealFolders(folders, user) {
		const folderIds = folders.map(folder => folder.id);

		// 내가 생성한 콘텐츠와 공유받은 콘텐츠의 폴더별 개수를 병렬로 조회
		const [myContentCount, sharedContentCount] = await Promise.all([
			this.userModel.getMyContentCountByFolders(folderIds, user.pid),
			this.userModel.getSharedContentCountByFolders(folderIds, user.email),
		]);

		// folderId별로 개수 합계 계산
		const countMap = {};
		folderIds.forEach(folderId => {
			countMap[folderId] = 0;
		});

		// 내가 생성한 콘텐츠 개수 추가
		myContentCount.forEach(item => {
			if (item.folderId) {
				countMap[item.folderId] = (countMap[item.folderId] || 0) + item._count;
			}
		});

		// 공유받은 콘텐츠 개수 추가
		sharedContentCount.forEach(item => {
			if (item.folderId) {
				countMap[item.folderId] = (countMap[item.folderId] || 0) + item._count;
			}
		});

		// 실제 폴더들 매핑 및 createAt 기준 정렬
		return folders
			.map(folder => ({
				id: folder.id,
				name: folder.name,
				createAt: folder.createAt,
				updateAt: folder.updateAt,
				_count: countMap[folder.id] || 0,
			}))
			.sort((a, b) => new Date(a.createAt) - new Date(b.createAt));
	}

	// 가상 폴더들의 콘텐츠 개수 통합 계산
	async getVirtualFolderCounts(user) {
		try {
			const { pid, email } = user;

			// 내가 생성한 콘텐츠 통계와 공유받은 콘텐츠(전체/미분류) 개수를 병렬로 조회
			const [myContentStats, totalSharedCount, unfiledSharedCount] = await Promise.all([
				this.userModel.getMyContentStats(pid),
				this.userModel.getSharedContentCount(email),
				this.userModel.getUnfiledSharedContentCount(email),
			]);

			return {
				root: myContentStats.total + totalSharedCount,
				success: myContentStats.done,
				error: myContentStats.error,
				received: unfiledSharedCount,
			};
		} catch (err) {
			throw err;
		}
	}

	// 개인 폴더 수정
	async updateFolder(user, id, name) {
		try {
			// 가상 폴더는 수정할 수 없음
			if (folderUtils.isVirtualFolder(id)) {
				throw new HttpError(1913); // '이 폴더는 수정할 수 없습니다.'
			}

			// 폴더 존재 여부 체크
			const folder = await this.userModel.findFolderById(id);
			if (!folder) throw new HttpError(1903); // 존재하지 않는 폴더입니다.

			if (folder.pid !== user.pid) throw new HttpError(1302); // 권한이 없습니다.

			return await this.userModel.updateFolder(id, name);
		} catch (err) {
			throw err;
		}
	}

	// 개인 폴더 삭제
	async deleteFolder(user, auth, folderId) {
		try {
			// 가상 폴더는 삭제할 수 없음
			if (folderUtils.isVirtualFolder(folderId)) {
				throw new HttpError(1910); // '이 폴더는 삭제할 수 없습니다.'
			}

			const folder = await this.userModel.findFolderById(folderId);
			if (!folder) throw new HttpError(1903); // 존재하지 않는 폴더입니다.
			if (folder.pid !== user.pid) throw new HttpError(1302); // 권한이 없습니다.

			// 폴더 항목들 조회
			const contents = await this.getFolderItems(user, { folderId });
			const contentIds = contents.map(content => content.contentId);

			// 항목이 있는 경우 휴지통 이동
			if (contentIds.length > 0) {
				await contentService.removeBulkContentsFromList(contentIds, auth, user);
			}
			// 폴더 삭제
			await this.userModel.deleteFolder(user.pid, folderId);
		} catch (err) {
			throw err;
		}
	}

	// 폴더 항목들 조회
	async getFolderItems(user, options, workspaceId) {
		try {
			const { folderId } = options;

			// 실제 폴더인 경우 권한 검증
			if (!folderUtils.isVirtualFolder(folderId)) {
				const folder = await this.userModel.findFolderById(folderId);
				if (!folder) throw new HttpError(1903); // 존재하지 않는 폴더입니다.
				if (folder.pid !== user.pid) throw new HttpError(1302); // 권한이 없습니다.
			}

			// 워크스페이스 설정: '내 회의록'(success)에 공유받은 회의록 병합 (가상 폴더에서만 조회)
			const mergeSharedIntoMy = folderUtils.isVirtualFolder(folderId)
				? await this.userModel.getWorkspaceBooleanSetting(workspaceId, 'merge_shared_into_my_meetings')
				: false;

			// 공통 폴더 필터링 로직 사용
			const filteredOptions = await folderUtils.applyFolderFiltering(
				user.pid,
				user.email,
				folderId,
				options,
				mergeSharedIntoMy
			);

			const contents = await this.contentModel.getContents(user.pid, filteredOptions);

			return await getContentsResponseWithIds(contents, user.email, user.pid);
		} catch (err) {
			throw err;
		}
	}

	// 폴더 항목들 이동
	async moveContentToFolder(user, contentIds, folderId) {
		try {
			// 1. 접근 가능한 콘텐츠 조회 및 소유권 정보 확인
			const { accessibleContents, myOwnContentIds, sharedContentIdSet, errorContentIds } =
				await contentService.getAccessibleContentsWithOwnership(contentIds, user);

			// 2. 에러 콘텐츠는 이동 불가능
			if (errorContentIds.length > 0) throw new HttpError(1914); // '에러 콘텐츠는 이동할 수 없습니다.'

			// 요청된 콘텐츠 중에서 공유받은 콘텐츠만 필터링
			const sharedContentIdsToMove = contentIds.filter(id => sharedContentIdSet.has(id));

			if (accessibleContents.length === 0) throw new HttpError(1904); // 존재하지 않는 콘텐츠
			if (accessibleContents.length !== contentIds.length) throw new HttpError(1185); // 접근 불가능한 콘텐츠가 포함되어 있습니다.

			// 3. 폴더 타입별 처리
			if (folderId === folderUtils.VIRTUAL_FOLDER.ROOT) {
				if (myOwnContentIds.length > 0) {
					await this.userModel.removeContentsInMyFolders(user.pid, myOwnContentIds);
				}
				if (sharedContentIdsToMove.length > 0) {
					await this.userModel.removeSharedContentsFromFolders(user.email, sharedContentIdsToMove);
				}
			} else if (folderId === folderUtils.VIRTUAL_FOLDER.RECEIVED) {
				if (myOwnContentIds.length > 0) {
					throw new HttpError(1909); // '내 생성 콘텐츠는 공유 받은 폴더로 이동 불가'
				}
				if (sharedContentIdsToMove.length > 0) {
					await this.userModel.removeSharedContentsFromFolders(user.email, sharedContentIdsToMove);
				}
			} else if (folderId === folderUtils.VIRTUAL_FOLDER.SENT || folderId === folderUtils.VIRTUAL_FOLDER.ERROR) {
				throw new HttpError(1911); // '이 폴더로 이동할 수 없습니다.'
			} else if (folderId === folderUtils.VIRTUAL_FOLDER.SUCCESS) {
				if (myOwnContentIds.length > 0) {
					await this.userModel.removeContentsInMyFolders(user.pid, myOwnContentIds);
				}
				if (sharedContentIdsToMove.length > 0) {
					throw new HttpError(1912); // '공유 받은 콘텐츠는 이 폴더로 이동할 수 없습니다.'
				}
			} else {
				// 실제 폴더로 이동
				const folder = await this.userModel.findFolderById(folderId);
				if (!folder) throw new HttpError(1903); // 존재하지 않는 폴더입니다.
				if (folder.pid !== user.pid) throw new HttpError(1302); // 권한이 없습니다.

				if (myOwnContentIds.length > 0) {
					await this.userModel.moveContentsToFolder(user.pid, myOwnContentIds, folderId);
				}
				if (sharedContentIdsToMove.length > 0) {
					await this.userModel.moveSharedContentsToFolder(user.email, sharedContentIdsToMove, folderId);
				}
			}
		} catch (err) {
			throw err;
		}
	}

	async getUserNotificationSetting({ pid }) {
		try {
			return await this.userModel.getUserNotificationSetting(pid);
		} catch (err) {
			throw err;
		}
	}

	async updateUserNotificationSetting({ pid }, data) {
		try {
			return await this.userModel.updateUserNotificationSetting(pid, data);
		} catch (err) {
			throw err;
		}
	}

	async getUserNotificationManagement({ pid }, workspaceId) {
		try {
			const channels = Object.values(Enums.UserNotificationChannel);
			const eventTypes = Object.values(Enums.UserNotificationEventType);

			// 관리자 강제 모드: 개인 설정 무시하고 워크스페이스 관리자 기본값으로 반환
			const userManaged = await this.userModel.getWorkspaceUseNotificationSetting(workspaceId);
			if (!userManaged) {
				const defaults = await this.userModel.getWorkspaceNotificationDefaults(workspaceId);
				const allCombinations = [];
				channels.forEach(channel => {
					eventTypes.forEach(eventType => {
						const adminValue = defaults[notiDefaultKey(eventType, channel)];
						allCombinations.push({
							channel,
							eventType,
							isUsed: adminValue !== undefined ? adminValue : true,
						});
					});
				});
				return allCombinations;
			}

			// 개인 관리 모드(기본): 사용자 설정 기준, 행이 없으면 기본 On
			const result = await this.userModel.getUserNotificationManagement(pid);

			const existingDataMap = new Map();
			result.forEach(item => {
				const key = `${item.channel}_${item.eventType}`;
				existingDataMap.set(key, item.isUsed);
			});

			const allCombinations = [];
			channels.forEach(channel => {
				eventTypes.forEach(eventType => {
					const key = `${channel}_${eventType}`;
					const existingValue = existingDataMap.get(key);
					allCombinations.push({
						channel,
						eventType,
						isUsed: existingValue !== undefined ? existingValue : true,
					});
				});
			});

			return allCombinations;
		} catch (err) {
			throw err;
		}
	}

	async updateUserNotificationManagementIsUsed({ pid }, notifications, workspaceId) {
		try {
			// 관리자 강제 모드에서는 개인이 알림 설정을 수정할 수 없음 (화면 숨김 + API 방어)
			const userManaged = await this.userModel.getWorkspaceUseNotificationSetting(workspaceId);
			if (!userManaged) throw new HttpError(1302);

			return await this.userModel.upsertUserNotificationManagementIsUsed(pid, notifications);
		} catch (err) {
			throw err;
		}
	}

	// 사용자의 각 약관별 최신 동의 이력 조회
	async getLatestUserAgreementsByTermsIds(email, termsIds) {
		try {
			const agreements = await this.userModel.getUserAgreementsByTermsIds(email, termsIds);

			// 각 약관별로 최신 동의 이력만 필터링
			const latestAgreements = [];
			const processedTermsIds = new Set();

			for (const agreement of agreements) {
				if (!processedTermsIds.has(agreement.termsId)) {
					latestAgreements.push(agreement);
					processedTermsIds.add(agreement.termsId);
				}
			}

			return latestAgreements;
		} catch (err) {
			throw err;
		}
	}

	// 약관 데이터 포맷팅 헬퍼 함수
	formatTermsWithAgreements(publishedTerms, agreementMap = new Map()) {
		return publishedTerms.map(term => {
			const latestAgreement = agreementMap.get(term.id);

			return {
				id: term.id,
				title: term.title,
				content: term.content,
				isRequired: term.isRequired,
				category: {
					id: term.category.id,
					name: term.category.name,
					priority: term.category.priority,
				},
				version: term.version,
				publishedAt: term.publishedAt,
				// 최신 동의 상태 추가
				latestAgreement:
					latestAgreement ?
						{
							id: latestAgreement.id,
							status: latestAgreement.status,
							createAt: latestAgreement.createAt,
						}
					:	null,
				// 프론트엔드에서 체크박스 상태 판단용
				isConsented: latestAgreement ? latestAgreement.status === Enums.AgreementStatus.CONSENTED : false,
			};
		});
	}

	// 약관 동의 상태 조회
	async getTermsConsentStatus({ email }, workspaceId) {
		try {
			// 워크스페이스 ID 검증
			if (!workspaceId) throw new HttpError(1000, '워크스페이스 정보가 없습니다');

			// 1. 워크스페이스 권한 조회 및 시행중인 약관들 조회
			const [workspaceAgreementSettings, publishedTerms] = await Promise.all([
				this.userModel.getWorkspaceAgreementSettings(workspaceId),
				this.userModel.getPublishedTermsByWorkspace(workspaceId),
			]);

			const isAgreementEnforced = workspaceAgreementSettings.some(setting => setting && setting.value === 'true');

			// 2. 조기 종료 조건 체크 (불필요한 DB 호출 방지)
			if (!isAgreementEnforced || publishedTerms.length === 0) {
				return {
					isAgreementEnforced,
					needConsent: false,
					publishedTerms: this.formatTermsWithAgreements(publishedTerms),
				};
			}

			const termsIds = publishedTerms.map(term => term.id);

			// 3. 각 약관별 최신 동의 이력 조회
			const latestAgreements = await this.getLatestUserAgreementsByTermsIds(email, termsIds);

			// 4. 성능 최적화: 배열을 Map으로 변환
			const agreementMap = new Map(latestAgreements.map(agreement => [agreement.termsId, agreement]));

			// 5. 필수 약관 중에서 동의가 필요한지 확인
			let needConsent = false;
			for (const term of publishedTerms) {
				if (term.isRequired) {
					const latestAgreement = agreementMap.get(term.id);

					// 동의 이력이 없거나, 최신 이력이 거부인 경우
					if (!latestAgreement || latestAgreement.status !== Enums.AgreementStatus.CONSENTED) {
						needConsent = true;
						break;
					}
				}
			}

			// 6. 응답 데이터 포맷팅 - 재사용 함수 호출
			const formattedTerms = this.formatTermsWithAgreements(publishedTerms, agreementMap);

			return { isAgreementEnforced, needConsent, publishedTerms: formattedTerms };
		} catch (err) {
			throw err;
		}
	}

	// 약관 동의서 제출
	async createTermsAgreement({ userName, email }, { agreements }, { ipAddress, userAgent, workspaceId }) {
		try {
			// 1. 약관 ID 추출 및 중복 제거
			const termsIds = [...new Set(agreements.map(agreement => agreement.termsId))];

			// 2. 워크스페이스에서 해당 약관들이 시행중인지 확인
			const publishedTerms = await this.userModel.getTermsByIds(workspaceId, termsIds);
			if (publishedTerms.length !== termsIds.length) {
				throw new HttpError(1000, '존재하지 않거나 시행중이 아닌 약관이 포함되어 있습니다');
			}

			// 3. 필수 약관 거부 여부 확인
			const requiredTerms = publishedTerms.filter(term => term.isRequired);
			const declinedRequiredTerms = agreements.filter(agreement => {
				const term = requiredTerms.find(t => t.id === agreement.termsId);
				return term && agreement.status === Enums.AgreementStatus.DECLINED;
			});

			if (declinedRequiredTerms.length > 0) {
				const declinedTermsTitles = declinedRequiredTerms.map(agreement => {
					const term = publishedTerms.find(t => t.id === agreement.termsId);
					return term.title;
				});
				throw new HttpError(1000, `필수 약관에 동의가 필요합니다: ${declinedTermsTitles.join(', ')}`);
			}

			// 4. 현재 사용자의 각 약관별 최신 동의 이력 조회 (email 기반)
			const latestAgreements = await this.getLatestUserAgreementsByTermsIds(email, termsIds);

			// 5. 성능 최적화: 배열을 Map으로 변환 (O(n²) → O(n))
			const latestAgreementMap = new Map(latestAgreements.map(agreement => [agreement.termsId, agreement]));

			// 6. 동의서 생성이 필요한 약관들 필터링
			const agreementsToCreate = [];

			for (const agreement of agreements) {
				const latestAgreement = latestAgreementMap.get(agreement.termsId);

				// 최신 동의 상태와 다르거나 동의 이력이 없는 경우만 생성
				if (!latestAgreement || latestAgreement.status !== agreement.status) {
					agreementsToCreate.push(agreement);
				}
			}

			// 7. 새로운 동의서 레코드 생성
			const createdAgreements = [];
			for (const agreement of agreementsToCreate) {
				const createdAgreement = await this.userModel.createTermsAgreement({
					userName,
					email,
					termsId: agreement.termsId,
					status: agreement.status,
					ipAddress,
					userAgent,
					workspaceId,
				});
				createdAgreements.push(createdAgreement);
			}

			return {
				createdCount: createdAgreements.length,
				skippedCount: agreements.length - createdAgreements.length,
				createdAgreements: createdAgreements.map(agreement => ({
					id: agreement.id,
					termsId: agreement.termsId,
					status: agreement.status,
					createAt: agreement.createAt,
				})),
			};
		} catch (err) {
			throw err;
		}
	}
}

export default new UserService();
