import axios from 'axios';
import https from 'https';

let BASE_URL = null;
let DEFAULT_LANGUAGE = 'ko';
let HTTPS_AGENT = null;

process.on('configChanged', () => {
	BASE_URL = process.env.LLM_CHATBOT_URL || 'http://3.35.96.235:8081';
	DEFAULT_LANGUAGE = process.env.LLM_CHATBOT_DEFAULT_LANGUAGE || 'ko';

	// 자체 서명된 인증서 허용 (내부망 HTTPS)
	const rejectUnauthorized = process.env.LLM_CHATBOT_REJECT_UNAUTHORIZED !== 'false';
	HTTPS_AGENT = new https.Agent({
		rejectUnauthorized,
	});
});

/**
 * LLM Chatbot Client Service
 * 외부 LLM 챗봇 API와 통신하는 서비스
 */
class LLMClientService {
	constructor() {
		this.timeout = parseInt(process.env.LLM_CHATBOT_TIMEOUT || '120000', 10); // 기본 2분으로 증가
	}

	/**
	 * LLM 챗봇 API 호출
	 * @param {Object} params - API 호출 파라미터
	 * @param {string[]} params.mid - 회의록 UUID 목록 (최대 3개)
	 * @param {string} params.query - 사용자 질문
	 * @param {string} params.user - 사용자 이메일
	 * @param {string} params.conversationId - 대화 세션 ID (빈 값으로 시작)
	 * @param {string} params.language - LLM 답변 언어 (ko, en, cn)
	 * @param {string} params.responseMode - 응답 모드 (blocking, streaming)
	 * @returns {Promise<Object>} LLM 응답 데이터
	 */
	async chat({ mid, query, user, conversationId = '', language = DEFAULT_LANGUAGE, responseMode = 'blocking' }) {
		try {
			const requestUrl = `${BASE_URL}/llm/chat`;

			log.i('[LLMClientService : chat] Request:', {
				url: requestUrl,
				timeout: this.timeout,
				mid,
				query,
				user,
				conversationId,
				language,
				responseMode,
			});

			const requestData = {
				inputs: {
					mid,
					language,
				},
				query,
				response_mode: responseMode,
				user,
				conversation_id: conversationId,
			};

			log.i('[LLMClientService : chat] Request data:', JSON.stringify(requestData));

			const axiosConfig = {
				method: 'POST',
				maxBodyLength: Infinity,
				url: requestUrl,
				headers: {
					'Content-Type': 'application/json',
				},
				data: requestData,
				timeout: this.timeout,
			};

			// HTTPS인 경우 httpsAgent 추가 (자체 서명 인증서 허용)
			if (requestUrl.startsWith('https://') && HTTPS_AGENT) {
				axiosConfig.httpsAgent = HTTPS_AGENT;
			}

			const response = await axios.request(axiosConfig);

			log.i('[LLMClientService : chat] Response received');

			return this._transformResponse(response.data);
		} catch (err) {
			log.e('[LLMClientService : chat] Error:', err.message);
			log.e('[LLMClientService : chat] Error code:', err.code);
			log.e('[LLMClientService : chat] BASE_URL:', BASE_URL);
			if (err.response) {
				log.e('[LLMClientService : chat] Response status:', err.response.status);
				log.e('[LLMClientService : chat] Response data:', err.response.data);
			}
			throw err;
		}
	}

	/**
	 * 외부 API 응답을 내부 포맷으로 변환
	 * @param {Object} response - 외부 API 응답
	 * @returns {Object} 변환된 응답
	 */
	_transformResponse(response) {
		const { conversation_id: conversationId, result, metadata } = response;

		// answer_sections를 단일 content로 병합
		const mergedContent = result.answer_sections
			.map(section => {
				let content = section.content;
				if (section.section_title) {
					content = `### ${section.section_title}\n\n${content}`;
				}
				return content;
			})
			.join('\n\n');

		// citations를 내부 포맷으로 변환
		const citations = result.citations.map(citation => {
			const { ref_id, type, contentId, title, text, segmentId, speaker, index, topic } = citation;

			// 인용 유형에 따른 추가 정보 매핑
			const citationData = {
				label: `${ref_id}`,
				quote: title,
				linkContentId: contentId,
				type,
				text,
			};

			if (type === 'transcription' && segmentId) {
				citationData.segmentId = segmentId;
				citationData.speaker = speaker;
			}

			if (type === 'selection_summary' && typeof index === 'number') {
				citationData.index = index;
				citationData.topic = topic;
			}

			return citationData;
		});

		return {
			conversationId,
			content: mergedContent,
			citations,
			metadata,
		};
	}

	/**
	 * 스트리밍 모드 지원 (향대 확장용)
	 * @param {Object} params - API 호출 파라미터
	 * @returns {AsyncIterable} 스트리밍 응답
	 */
	async *chatStream(params) {
		// TODO: SSE/WebSocket을 통한 스트리밍 구현
		throw new Error('Streaming mode not yet implemented');
	}
}

export default new LLMClientService();
