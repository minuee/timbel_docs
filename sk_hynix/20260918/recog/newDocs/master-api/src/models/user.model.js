import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class UserModel extends BaseDatabase {
	constructor() {
		super('UserModel');
	}

	/**
	 * @param {string} pid
	 * @description 사용자 정보 조회
	 */

	async getUserInfoByUserId(pid) {
		return await this.mariaDB.userProfile.findUnique({
			where: {
				pid,
			},
			select: {
				pid: true,
				nickName: true,
				email: true,
				thumbnailUrl: true,
			},
		});
	}

	async getUserInfosByUserIds(pids) {
		return await this.mariaDB.userProfile.findMany({
			where: {
				pid: {
					in: pids,
				},
			},
			select: {
				pid: true,
				nickName: true,
				email: true,
				thumbnailUrl: true,
			},
		});
	}

	async findUserProfileByEmail(email) {
		return await this.mariaDB.userProfile.findFirst({
			where: {
				email,
			},
		});
	}

	async findUserProfileByEmails(emails) {
		return await this.mariaDB.userProfile.findMany({
			where: {
				email: {
					in: emails,
				},
			},
			select: {
				pid: true,
				email: true,
			},
		});
	}

	async getMembersFromWorkspace(memberPids, keyword) {
		return await this.mariaDB.userProfile.findMany({
			where: {
				OR: [
					{ AND: [{ pid: { in: memberPids } }, { name: { contains: keyword } }] },
					{ AND: [{ pid: { in: memberPids } }, { nickName: { contains: keyword } }] },
					{ AND: [{ pid: { in: memberPids } }, { email: { contains: keyword } }] },
				],
			},
		});
	}

	async getUserByEmail(email) {
		return this.mariaDB.user.findFirst({
			where: {
				profile: {
					email: {
						equals: email,
					},
				},
			},
			select: {
				profile: {
					select: {
						pid: true,
						email: true,
						nickName: true,
						thumbnailUrl: true,
						company: {
							select: {
								empno: true,
								userId: true,
								platform: true,
								deptName: true,
								deptCode: true,
								companyCode: true,
							},
						},
					},
				},
				config: {
					select: {
						locale: true,
						summarizer: true,
						transcribeLang: true,
						transcribeEngine: true,
					},
				},
			},
		});
	}

	// 개인 폴더 생성
	async createFolder(user, name) {
		return await this.mariaDB.folder.create({
			data: { pid: user.pid, name },
		});
	}

	// 개인 폴더 존재 여부 조회
	async findFolderById(id) {
		return await this.mariaDB.folder.findUnique({
			where: { id },
		});
	}

	// 개인 폴더명 조회
	async findFolderByName(pid, name) {
		return await this.mariaDB.folder.findFirst({
			where: { pid, name },
		});
	}

	// 개인 폴더 목록 조회
	async getFolders(pid) {
		return await this.mariaDB.folder.findMany({
			where: { pid },
			orderBy: { name: 'asc' },
		});
	}

	// 특정 폴더로 콘텐츠 이동
	async moveContentsToFolder(pid, contentIds, targetFolderId) {
		return await this.mariaDB.content.updateMany({
			where: {
				creator: { pid },
				contentId: { in: contentIds },
			},
			data: {
				folderId: targetFolderId,
			},
		});
	}

	// 콘텐츠들을 개인의 모든 폴더에서 제거 (root로 이동)
	async removeContentsInMyFolders(pid, contentIds) {
		return await this.mariaDB.content.updateMany({
			where: {
				creator: { pid },
				contentId: { in: contentIds },
			},
			data: {
				folderId: null,
			},
		});
	}

	// 이미 폴더에 있는 특정 콘텐츠 확인
	async existContentsInFolder(pid, folderId, contentIds) {
		return await this.mariaDB.content.findMany({
			where: {
				creator: { pid },
				folderId,
				contentId: { in: contentIds },
			},
			select: { contentId: true },
		});
	}

	// 특정 폴더내의 내가 생성한 콘텐츠 contentIds 조회
	async getMyContentIdsByFolderId(folderId) {
		return await this.mariaDB.content.findMany({
			where: { folderId },
			select: { contentId: true },
		});
	}

	// 특정 폴더내의 공유받은 콘텐츠 contentIds 조회
	async getSharedContentIdsByFolderId(folderId, email) {
		return await this.mariaDB.contentShareUser.findMany({
			where: { folderId, email },
			select: { contentId: true },
		});
	}

	// 내가 생성한 콘텐츠의 폴더별 개수 조회
	async getMyContentCountByFolders(folderIds, pid) {
		return await this.mariaDB.content.groupBy({
			where: {
				creator: { pid },
				folderId: { in: folderIds },
			},
			by: ['folderId'],
			_count: true,
		});
	}

	// 공유받은 콘텐츠의 폴더별 개수 조회
	async getSharedContentCountByFolders(folderIds, email) {
		return await this.mariaDB.contentShareUser.groupBy({
			where: {
				email,
				folderId: { in: folderIds },
			},
			by: ['folderId'],
			_count: true,
		});
	}

	// 내가 생성한 콘텐츠 총 개수 조회
	async getMyContentCount(pid) {
		return await this.mariaDB.content.count({
			where: {
				creator: { pid },
				isDeleted: false,
			},
		});
	}

	// 공유받은 콘텐츠 총 개수 조회
	async getSharedContentCount(email) {
		return await this.mariaDB.contentShareUser.count({
			where: {
				email,
			},
		});
	}

	// 공유받은 콘텐츠 중 실제 폴더에 속하지 않은(미분류) 개수 조회
	async getUnfiledSharedContentCount(email) {
		return await this.mariaDB.contentShareUser.count({
			where: {
				email,
				folderId: null,
			},
		});
	}

	// 내가 생성한 콘텐츠 중 특정 상태의 개수 조회
	async getMyContentCountByStatus(pid, status) {
		return await this.mariaDB.content.count({
			where: {
				creator: { pid },
				transcribeStatus: status,
				isDeleted: false,
			},
		});
	}

	// 내가 생성한 콘텐츠의 상태별 통계 조회
	async getMyContentStats(pid) {
		const result = await this.mariaDB.content.groupBy({
			where: {
				creator: { pid },
				isDeleted: false,
			},
			by: ['transcribeStatus'],
			_count: true,
		});

		const stats = { total: 0, done: 0, error: 0, waiting: 0 };
		result.forEach(item => {
			const status = item.transcribeStatus.toLowerCase();
			if (stats.hasOwnProperty(status)) {
				stats[status] = item._count;
			}
			stats.total += item._count;
		});

		return stats;
	}

	// 공유받은 콘텐츠들을 특정 폴더로 이동
	async moveSharedContentsToFolder(email, contentIds, targetFolderId) {
		return await this.mariaDB.contentShareUser.updateMany({
			where: {
				email,
				contentId: { in: contentIds },
			},
			data: {
				folderId: targetFolderId,
			},
		});
	}

	// 공유받은 콘텐츠들을 폴더에서 제거 (root로 이동)
	async removeSharedContentsFromFolders(email, contentIds) {
		return await this.mariaDB.contentShareUser.updateMany({
			where: {
				email,
				contentId: { in: contentIds },
			},
			data: {
				folderId: null,
			},
		});
	}

	// 개인 폴더 삭제
	async deleteFolder(pid, id) {
		return await this.mariaDB.folder.delete({
			where: { pid, id },
		});
	}

	// 개인 폴더 수정
	async updateFolder(id, name) {
		return await this.mariaDB.folder.update({
			where: { id },
			data: { name },
		});
	}

	async getUserByEmpnoAndCompanyCode({ empno, companyCode }) {
		return await this.mariaDB.userProfile.findFirst({
			where: {
				company: {
					is: {
						empno: {
							equals: empno,
						},
						companyCode: {
							equals: companyCode.toUpperCase(),
						},
					},
				},
			},
			include: {
				company: true,
			},
		});
	}

	async getUserNotificationSetting(pid) {
		return await this.mariaDB.userNotificationSetting.findUnique({
			where: {
				pid,
			},
		});
	}

	async updateUserNotificationSetting(pid, data) {
		return await this.mariaDB.userNotificationSetting.update({
			where: {
				pid,
			},
			data,
		});
	}

	async getUserNotificationManagement(pid, options = null) {
		const where = { pid };

		if (options) {
			const { channel, eventType } = options;
			where.channel = channel;
			where.eventType = eventType;
		}

		return await this.mariaDB.userNotificationManagement.findMany({
			where,
		});
	}

	async createUserNotificationManagement(data) {
		return await this.mariaDB.userNotificationManagement.create({
			data,
		});
	}

	async updateUserNotificationManagementIsUsed(id, data) {
		const { isUsed } = data;
		return await this.mariaDB.userNotificationManagement.update({
			where: {
				id,
			},
			data: {
				isUsed,
			},
		});
	}

	async upsertUserNotificationManagementIsUsed(pid, notifications) {
		return await this.mariaDB.$transaction(async tx => {
			const results = [];
			for (const notification of notifications) {
				const { channel, eventType, isUsed } = notification;
				results.push(
					await tx.userNotificationManagement.upsert({
						where: { pid_channel_eventType: { pid, channel, eventType } },
						create: { pid, channel, eventType, isUsed },
						update: { isUsed },
						select: { channel: true, eventType: true, isUsed: true },
					})
				);
			}
			return results;
		});
	}

	async getWorkspaceAgreementSettings(workspaceId) {
		return await this.mariaDB.workspaceSetting.findMany({
			where: {
				workspaceId,
				key: 'enforce_agreement',
			},
			select: {
				value: true,
			},
		});
	}

	// 워크스페이스 boolean 기능 설정 조회 (행이 없으면 false = 기본값)
	async getWorkspaceBooleanSetting(workspaceId, key) {
		if (!workspaceId) return false;
		const setting = await this.mariaDB.workspaceSetting.findFirst({
			where: { workspaceId, key },
			select: { value: true },
		});
		return setting?.value === 'true';
	}

	// 알림 관리 사용 여부 조회. true = 사용자 개인 관리(기본), false = 관리자 강제 모드.
	// 행이 없으면 기본 true(현행 유지)로 처리한다.
	async getWorkspaceUseNotificationSetting(workspaceId) {
		if (!workspaceId) return true;
		const setting = await this.mariaDB.workspaceSetting.findFirst({
			where: { workspaceId, key: 'use_notification_setting' },
			select: { value: true },
		});
		return setting ? setting.value !== 'false' : true;
	}

	// 워크스페이스 관리자 알림 기본값(notification_default.*) 조회 → { [key]: boolean } 맵.
	async getWorkspaceNotificationDefaults(workspaceId) {
		if (!workspaceId) return {};
		const rows = await this.mariaDB.workspaceSetting.findMany({
			where: { workspaceId, key: { startsWith: 'notification_default_' } },
			select: { key: true, value: true },
		});
		const map = {};
		rows.forEach(row => {
			map[row.key] = row.value === 'true';
		});
		return map;
	}

	// 워크스페이스의 시행중인 약관 조회
	async getPublishedTermsByWorkspace(workspaceId) {
		return await this.mariaDB.terms.findMany({
			where: {
				workspaceId,
				status: this.Enums.TermsStatus.PUBLISHED,
			},
			include: {
				category: { select: { id: true, name: true, priority: true } },
			},
			orderBy: [{ category: { priority: 'asc' } }],
		});
	}

	// 사용자의 약관 동의 이력 조회
	async getUserAgreementsByTermsIds(email, termsIds) {
		return await this.mariaDB.agreement.findMany({
			where: {
				email,
				termsId: { in: termsIds },
			},
			include: {
				terms: {
					select: {
						id: true,
						title: true,
						version: true,
					},
				},
			},
			orderBy: {
				createAt: 'desc',
			},
		});
	}

	// 약관 동의서 생성
	async createTermsAgreement({ userName, email, termsId, status, ipAddress, userAgent, workspaceId }) {
		return await this.mariaDB.agreement.create({
			data: {
				userName,
				email,
				termsId,
				status,
				ipAddress,
				userAgent,
				workspaceId,
			},
		});
	}

	// 특정 약관 ID들로 약관 정보 조회
	async getTermsByIds(workspaceId, termsIds) {
		return await this.mariaDB.terms.findMany({
			where: {
				workspaceId,
				id: {
					in: termsIds,
				},
				status: this.Enums.TermsStatus.PUBLISHED,
			},
			select: {
				id: true,
				title: true,
				isRequired: true,
				workspaceId: true,
			},
		});
	}

	// 라벨 생성
	async createContactLabel({ pid, name, color }) {
		return await this.mariaDB.contactLabel.create({
			data: { pid, name, color },
		});
	}

	// 사용자의 라벨 목록 조회
	async getContactLabelsByPid(pid) {
		return await this.mariaDB.contactLabel.findMany({
			where: { pid },
			orderBy: { createAt: 'asc' },
		});
	}

	// 라벨 ID로 라벨 조회
	async getContactLabelsByIds(pid, ids) {
		return await this.mariaDB.contactLabel.findMany({
			where: { pid, id: { in: ids } },
		});
	}

	// 라벨 이름으로 라벨 조회
	async getContactLabelsByNames(pid, names) {
		return await this.mariaDB.contactLabel.findMany({
			where: { pid, name: { in: names } },
		});
	}

	// 특정 이름의 라벨이 존재하는지 확인
	async checkContactLabelExists(pid, name) {
		const label = await this.mariaDB.contactLabel.findFirst({
			where: { pid, name },
		});
		return !!label;
	}

	// 라벨 삭제
	async deleteContactLabel(id) {
		return await this.mariaDB.contactLabel.delete({
			where: { id },
		});
	}

	// 라벨 수정
	async updateContactLabel(id, name, color) {
		return await this.mariaDB.contactLabel.update({
			where: { id },
			data: { name, color },
		});
	}

	// 라벨 ID로 라벨 조회
	async findContactLabelById(id) {
		return await this.mariaDB.contactLabel.findFirst({
			where: { id },
		});
	}

	// 특정 라벨과 연결된 모든 주소록의 라벨 연결 해제
	async disconnectLabelFromContacts(labelId) {
		return await this.mariaDB.labelOnContact.deleteMany({
			where: { labelId },
		});
	}
}

export default new UserModel();
