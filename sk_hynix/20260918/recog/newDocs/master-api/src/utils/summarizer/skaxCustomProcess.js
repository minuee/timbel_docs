import axios from 'axios';
import convert from '../convert/index.js';
import i18n from '../../configs/i18n-config.js';

const TAG = '[summarizer/skax-custom]';
export const MAX_TOKEN = 2000;
export const MAX_TOKEN_LENGTH = 16000;

// SKAX API에서는 토큰 계산이 불필요하므로 사용하지 않음
export const calcTokenSize = cont => {
	return 0;
};

export const getCompanyHeader = (company, ticketId) => {
	if (!company) return {};
	const { empno, companyCode, deptCode } = company;
	return {
		'aip-company': companyCode,
		'aip-department': deptCode,
		'aip-user': empno,
		'aip-app-id': 'gbaa-agent-mm-summary',
		'aip-transaction-id': ticketId,
	};
};

export const llm = async (tag, uid, mid, companyHeader = {}) => {
	const requestData = { input: { uid: uid, mid: mid } };
	const requestHeaders = {
		'accept': 'application/json',
		'aip-user': 'aiplatform3/agenttest',
		'Authorization': 'EMPTY',
		'Content-Type': 'application/json',
		...companyHeader,
	};

	const apiUrl = process.env.SKAX_API_URL || 'http://localhost:28080/summary/invoke';

	log.i(TAG, `[${tag}] API URL : ${apiUrl}`);
	log.i(TAG, `[${tag}] requestHeaders : ${JSON.stringify(requestHeaders)}`);
	log.i(TAG, `[${tag}] requestData : ${JSON.stringify(requestData)}`);
	log.i(TAG, `[${tag}] uid: ${uid}, mid: ${mid}`);

	try {
		const { data, status, statusText, headers } = await axios.post(apiUrl, requestData, {
			headers: requestHeaders,
			timeout: 1800000, // 30분
		});

		log.i(TAG, `[${tag}] response status : ${status} ${statusText}`);
		log.i(TAG, `[${tag}] response headers : ${JSON.stringify(headers)}`);
		log.i(TAG, `[${tag}] response data : ${JSON.stringify(data)}`);

		// 응답에서 final_minutes 추출
		const finalMinutes = data.output?.final_minutes || data;

		return {
			response: finalMinutes,
			token: 0, // SKAX API에서는 토큰 정보가 제공되지 않으므로 0으로 설정
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

// SKAX API에서는 프롬프트 분할이 불필요
export const userPromptSplitter = (systemPrompt, transcriptList, n = 0) => {
	return [transcriptList];
};

class skaxCustomProcess {
	constructor({ segmentInfo, summarySize, ticketId, lang, company, user, contentId }) {
		this.lang = lang;
		this.ticketId = ticketId;
		this.summaryRange = this.getSummaryRange(summarySize);
		this.companyHeader = getCompanyHeader(company, ticketId);
		this.compressedSegments = this.createCompressedSegments(segmentInfo);
		this.user = user;
		this.contentId = contentId;
	}

	// SKAX API에서는 이러한 개별 프로세스들이 불필요합니다

	space(tab = 1) {
		const defaultSpace = 3;
		return ' '.repeat(defaultSpace * tab);
	}

	displayFormat(summaryResult, masteringResult, topicsResult) {
		const tasks = [];
		const issues = [];
		const topics = [];
		const topicsData = [];
		const summaryTime = [];
		const visualText = [];

		// 기본 언어를 한국어로 설정하고, 지원되는 언어인 경우 해당 언어 사용
		const t = i18n[this.lang ?? 'ko'];

		visualText.push(`${t.title} :<br/>${masteringResult.title}<br/>`);
		visualText.push(`<br/>${t.keywords} :<br/>${masteringResult.keywords.join(', ')}<br/>`);
		visualText.push(`<br/>${t.summary} :<br/>${masteringResult.summary}<br/>`);
		visualText.push(`<br/>${t.topics} :<br/>`);

		topicsResult.forEach((topic, idx) => {
			topics.push(topic.TOPIC);
			topicsData.push({
				index: idx + 1,
				text: topic.TOPIC,
				start: topic.START_TIME,
				end: topic.END_TIME,
			});
			visualText.push(
				`${this.space()}${idx + 1}.${this.space()}${topic.TOPIC} [${topic.START_TIME} ~ ${topic.END_TIME}]<br/>`
			);
		});

		visualText.push(`<br/><br/>${t.topicsDetailSummary} :<br/>`);
		summaryResult.topics.forEach((topic, idx) => {
			const topicData = topicsData[idx];
			const timeRangeData = `${topicData.start} ~ ${topicData.end}`;
			const object = {
				index: idx + 1,
				topic: topic.title,
				time: timeRangeData,
				summary: [],
				issues: [],
				tasks: [],
			};
			visualText.push(`${this.space()}${idx + 1}. ${topic.title} <br/>`);

			// 세부 사항
			topic.details.forEach(detail => {
				object.summary.push(detail);
				visualText.push(`${this.space(2)}${detail.content}${this.space(1)}<br/>`);
			});

			// 이슈
			if (topic.issues && topic.issues.length > 0) {
				topic.issues.forEach(issue => {
					issues.push(issue.content);
					object.issues.push(issue);
					visualText.push(
						`${this.space(2)}[${t.issue}]${this.space(1)}${issue.content}${this.space(1)}<br/>`
					);
				});
			}

			// 할 일
			if (topic.actionItems && topic.actionItems.length > 0) {
				topic.actionItems.forEach(({ content, assignee, dueDate, timestamp }) => {
					const task = `${content}`;
					tasks.push(task);
					object.tasks.push({
						content: task,
						timestamp,
					});
					visualText.push(
						`${this.space(2)}[${t.task}]${this.space(1)}${content}${this.space(1)}( ${t.assignee}: ${assignee || '-'}${this.space(1)}${t.dueDate}: ${dueDate || '-'} )<br/>`
					);
				});
			}
			visualText.push(`<br/>`);
			summaryTime.push(object);
		});

		return { note: visualText.join(''), issues, tasks, topics, summaryTime };
	}

	getSummaryRange(summarySize) {
		let max = 4; // default 4

		if (summarySize === 'large') max = 8;
		else if (summarySize === 'small') max = 2;
		return { min: 1, max };
	}

	createCompressedSegments(segmentInfo) {
		const { speakerMap, mergedSegments } = segmentInfo;
		return mergedSegments.map(({ text, speakerId, startTime }) => {
			const { name, displayName = null } = speakerMap[speakerId];
			return {
				content: text,
				speaker: displayName ?? name,
				time: convert.timeFormat(startTime),
			};
		});
	}

	extractUserAndContentId() {
		return { user: this.user, contentId: this.contentId };
	}

	// 재시도 로직이 포함된 SKAX API 호출
	async callSkaxWithRetry(uid, mid, maxRetries = 3, retryDelay = 2000) {
		let lastError;

		for (let attempt = 1; attempt <= maxRetries; attempt++) {
			try {
				log.i(TAG, `[${this.ticketId}] SKAX API 호출 시도 ${attempt}/${maxRetries}`);

				const result = await llm(
					`skax summary ${this.ticketId} - attempt ${attempt}`,
					uid,
					mid,
					this.companyHeader
				);

				log.i(TAG, `[${this.ticketId}] SKAX API 호출 성공 (시도 ${attempt})`);
				return result;
			} catch (error) {
				lastError = error;
				log.w(TAG, `[${this.ticketId}] SKAX API 호출 실패 (시도 ${attempt}/${maxRetries}): ${error.message}`);

				// 500 에러이고 재시도가 남아있으면 대기 후 재시도
				if (error.response?.status === 500 && attempt < maxRetries) {
					log.i(TAG, `[${this.ticketId}] ${retryDelay}ms 대기 후 재시도...`);
					await this.sleep(retryDelay);
					retryDelay *= 1.5; // 백오프: 다음 재시도는 더 긴 대기
				} else {
					// 재시도 불가능한 에러이거나 최대 재시도 횟수 도달
					break;
				}
			}
		}

		log.e(TAG, `[${this.ticketId}] SKAX API 호출 최종 실패 (${maxRetries}회 시도)`);
		throw lastError;
	}

	// 유틸리티: 비동기 대기
	sleep(ms) {
		return new Promise(resolve => setTimeout(resolve, ms));
	}

	convertSkaxResponse(skaxTopics) {
		// SKAX topics 배열을 기존 형식으로 변환
		const topicsResult = skaxTopics.map(topic => ({
			TOPIC: topic.topic,
			START_TIME: topic.start_timestamp,
			END_TIME: topic.end_timestamp,
		}));

		// summaryResult 생성 (기존 displayFormat에서 사용하는 형식)
		const summaryResult = {
			topics: skaxTopics.map(topic => ({
				title: topic.topic,
				details: topic.detail?.map(d => ({ content: d.text, timestamp: d.timestamp })) || [],
				issues: topic.issue?.map(i => ({ content: i.text || i, timestamp: i.timestamp })) || [],
				actionItems:
					topic.todo?.map(t => ({
						content: t.text || t,
						timestamp: t.timestamp,
						assignee: t.assignee,
						dueDate: t.dueDate,
					})) || [],
			})),
		};

		return { topicsResult, summaryResult };
	}

	async runner() {
		try {
			// SKAX API 호출을 위한 파라미터 추출
			const { user, contentId } = this.extractUserAndContentId();
			const uid = user?.email;
			const mid = contentId;

			if (!uid || !mid) {
				throw new Error('필수 파라미터가 누락되었습니다: uid:email, mid:contentId');
			}

			log.i(TAG, `[${this.ticketId}] SKAX API 요약 시작 - uid: ${uid}, mid: ${mid}`);

			// SKAX API 호출 (재시도 로직 포함)
			const { response: skaxResult, token: totalToken } = await this.callSkaxWithRetry(
				uid,
				mid,
				3, // 최대 3회 재시도
				2000 // 2초 간격
			);

			const { title, summary, keywords, topics: skaxTopics } = skaxResult;

			// SKAX 응답을 기존 형식으로 변환
			const { topicsResult, summaryResult } = this.convertSkaxResponse(skaxTopics);
			const masteringResult = { title, summary, keywords };

			// displayFormat으로 note와 summaryTime 생성
			const { note, issues, tasks, topics, summaryTime } = this.displayFormat(
				summaryResult,
				masteringResult,
				topicsResult
			);

			const aiResult = { tasks, issues, topics, summary: [summary], keywords };

			log.i(TAG, `[${this.ticketId}] SKAX API 요약 완료`);
			return { note, title, aiResult, summaryTime, totalToken };
		} catch (err) {
			console.log(TAG, `[${this.ticketId}] error : `, err);
			return { note: err.message, title: '재요약이 필요한 콘텐츠', aiResult: {}, summaryTime: [], totalToken: 0 };
		}
	}
}

export default skaxCustomProcess;
