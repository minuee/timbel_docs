import { correctionService, proofreadingService, contentService } from '../../../services/index.js';
import base from '../../base.controller.js';
import authHandler from '../../../handlers/auth.handler.js';
import { HttpError } from '../../../handlers/error.handler.js';

class ContentCorrectionController {
	async getCorrection(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const options = req.query;
			if (!contentId) throw new HttpError(1000);

			await authHandler.isMoreThanContentOwner(contentId, auth, user);
			const result = await correctionService.getCorrection(contentId, auth, options);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async requestCorrection(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { mergedSegments = [] } = req.body;

			if (!contentId) throw new HttpError(1000);
			if (mergedSegments.length === 0) throw new HttpError(1000);

			await authHandler.isMoreThanContentOwner(contentId, auth, user);
			const result = await correctionService.requestCorrection(contentId, mergedSegments, auth, user);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async createCorrectionHistory(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { correctionId, mergedSegments = [] } = req.body;

			if (!contentId) throw new HttpError(1000);
			if (!correctionId) throw new HttpError(1000);
			if (mergedSegments.length === 0) throw new HttpError(1000);

			await authHandler.isMoreThanContentOwner(contentId, auth, user);
			await correctionService.createCorrectionHistory(correctionId, mergedSegments);

			base.sendSuccess(res, {});
		} catch (err) {
			next(err);
		}
	}

	async segmentProofreading(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { targetSegmentIds = [] } = req.body;

			if (!contentId) throw new HttpError(1000);
			if (targetSegmentIds.length === 0) throw new HttpError(1000);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);

			const result = await proofreadingService.segmentProofreading(contentId, targetSegmentIds, auth);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async addWordSetToCandidates(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { baseWord, newWord } = req.body;
			if (!contentId || !baseWord || !newWord) throw new HttpError(1000);

			await authHandler.isMoreThanContentOwner(contentId, auth, user);

			const wordSetDTO = { pid: user.pid, contentId, baseWord, newWord };
			await contentService.addWordSetToCandidates(wordSetDTO);
			base.sendSuccess(res, {});
		} catch (err) {
			next(err);
		}
	}
}

export default new ContentCorrectionController();

