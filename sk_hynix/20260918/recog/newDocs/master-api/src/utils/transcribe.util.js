import notify from './notify.util.js';
import haivEngine from './engines/Haiv/haiv.js';
import contentModel from '../models/content.model.js';
import { QueueError } from '../handlers/error.handler.js';
import transcribeResultModel from '../models/transcribeResult.model.js';
import contentHistoryModel from '../models/contentHistory.model.js';

const TAG = '[TranscribeUtil] ';

class TranscribeUtil {
	constructor(params, { member, config }, isLLM = false) {
		this.params = params;
		const { fileId, ticketId, contentId } = params;

		if (!fileId || !ticketId || !contentId) throw QueueError(1000);

		this.fileId = fileId;
		this.member = member;
		this.ticketId = ticketId;
		this.contentId = contentId;
		this.external = config.external ?? null;
		this.lang = config.transcribeLang || transcribeResultModel.Enums.SupportLang.ko;
		this.isMobile = config.isMobile ?? false;

		if (!isLLM) {
			const maxDuration = Number(process.env.MAX_DURATION) || 3 * 60 * 60 * 1000;
			const MAX_LIMIT_DURATION = maxDuration + 1000;

			if (params.duration > MAX_LIMIT_DURATION) {
				const error = new Error(`음성파일 길이가 최대 길이 ${maxDuration / 60000}분을 초과합니다.`);
				this.transUpdater({ status: 'ERROR' }, error);
				throw error;
			}

			this.transUpdater({ status: 'RUNNING' });
			const { transcribeEngine, id: workspaceId } = member.workspace.config;
			this.transOptions = {
				language: config.transcribeLang || transcribeResultModel.Enums.SupportLang.ko,
				attendeeNum: params.attendeeNum,
				memberId: member.id,
				workspaceId,
				contentId: this.contentId,
				ticketId: this.ticketId,
				...transcribeEngine,
			};
		}
	}

	async runner(filePath) {
		this.transOptions['filePath'] = filePath;

		switch (this.transOptions.provider) {
			case 'HAIV':
				return await haivEngine(this.transOptions, data => {
					this.statusUpdater(data);
				});

			default:
				throw QueueError(1107);
		}
	}

	async notify(status) {
		return await this.statusUpdater({ status });
	}

	async sendEmail(user, isCreate = true, isMerge = false) {
		const workspaceId = this.member?.workspace?.id;
		return await notify.contentDoneEmail(this.contentId, isCreate, user, this.isMobile, isMerge, workspaceId);
	}

	async createContentHistory(contentId, { status }) {
		try {
			if (!['DONE', 'ERROR'].includes(status)) return;

			const content = await contentModel.findContentHistoryByContentId(contentId);
			const contentHistory = {
				workspaceId: content.creator.workspaceId,
				contentId,
				contentType: content.type,
				contentTitle: content.title,
				meetingStartTime: content.meetingStartTime,
				meetingEndTime: content.meetingEndTime,
				duration: content.duration,
				transcribeStatus: status,
				userName: content.creator.user.profile.nickName,
				email: content.creator.user.profile.email,
			};
			await contentHistoryModel.createContentHistory(contentHistory);
		} catch (err) {
			log.e(TAG, `Error: ${err.message}`);
			throw err;
		}
	}

	async statusUpdater(data, err = null) {
		const { status } = data;
		if (!status) return;
		if (['DONE', 'ERROR'].includes(status) && this.external)
			await notify.externalEvent({ status, external: this.external, err }, this.params);
		return notify.sttStatus(data, this.params, this.member);
	}

	async transUpdater(targetData, err = null) {
		try {
			const where = { fileId: this.fileId, ticket: this.ticketId };

			delete targetData.speakerMap;

			await transcribeResultModel.updateStatus(where, targetData);
			await contentModel.updateTranscribeStatus(this.contentId, targetData.status);
			await this.createContentHistory(this.contentId, targetData);
			await this.statusUpdater(targetData, err);
			log.d(TAG, `Update ${JSON.stringify(Object.keys(targetData))} success: ${this.ticketId}`);
		} catch (err) {
			log.e(TAG, `Error: ${err.message}`);
		}
	}

	async contentUpdater({ keywords = [] }, title = '') {
		try {
			const targetData = {
				hashTag: keywords,
				title: title,
				transcribeStatus: 'DONE',
			};
			const where = { contentId: this.contentId };
			await contentModel.updateContent(where, targetData);
			log.i(TAG, `Update ${JSON.stringify(Object.keys(targetData))} success: ${this.ticketId}`);
		} catch (err) {
			log.e(TAG, `Error: ${err.message}`);
		}
	}
}

export default TranscribeUtil;
