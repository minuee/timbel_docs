import express from 'express';
import inboxController from '../controller/notification/inbox.controller.js';

const router = express.Router();

router.get('/', inboxController.getInboxByMemberId);
router.patch('/:inboxId', inboxController.updateisReadInbox);
router.patch('/', inboxController.updateisReadInboxByMemberId);
router.delete('/:inboxId', inboxController.deleteInbox);
router.delete('/', inboxController.deleteInboxMemberId);

export default router;
