import contentModel from '../../../models/content.model.js';
import bookmarkModel from '../../../models/bookmark.model.js';
import { HttpError } from '../../../handlers/error.handler.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';
import contentCaptureService from '../contentCapture.service.js';

const groupByContentId = (bookmarks, contentMap) => {
	const groupedData = {};

	bookmarks.forEach(item => {
		const { contentId, key, time, data: itemData } = item;

		if (!groupedData[contentId]) {
			const content = contentMap[contentId];
			const { type, title, createAt, updateAt, creator, editor, editedTitle, shareUsers } = content;
			const creatorNickName = creator.user.profile.nickName;
			const creatorPID = creator.user.profile.pid;
			const editorNickName = editor ? editor.user.profile.nickName : undefined;

			groupedData[contentId] = {
				contentId,
				bookmarkTime: time,
				title,
				editedTitle,
				contentType: type,
				createAt,
				updateAt,
				creatorNickName,
				creatorPID,
				lastUpdator: editorNickName || creatorNickName,
				bookmarks: {},
				shareUsers,
			};
		}

		if (!groupedData[contentId].bookmarks[key]) {
			groupedData[contentId].bookmarks[key] = [];
		}

		groupedData[contentId].bookmarks[key] = itemData;
	});

	return Object.values(groupedData);
};

const getBookmarks = async ({ email }, { member }) => {
	const contents = await contentModel.getBookmarkContents(email, member);

	const contentMap = contents.reduce((acc, content) => {
		acc[content.contentId] = content;
		return acc;
	}, {});

	const contentIds = Object.keys(contentMap);
	const bookmarks = await bookmarkModel.getBookmarks(contentIds);

	return groupByContentId(bookmarks, contentMap);
};

const updateBookmark = async (method, contentId, { item, itemId }, { member }, user) => {
	try {
		const file = await contentModel.findFileByContentId(contentId);
		const bookmarks = await bookmarkModel.getBookmarksByItem(contentId, item);
		const result = await bookmarkModel.findItemId(file.id, item, itemId);

		if (!result && itemId !== '-1') throw new HttpError(400, '존재하지 않는 itemId로 요청하셨습니다.');

		const params = { contentId, fileId: file.id, key: item, itemIds: [] };

		const isItemIdRequired = ['segments', 'summaryTime', 'mergedSegments'].includes(item);
		const isAlreadyBookmarked = bookmarks?.itemIds?.includes(itemId);

		if (method === 'delete') {
			if (isItemIdRequired) {
				if (!isAlreadyBookmarked && itemId !== '-1') throw new HttpError(400, '북마크된 항목이 아닙니다.');

				params.itemIds = itemId === '-1' ? [] : bookmarks?.itemIds?.filter(id => id !== itemId);
				params.isAll = params.isAll !== Enums.YesNo.N ? Enums.YesNo.N : params.isAll;
			} else {
				if (!bookmarks) throw new HttpError(400, '북마크된 항목이 아닙니다.');
			}
		}

		if (method === 'post') {
			if (isItemIdRequired) {
				if (isAlreadyBookmarked) throw new HttpError(400, '이미 북마크된 항목입니다.');

				if (itemId === '-1') {
					params.itemIds = result[item].map(element => element.segmentId || String(element.index));
					params.isAll = Enums.YesNo.Y;
				} else {
					params.itemIds = bookmarks?.itemIds ? [...bookmarks.itemIds, itemId] : [itemId];
					if (params.itemIds.length === result[item].length) params.isAll = Enums.YesNo.Y;
				}
			} else {
				if (bookmarks?.key === item) throw new HttpError(400, '이미 북마크된 항목입니다.');
			}
		}

		if (bookmarks?.id) {
			params.id = bookmarks.id;
			if ((isItemIdRequired && params.itemIds?.length === 0) || !isItemIdRequired) {
				await bookmarkModel.deletePartialBookmark(params);
			} else {
				await bookmarkModel.updatePartialBookmark(params);
			}
		} else {
			await bookmarkModel.createPartialBookmark(params);
		}

		await contentCaptureService.createContentCapture('CONTENT', 'UPDATE_BOOKMARK', contentId, member.id, user);
	} catch (err) {
		throw err;
	}
};

export default {
	getBookmarks,
	updateBookmark,
};
