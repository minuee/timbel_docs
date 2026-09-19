import BaseService from '../base.service.js';
import { HttpError } from '../../handlers/error.handler.js';
import llmClientService from './llm-client.service.js';

class ChatbotService extends BaseService {
	constructor() {
		super();
	}

	// 불필요한 응답 필드를 제거
	removeUnnecessaryFields(chatbot) {
		const { id, pid, isDeleted, ...chatbotWithoutUnnecessaryFields } = chatbot;
		return chatbotWithoutUnnecessaryFields;
	}

	/**
	 * LLM API를 호출하여 봇 응답 생성
	 * @param {string[]} attachedContents - 첨부된 회의록 contentId 목록
	 * @param {string} query - 사용자 질문
	 * @param {string} user - 사용자 이메일
	 * @param {string} conversationId - 대화 세션 ID
	 * @returns {Promise<Object>} LLM 응답 데이터
	 */
	async getLLMResponse(attachedContents = [], query, user, conversationId = '') {
		try {
			// 최대 3개의 회의록만 지원
			const mid = attachedContents.slice(0, 3);

			const llmResponse = await llmClientService.chat({
				mid,
				query,
				user,
				conversationId,
			});

			log.i('[ChatbotService : getLLMResponse] LLM response received:', {
				conversationId: llmResponse.conversationId,
				citationsCount: llmResponse.citations?.length || 0,
			});

			return llmResponse;
		} catch (err) {
			log.e('[ChatbotService : getLLMResponse] LLM API error:', err.message);
			throw new HttpError(5000, 'LLM API 호출 실패');
		}
	}

	/**
	 * LLM 응답을 메시지 형식으로 변환
	 * @param {Object} llmResponse - LLM API 응답
	 * @returns {Object} 메시지 데이터
	 */
	formatLLMResponseToMessage(llmResponse) {
		const { content, citations } = llmResponse;

		// [ref_id] 형식의 인용 태그를 [^ref_id] 형식으로 변환 (마크다운 호환)
		const formattedContent = content.replace(/\[(\d+)\]/g, '[^$1]');

		return {
			message: formattedContent,
			citations: citations || [],
		};
	}

	async getChatbotList(user) {
		log.i('[ChatbotService : getChatbotList] user : ', user);
		const { pid } = user;
		const list = await this.chatbotModel.getChatbots(pid);
		return {
			count: list.length,
			list,
		};
	}

	async getChatDetail(id, user) {
		const { pid } = user;

		const getChatbot = await this.chatbotModel.getChatbotByChatId(id, pid);
		if (!getChatbot) throw new HttpError(2001);

		const chatbot = await this.chatbotModel.getChatDetail(id, pid);
		if (!chatbot) throw new HttpError(1101);

		return this.removeUnnecessaryFields(chatbot);
	}

	async createChatbot(user, createChatbotDTO) {
		const { pid, email } = user;
		const { attachedContents, query } = createChatbotDTO;

		// 1. LLM API 호출
		const llmResponse = await this.getLLMResponse(attachedContents, query, email, '');

		// 2. 챗봇 생성 (conversation_id 저장)
		const { id, ...chatbot } = await this.chatbotModel.createChatbot(pid, {
			attachedContents,
			query,
			conversationId: llmResponse.conversationId,
		});

		const chatbotWithoutUnnecessaryFields = this.removeUnnecessaryFields(chatbot);

		// 3. LLM 응답을 메시지로 저장
		const { message, citations } = this.formatLLMResponseToMessage(llmResponse);
		const botMessage = await this.chatbotModel.addMessage(id, 1, message, citations, true);

		const result = {
			...chatbotWithoutUnnecessaryFields,
			response: botMessage,
		};

		return result;
	}

	async sendQuery(id, query, pid) {
		const getChatbot = await this.chatbotModel.getChatbotByChatId(id, pid);
		if (!getChatbot) throw new HttpError(2001);

		const { attachedContents, messages, conversationId, ...chatbot } = getChatbot;

		const targetMessageIdx = messages[0].idx + 1;

		log.i('[ChatbotService : sendQuery] getChatbot : ', JSON.stringify(getChatbot));

		// 사용자 메시지 저장
		await this.chatbotModel.addMessage(getChatbot.id, targetMessageIdx, query, [], false);

		// 사용자 이메일 조회 (member 테이블에서)
		const member = await this.memberModel.getMemberByPid(pid);
		const userEmail = member?.user?.profile?.email || '';

		// LLM API 호출 (이전 conversation_id 사용)
		const contentIds = attachedContents.map(({ contentId }) => contentId);
		const llmResponse = await this.getLLMResponse(contentIds, query, userEmail, conversationId || '');

		// conversation_id 업데이트
		await this.chatbotModel.updateConversationId(getChatbot.id, llmResponse.conversationId);

		// LLM 응답을 메시지로 저장
		const { message, citations } = this.formatLLMResponseToMessage(llmResponse);
		const botMessage = await this.chatbotModel.addMessage(
			getChatbot.id,
			targetMessageIdx + 1,
			message,
			citations,
			true
		);

		const chatbotWithoutUnnecessaryFields = this.removeUnnecessaryFields(chatbot);

		const result = {
			...chatbotWithoutUnnecessaryFields,
			response: botMessage,
		};

		return result;
	}

	async deleteChatbot(id, pid) {
		const getChatbot = await this.chatbotModel.getChatbotByChatId(id, pid);
		if (!getChatbot) throw new HttpError(2001);

		await this.chatbotModel.deleteChatbot(getChatbot.id);

		return;
	}
}

export default new ChatbotService();
