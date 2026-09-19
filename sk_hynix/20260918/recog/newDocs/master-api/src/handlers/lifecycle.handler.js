import { taskQueue } from '../utils/index.js';
import contentModel from '../models/content.model.js';
import worker from '../utils/lifecycleWorker/index.js';
import lifeCycleModel from '../models/lifecycle.model.js';
import { getDelayUntil, getDateTime } from '../utils/date.util.js';
import workspacePolicyModel from '../models/workspacePolicy.model.js';

let SYS_LIFE_CYCLE_BATCH_DAY = 1;
let SYS_LIFE_CYCLE_BATCH_HOUR = 3;

// 기본 3일 후 03시 배치

const TAG = '[lifecycleHandler]';
const WORKERS = Object.keys(worker);

const getLastCompletedTargetCreationDate = async (workspaceId, policyId) => {
	try {
		const { targetId } = await lifeCycleModel.getLastCompletedTarget(workspaceId, policyId);
		if (!targetId) return undefined;

		const { createAt = undefined } = (await contentModel.findSimpleContentById(targetId)) || {};
		log.i(TAG, `lastCompletedContentId : ${targetId}, createAt : ${createAt}`);
		return createAt;
	} catch (err) {
		log.e(TAG, `getLastCompletedTargetCreationDate 오류 : ${err}`);
		return undefined;
	}
};

const lifecycleWorker = async task => {
	const { targetDomain, policies = [], workspaceId } = task;
	for (const policy of policies) {
		const executionLog = await lifeCycleModel.createLifeCyclePolicyExecutionLog(workspaceId, policy);
		const start = new Date();

		try {
			const { policyType = 'ALL', id } = policy;
			log.i(TAG, ` [${targetDomain}] [${policyType}] 워커 생성 시작`);
			const lastCompletedTargetCreationDate = await getLastCompletedTargetCreationDate(workspaceId, id);

			if (!WORKERS.includes(policyType.toLowerCase())) {
				log.e(TAG, ` [${targetDomain}] [${policyType}] 워커 생성 오류 : ${policyType} 워커가 없습니다.`);
				continue;
			}

			const results = await worker[policyType.toLowerCase()](task, policy, lastCompletedTargetCreationDate);

			await lifeCycleModel.updateLifeCyclePolicyExecutionLog(executionLog.id, {
				...results,
				durationMs: new Date().getTime() - start.getTime(),
			});
		} catch (err) {
			log.e(TAG, ` [${targetDomain}] 워커 생성 오류 : ${err}`);
			await lifeCycleModel.updateLifeCyclePolicyExecutionLog(executionLog.id, {
				failedCount: -1,
				failureReason: 'lifecycleWorker Error -> ' + err.message,
				durationMs: new Date().getTime() - start.getTime(),
			});
		}
	}
};

const LIFECYCLE_CONCURRENCY = Number(process.env.LIFECYCLE_CONCURRENCY) || 10;
const dailyLifecycleQueue = new taskQueue('lifecycle', lifecycleWorker, LIFECYCLE_CONCURRENCY);

const dailyQueueSetup = async () => {
	const today = getDateTime(new Date(), 'YYYYMMDD');
	const taskId = `${TAG}-${today}`;
	try {
		const isDelete = await dailyQueue.cancelTask(taskId);
		if (isDelete) log.i(TAG, ` [${taskId}] 기존 daily Worker 정리 완료`);

		await dailyQueue.addTask({ taskId }, getDelayUntil(SYS_LIFE_CYCLE_BATCH_DAY, SYS_LIFE_CYCLE_BATCH_HOUR + 1));
	} catch (err) {
		log.e(TAG, `dailyQueueSetup 오류 : ${err}`);
		await dailyQueue.addTask(
			{ taskId: `${TAG}-${Date.now()}` },
			getDelayUntil(SYS_LIFE_CYCLE_BATCH_DAY, SYS_LIFE_CYCLE_BATCH_HOUR + 1)
		);
	}
};

// 서비스 실행과 동시에 수행되는 프로세스로
// 라이프 사이클 배치에 대한 큐를 생성
// 정책이 있는 워크스페이스 개수 만큼 배치 생성
const lifecycleInit = async () => {
	const workspaces = await workspacePolicyModel.findAll();
	const status = {
		success: [],
		fail: [],
	};
	log.i(TAG, `워크스페이스 daily Worker 생성 대상 : ${workspaces.length}개`);

	for (const workspace of workspaces) {
		const { id, policy, domain } = workspace;

		const isDelete = await dailyLifecycleQueue.cancelTask(id);
		if (isDelete) log.i(TAG, ` [${domain}] 기존 daily Worker 정리 완료 : ${id}`);

		if (policy.length === 0) continue;

		const task = {
			taskId: id,
			workspaceId: id,
			targetDomain: domain,
			policies: policy,
		};

		log.i(TAG, ` [${domain}] daily Worker 생성 시작 : ${id}`);
		const result = await dailyLifecycleQueue.addTask(
			task,
			getDelayUntil(SYS_LIFE_CYCLE_BATCH_DAY, SYS_LIFE_CYCLE_BATCH_HOUR)
		);
		status[result ? 'success' : 'fail'].push(workspace);
	}

	log.i(TAG, `daily Worker 생성 완료 : ${status.success.length}개 성공, ${status.fail.length}개 실패`);
	await dailyLifecycleQueue.printQueueStatus();

	await dailyQueueSetup();
};

process.on('configChanged', () => {
	const instanceId = process.env.INSTANCE_ID || '0';
	log.i(TAG, `instanceId : ${instanceId}`);
	if (instanceId === '0') {
		SYS_LIFE_CYCLE_BATCH_DAY = Number(process.env.SYS_LIFE_CYCLE_BATCH_DAY) || 1;
		SYS_LIFE_CYCLE_BATCH_HOUR = Number(process.env.SYS_LIFE_CYCLE_BATCH_HOUR) || 3;
		log.i(TAG, `[${SYS_LIFE_CYCLE_BATCH_DAY}] [${SYS_LIFE_CYCLE_BATCH_HOUR}] 데일리 배치 생성 시작`);
		lifecycleInit();
	}
});
const dailyQueue = new taskQueue('lifecycleInit', lifecycleInit, 1);

export default lifecycleInit;
