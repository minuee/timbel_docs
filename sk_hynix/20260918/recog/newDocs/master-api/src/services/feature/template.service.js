import { transform } from '../../utils/index.js';
import templateModel from '../../models/template.model.js';

class TemplateService {
	constructor() {
		this.templateModel = templateModel;
	}

	async getTemplates(member, type) {
		try {
			const templates = await this.templateModel.getTemplates(member, type);
			log.i('[templateService] 조회된 템플릿 수 -> ', templates.length);

			const result = transform.transformTemplates(templates);
			log.i('[templateService] 템플릿 통합 후 카테고리 수 -> ', result.length);
			return result;
		} catch (err) {
			throw err;
		}
	}

	async favoriteTemplate(member, templateId) {
		try {
			const template = await this.templateModel.getTemplateByMemberAndTemplateId(member, templateId);
			if (!template) throw new HttpError(2201);

			log.i('[templateService] favoriteTemplate', JSON.stringify(template, null, 2));
			const { favorites } = template;
			const isFavorite = favorites.length > 0;
			let result = null;
			if (isFavorite) {
				const { idx } = favorites[0];
				result = await this.templateModel.unfavoriteTemplate({
					templateId: template.id,
					version: template.version,
					memberId: member.id,
					idx,
				});
			} else {
				result = await this.templateModel.favoriteTemplate(member, template);
			}
			return result;
		} catch (err) {
			throw err;
		}
	}
}

export default new TemplateService();
