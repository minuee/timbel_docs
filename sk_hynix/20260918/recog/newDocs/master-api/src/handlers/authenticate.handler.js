import axios from 'axios';
import jwt from 'jsonwebtoken';
import { HttpError } from './error.handler.js';
import userModel from '../models/user.model.js';

const TAG = '[sessionHandler] ';

const isExternalApiRequest = ({ headers }) => {
	const { 'x-timblo-auth': apiAuth, authorization } = headers;
	if (!apiAuth || !authorization) return false;
	if (apiAuth !== process.env['ENCRYPT_SECRET_KEY']) throw new HttpError(401, '승인되지 않은 API 서버 호출 입니다.');

	return authorization.split(' ')[1];
};

const extractTimbloAuthToken = ({ headers, query }) => {
	let { 'x-timblo-token': token } = headers;

	// 개발 환경 인증 처리를 위한 코드 추가
	if (!token && process.env.NODE_ENV === 'development') {
		const { authorization = null } = headers;
		const { accessToken = null } = query;
		token = !authorization ? accessToken : authorization.split(' ')[1];
	}

	return token;
};

const withTimbloToken = async req => {
	log.i(TAG, '-- timbloTokenAuth Timblo 회원 인증으로 진행');

	const token = extractTimbloAuthToken(req);
	if (!token) throw new HttpError(401);
	log.i(TAG, '-- timbloTokenAuth Header Token 확인');

	log.d(TAG, '-- timbloTokenAuth Token:', token);
	const decoded = jwt.decode(token) ?? {};
	if (!decoded.hasOwnProperty('pid')) throw new HttpError(401, '토큰 정보가 올바르지 않습니다.');
	log.i(TAG, '-- timbloTokenAuth JWT decode 확인');

	req.user = decoded;
	req.token = token;
};

const postConnectAccount = async (employeeInfo, token) => {
	try {
		const { data } = await axios.post(`${process.env.AUTH_API_URL}auth/sso/external`, employeeInfo, {
			headers: {
				Authorization: `Bearer ${token}`,
				'external-api-key': process.env.ENCRYPT_SECRET_KEY,
				'Content-Type': 'application/json',
			},
		});
		if (data.httpCode !== 200) throw new HttpError(401, data.message);
		log.i(TAG, `-- postConnectAccount 회사 정보로 가입 완료`);
		return data;
	} catch (err) {
		throw new HttpError(401, '전사 정보에 등록된 사용자가 아닙니다.');
	}
};

const withEmployeeInfo = async (employeeInfo, token) => {
	const empUser = await userModel.getUserByEmpnoAndCompanyCode(employeeInfo);
	if (empUser) return await userModel.getUserByEmail(empUser.email);

	const { data: newConnectUser } = await postConnectAccount(employeeInfo, token);

	return await userModel.getUserByEmail(newConnectUser.profile.email);
};

const withExternalApi = async req => {
	log.i(TAG, '-- externalApiAuth 외부 API 인증으로 진행', req.path);
	const token = isExternalApiRequest(req);
	const { email, empno, companyCode } = req.query;

	let user = null;
	if (empno && companyCode) user = await withEmployeeInfo({ empno, companyCode }, token);
	if (!user && email) user = await userModel.getUserByEmail(email.toLowerCase());
	if (!user && email?.startsWith('rec_system_') && email?.split('@')[1] === 'adotbiz.ai') {
		log.i(TAG, `채용 계정 생성 요청 -> ${email}`);
		const { data } = await axios.post(
			`${process.env.AUTH_API_URL}auth/interview/signup`,
			{ email, token },
			{
				headers: {
					Authorization: `Bearer ${token}`,
					'external-api-key': process.env.ENCRYPT_SECRET_KEY,
					'Content-Type': 'application/json',
				},
			}
		);
		log.i(TAG, `채용 계정 생성 응답 -> ${JSON.stringify(data)}`);
		if (data.httpCode !== 200) throw new HttpError(401, data.message);
		user = await userModel.getUserByEmail(email.toLowerCase());
	}
	if (!user) throw new HttpError(401, '전사 정보에 등록된 사용자가 아닙니다.');

	req.query.email = user.profile.email ?? email;
	log.i(TAG, '-- externalApiAuth 외부 API 인증 완료', JSON.stringify(user, null, 2));
	req.user = {
		...user.profile,
		config: {
			lang: user.config.locale,
			...user.config,
			external: {
				...req.query,
				token,
			},
		},
	};
	req.token = null;
	log.i(TAG, '-- externalApiAuth 외부 API 인증 완료');
};

export const authenticateRequest = async (req, res, next) => {
	try {
		if (isExternalApiRequest(req)) await withExternalApi(req);
		else await withTimbloToken(req);

		next();
	} catch (err) {
		log.e(TAG, '-- authentication error => ', err.message);
		next(err);
	}
};

export default authenticateRequest;
