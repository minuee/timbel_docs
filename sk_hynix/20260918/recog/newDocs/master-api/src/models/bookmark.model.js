import { validate } from 'uuid';
import { HttpError } from '../handlers/error.handler.js';
import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class BookmarkModel extends BaseDatabase {
	constructor() {
		super('BookmarkModel');
	}

	async findItemId(fileId, item, itemId) {
		try {
			let where = {};

			where.fileId = fileId;

			if (itemId === '-1') {
				where[item] = { some: {} };
			} else if (itemId) {
				const isUUID = validate(itemId);
				const key = isUUID ? 'segmentId' : 'index';

				where[item] = { some: { [key]: isUUID ? itemId : parseInt(itemId, 10) } };
			}

			return await this.mongoDB.transcribeResult.findFirst({
				where,
			});
		} catch (err) {
			throw new HttpError(400, '존재하지 않는 itemId로 요청하셨습니다.');
		}
	}

	// 재작성(구 BookMarkedView 우회): 뷰는 viewOn:TranscribeResult 라 조회 시 항상 전 문서를 스캔하고
	// contentId가 $lookup 이후 계산 필드라 인덱스 push down이 불가 → 10~40초. 아래는 동일 결과를
	// Bookmarks(contentId 인덱스) 직접 조회 + 참조된 TranscribeResult(fileId 인덱스)만 로드해 앱단에서 조립.
	static TRANSCRIBE_SELECT = {
		id: true,
		fileId: true,
		segments: true,
		mergedSegments: true,
		speakerInfo: true,
		summaryTime: true,
		aiResult: true,
	};

	// 세그먼트의 화자명 = speakerInfo의 displayName(없으면 name). 구 뷰 로직과 동일.
	_resolveSpeakerName(speakerInfo = [], speakerId) {
		const sp = speakerInfo.find(s => s.speakerId === speakerId);
		if (!sp) return undefined; // 뷰에서 매칭 없으면 name 필드가 missing 처리됨
		return sp.displayName == null ? sp.name : sp.displayName;
	}

	_mapSegment(seg, speakerInfo) {
		return {
			segmentId: seg.segmentId,
			speakerId: seg.speakerId,
			startTime: seg.startTime,
			endTime: seg.endTime,
			duration: seg.duration,
			text: seg.text,
			name: this._resolveSpeakerName(speakerInfo, seg.speakerId),
		};
	}

	// 구 BookMarkedView $project.data 이식. bookmark(key/itemIds/isAll) + transcribe → data 배열/값.
	_assembleData(bookmark, tr) {
		const { key, itemIds } = bookmark;
		const ai = tr.aiResult || {};
		const summaryTime = tr.summaryTime || [];
		const segments = tr.segments || [];
		const mergedSegments = tr.mergedSegments || [];
		const speakerInfo = tr.speakerInfo || [];
		const hasItems = Array.isArray(itemIds) && itemIds.length > 0;

		if (!hasItems) {
			// itemIds 비었/없음 = 해당 key 전체
			switch (key) {
				case 'summaryTime':
					return summaryTime;
				case 'segments':
					return segments;
				case 'speakerInfo':
					return speakerInfo;
				case 'topics':
					return ai.topics ?? null;
				case 'keywords':
					return ai.keywords ?? null;
				case 'summary':
					return ai.summary ?? null;
				case 'issues':
					return ai.issues ?? null;
				case 'tasks':
					return ai.tasks ?? null;
				default:
					return null;
			}
		}

		// itemIds 지정 = 해당 항목만 필터
		switch (key) {
			case 'summaryTime':
				return summaryTime.filter(s => itemIds.includes(String(s.index)));
			case 'mergedSegments':
				return mergedSegments
					.filter(s => itemIds.includes(s.segmentId))
					.map(s => this._mapSegment(s, speakerInfo));
			case 'segments':
				return segments.filter(s => itemIds.includes(s.segmentId)).map(s => this._mapSegment(s, speakerInfo));
			default:
				return null;
		}
	}

	// 뷰 1행 형태 { id, contentId, key, time, isAll, data }. 구 뷰의 $match{data:{$ne:[]}} = 빈 배열만 드롭.
	// id는 구 뷰가 TranscribeResult._id를 반환하던 것을 그대로 유지(동작 보존).
	_buildRow(bookmark, tr) {
		if (!tr) return null; // 뷰 base가 TranscribeResult라 전사결과 없으면 애초에 미출력
		const data = this._assembleData(bookmark, tr);
		// 데이터가 사라진 스테일 북마크(예: 재요약으로 aiResult.topics가 null이 된 topics 북마크)는
		// 빈 배열뿐 아니라 null도 드롭한다. (null이 그대로 나가면 FO에서 null.join() 크래시)
		if (data == null || (Array.isArray(data) && data.length === 0)) return null;
		return {
			id: tr.id,
			contentId: bookmark.contentId,
			key: bookmark.key,
			time: bookmark.time,
			isAll: bookmark.isAll,
			data,
		};
	}

	// 북마크 목록 → 참조 TranscribeResult(fileId 인덱스)만 로드해 행 조립.
	async _assembleRows(bookmarks) {
		if (!bookmarks.length) return [];
		const fileIds = [...new Set(bookmarks.map(b => b.fileId).filter(Boolean))];
		const transcribes = await this.mongoDB.transcribeResult.findMany({
			where: { fileId: { in: fileIds } },
			select: BookmarkModel.TRANSCRIBE_SELECT,
		});
		const trByFileId = new Map(transcribes.map(t => [t.fileId, t]));
		return bookmarks.map(bm => this._buildRow(bm, trByFileId.get(bm.fileId))).filter(Boolean);
	}

	async getBookmarks(contentsIds, take) {
		const options = {
			orderBy: { time: 'desc' },
			where: { contentId: { in: contentsIds } },
		};
		if (take > 0) options.take = take;

		const bookmarks = await this.mongoDB.bookmarks.findMany(options);
		return this._assembleRows(bookmarks);
	}

	async getBookmarksByContentId(contentId) {
		const bookmarks = await this.mongoDB.bookmarks.findMany({
			where: { contentId },
			orderBy: { time: 'desc' },
		});
		return this._assembleRows(bookmarks);
	}

	async getBookmarksByItem(contentId, key) {
		return await this.mongoDB.bookmarks.findFirst({
			where: {
				contentId,
				key,
			},
			select: {
				id: true,
				key: true,
				itemIds: true,
				time: true,
			},
		});
	}

	async getBookmarksPartially(fileId) {
		return await this.mongoDB.bookmarks.findMany({
			where: {
				fileId,
			},
			select: {
				id: true,
				key: true,
				itemId: true,
				createAt: true,
				updateAt: true,
			},
		});
	}

	async updatePartialBookmark({ id, itemIds, isAll }) {
		return await this.mongoDB.bookmarks.update({
			where: {
				id,
			},
			data: {
				itemIds,
				isAll,
				time: new Date(),
			},
		});
	}

	async createPartialBookmark({ contentId, fileId, key, itemIds, isAll }) {
		return await this.mongoDB.bookmarks.create({
			data: {
				contentId,
				fileId,
				key,
				itemIds,
				isAll,
				time: new Date(),
			},
		});
	}

	async deletePartialBookmark({ id }) {
		return await this.mongoDB.bookmarks.delete({
			where: {
				id,
			},
		});
	}

	// 파일의 모든 북마크 삭제(재요약 STT 재실행 시 세그먼트가 새로 생성되어 기존 북마크 앵커가 무효화되므로 정리).
	async deleteBookmarksByFileId(fileId) {
		return await this.mongoDB.bookmarks.deleteMany({
			where: {
				fileId,
			},
		});
	}

	// 요약만 재수행(STT 미포함) 재요약 시: 전사(segments/mergedSegments/speakerInfo)는 그대로이므로 보존하고,
	// 재생성되는 AI요약 파생 북마크(topics/keywords/summary/issues/tasks/summaryTime)만 정리한다.
	async deleteBookmarksByFileIdAndKeys(fileId, keys) {
		return await this.mongoDB.bookmarks.deleteMany({
			where: {
				fileId,
				key: { in: keys },
			},
		});
	}
}

export default new BookmarkModel();
