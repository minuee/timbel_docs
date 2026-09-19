import stringUtil from './string.util.js';
import timeUtil from './time.util.js';
import jsonUtil from './json.util.js';
import segmentUtil from './segment.util.js';
import audioUtil from '../file/audio.util.js';
import markdownUtil from './markdown.util.js';
import { isDate } from '../date.util.js';
import { HttpError } from '../../handlers/error.handler.js';

class ConvertUtil {
	// String utilities
	originalnameEncoding = stringUtil.originalnameEncoding.bind(stringUtil);
	keywordTransform = stringUtil.keywordTransform.bind(stringUtil);

	// Time utilities
	timeFormat = timeUtil.timeFormat.bind(timeUtil);
	convertTimeFormat = timeUtil.convertTimeFormat.bind(timeUtil);

	// JSON utilities
	contentToJson = jsonUtil.contentToJson.bind(jsonUtil);
	contentToJsonV2SummaryOnly = jsonUtil.contentToJsonV2SummaryOnly.bind(jsonUtil);

	// Segment utilities
	processSegments = segmentUtil.processSegments.bind(segmentUtil);
	replaceSegments = segmentUtil.replaceSegments.bind(segmentUtil);
	createMergedSegments = segmentUtil.createMergedSegments.bind(segmentUtil);
	resetMergedSegments = segmentUtil.resetMergedSegments.bind(segmentUtil);
	convertTextSplitter = segmentUtil.convertTextSplitter.bind(segmentUtil);

	// Audio utilities
	toFlac = audioUtil.toFlac.bind(audioUtil);
	replaceFileWithFlac = audioUtil.replaceFileWithFlac.bind(audioUtil);
	convertPcmToFlac = audioUtil.convertPcmToFlac.bind(audioUtil);

	// Markdown utilities
	convertSummaryToHtml = markdownUtil.convertSummaryToHtml.bind(markdownUtil);

	normalizeDate(date) {
		if (!date) return null;
		if (date.includes('null')) date = date.replace('null', '');
		const parsedDate = new Date(date);
		if (isNaN(parsedDate)) throw new HttpError(400, '올바른 날짜 형식이 아닙니다.');
		if (!isDate(parsedDate)) throw new HttpError(400, '올바른 날짜 형식이 아닙니다.');
		return parsedDate;
	}
}

export default new ConvertUtil();
