/**
 * Content Controller - 통합 컨트롤러
 * 기능별로 분리된 컨트롤러들을 통합하여 기존 인터페이스 유지
 */
import uploadController from './content/upload.controller.js';
import shareController from './content/features/share.controller.js';
import attendeeController from './content/features/attendee.controller.js';
import noteController from './content/features/note.controller.js';
import memoController from './content/features/memo.controller.js';
import recycleController from './system/recycle.controller.js';
import detailController from './content/detail.controller.js';
import correctionController from './content/features/correction.controller.js';
import transcriptionController from './content/features/transcription.controller.js';
import summaryController from './content/features/summary.controller.js';
import mergeController from './content/features/merge.controller.js';

class ContentController {
	// Upload 관련
	uploadContent = uploadController.uploadContent.bind(uploadController);
	uploadEncryptionFileContent = uploadController.uploadEncryptionFileContent.bind(uploadController);
	uploadEncryptionFilesContent = uploadController.uploadEncryptionFilesContent.bind(uploadController);
	uploadThumbnail = uploadController.uploadThumbnail.bind(uploadController);
	uploadTextFileContent = uploadController.uploadTextFileContent.bind(uploadController);

	// Share 관련
	getContentShareUsers = shareController.getContentShareUsers.bind(shareController);
	addContentShareUser = shareController.addContentShareUser.bind(shareController);
	addContentShareUsers = shareController.addContentShareUsers.bind(shareController);
	updateShareUserPermission = shareController.updateShareUserPermission.bind(shareController);
	deleteContentShareUser = shareController.deleteContentShareUser.bind(shareController);

	// Attendee 관련
	getAttendees = attendeeController.getAttendees.bind(attendeeController);
	addAttendee = attendeeController.addAttendee.bind(attendeeController);
	changeAttendees = attendeeController.changeAttendees.bind(attendeeController);
	changeAttendeeName = attendeeController.changeAttendeeName.bind(attendeeController);
	deleteAttendee = attendeeController.deleteAttendee.bind(attendeeController);
	changeSpeakerForSegment = attendeeController.changeSpeakerForSegment.bind(attendeeController);

	// Note 관련
	getNoteContent = noteController.getNoteContent.bind(noteController);
	updateNoteContent = noteController.updateNoteContent.bind(noteController);
	pasteTextIntoNote = noteController.pasteTextIntoNote.bind(noteController);
	getMyNoteContent = noteController.getMyNoteContent.bind(noteController);
	updateMyNoteContent = noteController.updateMyNoteContent.bind(noteController);
	getNoteTemplates = noteController.getNoteTemplates.bind(noteController);

	// Memo 관련
	getMemos = memoController.getMemos.bind(memoController);
	createMemo = memoController.createMemo.bind(memoController);
	updateMemoText = memoController.updateMemoText.bind(memoController);
	updateMemoSecret = memoController.updateMemoSecret.bind(memoController);
	updateContentMemosSecret = memoController.updateContentMemosSecret.bind(memoController);
	deleteMemo = memoController.deleteMemo.bind(memoController);
	createMemoComment = memoController.createMemoComment.bind(memoController);
	updateMemoCommentText = memoController.updateMemoCommentText.bind(memoController);
	deleteMemoComment = memoController.deleteMemoComment.bind(memoController);

	// Recycle 관련
	getRecycleContents = recycleController.getRecycleContents.bind(recycleController);
	removeContentFromList = recycleController.removeContentFromList.bind(recycleController);
	removeBulkContentsFromList = recycleController.removeBulkContentsFromList.bind(recycleController);
	restoreContent = recycleController.restoreContent.bind(recycleController);
	truncateContent = recycleController.truncateContent.bind(recycleController);
	clearRecyleBin = recycleController.clearRecyleBin.bind(recycleController);

	// Detail 관련
	getContentDetail = detailController.getContentDetail.bind(detailController);
	getAllContents = detailController.getAllContents.bind(detailController);
	getCalendarContents = detailController.getCalendarContents.bind(detailController);
	downloadContent = detailController.downloadContent.bind(detailController);
	exportContentToDocs = detailController.exportContentToDocs.bind(detailController);
	updateContentTitle = detailController.updateContentTitle.bind(detailController);

	// Correction 관련
	getCorrection = correctionController.getCorrection.bind(correctionController);
	requestCorrection = correctionController.requestCorrection.bind(correctionController);
	createCorrectionHistory = correctionController.createCorrectionHistory.bind(correctionController);
	segmentProofreading = correctionController.segmentProofreading.bind(correctionController);
	addWordSetToCandidates = correctionController.addWordSetToCandidates.bind(correctionController);

	// Transcription 관련
	resetSegments = transcriptionController.resetSegments.bind(transcriptionController);
	changeSegments = transcriptionController.changeSegments.bind(transcriptionController);
	contentRetry = transcriptionController.contentRetry.bind(transcriptionController);

	// Summary 관련
	updateContentKeywords = summaryController.updateContentKeywords.bind(summaryController);
	reSummaryContent = summaryController.reSummaryContent.bind(summaryController);
	updateMeetingTime = summaryController.updateMeetingTime.bind(summaryController);
	addHighlight = summaryController.addHighlight.bind(summaryController);
	deleteHighlight = summaryController.deleteHighlight.bind(summaryController);
	updateSummaryContent = summaryController.updateSummaryContent.bind(summaryController);

	// Merge 관련
	mergeContents = mergeController.mergeContents.bind(mergeController);

	// User 관련 (도메인 기반 사용자 조회)
	getUsersFromDomain = detailController.getUsersFromDomain.bind(detailController);
}

export default new ContentController();
