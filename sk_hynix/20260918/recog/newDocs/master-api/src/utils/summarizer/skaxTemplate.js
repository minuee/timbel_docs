import https from 'https';
import axios from 'axios';
import { md } from '../convert/markdown.util.js';
import templateModel from '../../models/template.model.js';
import { QueueError } from '../../handlers/error.handler.js';

const TAG = '[summarizer/skax-template]';
const llm = async (tag, requestData) => {
	const requestHeaders = {
		'accept': 'application/json',
		'Content-Type': 'application/json',
	};

	const { uid, mid } = requestData.input;
	const apiUrl = process.env.SKAX_TEMPLATE_API_URL || 'https://3.35.96.235:29002/api/template_minutes';

	log.i(TAG, `[${tag}] API URL : ${apiUrl}`);
	log.i(TAG, `[${tag}] requestHeaders : ${JSON.stringify(requestHeaders)}`);
	log.i(TAG, `[${tag}] requestData : ${JSON.stringify(requestData)}`);
	log.i(TAG, `[${tag}] uid: ${uid}, mid: ${mid}`);

	try {
		const { data, status, statusText, headers } = await axios.post(apiUrl, requestData, {
			headers: requestHeaders,
			timeout: 1800000,
			httpsAgent: new https.Agent({
				rejectUnauthorized: false,
			}),
		});

		log.i(TAG, `[${tag}] response status : ${status} ${statusText}`);
		log.i(TAG, `[${tag}] response headers : ${JSON.stringify(headers)}`);
		log.i(TAG, `[${tag}] response data : ${JSON.stringify(data)}`);

		// 응답에서 final_minutes 추출 (langserve: { output: { final_minutes, additional_components: { keywords, short_summary } } })
		const finalMinutes = data.output?.final_minutes || data;
		const { keywords, short_summary, title } = data.output?.additional_components || data.output || data;

		return {
			finalMinutes,
			keywords: keywords || [],
			summary: short_summary? [short_summary] : [],
			// title이 문자열이고 공백 제외 내용이 있을 때만 사용, 아니면 빈값(→ short_summary 폴백)
			title: (typeof title === 'string' && title.trim()) ? title.trim() : '',
			token: 0,
		};
	} catch (axiosError) {
		log.e(TAG, `[${tag}] AxiosError occurred`);
		log.e(TAG, `[${tag}] Error message: ${axiosError.message}`);
		log.e(TAG, `[${tag}] Error code: ${axiosError.code}`);

		if (axiosError.response) {
			// 서버가 응답했지만 4xx, 5xx 상태 코드
			log.e(TAG, `[${tag}] Response status: ${axiosError.response.status}`);
			log.e(TAG, `[${tag}] Response statusText: ${axiosError.response.statusText}`);
			log.e(TAG, `[${tag}] Response headers: ${JSON.stringify(axiosError.response.headers)}`);
			log.e(TAG, `[${tag}] Response data: ${JSON.stringify(axiosError.response.data)}`);

			// 500 에러이고 "Internal Server Error" 응답인 경우 특별 처리
			if (axiosError.response.status === 500 && axiosError.response.data === 'Internal Server Error') {
				const contentErrorMessage = `SKAX API에서 해당 컨텐츠를 처리할 수 없습니다. 컨텐츠가 전사 완료 상태인지 확인하거나 잠시 후 다시 시도해주세요.`;
				log.e(TAG, `[${tag}] Content processing error: ${contentErrorMessage}`);
				throw new Error(contentErrorMessage);
			}
		} else if (axiosError.request) {
			// 요청이 보내졌지만 응답을 받지 못함
			log.e(TAG, `[${tag}] No response received`);
			log.e(TAG, `[${tag}] Request: ${JSON.stringify(axiosError.request)}`);
		} else {
			// 요청 설정 중 에러 발생
			log.e(TAG, `[${tag}] Error in request setup: ${axiosError.message}`);
		}

		// 원래 에러를 다시 throw
		throw axiosError;
	}
};

class skaxTemplate {
	constructor({ summarySize, ticketId, lang, user, contentId, templateId, contentIds, isMerge}) {
		this.lang = lang;
		this.ticketId = ticketId;
		this.summarySize = summarySize;
		this.user = user;
		this.contentId = contentId;
		this.templateId = templateId;
		this.contentIds = contentIds;
		this.isMerge = isMerge;
	}

