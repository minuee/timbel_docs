import axios from 'axios';
import { Agent } from 'https';
import { HttpError } from '../../handlers/error.handler.js';

const TAG = '[summarizer/skax-text-splitter]';
const DEFAULT_CHUNK_SIZE = process.env.SKAX_TEXT_SPLITTER_CHUNK_SIZE ?? 500;

const post = async (text, chunkSize) => {
	const requestData = {
		text_input: text,
		cunk_size: chunkSize,
	};
	const { data } = await axios.post(`${process.env.SKAX_API_URL}/text_splitter`, requestData, {
		httpsAgent: new Agent({
			rejectUnauthorized: false,
		}),
	});
	const { message, success, result } = data;
	const { chunks } = result;
	if (message !== 'text completed' || !success) throw new HttpError(1189);
	return chunks;
};

const skaxTextSpliter = async file => {
	try {
		let text = file.buffer.toString('utf8');
		const chunks = await post(text, file.chunkSize || DEFAULT_CHUNK_SIZE);
		return chunks;
	} catch (err) {
		log.e(TAG, `[${TAG}] error : ${err.message}`);
		throw new HttpError(1189);
	}
};

export default skaxTextSpliter;
