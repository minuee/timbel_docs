import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class TranscribeEngineModel extends BaseDatabase {
	constructor() {
		super('TranscribeEngineModel');
	}

	async getTranscribeEngineTag() {
		return await this.mariaDB.transcribeEngine.findMany({
			select: {
				tag: true,
			},
		});
	}
}

export default new TranscribeEngineModel();
