import { drive, taskQueue } from '../../utils/index.js';
import contentModel from '../../models/content.model.js';
import { HttpError } from '../../handlers/error.handler.js';

const { env } = process;

const recycleWorker = async task => {
	log.i('[recycleWorker] start');
	try {
		const { auth, contentId, isNow } = task;
		const file = await contentModel.findFileByContentId(contentId);
		if (!file) throw new HttpError(1124);
		log.i('[recycleWorker] 파일 정보 확인 ==> ', file.fileKey);

		const removeResult = await new drive(auth).removeObject(file);
		if (!removeResult) throw new HttpError(1125);
		log.i('[recycleWorker] 파일 삭제 완료');

		if (!isNow) {
			log.i('[recycleWorker] 데이터 isDelete 업데이트');
			await contentModel.truncateContent(contentId);
		}

		return true;
	} catch (err) {
		throw err;
	}
};

const RECYCLE_CONCURRENCY = Number(process.env.RECYCLE_CONCURRENCY) || 10;
const recycleQueue = new taskQueue('recycle', recycleWorker, RECYCLE_CONCURRENCY);

const addTask = async (contentId, auth) => {
	log.i('[recycleService : addTask] contentId : ', contentId);
	const task = {
		auth,
		contentId,
		isNow: false,
		taskId: contentId,
	};
	return recycleQueue.addTask(task, env.RECYCLE_DELAY ?? 2592000000); // 30일
};

const deleteTask = async contentId => {
	log.i('[recycleService : deleteTask] contentId : ', contentId);
	return recycleQueue.cancelTask(contentId);
};

const addNowDeleteTask = async (contentIds, auth) => {
	log.i('[recycleService : deleteNowTask] contentId : ', contentIds);
	contentIds.forEach(async contentId => {
		const task = {
			auth,
			contentId,
			isNow: true,
			taskId: contentId,
		};
		await recycleQueue.addFastTask(task);
	});
	log.i('[recycleService : deleteNowTask] task Clear check');
};

export default {
	addTask,
	deleteTask,
	addNowDeleteTask,
};
