import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class WorkspacePolicyModel extends BaseDatabase {
	constructor() {
		super('WorkspacePolicyModel');
	}

	async findAll() {
		return await this.mariaDB.workspace.findMany({
			select: {
				id: true,
				domain: true,
				policy: {
					select: {
						id: true,
						policyType: true,
						value: true,
						unit: true,
					},
				},
			},
			where: {
				policy: {
					some: {},
				},
			},
		});
	}
}

export default new WorkspacePolicyModel();
