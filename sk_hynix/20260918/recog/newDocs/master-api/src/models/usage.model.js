import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class UsageModel extends BaseDatabase {
	constructor() {
		super('UsageModel');
	}

	async addUsage({ contentId, auth }, type, count) {
		try {
			const { member } = auth;
			return await this.mariaDB.usage.create({
				data: {
					type,
					count,
					contentId,
					workspaceId: member.workspace.id,
					member: { connect: { id: member.id } },
				},
			});
		} catch (err) {
			// 오류나도 무관하게
			log.e(err);
		}
	}
}

export default new UsageModel();
