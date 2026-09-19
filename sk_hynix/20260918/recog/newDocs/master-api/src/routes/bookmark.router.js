import express from 'express';
import bookmarkController from '../controller/content/features/bookmark.controller.js';

const router = express.Router();

router.get('/', bookmarkController.getBookmarks);

router.post('/:contentId', bookmarkController.updateBookmark);
router.delete('/:contentId', bookmarkController.updateBookmark);

export default router;