	async getAdditionalComponents(options) {
		// 새 langserve 스키마 허용값(keywords, short_summary)로만 정규화 (speaker 등 미지원값은 제외)
		const COMPONENT_MAP = { keyword: 'keywords', keywords: 'keywords', summary: 'short_summary', short_summary: 'short_summary' };
		const additionalComponents = Object.keys(options || {})
			.filter(option => options[option] === true)
			.map(option => COMPONENT_MAP[option])
			.filter(Boolean);
		// 회의록 제목용 title은 템플릿 옵션과 무관하게 항상 요청(응답에 없거나 빈값이면 short_summary로 폴백)
		if (!additionalComponents.includes('title')) additionalComponents.push('title');
		log.i(TAG, `[${this.ticketId}] additionalComponents : ${JSON.stringify(additionalComponents)}`);
		return additionalComponents;
	}

	async callSkaxWithRetry(uid, mid, template, maxRetries = 3, retryDelay = 2000) {
		let lastError;

		const { key,  options = { speaker: false, keyword: false, summary: false } } = template;
		for (let attempt = 1; attempt <= maxRetries; attempt++) {
			try {
				log.i(TAG, `[${this.ticketId}] SKAX API 호출 시도 ${attempt}/${maxRetries}`);

				const requestData = {
					input: {
						input_type: this.isMerge ? 'timbel_minutes' : 'timbel_stt',
						mid,
						uid,
						tid: key,
						size: this.summarySize,
						output_lang: this.lang,
						additional_components: await this.getAdditionalComponents(options),
					},
				};
				const result = await llm(
					`skax summary ${this.ticketId} - attempt ${attempt}`,
					requestData,
					this.companyHeader
				);

				log.i(TAG, `[${this.ticketId}] SKAX API 호출 성공 (시도 ${attempt})`);
				return result;
			} catch (error) {
				lastError = error;
				log.w(TAG, `[${this.ticketId}] SKAX API 호출 실패 (시도 ${attempt}/${maxRetries}): ${error.message}`);

				if (error.response?.status === 500 && attempt < maxRetries) {
					log.i(TAG, `[${this.ticketId}] ${retryDelay}ms 대기 후 재시도...`);
					await this.sleep(retryDelay);
					retryDelay *= 1.5;
				} else {
					break;
				}
			}
		}

		log.e(TAG, `[${this.ticketId}] SKAX API 호출 최종 실패 (${maxRetries}회 시도)`);
		throw lastError;
	}

	sleep(ms) {
		return new Promise(resolve => setTimeout(resolve, ms));
	}

	async runner() {
		try {
			const uid = this.user?.email;
			const mids = this.isMerge ? this.contentIds : [this.contentId];

			log.i(TAG, `[${this.ticketId}] templateId : ${this.templateId}`);
			const template = await templateModel.getTemplateByTemplateId(this.templateId);
			log.i(TAG, `[${this.ticketId}] template : ${JSON.stringify(template)}`);
			if (!template) throw QueueError(2201);

			if (!uid || !mids) {
				throw new Error('필수 파라미터가 누락되었습니다: uid:email, mid:contentId');
			}

			log.i(TAG, `[${this.ticketId}] SKAX API 요약 시작 - uid: ${uid}, mid: ${mids}`);

			const { finalMinutes, keywords, summary, title } = await this.callSkaxWithRetry(uid, mids, template, 3, 2000);

			log.i(TAG, `[${this.ticketId}] summary : ${JSON.stringify(summary)}`);
			const aiResult = {
				summary,
				keywords,
				templateSummary: finalMinutes,
				issues: [
					'해당 회의록에 생성된 데이터는 현재 테스트 데이터로 실제 전송예정인 정보를 표시 합니다.',
					`uid : ${this.user?.email}`,
					`mids : ${mids}`,
					`template 정보 -> key : ${template.key}, inputType : ${template.inputType}`,
					`summarySize : ${this.summarySize}`,
					`lang : ${this.lang}`,
					`additionalComponents : ${await this.getAdditionalComponents(template.options)}`,
					'노트 탭에 작성된 데이터는 LLM 의 응답 final_minutes 결과 MD 형식으로 사용되었습니다.',
				],
			};

			// 제목: additional_components.title 우선, 없거나 빈값이면 기존처럼 short_summary(summary[0])로 폴백
			const finalTitle = title || summary[0] || '요약의 주제가 없습니다.';
			log.i(TAG, `[${this.ticketId}] title : ${finalTitle} (source: ${title ? 'title' : 'short_summary'})`);
			log.i(TAG, `[${this.ticketId}] SKAX API 요약 완료`);
			return { note: md.render(finalMinutes), title: finalTitle, aiResult };
		} catch (err) {
			console.log(TAG, `[${this.ticketId}] error : `, err);
			return { note: err.message, title: '재요약이 필요한 콘텐츠', aiResult: {}, summaryTime: [], totalToken: 0 };
		}
	}
}

export default skaxTemplate;
