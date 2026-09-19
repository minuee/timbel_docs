import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class NoticeModel extends BaseDatabase {
	constructor() {
		super('NoteModel');
	}

	async getNotices(workspaceId) {
		return await this.mariaDB.noticeView.findMany({
			where: {
				workspaceId,
				status: 'POST',
			},
		});
	}
}

export default new NoticeModel();
