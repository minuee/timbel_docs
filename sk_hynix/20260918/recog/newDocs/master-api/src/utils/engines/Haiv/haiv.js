import generate from '../../generate.util.js';
import { transcribe } from './utils/post.js';
import { pollStatusAndResults } from './utils/get.js';
import { QueueError } from '../../../handlers/error.handler.js';

const TAG = '[HaivService]';

const engine = async (transcribeOptions, updater) => {
	const { filePath = null } = transcribeOptions;

	if (!filePath) throw QueueError(1108);

	await generate.delayWithRandom('Haiv');
	try {
		const { data = {} } = await transcribe(transcribeOptions);
		if (data.hasOwnProperty('status') && data.status !== 'OK') {
			log.e(TAG, `[transcribe] Error code: `, data.errReason);
			throw QueueError(1103, data.errReason);
		}
		log.i(TAG, `Haiv Trasncribe Request Success data`);

		const result = await pollStatusAndResults(data, transcribeOptions, updater);
		log.i(TAG, `Haiv Trasncribe Polling Success result`);

		return result;
	} catch (err) {
		log.e(TAG, `Haiv Transcribe Error: ${JSON.stringify(err)}`);
		throw QueueError(1103, err.message);
	}
};

export default engine;
