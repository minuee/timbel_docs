import attendeeModel from '../../models/attendee.model.js';
import contentModel from '../../models/content.model.js';
import contentCaptureModel from '../../models/contentCapture.model.js';
import transcribeResultModel from '../../models/transcribeResult.model.js';

class ContentCaptureService {
	constructor() {
		this.contentModel = contentModel;
		this.contentCaptureModel = contentCaptureModel;
		this.attendeeModel = attendeeModel;
		this.transcribeResultModel = transcribeResultModel;
	}

	async createContentCapture(
		captureType,
		captureAction,
		contentId,
		memberId,
		{ nickName },
		attendeeCount = 0,
		shareEmail = null
	) {
		try {
			const content = await this.contentModel.findContentById(contentId);
			if (content.editedTitle !== null) {
				content.title = content.editedTitle;
			}

			if (attendeeCount === 0) {
				const file = await this.transcribeResultModel.findSpeakerInfoByContentId(contentId);
				attendeeCount = file?.transcribeResult?.speakerInfo?.length || 0;
			}

			const contentCapture = {
				captureType,
				captureAction,
				content,
				attendeeCount,
				creatorId: memberId,
				creatorNickName: nickName,
				shareEmail,
				serverId: process.env.NOTIFY_SERVER_ID || '',
			};
			await this.contentCaptureModel.createContentCapture(contentCapture);
		} catch (err) {
			log.e('[createContentCapture] error :', err.message);
			throw err;
		}
	}

	async createManyContentCapture(captureType, captureAction, contentIds, memberId, { nickName }, shareEmail = null) {
		try {
			const contents = await this.contentModel.getContentsIncludeDeleteByIds(contentIds);
			const files = await this.transcribeResultModel.findSpeakerInfosByContentIds(contentIds);

			const contentCaptures = contents.map(content => {
				const file = files.find(file => file.contentId === content.contentId);
				return {
					captureType,
					captureAction,
					contentId: content.contentId,
					contentType: content.type,
					title: content.editedTitle || content.title,
					duration: content.duration,
					meetingStartTime: content.meetingStartTime,
					attendeeCount: file?.transcribeResult?.speakerInfo?.length || 0,
					creatorId: memberId,
					creatorNickName: nickName,
					shareEmail,
					serverId: process.env.NOTIFY_SERVER_ID || '',
				};
			});
			await this.contentCaptureModel.createManyContentCapture(contentCaptures);
		} catch (err) {
			log.e('[ContentCaptureService : createManyContentCapture] error :', err.message);
			throw err;
		}
	}
}

export default new ContentCaptureService();
