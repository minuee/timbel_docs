import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class TemplateModel extends BaseDatabase {
	constructor() {
		super('TemplateModel');

		this.favoriteSelect = id => ({
			where: { memberId: id },
			select: {
				idx: true,
				templateId: true,
				version: true,
			},
		});
	}

	// 기본 템플릿 조회
	async getGlobalTemplate() {
		return await this.mongoDB.template.findFirst({
			where: { workspaceId: 'global', isUsed: 'Y', isDeleted: 'N' },
			select: {
				id: true,
				version: true,
				title: true,
				description: true,
				createAt: true,
				updateAt: true,
				template: { select: { index: true, moduleKey: true, displayName: false, items: true } },
			},
		});
	}

	// 기본 템플릿 생성
	async createGlobalTemplate() {
		const template = [
			{
				'index': 0,
				'moduleKey': 'title',
				'items': [{ 'index': 0, 'type': 'basic', 'value': '제목:\n{{title}}\n' }],
			},
			{
				'index': 1,
				'moduleKey': 'topics',
				'items': [{ 'index': 0, 'type': 'basic', 'value': '주제:\n{{topics}}\n' }],
			},
			{
				'index': 2,
				'moduleKey': 'speakerInfo',
				'items': [{ 'index': 0, 'type': 'basic', 'value': '참석자:\n{{speakerInfo}}\n' }],
			},
			{
				'index': 3,
				'moduleKey': 'keywords',
				'items': [{ 'index': 0, 'type': 'basic', 'value': '키워드:\n{{keywords}}\n' }],
			},
			{
				'index': 4,
				'moduleKey': 'summary',
				'items': [{ 'index': 0, 'type': 'basic', 'value': '핵심 요약:\n{{summary}}\n' }],
			},
			{
				'index': 5,
				'moduleKey': 'issues',
				'items': [{ 'index': 0, 'type': 'basic', 'value': '이슈:\n{{issues}}\n' }],
			},
			{
				'index': 6,
				'moduleKey': 'tasks',
				'items': [{ 'index': 0, 'type': 'basic', 'value': '할 일:\n{{tasks}}\n' }],
			},
			{
				'index': 7,
				'moduleKey': 'summaryTime',
				'items': [
					{ 'index': 0, 'type': 'basic', 'value': '주제별 상세 요약:' },
					{
						'index': 1,
						'type': 'loop',
						'value': '{{st_topic}}\n{{st_summary}}\n{{st_issues}}\n{{st_tasks}}\n\n',
					},
					{ 'index': 2, 'type': 'basic', 'value': '' },
				],
			},
		];

		const preview = `제목:\n{{title}}\n\n\n주제:\n{{topics}}\n\n\n참석자:\n{{speakerInfo}}\n\n\n키워드:\n{{keywords}}\n\n\n핵심 요약:\n{{summary}}\n\n\n이슈:\n{{issues}}\n\n\n할 일:\n{{tasks}}\n\n\n{{st_topic}}\n{{st_summary}}\n{{st_issues}}\n{{st_tasks}}\n\n`;

		return await this.mongoDB.template.create({
			data: {
				workspaceId: 'global',
				title: '기본 템플릿',
				version: '1.0.0',
				description: '기본 템플릿',
				preview,
				isUsed: 'Y',
				isDeleted: 'N',
				creatorPID: 'system',
				editorPID: 'system',
				template,
			},
		});
	}

	// 노트 템플릿 목록 조회
	async getNoteTemplates(workspaceId) {
		return await this.mongoDB.template.findMany({
			where: { workspaceId, isUsed: 'Y', isDeleted: 'N' },
			select: {
				id: true,
				version: true,
				title: true,
				description: true,
				createAt: true,
				updateAt: true,
				template: { select: { index: true, moduleKey: true, displayName: false, items: true } },
			},
			orderBy: { createAt: 'asc' },
		});
	}

	// 템플릿 상세 조회
	async getTemplateById(templateId) {
		return await this.mongoDB.template.findFirst({
			where: {
				id: templateId,
			},
		});
	}

	async getTemplates(member, type) {
		const { workspace } = member;
		const inputType = type === 'normal' ? 'timbel_stt' : 'timbel_minutes';
		log.i('[templateModel] getTemplates', workspace.id, inputType);
		return await this.mariaDB.template.findMany({
			where: {
				OR: [{ workspaceId: workspace.id }, { workspaceId: null }],
				isUsed: 'Y',
				isDeleted: 'N',
				inputType,
			},
			select: {
				id: true,
				inputType: true,
				name: true,
				description: true,
				preview: true,
				createAt: true,
				category: true,
				favorites: this.favoriteSelect(member.id),
			},
		});
	}

	async getTemplateByTemplateId(templateId) {
		return await this.mariaDB.template.findFirst({
			where: { id: templateId, isUsed: 'Y', isDeleted: 'N' },
			select: {
				id: true,
				workspaceId: true,
				version: true,
				key: true,
				inputType: true,
				options: true,
			},
			orderBy: { version: 'desc' },
		});
	}

	async getTemplateByMemberAndTemplateId(member, templateId) {
		const { id, workspace } = member;
		return await this.mariaDB.template.findFirst({
			where: {
				id: templateId,
				OR: [{ workspaceId: workspace.id }, { workspaceId: null }],
				isUsed: 'Y',
				isDeleted: 'N',
			},
			select: {
				id: true,
				workspaceId: true,
				version: true,
				favorites: this.favoriteSelect(id),
			},
		});
	}

	async favoriteTemplate(member, template) {
		const { id } = member;
		const { id: templateId, version } = template;
		return await this.mariaDB.templateFavorite.create({
			data: { templateId, version, memberId: id },
		});
	}

	async unfavoriteTemplate(where) {
		return await this.mariaDB.templateFavorite.delete({
			where,
		});
	}
}

export default new TemplateModel();
