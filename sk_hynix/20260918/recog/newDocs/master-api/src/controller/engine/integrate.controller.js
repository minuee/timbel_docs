import base from '../base.controller.js';
import { summaryService } from '../../services/index.js';
import { HttpError } from '../../handlers/error.handler.js';

class IntegrateController {
	async segmentToSummary(req, res, next) {
		try {
			const { body } = req;
			const requireKeys = ['speakerMap', 'segments'];
			const bodyKeys = Object.keys(body);
			if (!requireKeys.every(key => bodyKeys.includes(key)))
				throw new HttpError(1000, 'Body 필수 값이 누락되었습니다.');

			const result = await summaryService.segmentToSummary(body);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}
}

export default new IntegrateController();

