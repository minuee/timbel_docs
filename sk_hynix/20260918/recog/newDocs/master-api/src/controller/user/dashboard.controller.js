import base from '../base.controller.js';
import dashboardService from '../../services/user/dashboard.service.js';

class DashboardController {
	async getDashboard(req, res, next) {
		try {
			const { user, auth } = req;

			const data = await dashboardService.getDashboardData(user, auth);

			base.sendSuccess(res, data);
		} catch (err) {
			next(err);
		}
	}
}

export default new DashboardController();
