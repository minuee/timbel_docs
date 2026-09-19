import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class InboxModel extends BaseDatabase {
	constructor() {
		super('InboxModel');
	}

	async getInboxContentByMemberId(memberId, { startDate, endDate }) {
		const options = {
			orderBy: {
				createAt: 'desc',
			},
			where: {
				receiverId: memberId,
			},
		};

		if (startDate && endDate) {
			options.where.AND = {
				createAt: {
					gte: startDate,
					lt: endDate,
				},
			};
		}

		return await this.mariaDB.inboxContent.findMany(options);
	}

	async updateisReadInbox(inboxId, memberId) {
		return await this.mariaDB.inbox.update({
			where: {
				inboxId,
				receiverId: memberId,
			},
			data: {
				isRead: true,
			},
		});
	}

	async updateisReadInboxByMemberId(memberId) {
		return await this.mariaDB.inbox.updateMany({
			where: {
				receiverId: memberId,
				isRead: false,
			},
			data: {
				isRead: true,
			},
		});
	}

	async deleteInbox(inboxId, memberId) {
		return await this.mariaDB.inbox.update({
			where: {
				inboxId,
				receiverId: memberId,
			},
			data: {
				isDeleted: true,
			},
		});
	}

	async deleteInboxMemberId(memberId) {
		return await this.mariaDB.inbox.updateMany({
			where: {
				receiverId: memberId,
				isDeleted: false,
			},
			data: {
				isDeleted: true,
			},
		});
	}
}

export default new InboxModel();
