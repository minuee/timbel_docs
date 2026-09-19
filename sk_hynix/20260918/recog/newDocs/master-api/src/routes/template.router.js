import express from 'express';
import templateController from '../controller/feature/template.controller.js';

const router = express.Router();

router.get('/', templateController.getTemplates);
router.post('/:templateId/favorite', templateController.favoriteTemplate);

export default router;
