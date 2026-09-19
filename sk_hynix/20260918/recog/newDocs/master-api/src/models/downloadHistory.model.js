import BaseDatabase from '@timbel-timblo-onpremise/prisma';
class DownloadHistoryModel extends BaseDatabase {
	constructor() {
		super('DownloadHistoryModel');
	}

	async createDownloadHistory(queryDto) {
		const { type, device = this.Enums.DownloadDevice.PC, size, contentTitle, fileName, userName, email } = queryDto;
		const { contentId, workspaceId } = queryDto;
		return await this.mariaDB.downloadHistory.create({
			data: {
				type,
				device,
				size,
				contentTitle,
				fileName,
				userName,
				email,
				workspace: { connect: { id: workspaceId } },
				content: { connect: { contentId } },
			},
		});
	}

	async getDownloadHistory(email, { startDate, endDate }) {
		return await this.mariaDB.downloadHistory.findMany({
			where: {
				email,
				downloadAt: {
					gte: startDate,
					lt: endDate,
				},
			},
			select: {
				type: true,
			},
		});
	}
}

export default new DownloadHistoryModel();
