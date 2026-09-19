import BaseDatabase from '@timbel-timblo-onpremise/prisma';
class ContentHistoryModel extends BaseDatabase {
	constructor() {
		super('ContentHistoryModel');
	}

	async createContentHistory(data) {
		const {
			workspaceId,
			contentId,
			contentType,
			contentTitle,
			meetingStartTime,
			meetingEndTime,
			duration,
			transcribeStatus,
			userName,
			email,
		} = data;
		return await this.mariaDB.contentHistory.create({
			data: {
				contentType,
				contentTitle,
				meetingStartTime,
				meetingEndTime,
				duration,
				transcribeStatus,
				userName,
				email,
				workspace: { connect: { id: workspaceId } },
				content: { connect: { contentId: contentId } },
			},
		});
	}
}

export default new ContentHistoryModel();
