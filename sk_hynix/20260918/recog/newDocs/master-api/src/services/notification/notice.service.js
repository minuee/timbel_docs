import noticeModel from '../../models/notice.model.js';

class NoticeService {
	constructor() {
		this.noticeModel = noticeModel;
	}

	async getNotices(member) {
		try {
			const { workspace } = member;
			const notices = await this.noticeModel.getNotices(workspace.id);

			return notices;
		} catch (err) {
			throw err;
		}
	}
}

export default new NoticeService();
