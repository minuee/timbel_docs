import axios from 'axios';
import error from '../../configs/error.js';
import { findProfileByEmpno, findUserByPID } from '../../models/user.js';
import tokenAuthService from '../tokenService/tokenAuthService.js';
import parseRequestParam from '@baronote/tool/express/parseRequestParam.js';

// [초안] PC 녹음앱 시스템 로그인(AM-Tray) — 인가토큰 → 우리 토큰
//
// 흐름 (AM-Tray 시스템간 인증프로세스 ⑪~⑭)
//   1) PC앱이 AM-Tray DLL(GetSystemToken)로 받은 인가토큰(authzToken)을 보낸다.
//   2) 이 서버가 SSO 서버 ValidateToken 으로 검증한다(서버 to 서버) → USERID(사번)
//   3) 사번으로 사용자를 찾아 우리 토큰을 발급한다.
//      (약관 동의 확인은 하지 않는다 — PC앱이 로그인 뒤 따로 확인한다)
//
// 응답: 다른 로그인과 같은 형식 { message, httpCode, data: { tokens: { accessToken, refreshToken }, is2FA } }
// 실패 httpCode: 403 사용자 없음 / 401 인가토큰 검증 실패
//
// .env
//   AMTRAY_VALIDATE_URL  개발 https://samlamdev.skhynix.com/tray/api/ValidateToken
//                        운영 https://csam.skhynix.com/tray/api/ValidateToken
//   AMTRAY_SYSTEM_ID     AIMEETING (AM 담당자 확정값)

const TAG = '[SSO_AMTRAY]';
const VALIDATE_TIMEOUT_MS = 10 * 1000;

// ValidateToken 응답에서 결과·사용자 ID 를 꺼낸다.
// 자료마다 표기가 달라서(Result/RESULT/RESULTID, Success/SUCCESS/SUCCES) 대소문자를 가리지 않고 본다.
const readValidateResult = (body = {}) => {
	const attr = body.attr || body.ATTR || {};
	const result = String(attr.Result ?? attr.RESULT ?? attr.RESULTID ?? attr.ResultId ?? '').toUpperCase();
	const userId = String(attr.USERID ?? attr.UserId ?? attr.userId ?? '').trim();
	return { status: body.status, result, userId };
};

// 인가토큰 검증 → USERID(사번). 실패면 throw.
export const validateAuthzToken = async authzToken => {
	const url = process.env.AMTRAY_VALIDATE_URL;
	const systemID = process.env.AMTRAY_SYSTEM_ID || 'AIMEETING';
	if (!url) {
		log.e(TAG, 'AMTRAY_VALIDATE_URL 미설정');
		throw error.AmTrayValidateError;
	}

	let body;
	try {
		const { data } = await axios.post(
			url,
			{ systemID, authzToken },
			{ headers: { 'Content-Type': 'application/json' }, timeout: VALIDATE_TIMEOUT_MS }
		);
		body = data;
	} catch (err) {
		// 인가토큰 값은 로그에 남기지 않는다
		log.e(TAG, 'ValidateToken 호출 실패 => ', err.message, err.response?.status);
		throw error.AmTrayValidateError;
	}

	const { status, result, userId } = readValidateResult(body);
	log.i(TAG, 'ValidateToken 응답 => ', JSON.stringify({ status, result, hasUserId: !!userId }));

	if ((result === 'SUCCESS' || result === 'SUCCES') && userId) return userId;
	if (result === 'SYSTEMID_INVALID') throw error.AmTraySystemIdInvalidError;
	if (result === 'TOKEN_INVALID') throw error.AmTrayTokenInvalidError;
	throw error.AmTrayValidateError;
};

const ssoAmTray = async (req, res) => {
	try {
		const authzToken = parseRequestParam(req, 'authzToken');
		if (!authzToken) throw error.ParamsUndefinedError;

		// 1) 인가토큰 검증 → 사번
		const empno = await validateAuthzToken(authzToken);

		// 2) 사번 → 프로필(pid, email)
		//    ※ 신규 사용자는 여기서 만들 수 없다(ValidateToken 은 사번만 준다 — 이름·이메일 없음).
		//      웹 SSO 로 한 번 로그인해 계정이 있어야 한다.
		const profile = await findProfileByEmpno(empno);
		if (!profile) throw error.NotFoundUserInfo;

		// 3) 토큰 발급
		const submitter = await findUserByPID(profile.pid, { profile: { include: { company: true } } });
		if (!submitter) throw error.NotFoundUserInfo;

		const { session } = req;
		session.isSSO = true;
		return tokenAuthService(submitter, session, res);
	} catch (err) {
		log.e(TAG, 'error => ', err.message);
		res.sendJsonError(err);
	}
};

export default ssoAmTray;
