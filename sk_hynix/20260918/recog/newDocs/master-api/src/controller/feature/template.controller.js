import base from '../base.controller.js';
import templateService from '../../services/feature/template.service.js';

class TemplateController {
	async getTemplates(req, res, next) {
		try {
			const { auth } = req;
			const { member } = auth;
			let { type } = req.query;
			if (!type) type = 'normal';
			const result = await templateService.getTemplates(member, type);

			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}

	async favoriteTemplate(req, res, next) {
		try {
			const { auth } = req;
			const { member } = auth;
			const { templateId } = req.params;
			const result = await templateService.favoriteTemplate(member, templateId);
			base.sendSuccess(res, result);
		} catch (err) {
			next(err);
		}
	}
}

export default new TemplateController();

