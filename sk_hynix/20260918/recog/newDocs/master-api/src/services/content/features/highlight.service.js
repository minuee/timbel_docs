import contentModel from '../../../models/content.model.js';
import { HttpError } from '../../../handlers/error.handler.js';
import highlightModel from '../../../models/highlight.model.js';

const validateSubCategory = category => {
	if (category?.key === 'summaryTime') {
		if (!category.sub) throw new HttpError(1182);
		try {
			validateCategory({ category: category.sub });
		} catch (err) {
			throw new HttpError(1183);
		}
	}
};

const validateCategory = ({ category }) => {
	const requiredKeys = ['key', 'idx'];
	const allowedKeys = ['key', 'idx', 'sub'];

	validateSubCategory(category);

	const categoryKeys = Object.keys(category);
	if (categoryKeys.length < 2) throw new HttpError(1179);
	if (categoryKeys.length > 3) throw new HttpError(1113);

	requiredKeys.forEach(key => {
		if (!categoryKeys.includes(key)) throw new HttpError(1184);
		if (category[key] === undefined) throw new HttpError(1181);
	});

	categoryKeys.forEach(key => {
		if (!allowedKeys.includes(key) || !key) throw new HttpError(1180);
		if (categoryKeys.length === 2 && category[key] === undefined) throw new HttpError(1181);
	});
};

const getHighlightTarget = ({ aiResult, summaryTime, mergedSegments }, { category }) => {
	const { key, idx, sub } = category;
	try {
		if (key === 'summaryTime') {
			const parent = summaryTime[idx];
			if (['topic', 'time'].includes(sub.key)) return parent[sub.key];
			return parent[sub.key][sub.idx]['content'];
		} else if (key === 'mergedSegments') {
			return mergedSegments[idx].text;
		} else if (Object.keys(aiResult).includes(key)) {
			return aiResult[key][idx];
		}
	} catch (err) {
		throw new HttpError(1176);
	}
	throw new HttpError(1175);
};

const getIndexOf = (highlightTarget, { text, startIdx = 0 }) => {
	const startIndex = highlightTarget.indexOf(text, startIdx);
	if (startIndex === -1) throw new HttpError(1176);

	const endIndex = startIndex + text.length;
	return { startIndex, endIndex };
};

export const addHighlight = async (contentId, highlight) => {
	const TAG = '[highlightService]';
	try {
		log.i(TAG, `addHighlight start`);

		validateCategory(highlight);

		const file = await contentModel.findFileByContentId(contentId, { transcribeResult: true });
		if (!file) throw new HttpError(1122);

		const { id, transcribeResult } = file;

		const highlightTarget = getHighlightTarget(transcribeResult, highlight);
		if (!highlightTarget) throw new HttpError(1176);
		log.i(TAG, `${id} highlightTarget: ${JSON.stringify(highlightTarget, null, 2)}`);

		const { startIndex, endIndex } = getIndexOf(highlightTarget, highlight);
		log.i(TAG, `${id} indexOf: ${startIndex} - ${endIndex}`);

		const alreadyHighlight = await highlightModel.findHighlightByText(id, highlight, startIndex, endIndex);
		log.i(TAG, `alreadyHighlight: ${JSON.stringify(alreadyHighlight, null, 2)}`);
		if (alreadyHighlight) throw new HttpError(1177);

		delete highlight.startIdx;
		const { category, text } = highlight;
		const { key, idx, sub } = category;
		return await highlightModel.addHighlight(id, {
			category: {
				key,
				idx: Number(idx),
				sub,
			},
			text,
			start: startIndex,
			end: endIndex,
		});
	} catch (err) {
		throw err;
	}
};

export const deleteHighlight = async (contentId, highlightId) => {
	const TAG = '[highlightService]';
	try {
		log.i(TAG, `deleteHighlight start`);
		const file = await contentModel.findFileByContentId(contentId, { highlights: true });
		if (!file) throw new HttpError(1122);

		await highlightModel.findHighlightById(file.id, highlightId);
		await highlightModel.deleteHighlight(file.id, [highlightId]);

		log.i(TAG, `deleteHighlight end`);
		return;
	} catch (err) {
		throw err;
	}
};

export default { addHighlight, deleteHighlight };
