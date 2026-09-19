import { generate, drive } from '../index.js';
import contentModel from '../../models/content.model.js';
import { QueueError } from '../../handlers/error.handler.js';
import lifeCycleModel from '../../models/lifecycle.model.js';
import transcribeResultModel from '../../models/transcribeResult.model.js';

const TAG = '[lifecycleWorker/file]';

const worker = async ({ workspaceId, contentId, creatorId, fileKey, lifeCycleTaskId }) => {
	const WORKER_TAG = `${TAG} [${contentId}] [${fileKey}] `;
	try {
		log.i(WORKER_TAG, `워커 시작`);
		await lifeCycleModel.updateLifeCycleTask(lifeCycleTaskId, { processingAt: new Date() });

		const creatorSalt = `${creatorId}${workspaceId}`;
		const kms = generate.keyFromString(creatorSalt);
		log.i(WORKER_TAG, `KMS 키 발급 --> ${kms}`);

		const removeResult = await new drive({ kms }).removeObject({ fileKey });
		if (!removeResult) throw new QueueError(1125);
		log.i(WORKER_TAG, `파일 삭제 완료 --> ${removeResult}`);

		await lifeCycleModel.updateLifeCycleTask(lifeCycleTaskId, { completedAt: new Date() });
		log.i(WORKER_TAG, `워커 종료`);
		return true;
	} catch (err) {
		log.e(WORKER_TAG, `오류 발생 --> ${err.message}`);
		await lifeCycleModel.updateLifeCycleTask(lifeCycleTaskId, { failedAt: new Date(), failureReason: err.message });
		return false;
	}
};

const addTask = async ({ workspaceId }, policy, startDate) => {
	log.i(TAG, `[${workspaceId}] [${policy.policyType}] 워커 처리 시작`);
	const results = {
		totalCount: 0,
		successCount: 0,
		failedCount: 0,
	};
	try {
		const contents = await contentModel.findExpiredContentByWorkspaceId(policy, workspaceId, startDate);
		log.i(TAG, `[${workspaceId}] Target File Count : ${contents.length}`);

		const contentIds = contents.map(content => content.contentId);
		const files = await transcribeResultModel.findFileKeyByContentIds(contentIds);
		log.i(TAG, `[${workspaceId}] Target File Key Count : ${files.length}`);

		if (files.length === 0) {
			log.i(TAG, `[${workspaceId}] No Target File`);
			return results;
		}
		const fileMap = new Map(files.map(file => [file.contentId, file.fileKey]));

		results.totalCount = files.length;

		for (const content of contents) {
			const { contentId, creatorId } = content;
			const fileKey = fileMap.get(contentId);

			const isExist = await lifeCycleModel.findLifeCycleTask(workspaceId, policy, contentId);
			if (isExist) {
				log.i(TAG, `[${workspaceId}] [${contentId}] [${fileKey}] 이미 처리된 Task 입니다.`);
				results.totalCount--;
				continue;
			}

			const lifeCycleTask = await lifeCycleModel.createLifeCycleTask(workspaceId, policy, contentId);
			const result = await worker({
				workspaceId,
				contentId,
				creatorId,
				fileKey,
				lifeCycleTaskId: lifeCycleTask.id,
			});

			if (result) results.successCount++;
			else results.failedCount++;
		}

		log.i(TAG, `[${workspaceId}] [${policy.policyType}] 워커 처리 완료`);

		return results;
	} catch (err) {
		log.e(TAG, `[${workspaceId}] [${policy.policyType}]오류 발생 --> ${err.message}`);
		return results;
	}
};

export default addTask;
