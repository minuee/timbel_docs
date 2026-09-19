import { HttpError } from './error.handler.js';
import memberModel from '../models/member.model.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';

class Authorization {
	constructor() {
		this.contentRoles = Enums.ContentShareRole;
	}
	/**
	 *
	 * Workspace 상에서 콘텐츠 작성 권한이 있는지 확인
	 *
	 * @param {*} auth
	 */
	isMember({ isAuthorized = false, member = undefined }) {
		if (!isAuthorized) return false;
		if (!member) return false;
		if (member.role === memberModel.Enums.WorkspaceRole.GUEST) {
			throw new HttpError(1004);
		}
	}

	/**
	 * @param {*} contentId
	 * @param {*} auth
	 * @param {*} user
	 * @returns {Promise<{contentId: number, workspaceId: number, creatorId: number, title: string, role: string}>}
	 * @description 콘텐츠 접근 권한 확인 후, shareUser를 role로 처리하여 반환
	 */
	async getUserRole(contentId, { member }, user) {
		const userContentAuth = await memberModel.findMemberContentByIdAndCreatorId(contentId, member.id, user.email);
		if (!userContentAuth) throw new HttpError(1121); // '아직 전사 결과가 없습니다.'
		const { shareUsers, ...rest } = userContentAuth;
		if (userContentAuth.creatorId === member.id) return { ...rest, role: this.contentRoles.OWNER };
		if (shareUsers.length === 0) throw new HttpError(1001); // 뷰어 이상 권한 필요
		return { ...rest, role: shareUsers[0].role };
	}

	// 요구하는 availableRoles 수준만큼 권한이 있는지 확인만 함
	async checkContentUserRole(contentId, { member }, user, availableRoles, permissionErrorCode = 1003) {
		const userContentAuth = await this.getUserRole(contentId, { member }, user);
		if (!availableRoles.includes(userContentAuth.role)) {
			const errorCode = availableRoles.includes(this.contentRoles.OWNER) ? permissionErrorCode : 1002; // 1003:소유자 권한~. 1002:편집자 이상 권한~
			throw new HttpError(errorCode);
		}
		return userContentAuth;
	}

	async isMoreThanContentViewer(contentId, { member }, user) {
		return await this.getUserRole(contentId, { member }, user);
	}

	async isMoreThanContentDownloader(contentId, { member }, user) {
		const availableRoles = Object.keys(this.contentRoles).filter(role => role !== this.contentRoles.VIEWER);
		return await this.checkContentUserRole(contentId, { member }, user, availableRoles, 1005);
	}

	async isMoreThanContentEditor(contentId, { member }, user) {
		const availableRoles = Object.keys(this.contentRoles).filter(
			role => role !== this.contentRoles.VIEWER && role !== this.contentRoles.DOWNLOADER
		);
		return await this.checkContentUserRole(contentId, { member }, user, availableRoles, 1002);
	}

	async isMoreThanContentOwner(contentId, { member }, user) {
		return await this.checkContentUserRole(contentId, { member }, user, [this.contentRoles.OWNER]);
	}

	async checkStreamAuth(contentId, { member }, user, { range }) {
		if (!range) return this.isMoreThanContentDownloader(contentId, { member }, user);
		return this.isMoreThanContentViewer(contentId, { member }, user);
	}
}

export default new Authorization();
