import contentModel from '../../../models/content.model.js';
import { HttpError } from '../../../handlers/error.handler.js';
import prompt from '../../../prompts/langRefineTranslation.js';
import highlightModel from '../../../models/highlight.model.js';
import { calcTokenSize, llm } from '../../../utils/summarizer/skCustomProcess.js';

export const MAX_TOKEN = 2000;
export const MAX_TOKEN_LENGTH = 16000;

const TAG = '[SegmentProofreading] ';
const { system, user } = prompt;
const systemTokenLength = calcTokenSize(system);

const userPromptSplitter = transcriptList => {
	const transcriptTokenLength = calcTokenSize(JSON.stringify(transcriptList));

	const bonus = transcriptTokenLength > 25000 || transcriptTokenLength < 1000 ? 0 : 1;
	const nSplit = Math.ceil(transcriptTokenLength / (MAX_TOKEN_LENGTH - systemTokenLength - MAX_TOKEN)) + bonus;
	const chunkSize = Math.ceil(transcriptList.length / nSplit);

	return Array.from({ length: Math.ceil(transcriptList.length / chunkSize) }, (_, i) =>
		transcriptList.slice(i * chunkSize, (i + 1) * chunkSize)
	);
};

const processChunks = async chunks => {
	const tasks = chunks.map(chunk => {
		const promptData = user.replace('##DATA##', JSON.stringify(chunk));
		return llm(TAG, system, promptData);
	});

	log.i(TAG, '청크 처리 시작. 총 청크 수:', tasks.length);
	return Promise.all(tasks);
};

const mergeResults = (mergedSegments, results, compressedSegments) => {
	const refineResult = [];
	let totalToken = 0;

	results.forEach(({ response, token }) => {
		totalToken += token;

		if (!response.isModified) return;

		const filteredSegments = response.segments.filter(
			segment => compressedSegments.find(s => s.segmentId === segment.segmentId)?.isTarget
		);

		refineResult.push(...filteredSegments);
	});

	return mergedSegments.map(segment => {
		const refinedSegment = refineResult.find(ref => ref.segmentId === segment.segmentId);
		const result = refinedSegment ? { ...segment, ...refinedSegment } : segment;
		const { isTarget, ...finalResult } = result;
		return finalResult;
	});
};

const langRefineProcessor = async (mergedSegments, targetSegments) => {
	const timeTag = `langRefineProcessor - [${targetSegments[0].segmentId}] `;
	console.time(timeTag);

	try {
		log.i(TAG, 'Prompt 수행 시작');
		const compressedSegments = targetSegments.map(({ text, segmentId, speakerId, isTarget }) => ({
			text,
			isTarget,
			segmentId,
			speakerId,
		}));

		log.d(TAG, '압축된 세그먼트:', JSON.stringify(compressedSegments, null, 2));

		const transcriptChunks = userPromptSplitter(compressedSegments);
		const results = await processChunks(transcriptChunks);
		const refinedSegments = mergeResults(mergedSegments, results, compressedSegments);

		console.timeEnd(timeTag);
		log.i(TAG, 'Prompt 수행 완료');
		return refinedSegments;
	} catch (err) {
		log.e(TAG, 'Prompt 수행 오류:', JSON.stringify(err));
		throw new HttpError(1174);
	}
};

const extractSegmentsWithContext = (segments, targetIds, contextSize = 2) => {
	const indices = new Set();

	targetIds.forEach(targetId => {
		const index = segments.findIndex(segment => segment.segmentId === targetId);
		if (index !== -1) {
			const start = Math.max(0, index - contextSize);
			const end = Math.min(segments.length - 1, index + contextSize);

			for (let i = start; i <= end; i++) {
				indices.add(i);
				if (segments[i].segmentId === targetId) {
					segments[i].isTarget = true;
				}
			}
		}
	});

	if (indices.size === 0) throw new HttpError(1173);

	return Array.from(indices)
		.sort((a, b) => a - b)
		.map(index => segments[index]);
};

export const segmentProofreading = async (contentId, targetSegmentIds) => {
	try {
		log.i(TAG, '문장 교정 시작');
		const { id, transcribeResult } = await contentModel.findFileByContentId(contentId, { transcribeResult: true });
		const { mergedSegments } = transcribeResult;

		const targetSegments = extractSegmentsWithContext(mergedSegments, targetSegmentIds);
		log.d(TAG, '처리할 세그먼트:', JSON.stringify(targetSegments, null, 2));

		const refinedSegments = await langRefineProcessor(mergedSegments, targetSegments);

		await Promise.all([
			contentModel.updateMergedSegments(id, refinedSegments),
			highlightModel.clearHighlightByFileId({ fileId: id }, 'mergedSegments'),
		]);

		log.i(TAG, '문장 교정 완료');
		return true;
	} catch (err) {
		throw err;
	}
};

export default { segmentProofreading };
