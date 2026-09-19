import { shareService } from '../../../services/index.js';
import base from '../../base.controller.js';
import authHandler from '../../../handlers/auth.handler.js';
import { HttpError } from '../../../handlers/error.handler.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';
import { validate } from '../../../utils/index.js';

class ContentShareController {
	async getContentShareUsers(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;

			if (!contentId) {
				throw new HttpError(1000);
			}

			await authHandler.isMoreThanContentViewer(contentId, auth, user);
			const result = await shareService.getContentShareUsers(contentId);

			base.sendSuccess(res, result);
		} catch (error) {
			next(error);
		}
	}

	async updateShareUserPermission(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, email, permission } = req.body;
			const isDefinePermission = base.ContentShareRoleValues.includes(permission?.toUpperCase());
			if (!contentId || !email || !permission) {
				throw new HttpError(1000);
			}
			if (!isDefinePermission) {
				throw new HttpError(1116);
			}

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const result = await shareService.updateShareUserPermission(contentId, email, permission.toUpperCase());

			base.sendSuccess(res, result);
		} catch (error) {
			next(error);
		}
	}

	async addContentShareUser(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, email } = req.body;

			if (!contentId) {
				throw new HttpError(1000);
			}

			validate.emailRegexValidate(email);

			if (user.email === email) {
				throw new HttpError(1112);
			}

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const result = await shareService.addContentShareUser(auth, user, contentId, email);
			base.sendSuccess(res, result);
		} catch (error) {
			next(error);
		}
	}

	async addContentShareUsers(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, emails, role = Enums.ContentShareRole.VIEWER } = req.body;

			if (!contentId || !emails || !Array.isArray(emails))
				throw new HttpError(1000, 'contentId 혹은 배열인 emails가 없습니다.');

			if (!Object.values(Enums.ContentShareRole).includes(role)) throw new HttpError(1116); // 정의되지 않은 역할 에러
			if (role === Enums.ContentShareRole.OWNER) throw new HttpError(1305); // 소유자 역할 에러
			emails.forEach(email => {
				validate.emailRegexValidate(email);
				if (user.email === email) throw new HttpError(1112);
			});

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const result = await shareService.addContentShareUsers(auth, user, contentId, emails, role);
			base.sendSuccess(res, result);
		} catch (error) {
			console.log(error);
			next(error);
		}
	}

	async deleteContentShareUser(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, email } = req.params;
			if (!contentId || !email) {
				throw new HttpError(1000);
			}
			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const result = await shareService.deleteContentShareUser(contentId, email);
			base.sendNoContent(res);
		} catch (error) {
			next(error);
		}
	}
}

export default new ContentShareController();

