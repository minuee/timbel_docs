import fs from 'fs';
import axios from 'axios';
import FormData from 'form-data';
import redis from '../../../redis/client.util.js';
import keywordModel from '../../../../models/keywordBoostring.model.js';

global.ACCESS_TOKENS = {};
const ONE_HOUR_IN_SEC = 3600;
const isKeywordsBoosting = process.env.IS_KEYWORDS_BOOSTING || 'false';
const postRequest = async (url, headers, data, params) => {
	log.d(`[POST : Haiv postRequest] params: ${JSON.stringify(params)}`);
	return await axios.request({
		method: 'POST',
		maxBodyLength: Infinity,
		url,
		headers,
		params,
		data,
	});
};

export const authenticate = async ({ url, tag, params: { auth } }) => {
	const TAG = `[POST : Haiv authenticate : ${tag}]`;

	const accessToken = await redis.get(`transcribeEngineTokens:${tag}`);

	if (!accessToken && accessToken === null) {
		const headers = {
			'Content-Type': 'application/x-www-form-urlencoded',
		};
		const keycloakUrl = `${url}/auth/realms/sorizava/protocol/openid-connect/token`;
		try {
			const { data } = await postRequest(keycloakUrl, headers, auth);

			if (data.access_token && data.expires_in) {
				ACCESS_TOKENS[tag] = data.access_token;
				redis.set(`transcribeEngineTokens:${tag}`, data.access_token, data.expires_in - ONE_HOUR_IN_SEC);
				const expires = Date.now() + (data.expires_in - ONE_HOUR_IN_SEC) * 1000;
				log.i(TAG, `${tag} Access token 갱신 완료. 만료 시간: ${new Date(expires).toISOString()}`);
				return true;
			}
			return false;
		} catch (err) {
			return false;
		}
	}
	ACCESS_TOKENS[tag] = accessToken;
	return true;
};

const getKeywordsBoosting = async ({ memberId, workspaceId }) => {
	const keywords = await keywordModel.findAllKeywordBoostings({ id: memberId, workspace: { id: workspaceId } });
	const { preprocess, postprocess } = keywords.keywords.reduce(
		(acc, keyword) => {
			const target = keyword.isPostProcess ? acc.postprocess : acc.preprocess;
			target.push({
				order: target.length + 1,
				keyword: keyword.keyword,
				...(keyword.isPostProcess && { weight: keyword.weight }),
			});
			return acc;
		},
		{ preprocess: [], postprocess: [] }
	);

	return {
		keywordsBoosting: { preprocess, postprocess },
	};
};

export const transcribe = async engineOptions => {
	const { filePath, language = 'ko', url, attendeeNum = 99, tag = 'HAIV', params: engineParams } = engineOptions;
	await authenticate(engineOptions);

	const formData = new FormData();
	formData.append('fileName', fs.createReadStream(filePath));
	if (isKeywordsBoosting === 'true') {
		formData.append('metadata', JSON.stringify(await getKeywordsBoosting(engineOptions)));
	}

	const headers = {
		'Authorization': `Bearer ${ACCESS_TOKENS[tag]}`,
		...formData.getHeaders(),
	};

	const params = {
		model: engineParams.model,
		'num-speaker': attendeeNum,
		lang: language,
		'keyword-boosting': isKeywordsBoosting,
	};

	const uploadUrl = `${url}/api/decoding/projects/${engineParams.projectId}/upload`;

	return await postRequest(uploadUrl, headers, formData, params);
};

export default {
	transcribe,
};
