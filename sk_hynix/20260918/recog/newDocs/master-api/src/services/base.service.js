import userModel from '../models/user.model.js';
import noteModel from '../models/note.model.js';
import shareModel from '../models/share.model.js';
import searchModel from '../models/search.model.js';
import memberModel from '../models/member.model.js';
import corpusModel from '../models/corpus.model.js';
import contactModel from '../models/contact.model.js';
import chatbotModel from '../models/chatbot.model.js';
import contentModel from '../models/content.model.js';
import bookmarkModel from '../models/bookmark.model.js';
import calendarModel from '../models/calendar.model.js';
import highlightModel from '../models/highlight.model.js';
import contentCaptureModel from '../models/contentCapture.model.js';
import downloadHistoryModel from '../models/downloadHistory.model.js';
import transcribeResultModel from '../models/transcribeResult.model.js';
import reSummaryHistoryModel from '../models/reSummaryHistory.model.js';

class BaseService {
	constructor() {
		this.constructorModel();
	}

	constructorModel() {
		this.userModel = userModel;
		this.noteModel = noteModel;
		this.shareModel = shareModel;
		this.searchModel = searchModel;
		this.memberModel = memberModel;
		this.corpusModel = corpusModel;
		this.contactModel = contactModel;
		this.contentModel = contentModel;
		this.chatbotModel = chatbotModel;
		this.calendarModel = calendarModel;
		this.bookmarkModel = bookmarkModel;
		this.highlightModel = highlightModel;
		this.contentCaptureModel = contentCaptureModel;
		this.downloadHistoryModel = downloadHistoryModel;
		this.transcribeResultModel = transcribeResultModel;
		this.reSummaryHistoryModel = reSummaryHistoryModel;
	}
}

export default BaseService;
