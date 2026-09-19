import base from '../base.controller.js';
import { HttpError } from '../../handlers/error.handler.js';
import { userService } from '../../services/index.js';
import { validate } from '../../utils/index.js';

class UserUsageController {
	async getUsage(req, res, next) {
		try {
			const { user, auth } = req;
			// type = 'today' | 'n week' | 'n month'
			const { type = '3month' } = req.query;

			if (!validate.isValidPeriod(type))
				throw new HttpError(1000, `type 파라미터는 today, week, month 중 하나만 가능합니다.`);

			const data = await userService.getUsage(user, auth, type);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}
}

export default new UserUsageController();

