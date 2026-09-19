import base from '../../base.controller.js';
import authHandler from '../../../handlers/auth.handler.js';
import { HttpError } from '../../../handlers/error.handler.js';
import bookmarkService from '../../../services/content/features/bookmark.service.js';

class BookmarkController {
	async getBookmarks(req, res, next) {
		try {
			const { user, auth } = req;

			const result = await bookmarkService.getBookmarks(user, auth);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async updateBookmark(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			let { item, itemId } = req.query ?? req.body;
			const method = req.method.toLowerCase();

			if (!method || !contentId || !item) throw new HttpError(400, '파라미터가 없습니다.');

			const isItemIdRequired = ['segments', 'mergedSegments', 'summaryTime'];
			if (isItemIdRequired.includes(item) && !itemId) {
				throw new HttpError(400, `${isItemIdRequired.join(', ')} 경우 itemId가 필수입니다.`);
			}

			const itemList = base.BookmarksKeyValues;
			if (!itemList.includes(item)) {
				throw new HttpError(400, `item 파라미터는 ${itemList.join(', ')} 중 하나여야 합니다.`);
			}

			itemId = isNaN(itemId) ? itemId : String(itemId);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			await bookmarkService.updateBookmark(method, contentId, { item, itemId }, auth, user);

			const httpCode = method === 'delete' ? 204 : 200;
			base.sendSuccess(res, {}, httpCode);
		} catch (err) {
			next(err);
		}
	}
}

export default new BookmarkController();

