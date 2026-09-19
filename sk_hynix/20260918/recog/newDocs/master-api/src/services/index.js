import userService from './user/user.service.js';
import queueService from './system/queue.service.js';
import driveService from './system/drive.service.js';
import searchService from './system/search.service.js';
import corpusService from './feature/corpus.service.js';
import summaryService from './engine/summary.service.js';
import contentService from './content/content.service.js';
import inboxService from './notification/inbox.service.js';
import calendarService from './feature/calendar.service.js';
import memoService from './content/features/memo.service.js';
import noteService from './content/features/note.service.js';
import noticeService from './notification/notice.service.js';
import shareService from './content/features/share.service.js';
import bookmarkService from './content/features/bookmark.service.js';
import attendeeService from './content/features/attendee.service.js';
import contentDetailService from './content/contentDetail.service.js';
import highlightService from './content/features/highlight.service.js';
import correctionService from './content/features/correction.service.js';
import proofreadingService from './content/features/proofreading.service.js';

export {
	noteService,
	userService,
	memoService,
	shareService,
	driveService,
	inboxService,
	noticeService,
	searchService,
	corpusService,
	summaryService,
	contentService,
	attendeeService,
	calendarService,
	bookmarkService,
	highlightService,
	correctionService,
	proofreadingService,
	contentDetailService,
	queueService,
};
