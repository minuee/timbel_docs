import { contentService } from '../../services/index.js';
import base from '../base.controller.js';
import authHandler from '../../handlers/auth.handler.js';
import { HttpError } from '../../handlers/error.handler.js';

class ContentRecycleController {
	async getRecycleContents(req, res, next) {
		try {
			const { auth } = req;
			let { limit = 0, type = null } = req.query;
			limit = isNaN(limit) ? 0 : parseInt(limit, 10);

			const result = await contentService.getRecycleContents(auth, limit, type);

			base.sendSuccess(res, result);
		} catch (error) {
			next(error);
		}
	}

	async removeContentFromList(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			if (!contentId) throw new HttpError(1000);

			auth.permission = (await authHandler.isMoreThanContentViewer(contentId, auth, user)).role;
			const { message, httpCode } = await contentService.removeContentFromList(contentId, auth, user);
			base.sendSuccess(res, {}, httpCode, message);
		} catch (error) {
			next(error);
		}
	}

	async removeBulkContentsFromList(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentIds } = req.body;

			if (!contentIds || !Array.isArray(contentIds)) throw new HttpError(1000);
			if (contentIds.length === 0) throw new HttpError(1000);

			await contentService.removeBulkContentsFromList(contentIds, auth, user);
			base.sendNoContent(res);
		} catch (error) {
			next(error);
		}
	}

	async restoreContent(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			if (!contentId) {
				throw new HttpError(1000);
			}
			await authHandler.isMoreThanContentOwner(contentId, auth, user);
			const result = await contentService.restoreContent(contentId, auth, user);
			base.sendSuccess(res, result);
		} catch (error) {
			next(error);
		}
	}

	async truncateContent(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			if (!contentId) {
				throw new HttpError(1000);
			}
			await authHandler.isMoreThanContentOwner(contentId, auth, user);
			const result = await contentService.truncateContent(contentId, auth, user);
			base.sendSuccess(res, result);
		} catch (error) {
			next(error);
		}
	}

	async clearRecyleBin(req, res, next) {
		try {
			const { auth, user } = req;

			await authHandler.isMember(auth);
			const result = await contentService.clearRecyleBin(auth, user);
			base.sendSuccess(res, result);
		} catch (error) {
			next(error);
		}
	}
}

export default new ContentRecycleController();

