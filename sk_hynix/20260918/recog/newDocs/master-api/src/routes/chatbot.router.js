import express from 'express';
import chatbotController from '../controller/engine/chatbot.controller.js';

const router = express.Router();

router.post('/new', chatbotController.createChatbot);
router.post('/:id/query', chatbotController.sendQuery);

router.get('/list', chatbotController.getChatbotList);
router.get('/:id', chatbotController.getChatDetail);

router.delete('/:id', chatbotController.deleteChatbot);

export default router;
