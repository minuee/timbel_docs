/* eslint-disable no-useless-escape */
import axios from 'axios';
import convert from '../convert/index.js';

const TAG = '[summarizer/haivSLLM]';

let BASE_URL = null;
process.on('configChanged', () => {
	BASE_URL = process.env.HAIV_SLLM_API_URL || 'https://openapi.vito.ai/v1/';
});

const postRequest = async (path, headers, data) => {
	return await axios.request({
		method: 'POST',
		maxBodyLength: Infinity,
		url: `${BASE_URL}${path}`,
		headers,
		data,
	});
};

const processPrompt = async segments => {
	try {
		const headers = {
			'Content-Type': 'application/json',
		};
		const { data = [] } = await postRequest('summarize/json', headers, segments);
		let result = {};
		data.forEach(item => {
			result = {
				...result,
				...item,
			};
		});
		return result;
	} catch (err) {
		log.e(TAG, `error => ${err.message}`);
		return err.message;
	}
};

const summarizer = async ({ speakerMap, segments }, prompts) => {
	try {
		log.i(TAG, `started summarizer with segments len : ${segments.length} and ${prompts.length} prompts`);
		const compressedSegments = segments.map(({ text, speakerId, startTime }) => {
			return {
				content: text,
				speaker: speakerMap[speakerId].name,
				time: convert.timeFormat(startTime),
			};
		});

		log.i(TAG, `started summarizer with segments len : ${compressedSegments.length} and ${prompts.length} prompts`);
		const summaryResponses = await processPrompt(compressedSegments);

		log.i(TAG, `completed summarizer with responses`);
		return { summaryResponses, totalToken: 0 };
	} catch (err) {
		log.e(TAG, `error => ${err.message}`);
		throw err;
	}
};

export default summarizer;
