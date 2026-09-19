import fs from 'fs';
import { Buffer } from 'buffer';
import demo from '../content/demoContent.service.js';
import normalizeService from './normalize.service.js';
import contentModel from '../../models/content.model.js';
import recogService, { llmTaskQueue } from '../engine/recog.service.js';

import contentCaptureService from '../content/contentCapture.service.js';
import transcribeResultModel from '../../models/transcribeResult.model.js';
import {
	drive,
	media,
	generate,
	secure,
	convert,
	notify,
	validate,
	skaxTextSplitter,
	taskQueue,
} from '../../utils/index.js';

const DEFAULT_PCM_DIR = '/usr/src/app/tmp/pcm/';
const DEFAULT_FLAC_DIR = '/usr/src/app/tmp/flac/';

let isFlacNormalize = true;

process.on('configChanged', () => {
	isFlacNormalize = process.env.IS_FLAC_NORMALIZE === 'true';
	log.i('[DriveService : configChanged] isFlacNormalize : ', isFlacNormalize);
});

const deletePcmWorker = async task => {
	log.i('[deletePcmWorker] start');
	try {
		const { taskId } = task;
		const pcmDir = `${process.env.PCM_DIR ?? DEFAULT_PCM_DIR}${taskId}/`;
		await fs.promises.rm(pcmDir, { recursive: true, force: true });

		log.i('[deletePcmWorker] 파일 삭제 완료');
	} catch (err) {
		log.e('[deletePcmWorker] error : ', err.message);
		throw err;
	}
};

const DELETE_PCM_CONCURRENCY = Number(process.env.DELETE_PCM_CONCURRENCY) || 10;
const deletePcmQueue = new taskQueue('delete-pcm', deletePcmWorker, DELETE_PCM_CONCURRENCY);

export const createResultData = (
	{ contentId, title, type, createAt, meetingStartTime, meetingEndTime, manualTag = [] },
	{ duration }
) => {
	return {
		content: {
			title,
			type,
			contentId,
			hashTag: [],
			manualTag,
			duration: duration,
			isShared: false,
			meetingStartTime,
			meetingEndTime,
			createAt,
		},
		transcribe: null,
	};
};

const uploadContent = async (file, auth, user, manualOptions = {}) => {
	let tmpRollbackData = null;
	let content = null;
	let fileData = null;
	try {
		const demoContent = await demo.getDemoContent(user, file);

		fileData = await new drive(auth).put(file);
		const tempFilePath = await media.parseMediaFile(file, fileData);
		generate.meetingTime(fileData);

		log.i('[ContentService : uploadContent] fileData : ', JSON.stringify(fileData, null, 2));

		content = await contentModel.createContent(auth, fileData, manualOptions);
		const { contentId } = content;

		const { id: fileId, fileKey, fileName } = await contentModel.createFileContent(contentId, fileData);
		const result = createResultData(content, fileData);

		tmpRollbackData = {
			fileId,
			fileKey,
			contentId,
		};

		log.i('[ContentService : uploadContent] result : ', tmpRollbackData);
		log.i('[ContentService : uploadContent] fileData : ', JSON.stringify(fileData, null, 2));
		const { duration = 0 } = fileData;
		if (duration !== 0) {
			const fileNameSplit = fileName.split('.');
			const extension = fileNameSplit[fileNameSplit.length - 1];
			log.i('[ContentService : uploadContent] extension : ', extension);
			const params = {
				fileId,
				fileKey,
				duration,
				contentId,
				tempFilePath,
				attendeeNum: file.attendeeNum,
				fileName,
				extension,
			};

			if (demoContent !== null) {
				params['demoContent'] = demoContent;
				result.transcribe = await demo.addTask(auth, params);
			} else {
				log.i('[ContentService : uploadContent] isFlacNormalize : ', isFlacNormalize, extension);
				result.transcribe =
					isFlacNormalize && extension === 'flac' ?
						await normalizeService.addTask(auth, params, user)
					:	await recogService.addTask(auth, params, user);
			}
		} else {
			throw new Error('duration is 0');
		}

		return result;
	} catch (err) {
		log.e('[ContentService : uploadContent] error : ', err.message);
		if (tmpRollbackData) {
			await new drive(auth).removeObject(tmpRollbackData);
			await contentModel.deleteFileContentByContentId(tmpRollbackData);
		} else if (content) {
			const contentId = content.contentId;
			const status = 'ERROR';
			await contentModel.updateTranscribeStatus(contentId, status);
			await contentCaptureService.createContentCapture(status, 'MONGO', contentId, auth.member.id, user);
			await notify.sttStatus({ status }, { contentId, fileName: fileData.title }, auth.member);
		}
		throw err;
	}
};

const checkFileList = async (filePath, totalNum, num = null) => {
	const fragmentPcmFileList = await fs.promises.readdir(filePath);
	let fileNumbers;
	let missingFiles;

	if (num) {
		fragmentPcmFileList.sort((a, b) => a.split('_')[0] - b.split('_')[0]);
		fileNumbers = fragmentPcmFileList.map(name => parseInt(name.split('_')[0]));
		missingFiles = Array.from({ length: totalNum }, (_, i) => i + 1).filter(num => !fileNumbers.includes(num));
	} else {
		fragmentPcmFileList.sort(
			(a, b) => a.split('_').pop().replace('.pcm', '') - b.split('_').pop().replace('.pcm', '')
		);
		fileNumbers = fragmentPcmFileList.map(name => parseInt(name.split('_').pop().replace('.pcm', '')));
		missingFiles = Array.from({ length: totalNum }, (_, i) => i).filter(num => !fileNumbers.includes(num));
	}

	log.i('[DriveService : checkFileList] : ', fragmentPcmFileList);
	return { missingFiles, fragmentPcmFileList };
};

