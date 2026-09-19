import base from '../base.controller.js';
import { HttpError } from '../../handlers/error.handler.js';
import { corpusService } from '../../services/index.js';

class UserCorpusController {
	async getCorpus(req, res, next) {
		try {
			const { auth } = req;
			const { search = null } = req.query;

			const data = await corpusService.getCorpus(auth, search);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async checkCorpusSoruce(req, res, next) {
		try {
			const { auth } = req;
			const { source } = req.query;

			const data = await corpusService.checkCorpusSource(auth, source);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async createCorpus(req, res, next) {
		try {
			const { auth } = req;
			const { source, target, memo } = req.body;

			if (!source || !target) {
				throw new HttpError(1000);
			}

			if (source === target) {
				throw new HttpError(1803);
			}

			const createCorpusDTO = { source, target, memo };
			const data = await corpusService.createCorpus(auth, createCorpusDTO);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async updateCorpus(req, res, next) {
		try {
			const { auth } = req;
			const { corpusId } = req.params;
			const { source, target, memo = null } = req.body;

			if (!source || !target) {
				throw new HttpError(1000);
			}

			const updateCorpusDTO = { source, target, memo, updaterId: auth.member.id };
			const data = await corpusService.updateCorpus(corpusId, updateCorpusDTO);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async deleteCorpus(req, res, next) {
		try {
			const { corpusId } = req.params;

			const data = await corpusService.deleteCorpus(corpusId);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}
}

export default new UserCorpusController();
