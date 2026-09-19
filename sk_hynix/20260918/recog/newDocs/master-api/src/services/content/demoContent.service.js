import fs from 'fs';
import { createNote } from '../engine/llm.service.js';
import memberModel from '../../models/member.model.js';
import contentModel from '../../models/content.model.js';
import { HttpError } from '../../handlers/error.handler.js';
import transcribeResultModel from '../../models/transcribeResult.model.js';
import { drive, notify, taskQueue, generate, statusUpdater } from '../../utils/index.js';

const TAG = '[DemoContentService] ';

let baseUser = process.env.baseUser;
process.on('configChanged', () => {
	baseUser = process.env.baseUser;
});

const findFileAndtranscribeResultAndNoteByContentId = async contentId => {
	return await contentModel.findFileByContentId(contentId, {
		note: true,
		transcribeResult: true,
	});
};

const convertSummaryTimes = (summaryTimes = []) => {
	return summaryTimes.map(summaryTime => {
		const { tasks, issues } = summaryTime;
		return {
			...summaryTime,
			tasks: tasks === null ? [] : tasks,
			issues: issues === null ? [] : issues,
		};
	});
};

const demoWorker = async task => {
	const { fileId, ticketId: ticket, auth, contentId, demoContent } = task;
	const { member } = auth;

	const updater = new statusUpdater(task, member);
	const TAG = `[demoWorker : ${ticket}] PID : [${member.id}]`;
	await updater.call('RUNNING');
	log.i(TAG, ' : start ');
	try {
		const { contentId: demoContentId } = demoContent;
		const targetData = await findFileAndtranscribeResultAndNoteByContentId(demoContentId);
		if (!targetData || targetData.contentId !== demoContentId) {
			throw new HttpError(1104, demoContentId);
		}
		log.i(TAG, ' : found targetData !!');
		const { transcribeResult, note } = targetData;
		const { mergedSegments, segments, speakerInfo, summaryTime, aiResult } = transcribeResult;
		const patchSummaryTimes = convertSummaryTimes(summaryTime);
		await transcribeResultModel.updateStatus(
			{ fileId, ticket },
			{
				status: 'DONE',
				segments,
				speakerInfo,
				summaryTime: patchSummaryTimes,
				aiResult,
				mergedSegments,
			}
		);
		log.i(TAG, ' : updated transcribeResult !!');
		await createNote(contentId, note.content);
		log.i(TAG, ' : created note !!');
		await contentModel.updateContent(
			{ contentId },
			{
				title: demoContent.title,
				transcribeStatus: 'DONE',
				hashTag: demoContent.hashTag,
			}
		);
		log.i(TAG, ' : updated contentModel !!');
		await updater.call('DONE');
	} catch (err) {
		log.e(TAG, `Task ${ticket} failed: ${err.message}`);
		await updater.call('ERROR');
	}
};

const demoTaskQueue = new taskQueue('demo', demoWorker, 100);

export const findDemoContnetId = async ({ title }) => {
	const baseMember = await memberModel.findMemberByUserEmail(baseUser);
	log.i(TAG, '[isDemoContent] baseMember => ', JSON.stringify(baseMember, null, 2));
	const baseContent = await contentModel.findContentByCreatorIdAndTitle(baseMember.id, title);
	if (!baseContent) {
		log.i(TAG, '[isDemoContent] baseContent is not exist');
		return null;
	}
	log.i(TAG, '[isDemoContent] found baseContent !!');

	return baseContent;
};

const addTask = async (auth, { fileId, contentId, demoContent, fileName }) => {
	try {
		log.i(TAG, ' : start ');
		const ticketId = generate.ticketId();
		log.i(TAG, ' : ticketId => ', ticketId);

		if (await demoTaskQueue.isTaskRunning(fileId)) {
			throw new HttpError(1105, fileId);
		}

		await transcribeResultModel.create(fileId, ticketId, auth);
		const taskParams = {
			auth,
			fileId,
			ticketId,
			contentId,
			demoContent,
			taskId: fileId,
			fileName,
		};

		await notify.sttStatus({ status: 'WAITING' }, taskParams, auth.member);
		await demoTaskQueue.addTask(taskParams);

		return {
			fileId,
			status: 'WAITING',
		};
	} catch (err) {
		log.e(TAG, 'error => ', err.message);
		throw err;
	}
};

const createFileObject = ({ name }) => {
	const fileBuffer = fs.readFileSync(name);
	const stats = fs.statSync(name);

	return {
		size: stats.size,
		buffer: fileBuffer,
	};
};

const getDemoFile = async ({ contentId, workspaceId, creatorId }) => {
	const { fileKey } = await contentModel.findFileByContentId(contentId);
	const kms = generate.keyFromString(`${creatorId}${workspaceId}`);
	const kmsKey = `${kms}/${fileKey}`;
	const params = new drive({}).createGetParams(kmsKey);
	const fileObject = await new drive({}).getObject(kmsKey, params);
	return createFileObject(fileObject);
};

const patchDemoFile = async file => {
	const demoContent = await findDemoContnetId({ title: file.originalname });

	if (demoContent !== null) {
		log.i('[ContentService : uploadContent] demoContent : ', JSON.stringify(demoContent, null, 2));
		const { buffer, size } = await getDemoFile(demoContent);
		const { type, fileName } = demoContent;
		file['buffer'] = buffer;
		file['size'] = size;
		file['inputType'] = type;
		file['originalname'] = fileName;
		file['mimetype'] = type === 'VIDEO' ? 'video/mp4' : file['mimetype'];
	}
	return demoContent ?? null;
};

const getDemoContent = async (user, file) => {
	const isDemoUser = process.env.demoUser === user.email;
	return isDemoUser ? patchDemoFile(file) : null;
};

export default {
	addTask,
	getDemoContent,
};
