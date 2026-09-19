import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class CorrectionModel extends BaseDatabase {
	constructor() {
		super('CorrectionModel');
	}

	async getCorrection(contentId, creatorId, findOptions = {}) {
		const { version = null } = findOptions;
		const options = {
			orderBy: {
				version: 'desc',
			},
			where: {
				contentId,
				creatorId,
			},
		};

		if (version) {
			options.where.version = version;
		}

		return await this.mariaDB.correction.findFirst(options);
	}

	async createCorrection(contentId, creatorId) {
		return await this.mariaDB.correction.create({
			data: {
				contentId,
				creatorId,
			},
		});
	}

	async createCorrectionResult(corrections) {
		return await this.mariaDB.correctionResult.createMany({
			data: corrections,
		});
	}

	async updateStatusCorrection(id, status) {
		return await this.mariaDB.correction.update({
			where: {
				id,
			},
			data: {
				status,
			},
		});
	}
}

export default new CorrectionModel();
