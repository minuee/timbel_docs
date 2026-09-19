import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class KeywordBoostringModel extends BaseDatabase {
	constructor() {
		super('KeywordBoostringModel');
	}

	async isExisted({ id, workspace }, { keyword, keywordId }) {
		const where = {
			workspaceId: workspace.id,
			creatorId: id,
			keyword,
			...(keywordId && { id: { not: Number(keywordId) } }),
		};
		const existed = await this.mariaDB.keywordBoosting.findFirst({
			where,
		});
		return existed ? true : false;
	}

	async createKeywordBoosting({ id, workspace }, keywordData = {}) {
		return await this.mariaDB.keywordBoosting.create({
			data: {
				workspace: { connect: { id: workspace.id } },
				creator: { connect: { id } },
				...keywordData,
			},
		});
	}

	async createManyKeywordBoostings({ id, workspace }, keywords = []) {
		if (!keywords.length) return { count: 0 };
		return await this.mariaDB.keywordBoosting.createMany({
			data: keywords.map(keyword => ({ workspaceId: workspace.id, creatorId: id, keyword })),
			skipDuplicates: true,
		});
	}

	async findAllKeywordBoostings({ id, workspace }, sortOrder = 'latest') {
		const orderBy = sortOrder === 'latest' ? { createAt: 'desc' } : { keyword: 'asc' };
		const keywordBoostings = await this.mariaDB.keywordBoosting.findMany({
			where: {
				workspaceId: workspace.id,
				creatorId: id,
			},
			orderBy,
			select: {
				id: true,
				keyword: true,
				isPostProcess: true,
				createAt: true,
			},
		});
		return {
			keywords: keywordBoostings,
			totalCount: keywordBoostings.length,
		};
	}

	async getKeywordBoostingCount({ id, workspace }) {
		return await this.mariaDB.keywordBoosting.count({
			where: {
				workspaceId: workspace.id,
				creatorId: id,
			},
		});
	}

	async findKeywordById({ id, workspace }, keywordId) {
		return await this.mariaDB.keywordBoosting.findFirst({
			where: {
				id: Number(keywordId),
				workspaceId: workspace.id,
				creatorId: id,
			},
		});
	}

	async deleteKeywordBoosting({ id, workspace }, keywordId) {
		return await this.mariaDB.keywordBoosting.delete({
			where: {
				workspaceId: workspace.id,
				creatorId: id,
				id: keywordId,
			},
		});
	}
}

export default new KeywordBoostringModel();
