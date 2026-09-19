import BaseDatabase from '@timbel-timblo-onpremise/prisma';

class LifeCycleModel extends BaseDatabase {
	constructor() {
		super('LifeCycleModel');
	}

	async findLifeCycleTask(workspaceId, { id, policyType }, targetId) {
		return await this.mariaDB.lifecycleTask.findFirst({
			where: { workspaceId, policyId: id, targetId, targetType: policyType },
		});
	}

	async createLifeCycleTask(workspaceId, { id, policyType, value, unit }, targetId) {
		return await this.mariaDB.lifecycleTask.create({
			data: {
				workspaceId,
				policy: {
					connect: { id },
				},
				policyValue: value,
				policyUnit: unit,
				targetId,
				targetType: policyType,
			},
		});
	}

	async updateLifeCycleTask(id, { processingAt, completedAt, failedAt, failureReason }) {
		return await this.mariaDB.lifecycleTask.update({
			where: { id },
			data: { processingAt, completedAt, failedAt, failureReason },
		});
	}

	async createLifeCyclePolicyExecutionLog(workspaceId, { id }) {
		return await this.mariaDB.lifecyclePolicyExecutionLog.create({
			data: { workspaceId, policy: { connect: { id } } },
		});
	}

	async updateLifeCyclePolicyExecutionLog(id, { totalCount, successCount, failedCount, durationMs }) {
		return await this.mariaDB.lifecyclePolicyExecutionLog.update({
			where: { id },
			data: { totalCount, successCount, failedCount, durationMs },
		});
	}

	async getContentLifecycle(contentId) {
		return await this.mariaDB.lifecycleTask.findMany({
			where: { targetId: { in: [contentId] }, completedAt: { not: null } },
			select: { targetType: true, policyValue: true, policyUnit: true },
		});
	}

	async getLastCompletedTarget(workspaceId, policyId) {
		return await this.mariaDB.lifecycleTask.findFirst({
			where: { workspaceId, policyId, completedAt: { not: null } },
			orderBy: { completedAt: 'desc' },
			select: { targetId: true },
		});
	}
}

export default new LifeCycleModel();