const createUploadContentFile = async (filePath, fileName, attendeeNum) => {
	const data = await fs.promises.readFile(filePath);
	const buffer = Buffer.from(data);
	return {
		fieldname: 'file',
		originalname: `${fileName}.flac`,
		encoding: '7bit',
		mimetype: 'audio/flac',
		buffer: buffer,
		size: buffer.length,
		attendeeNum: attendeeNum,
		inputType: 'RECORD',
		isRecord: true,
	};
};

const deleteEncryptionContentTmpFiles = async diractories => {
	await Promise.all(
		diractories.map(directory => fs.promises.rm(directory, { recursive: true, force: true }).catch(() => {}))
	);
};

const checkDirectoryExist = async directoryPath => {
	try {
		await fs.promises.access(directoryPath);
		return true;
	} catch (error) {
		return false;
	}
};

const uploadEncryptionContent = async (
	files,
	{ deviceId, fileName, num = null, totalNum, end = null, attendeeNum, originalnames },
	auth,
	user,
	manual = {}
) => {
	const pcmDir = `${process.env.PCM_DIR ?? DEFAULT_PCM_DIR}${fileName}-${deviceId}/`;
	const flacDir = `${process.env.FLAC_DIR ?? DEFAULT_FLAC_DIR}${fileName}-${deviceId}/`;
	const taskId = `${fileName}-${deviceId}`;
	const isPcmDirExist = await checkDirectoryExist(pcmDir);

	if (!isPcmDirExist) await fs.promises.mkdir(pcmDir, { recursive: true });

	await media.parsePcmFile(pcmDir, files, num, totalNum, originalnames);

	if (!isPcmDirExist)
		await deletePcmQueue.addTask({ taskId }, process.env.DELETE_PCM_DELAY ?? 30 * 24 * 60 * 60 * 1000); // 30일

	if (end === 'false') return {};

	await validate.checkDuplicateMobileRecordContent(auth.member.id, `${fileName}.flac`);

	try {
		const { missingFiles, fragmentPcmFileList } = await checkFileList(pcmDir, totalNum, num);
		if (missingFiles.length > 0) {
			log.i('[uploadEncryptionContent] missingFiles', { missingFiles });
			return { missingFiles };
		}

		log.i('[uploadEncryptionContent] cancelTask : ', taskId);
		await deletePcmQueue.cancelTask(taskId);

		const decryptedFilePath = await secure.decryptFilesAesCbc(pcmDir, fragmentPcmFileList, fileName);
		const flacFilePath = await convert.convertPcmToFlac(decryptedFilePath, flacDir, fileName);
		await fs.promises.rm(pcmDir, { recursive: true, force: true });

		const uploadFile = await createUploadContentFile(flacFilePath, fileName, attendeeNum);
		const result = await uploadContent(uploadFile, auth, user, manual);

		await deleteEncryptionContentTmpFiles([pcmDir, flacDir]);
		return result;
	} catch (err) {
		await deleteEncryptionContentTmpFiles([pcmDir, flacDir]);
		log.e('[DriveService : uploadEncryptionContent] error : ', err.message);
		throw err;
	}
};

const getFileStream = async (auth, contentId) => {
	log.i(`[downloadContent : getFileStream] 파일 스트림 생성 시작`);

	const file = await contentModel.findFileByContentId(contentId);
	if (!file) {
		throw new HttpError(1000);
	}

	return await new drive(auth).createMinIOStream(file);
};

const uploadThumbnail = async (pid, file, type) => {
	try {
		const result = await new drive({}).putThumbnailObject(pid, type, file);
		return result;
	} catch (err) {
		log.e('[ContentService : uploadThumbnail] error : ', err.message);
		throw err;
	}
};

const uploadTextFileContent = async (file, auth, user) => {
	try {
		const chunks = await skaxTextSplitter(file);
		const taskId = generate.ticketId();
		const fileKey = generate.fileKey();
		file.apiKey = fileKey;

		const transcribeData = {
			...convert.convertTextSplitter(chunks, { language: auth.config.transcribeLang }),
		};
		transcribeData.mergedSegments = convert.createMergedSegments({ segments: transcribeData.segments });
		log.i('[ContentService : uploadTextFileContent] transcribeData : ', JSON.stringify(transcribeData, null, 2));

		const { content, file: textFile } = await contentModel.createTextContent(auth, file);
		log.i('[ContentService : uploadTextFileContent] content : ', JSON.stringify(content, null, 2));

		await transcribeResultModel.createTextTranscribeResult(textFile.id, taskId, auth, transcribeData);

		const taskParams = {
			user,
			taskId,
			segmentInfo: transcribeData,
			preParams: {
				auth,
				contentId: content.contentId,
				fileId: textFile.id,
				ticketId: taskId,
			},
		};
		const result = await llmTaskQueue.addTask(taskParams);
		if (!result) throw new HttpError(1127);

		return createResultData(content, { duration: 0 });
	} catch (err) {
		log.e('[DriveService : uploadTextFileContent] error : ', err.message);
		throw err;
	}
};
export default {
	uploadContent,
	uploadEncryptionContent,
	getFileStream,
	uploadThumbnail,
	uploadTextFileContent,
};
