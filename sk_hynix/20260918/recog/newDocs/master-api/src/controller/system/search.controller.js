import base from '../base.controller.js';
import ConvertUtil from '../../utils/convert/index.js';
import folderUtils from '../../utils/folder.util.js';
import { searchService } from '../../services/index.js';
import authHandler from '../../handlers/auth.handler.js';
import { HttpError } from '../../handlers/error.handler.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';

class SearchController {
	// 키워드로 컨텐츠 검색
	async searchContentsbyKeyword(req, res, next) {
		try {
			let { keyword, filter, attendee, page, take, startDate, endDate, folderId, shared, mediaType } = req.query;

			if (!keyword || keyword.trim() === '') throw new HttpError(400, '검색어를 입력해주세요.');
			if (!filter || filter === '') filter = 'all';

			const possibleFilter = ['all', 'title', 'hashTag', 'creator', 'detail', 'fileName'];
			if (!possibleFilter.includes(filter)) throw new HttpError(400, '검색 옵션이 올바르지 않습니다.');

			if (mediaType) {
				mediaType = mediaType.toUpperCase();
				if (!Object.values(Enums.ContentType).includes(mediaType))
					throw new HttpError(400, '미디어 타입이 올바르지 않습니다.');
			}

			if (shared) {
				shared = shared.toLocaleLowerCase();
				if (![folderUtils.VIRTUAL_FOLDER.RECEIVED, folderUtils.VIRTUAL_FOLDER.SENT].includes(shared))
					throw new HttpError(400, '공유 여부 선택값이 올바르지 않습니다.');
			}

			page = page ? parseInt(req.query.page) : 1;
			take = take ? parseInt(req.query.take) : 0; // 0이면 전체 검색

			startDate = ConvertUtil.normalizeDate(startDate) || new Date(0);
			endDate = ConvertUtil.normalizeDate(endDate) || new Date();

			if (startDate > endDate) throw new HttpError(400, '시작일이 종료일보다 늦을 수 없습니다.');

			const currentDate = new Date();
			endDate.setHours(23, 59, 59, 999);
			if (endDate > currentDate) endDate = currentDate;

			// 키워드가 정규식인 경우 이스케이프 처리
			const savedKeyword = keyword;
			keyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
			attendee = attendee?.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') || '';

			const searchDTO = {
				keyword,
				savedKeyword,
				filter,
				attendee,
				page,
				take,
				startDate,
				endDate,
				folderId,
				shared,
				mediaType,
			};
			const result = await searchService.searchContentsByKeyword(req.user, searchDTO);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	// 최근 검색 키워드 조회
	async getKeywordsHistory(req, res, next) {
		try {
			const { pid } = req.user;

			const result = await searchService.getKeywordsHistory(pid);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	// 최근 검색어 전체 삭제
	async deleteAllKeywordHistory(req, res, next) {
		try {
			const { pid } = req.user;
			await searchService.deleteAllKeywordHistory(pid);
			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	// 최근 검색어 특정 삭제
	async deleteKeywordHistoryById(req, res, next) {
		try {
			const { pid } = req.user;
			let { keywordId } = req.params;
			if (!keywordId) throw new HttpError(1000, '삭제할 키워드 ID가 필요합니다');
			if (keywordId && isNaN(parseInt(keywordId))) throw new HttpError(1000, '유효한 keywordId가 필요합니다');
			await searchService.deleteKeywordHistoryById(pid, parseInt(keywordId));
			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	// 최근 검색 후 열람 컨텐츠 기록(임시API)
	async upsertContentViewedHistoryBySearching(req, res, next) {
		try {
			const { auth, user } = req;

			const { contentId } = req.params;

			const { pid } = req.user;

			if (!contentId) {
				throw new HttpError(1000);
			}

			await authHandler.isMoreThanContentViewer(contentId, auth, user);

			const result = await searchService.upsertContentViewedHistoryBySearching(pid, contentId);

			base.sendCreated(res, result);
		} catch (err) {
			next(err);
		}
	}

	// 최근 검색 후 컨텐츠 열람기록 목록 조회
	async getContentViewedListBySearching(req, res, next) {
		try {
			const { pid } = req.user;

			const result = await searchService.getContentViewedListBySearching(pid);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	// 최근 검색 후, 컨텐츠열람 기록 삭제
	async deleteContentViewedBySearching(req, res, next) {
		try {
			const { contentId } = req.params;

			const { pid } = req.user;

			if (!contentId) {
				throw new HttpError(1000);
			}

			await searchService.deleteContentViewedBySearching(pid, contentId);

			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}
}

export default new SearchController();

