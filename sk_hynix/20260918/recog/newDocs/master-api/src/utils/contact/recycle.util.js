import { taskQueue } from '../index.js';
import contactModel from '../../models/contact.model.js';
import { HttpError } from '../../handlers/error.handler.js';

const { env } = process;

const TAG = '[contact-recycle-util]';
const contactRecycleWorker = async task => {
	log.i(TAG, '[contactRecycleWorker] start');
	try {
		const { user, contactId } = task;
		const contact = await contactModel.findContactById(user.pid, contactId);
		if (!contact) throw new HttpError(1902);
		log.i(TAG, '[contactRecycleWorker] 주소록 정보 확인 ==> ', contact.id);

		await contactModel.deleteContact(contactId);

		const result = await contactModel.findContactById(user.pid, contactId);
		if (!result) log.i(TAG, '[contactRecycleWorker] 주소록 삭제 완료');

		return true;
	} catch (err) {
		throw err;
	}
};

const CONTACT_RECYCLE_CONCURRENCY = Number(process.env.CONTACT_RECYCLE_CONCURRENCY) || 10;
const contactRecycleQueue = new taskQueue('contact-recycle', contactRecycleWorker, CONTACT_RECYCLE_CONCURRENCY);

const addContactRecycleTask = async (contactId, user) => {
	log.i(TAG, '[addTask] contactId : ', contactId);
	const task = {
		user,
		contactId,
		taskId: contactId,
	};
	return contactRecycleQueue.addTask(task, env?.CONTACT_RECYCLE_DELAY ?? 2592000000); // 30일
};

const cancelContactRecycleTask = async contactId => {
	log.i(TAG, '[cancelTask] contactId : ', contactId);
	return contactRecycleQueue.cancelTask(contactId);
};

const directlyDeleteContact = async (contactIds, user) => {
	log.i(TAG, '[directlyDeleteContact] contactIds : ', contactIds);
	contactIds.forEach(async contactId => {
		const task = {
			user,
			contactId,
			taskId: contactId,
		};
		await contactRecycleQueue.addFastTask(task);
	});
	log.i(TAG, '[directlyDeleteContact] task Clear check');
};

export default {
	addContactRecycleTask,
	cancelContactRecycleTask,
	directlyDeleteContact,
};

