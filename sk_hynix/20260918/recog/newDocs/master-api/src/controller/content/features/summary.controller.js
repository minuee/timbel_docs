import { contentService, highlightService } from '../../../services/index.js';
import base from '../../base.controller.js';
import authHandler from '../../../handlers/auth.handler.js';
import { HttpError } from '../../../handlers/error.handler.js';
import { validate } from '../../../utils/index.js';

class ContentSummaryController {
	async updateContentKeywords(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { keywords = [] } = req.body;

			if (keywords.length === 0) {
				throw new HttpError(1000);
			}

			await authHandler.isMoreThanContentEditor(contentId, auth, user);

			await contentService.updateContentKeywords(contentId, keywords, auth, user);
			base.sendSuccess(res, {});
		} catch (err) {
			next(err);
		}
	}

	async reSummaryContent(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { size = 'large', lang = 'ko', templateId = 'DEF-DEFAULT-BASIC' } = req.body;

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			auth.config.summarySize = size;
			auth.config.transcribeLang = lang;
			auth.config.templateId = templateId;
			const result = await contentService.reSummaryContent(contentId, auth, user);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async updateMeetingTime(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;

			if (!contentId) throw new HttpError(1000);
			validate.isMeetingTimeData(req.body);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			await contentService.updateMeetingTime(contentId, req.body, auth, user);

			base.sendSuccess(res, {});
		} catch (err) {
			next(err);
		}
	}

	async addHighlight(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { category, text } = req.body;

			if (!contentId || !category || !text) throw new HttpError(1000);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);

			const result = await highlightService.addHighlight(contentId, req.body);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async deleteHighlight(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, highlightId } = req.params;

			if (!contentId || !highlightId) throw new HttpError(1000);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);

			await highlightService.deleteHighlight(contentId, highlightId);

			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	async updateSummaryContent(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const allowBodyKeys = ['category', 'data', 'removeHighlightIds'];
			const allowCategoryKeys = ['issues', 'summary', 'tasks', 'topics', 'summaryTime'];

			const bodyKeys = Object.keys(req.body);

			if (bodyKeys.some(key => !allowBodyKeys.includes(key)))
				throw new HttpError(1000, 'Body 허용 값이 아닙니다.');
			if (!allowBodyKeys.every(key => bodyKeys.includes(key)))
				throw new HttpError(1000, 'Body 필수 값이 누락되었습니다.');

			const { category = '' } = req.body;
			if (!allowCategoryKeys.includes(category))
				throw new HttpError(1000, `Category 허용 값이 아닙니다. 허용 값 : ${allowCategoryKeys.join(', ')}`);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);

			await contentService.updateSummaryContent(contentId, req.body);

			base.sendSuccess(res, {});
		} catch (err) {
			next(err);
		}
	}
}

export default new ContentSummaryController();
