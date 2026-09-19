import dateUtil from '../../utils/date.util.js';
import base from '../base.controller.js';
import { HttpError } from '../../handlers/error.handler.js';
import contentService from '../../services/content/content.service.js';
import calendarService from '../../services/feature/calendar.service.js';

class CalendarController {
	async getCalendars(req, res, next) {
		try {
			const { auth, user } = req;

			let { startDate, endDate } = req.query;
			if (!startDate || !endDate) {
				throw new HttpError(1000);
			}

			dateUtil.isValidDate(startDate, endDate);

			const options = dateUtil.formatDateRange(startDate, endDate);
			log.d('CalendarController', `options : ${JSON.stringify(options)}`);

			const result = await calendarService.getCalendars(user, auth.member, options);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async createCalendar(req, res, next) {
		try {
			const { auth, user } = req;
			const { title, meetingStartDate, attachedContents = [], reminderMinutes = 0 } = req.body;
			if (!title || !meetingStartDate) {
				throw new HttpError(1000);
			}

			if (attachedContents.length !== 0 && attachedContents.length > 5) {
				throw new HttpError(2101);
			}

			if (attachedContents.length !== new Set(attachedContents).size) {
				throw new HttpError(2102);
			}

			if (reminderMinutes < 0) {
				throw new HttpError(2108);
			}

			const createCalendarDTO = {
				title,
				meetingStartDate: dateUtil.toISOString(meetingStartDate),
				attachedContents,
				reminderMinutes: Number(reminderMinutes),
			};
			const result = await calendarService.createCalendar(auth, user, createCalendarDTO);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async connectWebcal(req, res, next) {
		try {
			const { user } = req;
			const { url } = req.body;
			if (!url) {
				throw new HttpError(1000);
			}

			const result = await calendarService.connectWebcal(user, url);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async getIntegrateSettings(req, res, next) {
		try {
			const { user } = req;
			const result = await calendarService.getIntegrateSettings(user);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async disconnectWebcal(req, res, next) {
		try {
			const { user } = req;
			const { provider } = req.params;
			if (!provider) {
				throw new HttpError(1000);
			}

			const result = await calendarService.disconnectWebcal(user, provider);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async syncIntegrate(req, res, next) {
		try {
			const { user } = req;
			const { force = false } = req.query;
			const result = await calendarService.syncIntegrate(user, force === 'true');
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async getIntegrateCalendars(req, res, next) {
		try {
			const { user } = req;
			const result = await calendarService.getIntegrateCalendars(user);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async loadIntegrate(req, res, next) {
		try {
			const { auth } = req;
			const { ids = [] } = req.body;
			if (ids.length === 0) {
				throw new HttpError(1000);
			}

			const result = await calendarService.loadIntegrate(auth, ids);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async deleteCalendar(req, res, next) {
		try {
			const { user, auth } = req;
			const { id } = req.params;
			if (!id) {
				throw new HttpError(1000);
			}
			log.d('[CalendarController][deleteCalendar]', `id : ${id}`);
			const contentIds = await calendarService.deleteCalendar(id);
			if (contentIds.length > 0) {
				await contentService.removeBulkContentsFromList(contentIds, auth, user);
			}
			base.sendNoContent(res);
		} catch (err) {
			next(err);
		}
	}

	async updateCalendar(req, res, next) {
		try {
			const { user } = req;
			const { id } = req.params;
			if (!id) {
				throw new HttpError(1000);
			}
			const { reminderMinutes = 0 } = req.body;
			if (Number(reminderMinutes) < 0) {
				throw new HttpError(2108);
			}
			const result = await calendarService.updateCalendar(id, Number(reminderMinutes), user);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}
}

export default new CalendarController();

