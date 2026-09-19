import express from 'express';
import multerUtil from '../utils/file/multer.util.js';
import userController from '../controller/user.controller.js';

const router = express.Router();

router.get('/usage', userController.getUsage);

router.get('/corpus', userController.getCorpus);
router.get('/corpus/check', userController.checkCorpusSoruce);
router.post('/corpus', userController.createCorpus);
router.patch('/corpus/:corpusId', userController.updateCorpus);
router.delete('/corpus/:corpusId', userController.deleteCorpus);

router.get('/contact', userController.getContacts);
router.post('/contact', userController.createContact);
router.get('/contact/template', userController.downloadContactTemplate);
router.post('/contact/bulk', multerUtil.uploadContactFile(), userController.createBulkContacts);
router.delete('/contact', userController.deleteContacts);
router.patch('/contact/favorite', userController.updateContactFavorite);
router.patch('/contact/recycle', userController.updateContactRecycle);
router.patch('/contact/labeling', userController.updateContactLabeling);
router.get('/contact/search', userController.searchContacts);
router.delete('/contact/:contactId', userController.deleteContact); // deprecated
router.patch('/contact/:contactId', userController.updateContact);

router.get('/contact/label', userController.getContactLabels);
router.post('/contact/label', userController.createContactLabel);
router.delete('/contact/label/:labelId', userController.deleteContactLabel);
router.put('/contact/label/:labelId', userController.updateContactLabel);

router.get('/folder', userController.getFolders);
router.post('/folder', userController.createFolder);
router.patch('/folder/item', userController.moveContentToFolder);
router.get('/folder/:folderId', userController.getFolderItems);
router.patch('/folder/:folderId', userController.updateFolder);
router.delete('/folder/:folderId', userController.deleteFolder);

router.get('/notification/setting', userController.getUserNotificationSetting);
router.put('/notification/setting', userController.updateUserNotificationSetting);

router.get('/notification/management', userController.getUserNotificationManagement);
router.patch('/notification/management', userController.updateUserNotificationManagementIsUsed);

router.get('/terms/consent', userController.getTermsConsent); // 약관별 동의 상태 조회
router.post('/terms/agreement', userController.createTermsConsent); // 약관별 동의서 제출

router.get('/:keyword', userController.getMembersFromWorkspace);

export default router;
