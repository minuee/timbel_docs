import express from 'express';
import keywordController from '../controller/feature/keyword.controller.js';
import multerUtil from '../utils/file/multer.util.js';

const router = express.Router();

router.post('/', keywordController.createKeywordBoosting);
router.get('/', keywordController.getKeywordBoostings);
router.get('/template', keywordController.downloadKeywordTemplate);
router.post('/bulk', multerUtil.uploadContactFile(), keywordController.bulkCreateKeywordBoosting);
router.delete('/:keywordId', keywordController.deleteKeywordBoosting);

export default router;
