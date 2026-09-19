import base from '../base.controller.js';
import { HttpError } from '../../handlers/error.handler.js';
import chatbotService from '../../services/engine/chatbot.service.js';

class ChatbotController {
	async getChatbotList(req, res, next) {
		try {
			const { user } = req;
			const data = await chatbotService.getChatbotList(user);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async getChatDetail(req, res, next) {
		try {
			const { user, params } = req;
			const { id } = params;
			if (!id) throw new HttpError(1000);

			const data = await chatbotService.getChatDetail(id, user);
			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async createChatbot(req, res, next) {
		try {
			const { user } = req;
			const { attachedContents = [], query = '' } = req.body;
			if (attachedContents.length === 0) throw new HttpError(1000);

			const createChatbotDTO = { attachedContents, query };
			const data = await chatbotService.createChatbot(user, createChatbotDTO);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async sendQuery(req, res, next) {
		try {
			const { params, body, user } = req;
			const { id } = params;
			const { query } = body;
			if (query.trim() === '') throw new HttpError(1000);

			const data = await chatbotService.sendQuery(id, query, user.pid);
			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async deleteChatbot(req, res, next) {
		try {
			const { params, user } = req;
			const { id } = params;
			await chatbotService.deleteChatbot(id, user.pid);
			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}
}

export default new ChatbotController();

