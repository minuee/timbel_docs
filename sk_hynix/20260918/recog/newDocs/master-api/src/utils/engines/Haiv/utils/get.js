import axios from 'axios';
import { authenticate } from './post.js';
import { convertUtteStructAndSpeakerInfo } from './parser.js';
import { QueueError } from '../../../../handlers/error.handler.js';

const TAG = '[GET : HAIV Transcribe Result polling]';
const getRequest = async (url, params, tag) => {
	return await axios.request({
		method: 'GET',
		maxBodyLength: Infinity,
		url,
		headers: {
			'Authorization': `Bearer ${ACCESS_TOKENS[tag]}`,
		},
		params,
	});
};

const progressStateRequest = async (decodingId, { contentId, ticketId, url, tag, params: { projectId } }) => {
	const stateUrl = `${url}/api/decoding/projects/${projectId}/state`;
	const res = await getRequest(stateUrl, { decodingId }, tag);

	if (res.status !== 200) {
		throw QueueError(1106, `Polling failed for ID ${decodingId}`);
	}

	return res.data;
};

const textContentRequest = async (dataId, { url, tag, params: { projectId, organization } }) => {
	let page = 0;
	let size = 100;
	const contents = [];

	while (true) {
		const segmentUrl = `${url}/api/organizations/${organization}/projects/${projectId}/data/${dataId}/segments`;
		const res = await getRequest(segmentUrl, { page, size }, tag);
		if (res.status !== 200) {
			throw QueueError(1103);
		}

		const {
			data: { content, pageable },
		} = res;

		contents.push(...content);
		log.i(TAG, `textContentRequest: ${page} / ${size} : ${content.length} segments received`);
		page = pageable.pageNumber + 1;

		if (page === pageable.pageSize) break;
		else if (content.length === 0) break;
	}

	return contents;
};

export const pollStatusAndResults = async ({ decodingId }, engineOptions, updater) => {
	return new Promise((resolve, reject) => {
		authenticate(engineOptions).then(() => {
			log.i(TAG, `Polling status for ID ${decodingId} transcribing started`);
			const interval = setInterval(async () => {
				try {
					const { state, fileList } = await progressStateRequest(decodingId, engineOptions);
					if (state === 'DONE' && fileList[0].status !== 'ERROR') {
						clearInterval(interval);
						const transcriptions = await textContentRequest(fileList[0].id, engineOptions);
						const data = convertUtteStructAndSpeakerInfo(transcriptions, engineOptions);
						log.i(TAG, `Polling status for ID ${decodingId} transcribing DONE`);
						resolve(data);
					}

					if (state === 'ERROR' || state === 'CANCEL') {
						throw QueueError(1106, `Polling failed for ID ${decodingId}`);
					}

					if (fileList[0].status === 'ERROR') {
						throw QueueError(1123, { errReason: fileList[0].errReason, errCode: fileList[0].errCode });
					}

					if (fileList[0] && Object.hasOwn(fileList[0], 'percentage')) {
						log.i(TAG, `Transcribe Progress : ${fileList[0].percentage}`);
						await updater({ status: 'PROGRESS', percentage: fileList[0].percentage });
					}
				} catch (err) {
					clearInterval(interval);
					reject(err);
				}
			}, 5000);
		});
	});
};
