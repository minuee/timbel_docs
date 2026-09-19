import fs from 'fs';
import recogService from '../engine/recog.service.js';
import { HttpError } from '../../handlers/error.handler.js';
import { taskQueue, drive, audioUtil, notify } from '../../utils/index.js';

const TAG = '[NormalizeService : ';

const normalizeWorker = async data => {
	const { auth, user, params } = data;
	log.i(TAG, `normalizeWorker] start`);
	try {
		const { tempFilePath, fileKey, fileName } = params;

		await audioUtil.normalizeAudioFile(tempFilePath);
		log.i(TAG, `normalizeWorker] audioUtil.normalizeAudioFile success`);

		const normalizedFileBuffer = await fs.promises.readFile(tempFilePath);
		const normalizedFile = {
			buffer: normalizedFileBuffer,
			originalname: fileName || 'normalized.flac',
			mimetype: 'audio/flac',
			size: normalizedFileBuffer.length,
		};

		await new drive(auth).replaceObject(fileKey, normalizedFile);
		log.i(TAG, `normalizeWorker] objectStorage file replaced with normalized file`);

		await recogService.addTask(auth, params, user);
		log.i(TAG, `normalizeWorker] recogService.addTask success`);

		await notify.sttStatus({ status: 'NORMALIZE_DONE' }, params, auth.member);
	} catch (err) {
		await notify.sttStatus({ status: 'ERROR' }, params, auth.member);
		log.e(TAG, `normalizeWorker] error => ${err.message}`);
		throw err;
	}
};

const normalizeTaskQueue = new taskQueue(
	`${process.env.NOMALIZE_TAG ?? 'normalize'}-${process.env.INSTANCE_ID ?? '0'}`,
	normalizeWorker,
	process.env.NORMALIZE_WORKER || 100
);

const addTask = async (auth, params, user) => {
	log.i(TAG, `create] start`);
	const { fileId } = params;

	if (await normalizeTaskQueue.isTaskRunning(fileId)) {
		throw new HttpError(1105, fileId);
	}

	try {
		const isAddTask = await normalizeTaskQueue.addTask({
			auth,
			user,
			params,
		});

		const status = isAddTask ? 'NORMALIZE_WAITING' : 'ERROR';
		await notify.sttStatus({ status }, params, auth.member);
		log.i(TAG, `createNormalizeTask] normalizeTaskQueue.addTask =>  ${isAddTask}`);
		return { fileId, status: 'NORMALIZE_WAITING' };
	} catch (err) {
		await notify.sttStatus({ status: 'ERROR' }, params, auth.member);
		log.e(TAG, `createNormalizeTask] error => ${err.message}`);
		throw err;
	}
};
export default {
	addTask,
};
