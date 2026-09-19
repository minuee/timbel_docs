import { redis } from '../../utils/index.js';
import Queue from 'bull';
import { createLegacyRedisClientConfig } from '../../utils/redis/connect.util.js';
import transcribeEngineModel from '../../models/transcribeEngine.model.js';

const getRecogQueueNames = async () => {
	const tags = await transcribeEngineModel.getTranscribeEngineTag();
	return tags.map(item => `recog-${item.tag}`);
};

const getRecogQueues = async queueName => {
	const queueNames = queueName ? [queueName] : await getRecogQueueNames();
	let result = {};

	for (const name of queueNames) {
		let jobsByState = {};
		const states = ['wait', 'active', 'paused', 'failed'];
		for (const state of states) {
			const jobIds =
				state === 'failed' ?
					await redis.client.zRange(`bull:${name}:${state}`, 0, -1)
				:	await redis.client.lRange(`bull:${name}:${state}`, 0, -1);

			const jobs = await Promise.all(
				jobIds.map(async jobId => {
					const jobData = await redis.client.hGetAll(`bull:${name}:${jobId}`, 'data');
					return {
						id: jobId,
						state: state,
						data: jobData.data ? JSON.parse(jobData.data) : null,
						opts: jobData.opts ? JSON.parse(jobData.opts) : null,
						progress: parseInt(jobData.progress) || 0,
						delay: parseInt(jobData.delay) || 0,
						timestamp: parseInt(jobData.timestamp) || null,
						processedOn: parseInt(jobData.processedOn) || null,
						finishedOn: parseInt(jobData.finishedOn) || null,
						attemptsMade: parseInt(jobData.attemptsMade) || 0,
						priority: parseInt(jobData.priority) || 0,
						stalledCounter: parseInt(jobData.stalledCounter) || 0,
						failedReason: jobData.failedReason || null,
					};
				})
			);
			jobsByState[state] = jobs;
		}
		result[name] = jobsByState;
	}
	return result;
};

const pauseQueue = async queueName => {
	try {
		const queue = new Queue(queueName, createLegacyRedisClientConfig());
		await queue.pause();

		log.i(`[QueueService : pauseQueue] Queue '${queueName}' paused successfully`);
		return { success: true, message: `Queue '${queueName}' paused successfully` };
	} catch (err) {
		log.e(`[QueueService : pauseQueue] Error pausing queue '${queueName}': ${err.message}`);
		throw err;
	}
};

const resumeQueue = async queueName => {
	try {
		const queue = new Queue(queueName, createLegacyRedisClientConfig());
		await queue.resume();

		log.i(`[QueueService : resumeQueue] Queue '${queueName}' resumed successfully`);
		return { success: true, message: `Queue '${queueName}' resumed successfully` };
	} catch (err) {
		log.e(`[QueueService : resumeQueue] Error resuming queue '${queueName}': ${err.message}`);
		throw err;
	}
};

const getJob = async (queueName, jobId) => {
	const queue = new Queue(queueName, createLegacyRedisClientConfig());
	return await queue.getJob(jobId);
};

const moveToFailedJob = async (queueName, jobId) => {
	const job = await getJob(queueName, jobId);
	if (!job) throw new Error(`Job ${jobId} not found`);

	try {
		const token = job.processedOn ? job.id : '0';
		await job.moveToFailed(new Error('사용자에 의해 실패 처리됨'), token, true);
	} catch (err) {
		throw err;
	}
};

const retryJob = async (queueName, jobId) => {
	const job = await getJob(queueName, jobId);
	if (!job) throw new Error(`Job ${jobId} not found`);

	try {
		await job.retry();
	} catch (err) {
		throw err;
	}
};

export default {
	getRecogQueues,
	pauseQueue,
	resumeQueue,
	moveToFailedJob,
	retryJob,
};
