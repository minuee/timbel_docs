import express from 'express';
import queueController from '../controller/system/queue.controller.js';

const router = express.Router();

router.get('/', queueController.getRecogQueues);
router.post('/:queueName/pause', queueController.pauseQueue);
router.post('/:queueName/resume', queueController.resumeQueue);
router.post('/:queueName/job/moveToFailed', queueController.moveToFailedJob);
router.post('/:queueName/job/retry', queueController.retryJob);

export default router;
