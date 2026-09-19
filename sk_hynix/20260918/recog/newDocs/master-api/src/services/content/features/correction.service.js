import axios from 'axios';
import correctionModel from '../../../models/correction.model.js';

let BASE_URL = null;
process.on('configChanged', () => {
	BASE_URL = process.env.CORRECTION_URL || 'https://abiz.timblo.io';
});

const getCorrection = async (contentId, { member }, options) => {
	try {
		const correction = await correctionModel.getCorrection(contentId, member.id, options);
		log.i('correction', correction);

		let response = await axios.request({
			method: 'GET',
			maxBodyLength: Infinity,
			url: `${BASE_URL}/llm_api/correction`,
			params: { contentId },
		});

		if (response.data.status !== correction.status) {
			await correctionModel.updateStatusCorrection(correction.id, response.data.status);
		}

		if (response.data.status === 'COMPLETED' || response.data.status === 'IN_PROGRESS') {
			response.data.results = JSON.parse(
				JSON.stringify(response.data.results)
					.replaceAll('chunk_idx', 'mergedSegmentIndex')
					.replaceAll('timestamp', 'startTime')
					.replaceAll('start_idx', 'startIndex')
					.replaceAll('end_idx', 'endIndex')
					.replaceAll('original_text', 'originalText')
					.replaceAll('correction_text', 'correctionText')
					.replaceAll('type_details', 'typeDetail')
			);
			response.data.correctionId = correction.id;
		}

		return response.data;
	} catch (err) {
		throw err;
	}
};

const requestCorrection = async (contentId, mergedSegments, { member }, { email }) => {
	try {
		const data = {
			contentId,
			email,
			'chunks': mergedSegments.map(segment => ({
				'chunk_idx': segment.segmentIndex,
				'chunk_content': segment.text,
				'timestamp': segment.startTime,
			})),
		};

		log.i('data', BASE_URL, data);

		const result = await axios.request({
			method: 'POST',
			maxBodyLength: Infinity,
			url: `${BASE_URL}/llm_api/correction`,
			headers: {
				'Content-Type': 'application/json',
			},
			data,
		});

		if (result.data.result === 'SUCCESS') {
			return await correctionModel.createCorrection(contentId, member.id);
		}

		return result.data;
	} catch (err) {
		throw err;
	}
};

const createCorrectionHistory = async (correctionId, mergedSegments) => {
	try {
		const corrections = mergedSegments.flatMap(segment =>
			segment.corrections.map(correction => ({
				correctionId,
				mergedSegmentIndex: segment.mergedSegmentIndex,
				startTime: segment.startTime,
				startIndex: correction.startIndex,
				endIndex: correction.endIndex,
				originalText: correction.originalText,
				correctionText: correction.correctionText,
				type: correction.type,
				typeDetail: correction.typeDetail,
				actionType: correction.actionType,
			}))
		);

		log.i('corrections', JSON.stringify(corrections));

		await correctionModel.createCorrectionResult(corrections);
	} catch (err) {
		throw err;
	}
};

export default {
	getCorrection,
	requestCorrection,
	createCorrectionHistory,
};
