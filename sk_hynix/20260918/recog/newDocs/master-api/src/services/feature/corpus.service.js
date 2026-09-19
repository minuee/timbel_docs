import corpusModel from '../../models/corpus.model.js';
import parserUtil from '../../utils/parser.util.js';
import { HttpError } from '../../handlers/error.handler.js';

const getCorpus = async ({ member }, search) => {
	try {
		const result = await corpusModel.getCorpus(member, search);
		return parserUtil.jsonBigintToInt(result);
	} catch (err) {
		throw err;
	}
};

const getCorpusSourceAndTarget = async memberId => {
	try {
		return await corpusModel.getCorpusSourceAndTarget(memberId);
	} catch (err) {
		throw err;
	}
};
const checkCorpusSource = async ({ member }, source) => {
	try {
		const result = await corpusModel.getCorpusByCreatorIdAndSoruce(member, source);
		return parserUtil.jsonBigintToInt(result);
	} catch (err) {
		throw err;
	}
};

const createCorpus = async ({ member }, data) => {
	try {
		const result = await corpusModel.createCorpus(member, data);
		return parserUtil.jsonBigintToInt(result);
	} catch (err) {
		if (err.code === 'P2002') {
			throw new HttpError(1802);
		}
		throw err;
	}
};

const updateCorpus = async (corpusId, data) => {
	try {
		const result = await corpusModel.updateCorpus(corpusId, data);
		return parserUtil.jsonBigintToInt(result);
	} catch (err) {
		if (err.code === 'P2025') {
			throw new HttpError(1801);
		}
		throw err;
	}
};

const deleteCorpus = async corpusId => {
	try {
		const result = await corpusModel.deleteCorpus(corpusId);
		return parserUtil.jsonBigintToInt(result);
	} catch (err) {
		if (err.code === 'P2025') {
			throw new HttpError(1801);
		}
		throw err;
	}
};

export default {
	getCorpus,
	getCorpusSourceAndTarget,
	checkCorpusSource,
	createCorpus,
	updateCorpus,
	deleteCorpus,
};
