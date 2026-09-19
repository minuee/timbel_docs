import { noteService } from '../../../services/index.js';
import base from '../../base.controller.js';
import authHandler from '../../../handlers/auth.handler.js';
import { HttpError } from '../../../handlers/error.handler.js';

class ContentNoteController {
	async getNoteContent(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;

			if (!contentId) {
				throw new HttpError(1000);
			}

			await authHandler.isMoreThanContentViewer(contentId, auth, user);

			const result = await noteService.getNoteContent(contentId);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async updateNoteContent(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { content = '' } = req.body;

			if (!contentId) {
				throw new HttpError(1000);
			}

			if (typeof content !== 'string') {
				throw new HttpError(400, 'content는 string이어야 합니다.');
			}

			await authHandler.isMoreThanContentEditor(contentId, auth, user);

			const result = await noteService.updateNoteContent(user, contentId, content, auth);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async pasteTextIntoNote(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { itemKey, itemValue } = req.body;

			if (!contentId || !itemKey || !itemValue) {
				throw new HttpError(1000);
			}

			await authHandler.isMoreThanContentOwner(contentId, auth, user);

			const result = await noteService.pasteTextIntoNote(user, contentId, itemKey, itemValue, auth);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async getMyNoteContent(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;

			if (!contentId) throw new HttpError(1000);
			await authHandler.isMoreThanContentViewer(contentId, auth, user);

			const result = await noteService.getMyNoteContent(user, contentId);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async updateMyNoteContent(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;
			const { content } = req.body;

			if (!contentId) throw new HttpError(1000);
			await authHandler.isMoreThanContentViewer(contentId, auth, user);

			const result = await noteService.updateMyNoteContent(user, contentId, content);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async getNoteTemplates(req, res, next) {
		try {
			const { auth, user } = req;
			const { contentId } = req.params;

			await authHandler.isMoreThanContentEditor(contentId, auth, user);

			const result = await noteService.getNoteTemplates(auth.member.workspace.id);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}
}

export default new ContentNoteController();

