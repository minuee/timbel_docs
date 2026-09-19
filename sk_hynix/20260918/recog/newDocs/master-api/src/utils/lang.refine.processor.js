import prompt from '../prompts/langRefineTranslation.js';
import { calcTokenSize, llm } from './summarizer/skCustomProcess.js';

export const MAX_TOKEN = 2000;
export const MAX_TOKEN_LENGTH = 16000;

const TAG = '[LangRefine] ';
const { system, user } = prompt;
const systemTokenLength = calcTokenSize(system);

const userPromptSplitter = transcriptList => {
	const transcriptTokenLength = calcTokenSize(JSON.stringify(transcriptList));

	const bonus = transcriptTokenLength > 25000 || transcriptTokenLength < 1000 ? 0 : 1;
	const nSplit = Math.ceil(transcriptTokenLength / (MAX_TOKEN_LENGTH - systemTokenLength - MAX_TOKEN)) + bonus;
	const chunkSize = Math.ceil(transcriptList.length / nSplit);
	const splitResult = [];

	for (let i = 0; i < transcriptList.length; i += chunkSize) {
		splitResult.push(transcriptList.slice(i, i + chunkSize));
	}

	return splitResult;
};

const userPromptSplitterWithSlidingChunk = transcriptList => {
	const baseChunks = userPromptSplitter(transcriptList);

	if (baseChunks.length <= 1) return baseChunks;

	const result = [];
	for (let i = 0; i < baseChunks.length; i++) {
		if (i === 0) result.push(baseChunks[i]);
		else if (i === baseChunks.length - 1) {
			const prevContext = baseChunks[i - 1].slice(-2);
			result.push([...prevContext, ...baseChunks[i]]);
		} else {
			const prevContext = baseChunks[i - 1].slice(-2);
			const nextContext = baseChunks[i + 1].slice(0, 2);
			result.push([...prevContext, ...baseChunks[i], ...nextContext]);
		}
	}
	return result;
};

const langRefineProcessor = async (mergedSegments, { config }) => {
	if (!config.isRefineProcess) return mergedSegments;

	const timeTag = `langRefineProcessor - [${mergedSegments[0]['segmentId']}] `;
	console.time(timeTag);
	try {
		log.i(TAG, 'lang refine 처리 실행');
		let totalToken = 0;
		const compressedSegments = mergedSegments.map(({ text, segmentId, speakerId }) => ({
			text,
			segmentId,
			speakerId,
		}));

		const refineResult = [];
		const transcriptChunks = userPromptSplitterWithSlidingChunk(compressedSegments);
		const tasks = transcriptChunks.map(transcriptChunk => {
			const promptData = user.replace('##DATA##', JSON.stringify(transcriptChunk));
			return llm(TAG, system, promptData);
		});

		log.i(TAG, '음성 데이터 청킹 및 tasks 시작 count : ', tasks.length);

		const results = await Promise.all(tasks);

		results.forEach(({ response, token }) => {
			if (response['isModified'] === true) refineResult.push(...response['segments']);
			totalToken += token;
		});

		const updateSegments = mergedSegments.map(segment => {
			const refinedSegment = refineResult.find(ref => ref.segmentId === segment.segmentId);
			return refinedSegment ? { ...segment, ...refinedSegment } : segment;
		});

		console.timeEnd(timeTag);

		log.i(TAG, 'lang refine 완료 ');
		return updateSegments;
	} catch (err) {
		log.e(TAG, 'lang refine Error : ', JSON.stringify(err));
		return mergedSegments;
	}
};

export default langRefineProcessor;
