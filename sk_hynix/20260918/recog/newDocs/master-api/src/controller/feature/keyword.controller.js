import base from '../base.controller.js';
import { HttpError } from '../../handlers/error.handler.js';
import keywordService from '../../services/feature/keyword.service.js';

class KeywordController {
	async createKeywordBoosting(req, res, next) {
		try {
			const { auth } = req;
			const { member } = auth;
			const { keyword, isPostProcess = false, weight = 0.0 } = req.body;

			if (!keyword) throw new HttpError(1000);
			if (keyword.match(/[a-zA-Z]/)) throw new HttpError(2402);

			const requestData = {
				keyword,
				isPostProcess,
				weight,
			};

			const result = await keywordService.createKeywordBoosting(member, requestData);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async getKeywordBoostings(req, res, next) {
		try {
			const { auth } = req;
			const { member } = auth;
			const { sortOrder = 'latest' } = req.query;

			if (!['latest', 'alphabetical'].includes(sortOrder)) sortOrder = 'latest';

			const result = await keywordService.getKeywordBoostings(member, sortOrder);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async deleteKeywordBoosting(req, res, next) {
		try {
			const { auth } = req;
			const { member } = auth;
			const { keywordId } = req.params;
			if (!keywordId) throw new HttpError(1000);

			const result = await keywordService.deleteKeywordBoosting(member, Number(keywordId));
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async downloadKeywordTemplate(req, res, next) {
		try {
			const { format = 'xlsx' } = req.query;
			const { buffer, filename, contentType } = await keywordService.getBulkTemplate(format);

			res.setHeader('Content-Type', contentType);
			res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
			res.setHeader('Content-Length', buffer.length);
			res.send(buffer);
		} catch (err) {
			next(err);
		}
	}

	async bulkCreateKeywordBoosting(req, res, next) {
		try {
			const { auth } = req;
			const { member } = auth;
			const file = req.file;
			if (!file) throw new HttpError(1000, '파일을 선택해주세요');

			const result = await keywordService.bulkCreateKeywordBoostings(member, file);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}
}

export default new KeywordController();

