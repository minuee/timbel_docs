import contentModel from '../../models/content.model.js';
import lifeCycleModel from '../../models/lifecycle.model.js';
import transcribeResultModel from '../../models/transcribeResult.model.js';

const TAG = '[lifecycleWorker/segment]';

const SECURITY_TEXT = '보안 정책(##DAYS##)으로 인해 기록이 삭제 되었습니다.';

const changeSegmentText = ({ mergedSegments, segments }, { value, unit }) => {
	const text = SECURITY_TEXT.replace('##DAYS##', `${value} ${unit.toLowerCase()}`);

	const newMergedSegments = mergedSegments.map(mergedSegment => {
		return {
			...mergedSegment,
			text,
		};
	});

	const newSegments = segments.map(segment => {
		return {
			...segment,
			text,
		};
	});

	return {
		mergedSegments: newMergedSegments,
		segments: newSegments,
		securityText: text,
	};
};

const worker = async ({ workspaceId, contentId, lifeCycleTaskId, transcribeResult, policy }) => {
	const { fileId } = transcribeResult;
	const WORKER_TAG = `${TAG} [${contentId}] [${fileId}] `;
	try {
		log.i(WORKER_TAG, `워커 시작`);
		await lifeCycleModel.updateLifeCycleTask(lifeCycleTaskId, { processingAt: new Date() });

		const { securityText, ...changeSegments } = changeSegmentText(transcribeResult, policy);
		log.i(WORKER_TAG, `[${workspaceId}] "${securityText}" 문구로 교체 완료`);

		await transcribeResultModel.updateTranscribeResult(fileId, changeSegments);

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
		const transcribeSegments = await transcribeResultModel.findSegmentByContentIds(contentIds);
		log.i(TAG, `[${workspaceId}] Target Segment Count : ${transcribeSegments.length}`);

		if (transcribeSegments.length === 0) {
			log.i(TAG, `[${workspaceId}] No Target Segment`);
			return results;
		}

		results.totalCount = transcribeSegments.length;

		for (const transcribeSegment of transcribeSegments) {
			const { contentId, transcribeResult } = transcribeSegment;

			const isExist = await lifeCycleModel.findLifeCycleTask(workspaceId, policy, contentId);
			if (isExist) {
				log.i(TAG, `[${workspaceId}] [${contentId}] 이미 처리된 Task 입니다.`);
				results.totalCount--;
				continue;
			}

			const lifeCycleTask = await lifeCycleModel.createLifeCycleTask(workspaceId, policy, contentId);
			const result = await worker({
				policy,
				workspaceId,
				contentId,
				transcribeResult,
				lifeCycleTaskId: lifeCycleTask.id,
			});

			if (result) results.successCount++;
			else results.failedCount++;
		}

		log.i(TAG, `[${workspaceId}] [${policy.policyType}] 워커 처리 완료`);

		return results;
	} catch (err) {
		log.e(TAG, `[${workspaceId}] 오류 발생 --> ${err.message}`);
		return results;
	}
};

export default addTask;
