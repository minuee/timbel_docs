import { HttpError } from './error.handler.js';
import { redis, generate } from '../utils/index.js';
import memberModel from '../models/member.model.js';

const TAG = '[authorizeMember] ';
// STT를 재수행하는 경로는 workspace.config.transcribeEngine이 필요하다(재요약 STT 포함 토글 On 시 recog 진입).
const UPLOAD_RELATED_PATHS = ['upload', 'merge', 'retry', 'reSummary'];

const getDefaultMemberOptions = (isUpload = false) => ({
	id: true,
	role: true,
	workspace: {
		select: {
			id: true,
			name: true,
			domain: true,
			config:
				!isUpload ? false : (
					{
						select: {
							transcribeEngine: true,
						},
					}
				),
		},
	},
});

const verifyTemporaryAccess = async req => {
	try {
		const { token } = req;
		if (token) {
			const { verify = null, isGuest = false } = await redis.get(`accessTokens:${token}`);
			if (verify && verify.isCert && isGuest) {
				req.auth = { isAuthorized: true };
				log.i(TAG, '-- authorization !isVerified');
				return true;
			}
		}
		return false;
	} catch (err) {
		throw new HttpError(401, '세션 상태를 확인할 수 없습니다.');
	}
};

const authorizeMember = async (req, res, next) => {
	try {
		const { user, headers, path } = req;
		const { 'x-timblo-mobi-gw': isMobile = 'FALSE' } = headers;
		if (await verifyTemporaryAccess(req)) return next();
		log.i(TAG, '-- 멤버 인증으로 진행');

		const options = getDefaultMemberOptions(UPLOAD_RELATED_PATHS.some(keyword => path.includes(keyword)));
		const member = await memberModel.findMemberByPID(user.pid, options);
		const salt = `${member.id}${member.workspace.id}`;

		log.i(TAG, '-- 인증 멤버:', member);
		req.auth = {
			member,
			isAuthorized: true,
			config: {
				...user.config,
				isMobile: isMobile?.trim().toUpperCase() === 'TRUE',
			},
			kms: generate.keyFromString(salt),
		};
	} catch (err) {
		return next(err);
	}
	next();
};

export default authorizeMember;
