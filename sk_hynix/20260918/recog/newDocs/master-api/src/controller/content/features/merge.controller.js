import { contentService } from '../../../services/index.js';
import base from '../../base.controller.js';
import authHandler from '../../../handlers/auth.handler.js';
import { HttpError } from '../../../handlers/error.handler.js';

class ContentMergeController {
	async mergeContents(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentIds, templateId = 'DEF-DEFAULT-BASIC', lang = 'ko', summary = 'medium' } = req.body;
			if (!contentIds || !Array.isArray(contentIds)) throw new HttpError(1000);
			if (contentIds.length === 0) throw new HttpError(1000);

			for (const contentId of contentIds) {
				await authHandler.isMoreThanContentViewer(contentId, auth, user);
			}

			auth.config.templateId = templateId;
			auth.config.transcribeLang = lang;
			auth.config.summarySize = summary;

			const result = await contentService.mergeContents(contentIds, auth, user);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}
}

export default new ContentMergeController();

