import notify from '../../../utils/notify.util.js';
import userModel from '../../../models/user.model.js';
import shareModel from '../../../models/share.model.js';
import contentModel from '../../../models/content.model.js';
import { HttpError } from '../../../handlers/error.handler.js';
import contentCaptureService from '../contentCapture.service.js';

class ShareService {
	constructor() {
		this.shareModel = shareModel;
		this.userModel = userModel;
		this.contentModel = contentModel;
		this.contentCaptureService = contentCaptureService;
	}

	async getContentShareUsers(contentId) {
		try {
			const result = [];
			const creator = await this.contentModel.findContentCreatorByContentId(contentId);
			result.push({
				contentId,
				role: this.contentModel.Enums.ContentShareRole.OWNER,
				email: creator.creatorEmail,
				nickName: creator.creatorNickName,
				thumbnailUrl: creator.creatorThumbnailUrl,
				createAt: creator.updateAt,
			});
			const sharedUsers = await this.shareModel.getContentShareUsers(contentId);
			result.push(...sharedUsers);
			return result;
		} catch (error) {
			throw error;
		}
	}

	async updateShareUserPermission(contentId, email, permission) {
		try {
			log.i('[ShareService : updateShareUserPermission] email : ', email);
			const [result] = await Promise.all([
				this.shareModel.updateShareUsersPermission(contentId, [email], permission),
				notify.updatingContentPermission(permission, contentId, [email]),
			]);
			return result;
		} catch (error) {
			throw error;
		}
	}

	// 컨텐츠 공유자 개별 추가(범용)
	async addContentShareUser({ member, config }, user, contentId, targetEmail) {
		try {
			const shareUser = await this.shareModel.getContentShareUserRole(contentId, targetEmail);
			if (shareUser) throw new HttpError(1301);

			let result = await this.shareModel.addContentShareUser(contentId, targetEmail);
			const targetUser = await this.userModel.findUserProfileByEmail(targetEmail);

			log.i('[ShareService : addContentShareUser] targetUser : ', targetUser);
			if (!targetUser) {
				await notify.inviteEmail(targetEmail, contentId, user);
				result = {
					...result,
					nickName: null,
					thumbnailUrl: null,
				};
			} else {
				await notify.sharedContent(user, targetEmail, contentId, config.isMobile);
				result = {
					...result,
					nickName: targetUser.nickName,
					thumbnailUrl: targetUser.thumbnailUrl,
				};

				await this.contentCaptureService.createContentCapture(
					'SHARE',
					'SHARED',
					contentId,
					member.id,
					user,
					0,
					targetEmail
				);
			}

			return result;
		} catch (error) {
			throw error;
		}
	}

	// 컨텐츠 공유자 다중 추가(주소록 기반)
	async addContentShareUsers({ member, config }, user, contentId, emails, role) {
		try {
			const usersBeforeShared = await this.shareModel.getContentShareUsers(contentId);

			// 이미 공유된 이메일 매핑 및 권한 기록
			const sharedEmailMap = {};
			usersBeforeShared.forEach(user => {
				sharedEmailMap[user.email] = user.role;
			});

			// 신규 공유 이메일과 권한 업데이트 필요 이메일을 분류
			const emailsToShare = [];
			const emailsToUpdateRole = [];
			emails.forEach(email => {
				if (email in sharedEmailMap) {
					if (sharedEmailMap[email] !== role) emailsToUpdateRole.push(email);
				} else {
					emailsToShare.push(email);
				}
			});

			if (emailsToShare.length === 0 && emailsToUpdateRole.length === 0) {
				return await this.getContentShareUsers(contentId);
			}

			// 신규 공유 및 권한 업데이트
			const promises = [];
			if (emailsToUpdateRole.length > 0) {
				promises.push(this.shareModel.updateShareUsersPermission(contentId, emailsToUpdateRole, role));
				promises.push(notify.updatingContentPermission(role, contentId, emailsToUpdateRole));
			}
			if (emailsToShare.length > 0) {
				promises.push(this.shareModel.addContentShareUsers(contentId, emailsToShare, role));
			}
			if (promises.length > 0) await Promise.all(promises);

			log.i('[ShareService : addContentShareUsers] emailsToShare : ', emailsToShare);

			const usersAfterShared = await this.getContentShareUsers(contentId);

			emailsToShare.forEach(async targetEmail => {
				// 공유자 알림 발송
				// 추후, 다중 공유 전용의 알림 기획 여부 검토필요
				await notify.sharedContent(user, targetEmail, contentId, config.isMobile);
				await this.contentCaptureService.createContentCapture(
					'SHARE',
					'SHARED',
					contentId,
					member.id,
					user,
					0,
					targetEmail
				);
			});

			return usersAfterShared;
		} catch (error) {
			throw error;
		}
	}

	async getContentShareUserRole(contentId, email) {
		try {
			const role = await this.shareModel.getContentShareUserRole(contentId, email);

			if (!role) {
				throw new HttpError(1304);
			}

			return role;
		} catch (error) {
			throw error;
		}
	}

	async deleteContentShareUser(contentId, targetEmail) {
		try {
			await this.shareModel.deleteContentShareUser(contentId, targetEmail);
			await notify.sharedContentEvent(contentId, [targetEmail], false);
			return {};
		} catch (error) {
			throw error;
		}
	}
}

export default new ShareService();
