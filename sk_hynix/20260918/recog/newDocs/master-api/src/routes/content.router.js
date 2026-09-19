import express from 'express';
import multerUtil from '../utils/file/multer.util.js';
import contentController from '../controller/content.controller.js';

const router = express.Router();

router.post(['/upload'], multerUtil.uploadFileWithTimeout(), contentController.uploadContent);
router.post(
	['/upload/encryption/files'],
	multerUtil.uploadFilesWithTimeout(),
	contentController.uploadEncryptionFilesContent
);
router.post(['/upload/encryption'], multerUtil.uploadFileWithTimeout(), contentController.uploadEncryptionFileContent);
router.post(['/upload/text'], multerUtil.uploadTextFile(), contentController.uploadTextFileContent);
router.post(['/thumbnail', '/thumbnail/:type'], multerUtil.uploadImageFile(), contentController.uploadThumbnail);

router.get(['/download', '/download/:contentId'], contentController.downloadContent);

router.post(['/recycle'], contentController.removeBulkContentsFromList);
router.delete(['/recycle/clear'], contentController.clearRecyleBin);
router.delete(['/recycle/:contentId'], contentController.removeContentFromList); // (deprecated)

router.delete(['/truncate', '/truncate/:contentId'], contentController.truncateContent);

router.get(['/recycle'], contentController.getRecycleContents);

router.delete(['/restore', '/restore/:contentId'], contentController.restoreContent);

router.get(['/', '/list'], contentController.getAllContents);
router.get('/calendar', contentController.getCalendarContents); // deprecated

router.get('/share/:contentId', contentController.getContentShareUsers);
router.post(['/share'], contentController.addContentShareUser);
router.put(['/share'], contentController.updateShareUserPermission);
router.post(['/share/bulk'], contentController.addContentShareUsers);
router.delete(['/share/:contentId/:email'], contentController.deleteContentShareUser);

router.post('/:contentId/retry', contentController.contentRetry);
router.patch('/:contentId/title', contentController.updateContentTitle);
router.get('/:contentId', contentController.getContentDetail);

router.get('/:contentId/memo', contentController.getMemos);
router.post('/:contentId/memo', contentController.createMemo);
router.patch('/:contentId/memo/secret', contentController.updateContentMemosSecret);
router.patch('/:contentId/memo/:memoId/secret', contentController.updateMemoSecret);
router.patch('/:contentId/memo/:memoId/text', contentController.updateMemoText);
router.delete('/:contentId/memo/:memoId', contentController.deleteMemo);

router.post('/:contentId/memo/:memoId/comment', contentController.createMemoComment);
router.patch('/:contentId/memo/:memoId/comment/:commentId/text', contentController.updateMemoCommentText);
router.delete('/:contentId/memo/:memoId/comment/:commentId', contentController.deleteMemoComment);

router.get('/:contentId/note', contentController.getNoteContent);
router.post('/:contentId/note', contentController.pasteTextIntoNote);
router.patch('/:contentId/note', contentController.updateNoteContent);

router.get('/:contentId/mynote', contentController.getMyNoteContent);
router.patch('/:contentId/myNote', contentController.updateMyNoteContent);

router.get(['/:contentId/template', '/:contentId/myNote/template'], contentController.getNoteTemplates);

router.get('/:contentId/attendees', contentController.getAttendees);
router.post('/:contentId/attendees', contentController.addAttendee);
router.put('/:contentId/attendees', contentController.changeAttendees);
router.delete('/:contentId/attendees/:speakerId', contentController.deleteAttendee);
router.patch('/:contentId/attendees/:speakerId', contentController.changeAttendeeName);

router.patch('/:contentId/keywords', contentController.updateContentKeywords);
router.post('/:contentId/transcription/reset', contentController.resetSegments);
router.patch('/:contentId/transcription/segments/text', contentController.changeSegments);
router.patch('/:contentId/transcription/:startTime/speaker', contentController.changeSpeakerForSegment);

router.get(['/:contentId/correction'], contentController.getCorrection);
router.post(['/:contentId/correction'], contentController.requestCorrection);
router.post(['/:contentId/correction/history'], contentController.createCorrectionHistory);

router.post(['/:contentId/reSummary'], contentController.reSummaryContent);
router.patch(['/:contentId/meetingTime'], contentController.updateMeetingTime);

router.post('/:contentId/dictionary', contentController.addWordSetToCandidates);
router.post('/:contentId/proofreading', contentController.segmentProofreading);

router.get('/:contentId/export', contentController.exportContentToDocs);

router.post('/:contentId/highlight', contentController.addHighlight);
router.delete('/:contentId/highlight/:highlightId', contentController.deleteHighlight);

router.patch('/:contentId/summary', contentController.updateSummaryContent);

router.post('/merge', contentController.mergeContents);

export default router;
