import { HttpError } from '../handlers/error.handler.js';
import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class ShareModel extends BaseDatabase {
	constructor() {
		super('ShareModel');
	}

	async getContentShareUsers(contentId) {
		return await this.mariaDB.sharedUserProfile.findMany({
			where: {
				contentId,
			},
		});
	}

	async updateShareUsersPermission(contentId, emails, permission) {
		return await this.mariaDB.contentShareUser.updateMany({
			where: { contentId, email: { in: emails } },
			data: { role: permission },
		});
	}

	// 공유 대상 유저 개별 추가
	async addContentShareUser(contentId, email) {
		return await this.mariaDB.contentShareUser.create({
			data: { contentId, email, role: 'VIEWER' },
		});
	}

	// 공유 대상 유저 다중 추가
	async addContentShareUsers(contentId, emails, role) {
		return await this.mariaDB.contentShareUser.createMany({
			data: emails.map(email => ({ contentId, email, role })),
		});
	}

	async getContentShareUserRole(contentId, email) {
		return await this.mariaDB.contentShareUser.findUnique({
			where: {
				contentId_email: {
					contentId,
					email,
				},
			},
		});
	}

	// 공유 대상 유저 개별 삭제(deprecated)
	async deleteContentShareUser(contentId, email) {
		const shareUser = await this.getContentShareUserRole(contentId, email);

		if (!shareUser) throw new HttpError(1303);

		return await this.mariaDB.contentShareUser.delete({
			where: {
				contentId_email: {
					contentId,
					email,
				},
			},
		});
	}

	/**
	 * 다중 동시 공유 해제용
	 */
	async findSharedContentsToMe(contentIds, email) {
		return await this.mariaDB.contentShareUser.findMany({
			where: { contentId: { in: contentIds }, email },
		});
	}

	async deleteBulkContentsShareUser(contentIds, email) {
		return await this.mariaDB.contentShareUser.deleteMany({
			where: {
				contentId: { in: contentIds },
				email,
			},
		});
	}

	/**
	 * @param {string[]} contentIds
	 * @description 공유된 사용자 정보 조회
	 */
	async getSharedUsers(contentIds) {
		return await this.mariaDB.sharedUserProfile.findMany({
			where: {
				contentId: {
					in: contentIds,
				},
			},
		});
	}

	/**
	 * @param {string} pid - 사용자 PID
	 * @param {Date} startDate - 시작 날짜
	 * @param {Date} endDate - 종료 날짜
	 * @description 내가 공유한 콘텐츠 ID들 조회 (sent)
	 */
	async getSentContentIds(pid, startDate, endDate) {
		const contents = await this.mariaDB.content.findMany({
			where: {
				creator: { pid },
				shareUsers: { some: {} },
				createAt: { gte: startDate, lte: endDate },
			},
			select: { contentId: true },
		});
		return contents.map(content => content.contentId);
	}

	/**
	 * @param {string} email - 사용자 이메일
	 * @param {Date} startDate - 시작 날짜
	 * @param {Date} endDate - 종료 날짜
	 * @description 내가 공유받은 콘텐츠 ID들 조회 (received)
	 */
	async getReceivedContentIds(email, startDate, endDate) {
		const contents = await this.mariaDB.content.findMany({
			where: {
				shareUsers: { some: { email } },
				createAt: { gte: startDate, lte: endDate },
			},
			select: { contentId: true },
		});
		return contents.map(content => content.contentId);
	}
}

export default new ShareModel();
