import { HttpError } from '../../handlers/error.handler.js';
import keywordModel from '../../models/keywordBoostring.model.js';
import keywordBulkUtil from '../../utils/keyword/bulk.util.js';

const KEYWORD_BOOSTING_MAX_COUNT = process.env.KEYWORD_BOOSTING_MAX_COUNT || 100;
class KeywordService {
	constructor() {
		this.keywordModel = keywordModel;
	}
	async createKeywordBoosting(member, requestData) {
		try {
			const isExisted = await this.keywordModel.isExisted(member, requestData);
			if (isExisted) throw new HttpError(2401);

			const count = await this.keywordModel.getKeywordBoostingCount(member);
			if (count >= KEYWORD_BOOSTING_MAX_COUNT) throw new HttpError(2405);

			const result = await this.keywordModel.createKeywordBoosting(member, requestData);
			if (!result) throw new HttpError(2403);

			return await this.keywordModel.findAllKeywordBoostings(member);
		} catch (err) {
			throw err;
		}
	}

	async getKeywordBoostings(member, sortOrder) {
		try {
			return await this.keywordModel.findAllKeywordBoostings(member, sortOrder);
		} catch (err) {
			throw err;
		}
	}

	async deleteKeywordBoosting(member, keywordId) {
		try {
			// 삭제 대상 키워드가 본인 소유로 실제 존재하는지 id로 확인(마지막 1개 삭제도 정상 처리)
			const existed = await this.keywordModel.findKeywordById(member, keywordId);
			if (!existed) throw new HttpError(2406);

			const result = await this.keywordModel.deleteKeywordBoosting(member, keywordId);
			if (!result) throw new HttpError(2404);

			return await this.keywordModel.findAllKeywordBoostings(member);
		} catch (err) {
			throw err;
		}
	}

	// 일괄 등록용 양식(XLSX 기본, format=csv 지원)
	async getBulkTemplate(format = 'xlsx') {
		if (format === 'csv') {
			return {
				buffer: await keywordBulkUtil.generateKeywordTemplateCSV(),
				filename: 'keyword_boosting.csv',
				contentType: 'text/csv; charset=utf-8',
			};
		}
		return {
			buffer: await keywordBulkUtil.generateKeywordTemplate(),
			filename: 'keyword_boosting.xlsx',
			contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
		};
	}

	// 파일(CSV/XLSX) 기반 키워드 부스팅 일괄 등록. 검증 통과분만 생성하고 성공/스킵 리포트 반환.
	async bulkCreateKeywordBoostings(member, file) {
		try {
			const keywords = await keywordBulkUtil.readKeywordFile(file);

			const { keywords: existingKeywords, totalCount: existingCount } =
				await this.keywordModel.findAllKeywordBoostings(member);

			const { results, globalErrors, keywordsToCreate } = keywordBulkUtil.validateBulkKeywords({
				keywords,
				existingKeywords,
				existingCount,
			});

			if (keywordsToCreate.length > 0) {
				await this.keywordModel.createManyKeywordBoostings(member, keywordsToCreate);
			}

			return keywordBulkUtil.buildBulkKeywordsResponse({ keywords, keywordsToCreate, results, globalErrors });
		} catch (err) {
			throw err;
		}
	}
}

export default new KeywordService();
