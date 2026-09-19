import userModel from '../../models/user.model.js';
import shareModel from '../../models/share.model.js';
import folderUtils from '../../utils/folder.util.js';
import searchModel from '../../models/search.model.js';
import contentModel from '../../models/content.model.js';
import { HttpError } from '../../handlers/error.handler.js';
import { getContentsResponseWithIds } from '../feature/calendar.service.js';
import transcribeResultModel from '../../models/transcribeResult.model.js';

class SearchService {
	constructor() {
		this.userModel = userModel;
		this.shareModel = shareModel;
		this.searchModel = searchModel;
		this.contentModel = contentModel;
		this.transcribeResultModel = transcribeResultModel;
		this.ownerRole = this.userModel.Enums.ContentShareRole.OWNER;
	}

	// 키워드로 컨텐츠 검색
	async searchContentsByKeyword(session, searchDTO) {
		try {
			const { pid, email } = session;
			const { keyword, savedKeyword, filter, attendee, shared, page, take, folderId } = searchDTO;

			// 1단계: 기본 접근 가능한 콘텐츠 조회 (내가 생성한 것 + 공유받은 것)
			// shared 파라미터는 제외하고 조회 (이후 별도 필터링)
			const baseSearchDTO = { ...searchDTO, shared: undefined };
			const accessibleContents = await this.contentModel.getMyAccessibleContentIds(pid, email, baseSearchDTO);
			let filteredContentIds = accessibleContents.map(content => content.contentId);

			// 2단계: folderId 필터 적용 (있을 경우)
			if (folderId) {
				// 공통 폴더 필터링 로직 사용
				searchDTO = await folderUtils.applyFolderFiltering(pid, email, folderId, searchDTO);

				// 가상 폴더인 경우
				if (folderUtils.isVirtualFolder(folderId)) {
					const folderContents = await this.contentModel.getContents(pid, searchDTO);
					const folderContentIds = folderContents.map(content => content.contentId);
					// 교집합: 접근 가능한 것 중 폴더에 속한 것
					filteredContentIds = filteredContentIds.filter(id => folderContentIds.includes(id));
				} else {
					// 실제 폴더인 경우: applyFolderFiltering에서 설정한 contentIds와 접근 가능한 콘텐츠의 교집합
					const folderContentIds = searchDTO.contentIds || [];
					filteredContentIds = filteredContentIds.filter(id => folderContentIds.includes(id));
				}
			}

			// 3단계: shared 필터 적용 (있을 경우)
			if (shared) {
				const sharedFilteredIds = await this.applySharedFilter(pid, email, searchDTO);
				// 교집합: 기존 필터 결과 중 shared 조건도 만족하는 것
				filteredContentIds = filteredContentIds.filter(id => sharedFilteredIds.includes(id));
			}

			// 최종 필터링된 contentIds 설정
			searchDTO.contentIds = filteredContentIds;

			if (['all', 'detail'].includes(filter)) {
				// detail 검색 옵션시, MongoDB 검색 결과 추가
				const searchedInMongoDB = await this.searchModel.searchContentDetail(searchDTO);
				searchDTO.searchedIdsForDetail = searchedInMongoDB.map(content => content.contentId);
				searchDTO.contentIds = [...new Set([...searchDTO.contentIds, ...searchDTO.searchedIdsForDetail])];
			}

			// 참석자 검색 옵션 추가시, contentIds에서 attendee 검색 결과와의 교집합 구하기
			if (attendee) {
				const searchedInMongoDB = await this.searchModel.searchContentByAttendee(searchDTO);
				searchDTO.searchedIdsForAttendee = searchedInMongoDB.map(content => content.contentId);
				searchDTO.contentIds = searchDTO.contentIds.filter(id => searchDTO.searchedIdsForAttendee.includes(id));
			}

			let [_count, pagedContents] = await this.searchModel.searchContentByKeyword(searchDTO);

			//검색 keyword 기록 최신화 (비동기)
			this.updateOrInsertKeyword(pid, savedKeyword).catch(console.error);

			const lastPage = take > 0 ? Math.ceil(_count / take) : 1;

			pagedContents = await getContentsResponseWithIds(pagedContents, email, pid);

			return { keyword, savedKeyword, attendee, _count, currentPage: page, lastPage, contents: pagedContents };
		} catch (err) {
			throw err;
		}
	}

