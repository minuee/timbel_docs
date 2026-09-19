import base from '../base.controller.js';
import { HttpError } from '../../handlers/error.handler.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';
import { userService } from '../../services/index.js';

class UserNotificationController {
	async getUserNotificationSetting(req, res, next) {
		try {
			const { user } = req;

			const result = await userService.getUserNotificationSetting(user);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async updateUserNotificationSetting(req, res, next) {
		try {
			const { user } = req;
			const {
				allowNotification,
				allowPush,
				allowEmail,
				allowContentCreate,
				allowContentShare,
				allowContentError,
			} = req.body;

			if (
				typeof allowNotification !== 'boolean' ||
				typeof allowPush !== 'boolean' ||
				typeof allowEmail !== 'boolean' ||
				typeof allowContentCreate !== 'boolean' ||
				typeof allowContentShare !== 'boolean' ||
				typeof allowContentError !== 'boolean'
			)
				throw new HttpError(1000);

			const result = await userService.updateUserNotificationSetting(user, {
				allowNotification,
				allowPush,
				allowEmail,
				allowContentCreate,
				allowContentShare,
				allowContentError,
			});

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async getUserNotificationManagement(req, res, next) {
		try {
			const { user, auth } = req;
			const workspaceId = auth?.member?.workspace?.id;
			const data = await userService.getUserNotificationManagement(user, workspaceId);
			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}

	async updateUserNotificationManagementIsUsed(req, res, next) {
		try {
			const { user, auth } = req;
			const workspaceId = auth?.member?.workspace?.id;
			const { notifications } = req.body;

			if (!Array.isArray(notifications) || notifications.length < 1) throw new HttpError(1000);
			notifications.forEach(notification => {
				const { channel, eventType, isUsed } = notification;
				if (!Object.values(Enums.UserNotificationChannel).includes(channel)) throw new HttpError(1000);
				if (!Object.values(Enums.UserNotificationEventType).includes(eventType)) throw new HttpError(1000);
				if (typeof isUsed !== 'boolean') throw new HttpError(1000);
			});

			const data = await userService.updateUserNotificationManagementIsUsed(user, notifications, workspaceId);
			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}
}

export default new UserNotificationController();
