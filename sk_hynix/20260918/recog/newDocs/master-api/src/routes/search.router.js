import express from 'express';
import searchController from '../controller/system/search.controller.js';

const router = express.Router();

router.get('/', searchController.searchContentsbyKeyword);
router.get('/history/keyword', searchController.getKeywordsHistory);
router.delete('/history/keyword', searchController.deleteAllKeywordHistory);
router.delete('/history/keyword/:keywordId', searchController.deleteKeywordHistoryById);

router.post('/history/content/:contentId', searchController.upsertContentViewedHistoryBySearching);

router.get('/history/content', searchController.getContentViewedListBySearching);
router.delete('/history/content/:contentId', searchController.deleteContentViewedBySearching);

export default router;
