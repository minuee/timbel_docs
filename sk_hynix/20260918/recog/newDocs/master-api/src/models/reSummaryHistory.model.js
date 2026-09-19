import BaseDatabase from '@timbel-timblo-onpremise/prisma';
class ReSummaryHistoryModel extends BaseDatabase {
	constructor() {
		super('ReSummaryHistoryModel');
	}

	async createReSummaryHistory(contentId, requesterId, summarySize) {
		return await this.mariaDB.reSummaryHistory.create({
			data: {
				content: {
					connect: {
						contentId: contentId,
					},
				},
				requester: {
					connect: {
						pid: requesterId,
					},
				},
				summarySize: summarySize.toUpperCase(),
			},
		});
	}

	async getReSummaryHistory(requesterId, { startDate, endDate }) {
		return await this.mariaDB.reSummaryHistory.findMany({
			where: {
				requesterId,
				requestedAt: {
					gte: startDate,
					lt: endDate,
				},
			},
			select: {
				summarySize: true,
			},
		});
	}
}

export default new ReSummaryHistoryModel();
