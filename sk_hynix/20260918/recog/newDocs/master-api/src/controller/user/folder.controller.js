import base from '../base.controller.js';
import { HttpError } from '../../handlers/error.handler.js';
import { userService } from '../../services/index.js';
import { validate } from '../../utils/index.js';

class UserFolderController {
	async createFolder(req, res, next) {
		try {
			const { user } = req;
			const { name } = req.body;

			if (!name?.trim()) throw new HttpError(1000, '폴더 이름을 입력해주세요');
			if (name.length > 20) throw new HttpError(1000, '폴더 이름은 20자 이하로 입력해주세요');

			const data = await userService.createFolder(user, name);
			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async getFolders(req, res, next) {
		try {
			const { user, auth } = req;
			const workspaceId = auth?.member?.workspace?.id;

			const data = await userService.getFolders(user, workspaceId);
			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async getFolderItems(req, res, next) {
		try {
			const { user, auth } = req;
			const { folderId } = req.params;
			if (!folderId) throw new HttpError(1000, '폴더 아이디를 전달해주세요');

			const options = validate.parseContentsQueryOptions({ ...req.query, folderId });
			const workspaceId = auth?.member?.workspace?.id;

			const contents = await userService.getFolderItems(user, options, workspaceId);
			base.sendSuccess(res, contents);
		} catch (err) {
			next(err);
		}
	}

	async moveContentToFolder(req, res, next) {
		try {
			const { user } = req;
			const { folderId, contentIds = [] } = req.body;

			if (!folderId) throw new HttpError(1000, '폴더 아이디를 전달해주세요');
			if (contentIds?.length === 0) throw new HttpError(1000, '콘텐츠 아이디를 전달해주세요');

			await userService.moveContentToFolder(user, contentIds, folderId);

			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	async updateFolder(req, res, next) {
		try {
			const { user } = req;
			const { folderId } = req.params;
			const { name } = req.body;

			if (!folderId) throw new HttpError(1000, '폴더 아이디를 전달해주세요');
			if (!name?.trim()) throw new HttpError(1000, '폴더 이름을 입력해주세요');
			if (name.length > 20) throw new HttpError(1000, '폴더 이름은 20자 이하로 입력해주세요');

			const data = await userService.updateFolder(user, folderId, name);
			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async deleteFolder(req, res, next) {
		try {
			const { user, auth } = req;
			const { folderId } = req.params;

			if (!folderId) throw new HttpError(1000, '폴더 아이디를 전달해주세요');

			await userService.deleteFolder(user, auth, folderId);
			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}
}

export default new UserFolderController();

