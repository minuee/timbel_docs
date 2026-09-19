import base from '../base.controller.js';
import queueService from '../../services/system/queue.service.js';
import { HttpError } from '../../handlers/error.handler.js';

class QueueController {
	async getRecogQueues(req, res, next) {
		try {
			const { auth } = req;
			const { queueName } = req.query;

			if (auth?.member?.role !== 'ADMIN') throw new HttpError(403);

			const result = await queueService.getRecogQueues(queueName);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async pauseQueue(req, res, next) {
		try {
			const { auth } = req;
			const { queueName } = req.params;

			if (auth?.member?.role !== 'ADMIN') throw new HttpError(403);
			if (!queueName) throw new HttpError(1000);

			const result = await queueService.pauseQueue(queueName);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async resumeQueue(req, res, next) {
		try {
			const { auth } = req;
			const { queueName } = req.params;

			if (auth?.member?.role !== 'ADMIN') throw new HttpError(403);
			if (!queueName) throw new HttpError(1000);

			const result = await queueService.resumeQueue(queueName);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async moveToFailedJob(req, res, next) {
		try {
			const { auth } = req;
			const { queueName } = req.params;
			const { jobId } = req.body;

			if (auth?.member?.role !== 'ADMIN') throw new HttpError(403);
			if (!queueName || !jobId) throw new HttpError(1000);

			const result = await queueService.moveToFailedJob(queueName, jobId);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async retryJob(req, res, next) {
		try {
			const { auth } = req;
			const { queueName } = req.params;
			const { jobId } = req.body;

			if (auth?.member?.role !== 'ADMIN') throw new HttpError(403);
			if (!queueName || !jobId) throw new HttpError(1000);

			const result = await queueService.retryJob(queueName, jobId);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async removeJob(req, res, next) {
		try {
			const { auth } = req;
			const { queueName } = req.params;
			const { jobId } = req.body;

			if (auth?.member?.role !== 'ADMIN') throw new HttpError(403);
			if (!queueName || !jobId) throw new HttpError(1000);

			const result = await queueService.removeJob(queueName, jobId);

			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}
}

export default new QueueController();

