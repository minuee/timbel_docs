import { memoService } from '../../../services/index.js';
import base from '../../base.controller.js';
import authHandler from '../../../handlers/auth.handler.js';
import { HttpError } from '../../../handlers/error.handler.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';

class ContentMemoController {
	async getMemos(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;

			await authHandler.isMoreThanContentViewer(contentId, auth, user);

			const memos = await memoService.getMemosByContentId(contentId, user.pid);
			base.sendSuccess(res, memos);
		} catch (err) {
			next(err);
		}
	}

	async createMemo(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { item, itemId = null, text, isSecret = false, segmentId = null, startTime = null } = req.body;

			if (!contentId || !item || !text) throw new HttpError(1000);

			const isItemIdRequired = ['segments', 'mergedSegments'];
			if (isItemIdRequired.includes(item) && !itemId)
				throw new HttpError(400, `${isItemIdRequired.join(', ')} 경우 itemId가 필수입니다.`);

			const itemList = Object.values(Enums.MemoItem);
			if (!itemList.includes(item))
				throw new HttpError(400, `item 파라미터는 ${itemList.join(', ')} 중 하나여야 합니다.`);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const createMemoDTO = { contentId, item, itemId, text, isSecret, segmentId, startTime };
			const memo = await memoService.createMemo(createMemoDTO, auth, user);
			base.sendCreated(res, memo);
		} catch (err) {
			next(err);
		}
	}

	async updateMemoText(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, memoId } = req.params;
			const { text } = req.body;

			if (!contentId || !memoId || !text) throw new HttpError(1000);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const updateMemoDTO = { contentId, memoId, text };
			const memo = await memoService.updateMemo(updateMemoDTO, auth, user);
			base.sendSuccess(res, memo);
		} catch (err) {
			next(err);
		}
	}

	async updateMemoSecret(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, memoId } = req.params;
			const { isSecret } = req.body;

			if (!contentId || !memoId || typeof isSecret !== 'boolean') throw new HttpError(1000);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const updateMemoDTO = { contentId, memoId, isSecret };
			const memo = await memoService.updateMemo(updateMemoDTO, auth, user);
			base.sendSuccess(res, memo);
		} catch (err) {
			next(err);
		}
	}

	async updateContentMemosSecret(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { isSecret } = req.body;

			if (!contentId || typeof isSecret !== 'boolean') throw new HttpError(1000);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const updateMemoDTO = { contentId, isSecret };
			const memo = await memoService.updateContentMemosSecret(updateMemoDTO, auth, user);
			base.sendSuccess(res, memo);
		} catch (err) {
			next(err);
		}
	}

	async deleteMemo(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, memoId = null } = req.params;

			if (!contentId) throw new HttpError(1000);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			await memoService.softDeleteMemo(contentId, memoId, auth, user);
			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	async createMemoComment(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, memoId } = req.params;
			const { text } = req.body;

			if (!contentId || !memoId || !text) throw new HttpError(1000);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const createMemoCommentDTO = { contentId, memoId, text };
			const memo = await memoService.createMemoComment(createMemoCommentDTO, auth, user);
			base.sendCreated(res, memo);
		} catch (err) {
			next(err);
		}
	}

	async updateMemoCommentText(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, memoId, commentId } = req.params;
			const { text } = req.body;

			if (!contentId || !memoId || !commentId || !text) throw new HttpError(1000);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const updateMemoCommentDTO = { contentId, memoId, commentId, text };
			const memo = await memoService.updateMemoCommentText(updateMemoCommentDTO, auth, user);
			base.sendSuccess(res, memo);
		} catch (err) {
			next(err);
		}
	}

	async deleteMemoComment(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId, memoId, commentId } = req.params;

			if (!contentId || !memoId || !commentId) throw new HttpError(1000);

			await authHandler.isMoreThanContentEditor(contentId, auth, user);
			const deleteMemoCommentDTO = { contentId, memoId, commentId };
			await memoService.softDeleteMemoComment(deleteMemoCommentDTO, auth, user);
			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}
}

export default new ContentMemoController();