	// shared 파라미터에 따른 콘텐츠 ID 필터링
	async applySharedFilter(pid, email, searchDTO) {
		try {
			const { shared, startDate, endDate } = searchDTO;

			if (shared === 'sent') {
				// 내가 공유한 콘텐츠 ID들 조회
				return await this.shareModel.getSentContentIds(pid, startDate, endDate);
			} else if (shared === 'received') {
				// 내가 공유받은 콘텐츠 ID들 조회
				return await this.shareModel.getReceivedContentIds(email, startDate, endDate);
			} else {
				// shared 값이 없거나 다른 값이면 빈 배열 반환
				return [];
			}
		} catch (err) {
			throw err;
		}
	}

	// 검색 keyword 기록
	async updateOrInsertKeyword(pid, keyword) {
		try {
			const existedKeywordHistory = await this.searchModel.getKeywordHistoryByKeyword(pid, keyword);

			const result = await this.searchModel.upsertKeywordHistory(pid, keyword, existedKeywordHistory?.keywordId);

			// 기록 10개 초과 확인 후, 10개이하로 관리
			const keywordHistory = await this.searchModel.getKeywordsHistory(pid);

			if (keywordHistory.length > 10) {
				const deleteResult = await this.searchModel.deleteKeywordHistoryById(
					pid,
					keywordHistory[keywordHistory.length - 1].keywordId
				);

				if (!deleteResult) {
					console.error('검색어 삭제 실패');
				}
			}

			if (!result) {
				console.error('검색어 저장 실패');
			}

			return result;
		} catch (err) {
			throw err;
		}
	}

	// 최근 검색어 조회
	async getKeywordsHistory(pid) {
		try {
			const result = await this.searchModel.getKeywordsHistory(pid);

			if (!result) {
				return [];
			}

			return result;
		} catch (err) {
			throw err;
		}
	}

	// 최근 검색어 전체 삭제
	async deleteAllKeywordHistory(pid) {
		try {
			const result = await this.searchModel.getCountSearchKeywordHistory(pid);
			if (result === 0) throw new HttpError(400, '삭제할 검색어 기록이 없습니다.');
			return await this.searchModel.deleteKeywordAllHistory(pid);
		} catch (err) {
			throw err;
		}
	}

	// 최근 검색 키워드 특정 삭제
	async deleteKeywordHistoryById(pid, keywordId) {
		try {
			const keywordResult = await this.searchModel.getKeywordHistoryById(pid, keywordId);
			if (!keywordResult) throw new HttpError(404, '해당 검색 정보를 찾을 수 없습니다.');
			return await this.searchModel.deleteKeywordHistoryById(pid, keywordId);
		} catch (err) {
			throw err;
		}
	}

	// 검색 후 컨텐츠 열람 기록 최신화
	async upsertContentViewedHistoryBySearching(pid, contentId) {
		try {
			const contentHistory = await this.searchModel.getContentViewedBySearching(pid, contentId);

			if (!contentHistory) {
				console.error('컨텐츠 열람기록 조회 실패');
			}

			const result = await this.searchModel.upsertContentViewedBySearching(pid, contentId, contentHistory?.id);

			if (!result) {
				console.error('컨텐츠 열람 기록 처리 실패');
			}

			// 10개 초과시, 가장 오래된 컨텐츠 조회 기록 삭제
			const contentHistoryList = await this.searchModel.getContentViewedListBySearching(pid);

			if (contentHistoryList.length > 10) {
				const deleteResult = await this.searchModel.deleteContentViewedBySearching(
					contentHistoryList[contentHistoryList.length - 1].id
				);

				if (!deleteResult) {
					console.error('컨텐츠 조회 기록, 삭제 실패');
				}
			}

			return;
		} catch (err) {
			throw err;
		}
	}

	// 최근 검색 후 컨텐츠 열람목록 조회
	async getContentViewedListBySearching(pid) {
		try {
			const contentHistoryList = await this.searchModel.getContentViewedListBySearching(pid);

			if (!contentHistoryList) {
				return [];
			}

			// contentHistoryList의 Content의 title를 flat 화
			for (const record of contentHistoryList) {
				record.title = record.Content.title;
				record.type = record.Content.type;
				delete record.Content;
			}

			return contentHistoryList;
		} catch (err) {
			throw err;
		}
	}

	// 최근 검색 후, 컨텐츠 열람 기록 삭제
	async deleteContentViewedBySearching(pid, contentId) {
		try {
			const contentResult = await this.searchModel.getContentViewedBySearching(pid, contentId);

			if (!contentResult) {
				throw new HttpError(404, '해당 컨텐츠의 열람 기록이 존재하지 않습니다.');
			}

			const resultDeleted = await this.searchModel.deleteContentViewedBySearching(contentResult.id);

			if (!resultDeleted) {
				throw new HttpError(500, '컨텐츠 열람 기록, 삭제 실패');
			}

			return;
		} catch (err) {
			throw err;
		}
	}
}

export default new SearchService();
