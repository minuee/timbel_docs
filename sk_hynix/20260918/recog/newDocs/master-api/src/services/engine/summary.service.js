import generate from '../../utils/generate.util.js';
import summarize from '../../utils/summarizer/index.js';

const TAG = '[SummaryService] ';
class SummaryService {
	constructor() {}

	async segmentToSummary(body) {
		const requestId = generate.ticketId();
		console.time(`[${requestId}] segmentToSummary`);
		const { lang = 'ko', summarySize = 'medium', speakerMap, segments: mergedSegments } = body;
		log.i(TAG, `[${requestId}] lang : ${lang}`);

		const { aiResult, summaryTime, totalToken } = await summarize({
			segmentInfo: { speakerMap, mergedSegments },
			ticketId: requestId,
			summarySize,
			lang,
		});
		log.i(TAG, `[${requestId}] 요약 완료`);
		console.timeEnd(`[${requestId}] segmentToSummary`);

		return { aiResult, summaryTime, totalToken };
	}
}

export default new SummaryService();
