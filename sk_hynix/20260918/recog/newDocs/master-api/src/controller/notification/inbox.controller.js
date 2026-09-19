import base from '../base.controller.js';
import { inboxService } from '../../services/index.js';
import { HttpError } from '../../handlers/error.handler.js';

class InboxController {
	async getInboxByMemberId(req, res, next) {
		try {
			const { auth } = req;
			const { nowDate = null } = req.query;
			let options = req.query;

			if (nowDate) {
				const isValidFormat = /^\d{8}$/.test(nowDate);
				if (!isValidFormat) {
					throw new HttpError(1117);
				}

				const baseDate = new Date(
					nowDate.substring(0, 4),
					nowDate.substring(4, 6) - 1,
					nowDate.substring(6, 8)
				);

				const startDate = new Date(baseDate);
				startDate.setDate(baseDate.getDate() - 30);

				const endDate = new Date(baseDate);
				endDate.setDate(baseDate.getDate() + 1);

				options['startDate'] = startDate;
				options['endDate'] = endDate;
			}

			const result = await inboxService.getInboxByMemberId(auth.member.id, options);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async updateisReadInbox(req, res, next) {
		try {
			const { auth } = req;
			const { inboxId } = req.params;

			if (!inboxId) {
				throw new HttpError(400, '파라미터가 없습니다.');
			}

			const result = await inboxService.updateisReadInbox(inboxId, auth.member.id);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async updateisReadInboxByMemberId(req, res, next) {
		try {
			const { auth } = req;

			const result = await inboxService.updateisReadInboxByMemberId(auth.member.id);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async deleteInbox(req, res, next) {
		try {
			const { auth } = req;
			const { inboxId } = req.params;

			if (!inboxId) {
				throw new HttpError(400, '파라미터가 없습니다.');
			}

			await inboxService.deleteInbox(inboxId, auth.member.id);

			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	async deleteInboxMemberId(req, res, next) {
		try {
			const { auth } = req;

			await inboxService.deleteInboxMemberId(auth.member.id);

			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}
}

export default new InboxController();

