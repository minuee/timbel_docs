import base from '../base.controller.js';
import { HttpError } from '../../handlers/error.handler.js';
import { userService } from '../../services/index.js';
import { convert } from '../../utils/index.js';

class UserWorkspaceController {
	async getMembersFromWorkspace(req, res, next) {
		try {
			const { auth, user } = req;
			let { keyword } = req.params;

			if (!keyword.trim()) throw new HttpError(1000, '검색어를 입력해주세요');

			keyword = convert.keywordTransform(keyword);

			const workspaceId = auth.member.workspace.id;
			const users = await userService.getMembersFromWorkspace(workspaceId, user?.pid, keyword);

			base.sendSuccess(res, users);
		} catch (err) {
			next(err);
		}
	}
}

export default new UserWorkspaceController();
