import fs from 'fs';
import llmWorker from './llm.service.js';
import corpusService from './corpus.service.js';
import usageModel from '../models/usage.model.js';
import contentCaptureService from './contentCapture.service.js';
import { HttpError, QueueError } from '../handlers/error.handler.js';
import transcribeResultModel from '../models/transcribeResult.model.js';
import { drive, notify, convert, taskQueue, generate, transcribe } from '../utils/index.js';

export const llmTaskQueue = new taskQueue('llm', llmWorker, process.env.LLM_WORKER || 100);

const checkRecogFilePath = async (auth, { tempFilePath, fileKey, extension }) => {
	if (fs.existsSync(tempFilePath)) {
		log.i('[recogWorker] 대상 파일 경로 정상 확인');
		return { filePath: tempFilePath, isTmp: false };
	}
	log.i('[recogWorker] 대상 파일 새로운 경로로 업데이트');
	const driveFileKey = `${auth.kms}/${fileKey}`;
	const tmpFile = await new drive(auth).fastLoadFile(driveFileKey, extension);
	return { filePath: tmpFile.name, tmpFile, isTmp: true };
};

const recogWorker = async task => {
	log.i('[recogWorker] start');
	const { ticketId, auth, duration, user } = task;
	const { id: memberId } = auth.member;
	const { filePath, isTmp = false, tmpFile = null } = await checkRecogFilePath(auth, task);
	let manager;

	const TAG = `[recogWorker : ${ticketId}] Member Id : [${memberId}]`;
	try {
		manager = new transcribe(task, auth);
		const segmentInfo = await manager.runner(filePath);
		const { segments = [], speakerInfo = [] } = segmentInfo;
		if (segments.length === 0) throw QueueError(1104);

		const corpus = await corpusService.getCorpusSourceAndTarget(memberId);
		segmentInfo.segments = convert.replaceSegments(segments, corpus);

		segmentInfo.mergedSegments = convert.createMergedSegments({ segments });
		log.i(TAG, `completed: STT results: ${segments.length} speakers: ${speakerInfo.length}`);

		const taskParams = {
			segmentInfo,
			preParams: task,
			taskId: ticketId,
			user,
		};

		await llmTaskQueue.addTask(taskParams);

		await manager.transUpdater({ ...segmentInfo, status: 'STT_DONE' });
		await usageModel.addUsage(task, 'TRANSCRIBE', duration);

		if (isTmp) tmpFile.removeCallback();
		else fs.unlinkSync(filePath);
	} catch (err) {
		log.e(TAG, `Task failed: ${JSON.stringify(err)}`);
		if (manager) await manager.transUpdater({ status: 'ERROR' }, err);
		await contentCaptureService.createContentCapture('ERROR', 'RECOG', task.contentId, memberId, user);
		throw err;
	}
};
const recogTaskQueues = {};

const getAssignedChannelCount = maxQueue => {
	const totalInstances = Number(process.env.RECOG_WORKER ?? 3);
	const instanceId = Number(process.env.INSTANCE_ID ?? 0);
	const baseChannels = Math.floor(maxQueue / totalInstances);
	const extraChannels = maxQueue % totalInstances;

	return baseChannels + (instanceId < extraChannels ? 1 : 0);
};

const getRecogTaskQueue = ({ member }) => {
	const {
		config: { transcribeEngine },
	} = member.workspace;
	const { tag, maxQueue = 1 } = transcribeEngine;
	if (!recogTaskQueues[tag]) {
		const concurrency = getAssignedChannelCount(maxQueue);
		recogTaskQueues[tag] = new taskQueue(`recog-${tag}`, recogWorker, concurrency, true);
		log.i(`[RecogService : getRecogTaskQueue] create recogTaskQueues[${tag}]`);
	}

	return recogTaskQueues[tag];
};

const addTask = async (auth, params, user) => {
	log.i('[RecogService : create] start ');
	const recogTaskQueue = getRecogTaskQueue(auth);
	const ticketId = generate.ticketId();
	const { fileId } = params;

	log.i('[RecogService : create] ticketId : ', ticketId);

	if (await recogTaskQueue.isTaskRunning(fileId)) {
		throw new HttpError(1105, fileId);
	}

	await transcribeResultModel.create(fileId, ticketId, auth);
	log.i('[RecogService : create] transcribeResultModel.create success ');

	const taskParams = {
		auth,
		user,
		ticketId,
		taskId: fileId,
		...params,
	};
	try {
		const isAddTask = await recogTaskQueue.addTask(taskParams);
		const status = isAddTask ? 'WAITING' : 'ERROR';
		await notify.sttStatus({ status }, taskParams, auth.member);
		log.i('[RecogService : create] recogTaskQueue.addTask =>  ', isAddTask);
		return {
			fileId,
			status: 'WAITING',
		};
	} catch (err) {
		await notify.sttStatus({ status: 'ERROR' }, taskParams, auth.member);
		log.e(`[RecogService : createRecog] error => `, err.message);
		throw err;
	}
};

export default {
	addTask,
};
