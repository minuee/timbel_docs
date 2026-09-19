import base from '../base.controller.js';
import { noticeService } from '../../services/index.js';

class NoticeController {
	async getNotices(req, res, next) {
		try {
			const { auth } = req;
			const { member } = auth;

			const result = await noticeService.getNotices(member);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}
}

export default new NoticeController();
