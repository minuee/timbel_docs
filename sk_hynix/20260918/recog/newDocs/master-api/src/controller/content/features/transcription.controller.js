import { contentService } from '../../../services/index.js';
import base from '../../base.controller.js';
import authHandler from '../../../handlers/auth.handler.js';
import { HttpError } from '../../../handlers/error.handler.js';

class ContentTranscriptionController {
	async resetSegments(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { resetSpeaker } = req.query;
			if (!contentId) throw new HttpError(1000);

			const options = {
				resetSpeaker: resetSpeaker?.toUpperCase() === 'Y' ? 'Y' : 'N',
			};

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			await contentService.resetSegments(contentId, auth, user, options);

			base.sendSuccess(res, {});
		} catch (err) {
			console.log(err);
			next(err);
		}
	}

	async changeSegments(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { segments } = req.body;

			if (!contentId || !segments) throw new HttpError(1000);
			if (!Array.isArray(segments)) throw new HttpError(400, 'segments는 배열이어야 합니다.');

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const result = await contentService.changeSegments(contentId, segments, auth, user);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async contentRetry(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			// 재요약(reSummary)과 동일하게 언어/템플릿/요약크기를 body로 받아 auth.config에 세팅한다.
			// 이 값이 transcribeResult.clientLanguage로 기록되며(없으면 STT/LLM 하위처리에서 오류),
			// 예전 재시도는 이걸 안 채워 clientLanguage 누락 오류가 났다.
			const { size = 'large', lang = 'ko', templateId = 'DEF-DEFAULT-BASIC' } = req.body || {};

			await authHandler.isMoreThanContentOwner(contentId, auth, user);
			auth.config = auth.config || {};
			auth.config.summarySize = size;
			auth.config.transcribeLang = lang;
			auth.config.templateId = templateId;
			await contentService.contentRetry(contentId, auth, user);

			base.sendSuccess(res, {});
		} catch (err) {
			next(err);
		}
	}
}

export default new ContentTranscriptionController();
