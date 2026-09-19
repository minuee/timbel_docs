import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class CorpusModel extends BaseDatabase {
	constructor() {
		super('CorpusModel');
	}

	async getCorpus({ id: memeberId }, search) {
		const options = {
			orderBy: {
				createAt: 'desc',
			},
			where: {
				creatorId: memeberId,
			},
		};

		if (search) {
			options.where.OR = [
				{ source: { contains: search } },
				{ target: { contains: search } },
				{ memo: { contains: search } },
			];
		}
		return await this.mariaDB.corpus.findMany(options);
	}

	async getCorpusSourceAndTarget(memeberId) {
		return await this.mariaDB.corpus.findMany({
			orderBy: {
				createAt: 'asc',
			},
			where: {
				creatorId: memeberId,
				isUsed: true,
			},
			select: {
				source: true,
				target: true,
			},
		});
	}

	async getCorpusByCreatorIdAndSoruce({ id: memeberId }, source) {
		return await this.mariaDB.corpus.findFirst({
			where: {
				creatorId: memeberId,
				source,
			},
		});
	}

	async createCorpus({ id: memberId, workspace }, data) {
		return await this.mariaDB.corpus.create({
			data: {
				workspaceId: workspace.id,
				creatorId: memberId,
				updaterId: memberId,
				...data,
			},
		});
	}

	async updateCorpus(corpusId, data) {
		return await this.mariaDB.corpus.update({
			where: { id: corpusId },
			data,
		});
	}

	async deleteCorpus(corpusId) {
		return await this.mariaDB.corpus.delete({
			where: { id: corpusId },
		});
	}

	async getCorpusCount(creatorId, { startDate, endDate }) {
		const [periodCount, totalCount] = await Promise.all([
			this.mariaDB.corpus.count({
				where: {
					creatorId,
					createAt: {
						gte: startDate,
						lt: endDate,
					},
				},
			}),
			this.mariaDB.corpus.count({
				where: {
					creatorId,
				},
			}),
		]);

		return {
			periodCount,
			totalCount,
		};
	}
}

export default new CorpusModel();
