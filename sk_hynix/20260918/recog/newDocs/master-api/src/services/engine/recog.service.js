import fs from 'fs';
import llmWorker from './llm.service.js';
import corpusService from '../feature/corpus.service.js';
import usageModel from '../../models/usage.model.js';
import contentCaptureService from '../content/contentCapture.service.js';
import memoService from '../content/features/memo.service.js';
import bookmarkModel from '../../models/bookmark.model.js';
import { HttpError, QueueError } from '../../handlers/error.handler.js';
import transcribeResultModel from '../../models/transcribeResult.model.js';
import { drive, notify, convert, taskQueue, generate, transcribe } from '../../utils/index.js';

export const llmTaskQueue = new taskQueue('llm', llmWorker, process.env.LLM_WORKER || 30);

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

		// 재요약/재시도(STT 포함) 시 세그먼트가 새로 생성되어 앵커가 무효화되므로, STT 성공을 확인한
		// 이 시점에 메모/북마크를 정리한다(큐 적재 직후 삭제 시 STT 실패로 인한 데이터 유실 방지).
		if (task.isCreate === false) {
			await Promise.all([
				memoService.realDeleteMemosByContentId(task.contentId),
				bookmarkModel.deleteBookmarksByFileId(task.fileId),
			]);
		}

		const taskParams = {
			segmentInfo,
			preParams: task,
			taskId: ticketId,
			user,
			// 재요약(STT 포함) 경로 유지를 위해 isCreate 전파. 신규 업로드는 미지정 → 기본 true(생성).
			isCreate: task.isCreate ?? true,
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

	await transcribeResultModel.upsert(fileId, ticketId, auth);
	log.i('[RecogService : create] transcribeResultModel.upsert success ');

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

export const recogRetry = async (jobId, { member }) => {
	const recogTaskQueue = getRecogTaskQueue({ member });
	const job = await recogTaskQueue.getJob(jobId);
	if (!job) throw new HttpError(1186);
	if ((await job.isActive()) || (await job.isWaiting()) || (await job.isDelayed())) {
		log.e(`[RecogService : recogRetry] Task with id ${jobId} is already running or waiting.`);
		throw new HttpError(1187);
	}
	try {
		await job.retry();
	} catch (err) {
		log.e(`[RecogService : recogRetry] error => `, err.message);
		throw new HttpError(1188);
	}
};

export default {
	addTask,
	recogRetry,
};
