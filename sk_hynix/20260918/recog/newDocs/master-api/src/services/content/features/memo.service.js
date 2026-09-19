import contentModel from '../../../models/content.model.js';
import memoModel from '../../../models/memo.model.js';
import { HttpError } from '../../../handlers/error.handler.js';
import contentCaptureService from '../contentCapture.service.js';

const getMemosByContentId = async (contentId, pid) => {
	const memos = await memoModel.getMemosByContentId(contentId);
	if (memos.length === 0) return [];

	return memos.map(memo => {
		if (memo.deleteAt !== null || (pid && memo.isSecret && memo.creator?.user?.profile?.pid !== pid))
			memo.text = null;

		memo.comments.map(comment => {
			if (comment.deleteAt !== null || (pid && memo.isSecret && comment.creator?.user?.profile?.pid !== pid))
				comment.text = null;

			return comment;
		});
		return memo;
	});
};

const getMemo = async (memoId, contentId, creatorId) => {
	const memo = await memoModel.getMemo(memoId);
	if (!memo || memo?.contentId !== contentId) throw new HttpError(2301);
	if (creatorId && memo.creatorId !== creatorId) throw new HttpError(2302);
	return memo;
};

const getContentMemosByCreator = async (contentId, creatorId) => {
	const memos = await memoModel.getContentMemosByCreator(contentId, creatorId);
	if (memos.length === 0) throw new HttpError(2304);
	return memos;
};

const createMemo = async (data, { member }, user) => {
	try {
		const { contentId, item, itemId, text, isSecret } = data;
		const file = await contentModel.findFileByContentId(contentId);
		const result = await memoModel.findItemInfo(file.id, item, item === 'summaryTime' ? parseInt(itemId) : itemId);
		if (!result) throw new HttpError(2303);

		const startTime =
			item === 'segments' || item === 'mergedSegments' ?
				result[item].find(segment => segment.segmentId === itemId).startTime
			:	null;

		const createMemoDto = { contentId, item, itemId, text, isSecret, startTime, creatorId: member.id };
		const createdMemo = await memoModel.createMemo(createMemoDto);
		await contentCaptureService.createContentCapture('CONTENT', 'UPDATE_MEMO', contentId, member.id, user);
		return createdMemo;
	} catch (err) {
		log.e(`createMemo error: ${err}`);
		throw err;
	}
};

const updateMemo = async (data, { member }, user) => {
	try {
		const { contentId, memoId, text = null, isSecret = null } = data;
		await getMemo(memoId, contentId, member.id);

		const updateMemoDTO = { text, isSecret };
		const updatedMemo = await memoModel.updateMemo(memoId, updateMemoDTO);
		await contentCaptureService.createContentCapture('CONTENT', 'UPDATE_MEMO', contentId, member.id, user);
		return updatedMemo;
	} catch (err) {
		log.e(`updateMemo error: ${err}`);
		throw err;
	}
};

const updateContentMemosSecret = async (data, { member }, user) => {
	try {
		const { contentId, isSecret } = data;
		await getContentMemosByCreator(contentId, member.id);

		const updatedMemos = await memoModel.updateMemosSecret(contentId, isSecret);
		await contentCaptureService.createContentCapture('CONTENT', 'UPDATE_MEMO', contentId, member.id, user);
		return updatedMemos;
	} catch (err) {
		log.e(`updateContentMemosSecret error: ${err}`);
		throw err;
	}
};

const softDeleteMemo = async (contentId, memoId, { member }, user) => {
	try {
		const memoIds = [];
		if (memoId) {
			await getMemo(memoId, contentId, member.id);
			memoIds.push(memoId);
		} else {
			const memos = await getContentMemosByCreator(contentId, member.id);
			memoIds.push(...memos.map(item => item.id));
		}

		const deletedMemosCount = await memoModel.softDeleteMemo(memoIds);
		await contentCaptureService.createContentCapture('CONTENT', 'UPDATE_MEMO', contentId, member.id, user);
		return deletedMemosCount;
	} catch (err) {
		log.e(`softDeleteMemo error: ${err}`);
		throw err;
	}
};

const getMemoComment = async (memoId, contentId, commentId) => {
	const memo = await getMemo(memoId, contentId);
	if (!memo.comments.find(comment => comment.id === commentId)) throw new HttpError(2305);
};

const createMemoComment = async (data, { member }, user) => {
	try {
		const { contentId, memoId } = data;
		await getMemo(memoId, contentId);

		const createMemoCommentDTO = {
			memoId,
			creatorId: member.id,
			text: data.text,
		};
		const createdComment = await memoModel.createMemoComment(createMemoCommentDTO);
		await contentCaptureService.createContentCapture('CONTENT', 'UPDATE_MEMO', contentId, member.id, user);
		return createdComment;
	} catch (err) {
		log.e(`createMemoComment error: ${err}`);
		throw err;
	}
};

const updateMemoCommentText = async (data, { member }, user) => {
	try {
		const { contentId, memoId, commentId, text } = data;
		await getMemoComment(memoId, contentId, commentId);

		const updatedMemo = await memoModel.updateMemoComment(commentId, { text });
		await contentCaptureService.createContentCapture('CONTENT', 'UPDATE_MEMO', contentId, member.id, user);
		return updatedMemo;
	} catch (err) {
		log.e(`updateMemoCommentText error: ${err}`);
		throw err;
	}
};

const softDeleteMemoComment = async (data, { member }, user) => {
	try {
		const { contentId, memoId, commentId } = data;
		await getMemoComment(memoId, contentId, commentId);

		await memoModel.softDeleteMemoComment(commentId);
		await contentCaptureService.createContentCapture('CONTENT', 'UPDATE_MEMO', contentId, member.id, user);
	} catch (err) {
		log.e(`softDeleteMemoComment error: ${err}`);
		throw err;
	}
};

const realDeleteMemosByContentId = async contentId => {
	try {
		await memoModel.realDeleteMemosByContentId(contentId);
	} catch (err) {
		log.e(`realDeleteMemosByContentId error: ${err}`);
		throw err;
	}
};

export default {
	getMemosByContentId,
	createMemo,
	updateMemo,
	updateContentMemosSecret,
	softDeleteMemo,
	createMemoComment,
	updateMemoCommentText,
	softDeleteMemoComment,
	realDeleteMemosByContentId,
};
