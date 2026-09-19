/**
 * User Controller - 통합 컨트롤러
 * 기능별로 분리된 컨트롤러들을 통합하여 기존 인터페이스 유지
 */
import workspaceController from './user/workspace.controller.js';
import corpusController from './user/corpus.controller.js';
import contactController from './user/contact.controller.js';
import folderController from './user/folder.controller.js';
import usageController from './user/usage.controller.js';
import notificationController from './user/notification.controller.js';
import termsController from './user/terms.controller.js';

class UserController {
	// Workspace 관련
	getMembersFromWorkspace = workspaceController.getMembersFromWorkspace.bind(workspaceController);

	// Corpus 관련
	getCorpus = corpusController.getCorpus.bind(corpusController);
	checkCorpusSoruce = corpusController.checkCorpusSoruce.bind(corpusController);
	createCorpus = corpusController.createCorpus.bind(corpusController);
	updateCorpus = corpusController.updateCorpus.bind(corpusController);
	deleteCorpus = corpusController.deleteCorpus.bind(corpusController);

	// Contact 관련
	createContact = contactController.createContact.bind(contactController);
	createBulkContacts = contactController.createBulkContacts.bind(contactController);
	downloadContactTemplate = contactController.downloadContactTemplate.bind(contactController);
	getContacts = contactController.getContacts.bind(contactController);
	deleteContact = contactController.deleteContact.bind(contactController);
	deleteContacts = contactController.deleteContacts.bind(contactController);
	updateContact = contactController.updateContact.bind(contactController);
	updateContactFavorite = contactController.updateContactFavorite.bind(contactController);
	updateContactRecycle = contactController.updateContactRecycle.bind(contactController);
	searchContacts = contactController.searchContacts.bind(contactController);
	createContactLabel = contactController.createContactLabel.bind(contactController);
	getContactLabels = contactController.getContactLabels.bind(contactController);
	deleteContactLabel = contactController.deleteContactLabel.bind(contactController);
	updateContactLabel = contactController.updateContactLabel.bind(contactController);
	updateContactLabeling = contactController.updateContactLabeling.bind(contactController);

	// Folder 관련
	createFolder = folderController.createFolder.bind(folderController);
	getFolders = folderController.getFolders.bind(folderController);
	getFolderItems = folderController.getFolderItems.bind(folderController);
	moveContentToFolder = folderController.moveContentToFolder.bind(folderController);
	updateFolder = folderController.updateFolder.bind(folderController);
	deleteFolder = folderController.deleteFolder.bind(folderController);

	// Usage 관련
	getUsage = usageController.getUsage.bind(usageController);

	// Notification 관련
	getUserNotificationSetting = notificationController.getUserNotificationSetting.bind(notificationController);
	updateUserNotificationSetting = notificationController.updateUserNotificationSetting.bind(notificationController);
	getUserNotificationManagement = notificationController.getUserNotificationManagement.bind(notificationController);
	updateUserNotificationManagementIsUsed = notificationController.updateUserNotificationManagementIsUsed.bind(
		notificationController
	);

	// Terms 관련
	getTermsConsent = termsController.getTermsConsent.bind(termsController);
	createTermsConsent = termsController.createTermsConsent.bind(termsController);
}

export default new UserController();
