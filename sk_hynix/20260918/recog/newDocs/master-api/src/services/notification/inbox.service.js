import inboxModel from '../../models/inbox.model.js';
import { HttpError } from '../../handlers/error.handler.js';

class InboxService {
	constructor() {
		this.inboxModel = inboxModel;
	}

	async getInboxByMemberId(memberId, options) {
		try {
			return await this.inboxModel.getInboxContentByMemberId(memberId, options);
		} catch (err) {
			throw err;
		}
	}

	async updateisReadInbox(inboxId, memberId) {
		try {
			return await this.inboxModel.updateisReadInbox(inboxId, memberId);
		} catch (err) {
			if (err.code === 'P2025') {
				throw new HttpError(1701);
			}
			throw err;
		}
	}

	async updateisReadInboxByMemberId(memberId) {
		try {
			return await this.inboxModel.updateisReadInboxByMemberId(memberId);
		} catch (err) {
			throw err;
		}
	}
	async deleteInbox(inboxId, memberId) {
		try {
			return await this.inboxModel.deleteInbox(inboxId, memberId);
		} catch (err) {
			if (err.code === 'P2025') {
				throw new HttpError(1701);
			}
			throw err;
		}
	}
	async deleteInboxMemberId(memberId) {
		try {
			return await this.inboxModel.deleteInboxMemberId(memberId);
		} catch (err) {
			throw err;
		}
	}
}

export default new InboxService();
