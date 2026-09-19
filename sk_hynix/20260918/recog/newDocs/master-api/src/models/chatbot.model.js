import BaseDatabase from '@timbel-timblo-onpremise/prisma';

const defaultMessageSelect = {
	idx: true,
	isBot: true,
	message: true,
	createAt: true,
	citations: {
		select: {
			label: true,
			quote: true,
			linkContentId: true,
			type: true,
			text: true,
			segmentId: true,
			speaker: true,
			index: true,
			topic: true,
		},
	},
};

const defaultChatDetailSelect = {
	id: true,
	chatId: true,
	createAt: true,
	updateAt: true,
	conversationId: true,
	attachedContents: {
		select: {
			contentId: true,
			type: true,
			title: true,
			editedTitle: true,
			isRecord: true,
			fileName: true,
			shareUsers: {
				select: {
					email: true,
					role: true,
				},
			},
		},
	},
};

const defaultAttachedContentsSelect = {
	select: {
		contentId: true,
		type: true,
		title: true,
		editedTitle: true,
		isRecord: true,
		fileName: true,
		shareUsers: {
			select: {
				email: true,
				role: true,
			},
		},
	},
};
class ChatbotModel extends BaseDatabase {
	constructor() {
		super('ChatbotModel');
	}

	async getChatbots(pid) {
		return await this.mariaDB.chatbot.findMany({
			where: {
				pid,
				isDeleted: false,
			},
			select: {
				chatId: true,
				title: true,
				createAt: true,
				updateAt: true,
			},
			orderBy: {
				createAt: 'desc',
			},
		});
	}

	async getChatDetail(chatId, pid) {
		return await this.mariaDB.chatbot.findUnique({
			where: { chatId_pid: { chatId, pid } },
			select: {
				...defaultChatDetailSelect,
				messages: { select: defaultMessageSelect },
			},
		});
	}

	async createChatbot(pid, createChatbotDTO) {
		const { attachedContents, query, conversationId } = createChatbotDTO;
		const attachedContentsData = attachedContents.map(content => ({ contentId: content }));
		log.i('[ChatbotModel : createChatbot] attachedContentsData : ', JSON.stringify(attachedContentsData));
		return await this.mariaDB.chatbot.create({
			data: {
				pid,
				title: process.env.DEFAULT_CHATBOT_TITLE || '새로운 챗봇',
				conversationId,
				attachedContents: { connect: attachedContentsData },
				messages: { create: { idx: 0, message: query } },
			},
		});
	}

	async addMessage(chatbotId, idx, message, citations = [], isBot = false) {
		return await this.mariaDB.chatMessage.create({
			data: {
				chatbot: { connect: { id: chatbotId } },
				message,
				isBot,
				idx,
				citations: { createMany: { data: citations } },
			},
			select: defaultMessageSelect,
		});
	}

	async addCitations(chatbotId, idx, citations) {
		return await this.mariaDB.chatCitation.createMany({
			data: citations.map(citation => ({
				chatId: chatbotId,
				messageIdx: idx,
				...citation,
			})),
		});
	}

	async getChatbotByChatId(chatId, pid) {
		return await this.mariaDB.chatbot.findUnique({
			where: { chatId_pid: { chatId, pid } },
			select: {
				...defaultChatDetailSelect,
				attachedContents: defaultAttachedContentsSelect,
				messages: {
					select: { idx: true },
					orderBy: { idx: 'desc' },
					take: 1,
				},
			},
		});
	}

	async deleteChatbot(id) {
		return await this.mariaDB.chatbot.update({
			where: { id },
			data: { isDeleted: true },
		});
	}

	async updateConversationId(id, conversationId) {
		return await this.mariaDB.chatbot.update({
			where: { id },
			data: { conversationId },
		});
	}
}
export default new ChatbotModel();
