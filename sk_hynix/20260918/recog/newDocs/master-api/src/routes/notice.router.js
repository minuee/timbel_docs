import express from 'express';
import noticeController from '../controller/notification/notice.controller.js';

const router = express.Router();

router.get('/', noticeController.getNotices);
export default router;
