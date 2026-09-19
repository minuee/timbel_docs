import base from '../base.controller.js';
import { dashboardService } from '../../services/user/dashboard.service.js';

class HomeController {
	async getDashboard(req, res, next) {
		try {
			const { user } = req;

			const data = await dashboardService(user);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}
}

export default new HomeController();

