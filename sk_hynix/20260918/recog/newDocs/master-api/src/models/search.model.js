import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class SearchModel extends BaseDatabase {
	constructor() {
		super('SearchModel');
	}

	// 최근 검색어 갯수 조회
	async getCountSearchKeywordHistory(pid) {
		return await this.mariaDB.searchKeywordHistory.count({
			where: {
				pid,
			},
		});
	}

	/**
	 * @param {string} pid
	 * @param {string} keyword
	 * @param {number} keywordId
	 * @description 최근 검색어 저장 or 업데이트
	 */
	async upsertKeywordHistory(pid, keyword, keywordId) {
		return await this.mariaDB.searchKeywordHistory.upsert({
			where: {
				keywordId: keywordId ? keywordId : 0,
			},
			update: {
				searchAt: new Date(),
			},
			create: {
				pid,
				keyword,
			},
		});
	}

	/**
	 * @param {string} pid
	 * @returns {id: number, keyword: string, searchAt: Date}
	 * @description 최근 검색어들 조회
	 */
	async getKeywordsHistory(pid) {
		return await this.mariaDB.searchKeywordHistory.findMany({
			where: {
				pid,
			},
			select: {
				keywordId: true,
				keyword: true,
				searchAt: true,
			},
			orderBy: {
				searchAt: 'desc',
			},
		});
	}

	/**
	 * @param {string} pid
	 * @param {string} keyword
	 * @return {keywordId: number}
	 * @description 최근 검색어 조회 by keyword
	 */
	async getKeywordHistoryByKeyword(pid, keyword) {
		return await this.mariaDB.searchKeywordHistory.findFirst({
			where: {
				pid,
				keyword,
			},
			select: {
				keywordId: true,
			},
		});
	}

	/**
	 * @param {string} pid
	 * @param {number} keywordId
	 * @return {pid: string, keywordId: number, keyword: string}
	 * @description 최근 검색어 조회 by Id
	 */
	async getKeywordHistoryById(pid, keywordId) {
		return await this.mariaDB.searchKeywordHistory.findUnique({
			where: {
				pid,
				keywordId,
			},
			select: {
				keywordId: true,
			},
		});
	}

	// 최근 검색어 전체 삭제
	async deleteKeywordAllHistory(pid) {
		return await this.mariaDB.searchKeywordHistory.deleteMany({
			where: {
				pid,
			},
		});
	}

	/**
	 * @param {string} pid
	 * @param {number} keywordId
	 * @return {id: number, keyword: string}
	 * @description 최근 검색어 삭제
	 */
	async deleteKeywordHistoryById(pid, keywordId) {
		return await this.mariaDB.searchKeywordHistory.delete({
			where: {
				pid,
				keywordId,
			},
		});
	}

	/**
	 * @param {string} pid
	 * @param {string} contentId
	 * @param {number} contentHistoryId
	 * @description 최근 검색 후, 컨텐츠 열람 조회 기록 최신화
	 */
	async upsertContentViewedBySearching(pid, contentId, contentHistoryId) {
		return await this.mariaDB.searchContentHistory.upsert({
			where: {
				id: contentHistoryId ? contentHistoryId : 0,
			},
			update: {
				viewAt: new Date(),
			},
			create: {
				pid,
				contentId,
				viewAt: new Date(),
			},
		});
	}

	/**
	 * @param {string} pid
	 * @returns {id: number, Content.title : string, viewAt: Date}[]
	 * @description 최근 검색 후, 컨텐츠 열람 기록 - 목록 조회
	 */
	async getContentViewedListBySearching(pid) {
		return await this.mariaDB.searchContentHistory.findMany({
			where: {
				pid,
			},
			select: {
				id: true,
				Content: {
					select: {
						title: true,
						type: true,
					},
				},
				contentId: true,
				viewAt: true,
			},
			orderBy: {
				viewAt: 'desc',
			},
		});
	}

	/**
	 * @param {string} pid
	 * @param {string} contentId
	 * @return {id: number}
	 * @description 최근 검색 후, 컨텐츠 열람 기록 - 단건 조회
	 */
	async getContentViewedBySearching(pid, contentId) {
		return await this.mariaDB.searchContentHistory.findFirst({
			where: {
				pid,
				contentId,
			},
			select: {
				id: true,
			},
		});
	}

	/**
	 * @param {string[]} contentIds
	 * @returns {id: number, title: string}
	 * @description 컨텐츠 id에 따라 검색한 컨텐츠 제목 조회
	 */
	async getContentViewedTitleBySearching(contentIds) {
		return await this.mariaDB.content.findMany({
			where: {
				contentId: {
					in: contentIds,
				},
			},
			select: {
				contentId: true,
				title: true,
			},
		});
	}

	/**
	 * @param {number} id
	 * @description 최근 검색 후, 열람 컨텐츠 기록 삭제(재사용)
	 */
	async deleteContentViewedBySearching(id) {
		return await this.mariaDB.searchContentHistory.delete({
			where: {
				id,
			},
		});
	}

	// 검색 조건에 따른 where 조건 설정
	setWhereCondition(searchDTO) {
		let { filter, keyword, contentIds, searchedIdsForDetail, startDate, endDate } = searchDTO;
		let baseCondition = { contentId: { in: contentIds }, createAt: { gte: startDate, lte: endDate } };

		const containsKeyword = { contains: keyword };

		const filters = {
			title: {
				OR: [
					{ AND: [{ editedTitle: { not: null } }, { editedTitle: containsKeyword }] },
					{ AND: [{ editedTitle: null }, { title: containsKeyword }] },
				],
			},
			hashTag: { OR: [{ hashTag: { array_contains: keyword } }, { manualTag: { array_contains: keyword } }] },
			creator: { creatorNickName: containsKeyword },
			fileName: { fileName: containsKeyword },
			detail: { contentId: { in: searchedIdsForDetail } },
			all: {
				OR: [
					{ AND: [{ editedTitle: { not: null } }, { editedTitle: containsKeyword }] },
					{ AND: [{ editedTitle: null }, { title: containsKeyword }] },
					{ OR: [{ hashTag: { array_contains: keyword } }, { manualTag: { array_contains: keyword } }] },
					{ creatorNickName: containsKeyword },
					{ contentId: { in: searchedIdsForDetail } },
				],
			},
		};

		const addCondition = filters[filter] || {};
		const where = { AND: [baseCondition, addCondition] };
		return where;
	}

	// 내 컨텐츠 검색 by keyword
	async searchContentByKeyword(searchDTO) {
		const whereCondition = this.setWhereCondition(searchDTO);
		let { page, take } = searchDTO;

		const [_count, pagedContents] = await Promise.all([
			this.mariaDB.contentWithUserProfiles.count({
				where: whereCondition,
			}),
			this.mariaDB.contentWithUserProfiles.findMany({
				where: whereCondition,
				take: take === 0 ? undefined : take,
				skip: take === 0 ? 0 : (page - 1) * take,
				orderBy: {
					updateAt: 'desc',
				},
			}),
		]);

		return [_count, pagedContents];
	}

	// 키워드로 상세 내용을 검색
	async searchContentDetail({ keyword, contentIds }) {
		const where = {
			contentId: { in: contentIds },
			transcribeResult: {
				mergedSegments: { some: { text: { contains: keyword } } },
			},
		};
		const result = await this.mongoDB.file.findMany({
			where,
			orderBy: { updateAt: 'desc' },
			select: { contentId: true },
		});
		return result;
	}

	// 참석자로 검색
	async searchContentByAttendee({ attendee, contentIds }) {
		const where = {
			contentId: { in: contentIds },
			transcribeResult: {
				speakerInfo: {
					some: {
						OR: [
							{ AND: [{ displayName: { not: null } }, { displayName: { contains: attendee } }] },
							{ AND: [{ displayName: null }, { name: { contains: attendee } }] },
						],
					},
				},
			},
		};
		const result = await this.mongoDB.file.findMany({
			where,
			orderBy: { updateAt: 'desc' },
			select: { contentId: true },
		});
		return result;
	}
}

export default new SearchModel();
