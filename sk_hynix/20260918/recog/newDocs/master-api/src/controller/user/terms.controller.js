import base from '../base.controller.js';
import { HttpError } from '../../handlers/error.handler.js';
import { userService } from '../../services/index.js';

class UserTermsController {
	async getTermsConsent(req, res, next) {
		try {
			const { user, auth } = req;
			const workspaceId = auth.member.workspace.id;
			const data = await userService.getTermsConsentStatus(user, workspaceId);
			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async createTermsConsent(req, res, next) {
		try {
			const { user, auth } = req;
			const { agreements } = req.body;

			// HTTP 요청 데이터 기본 검증
			if (!agreements || !Array.isArray(agreements)) {
				throw new HttpError(1000, '동의할 약관 정보를 올바르게 입력해주세요');
			}

			// 각 동의서 항목 기본 유효성 검사
			for (const agreement of agreements) {
				if (!agreement.termsId || !agreement.status) {
					throw new HttpError(1000, '약관 ID와 동의 상태를 모두 입력해주세요');
				}
				if (!['CONSENTED', 'DECLINED'].includes(agreement.status)) {
					throw new HttpError(1000, '동의 상태는 CONSENTED 또는 DECLINED만 가능합니다');
				}
			}

			// 사용자 정보 추출
			if (!user?.email) {
				throw new HttpError(1000, '사용자 정보를 확인할 수 없습니다');
			}

			const userName = user.nickName || user.name || '';
			const email = user.email;

			const workspaceId = auth.member.workspace.id;
			// IP 주소와 User-Agent 추출
			const ipAddress = req.headers['x-real-ip'] || req.ip || 'unknown';
			const userAgent = req.headers['user-agent'] || 'unknown';

			const data = await userService.createTermsAgreement(
				{ userName, email },
				{ agreements },
				{ ipAddress, userAgent, workspaceId }
			);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}
}

export default new UserTermsController();

