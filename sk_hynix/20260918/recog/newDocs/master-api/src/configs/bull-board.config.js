import { Queue } from 'bullmq';
import QueueLegacy from 'bull';
import { createBullBoard } from '@bull-board/api';
import { BullMQAdapter } from '@bull-board/api/bullMQAdapter';
import { BullAdapter } from '@bull-board/api/bullAdapter';
import { ExpressAdapter } from '@bull-board/express';
import transcribeEngineModel from '../models/transcribeEngine.model.js';
import { createRedisCluster, createLegacyRedisClientConfig, isRedisCluster } from '../utils/redis/connect.util.js';

/**
 * Bull Board 설정
 * Bull과 BullMQ 큐를 모두 모니터링할 수 있도록 설정
 *
 * Redis 연결 정보는 환경변수에서 읽어옵니다:
 * - Cluster 환경: REDIS_CLUSTER_HOSTS, REDIS_CLUSTER_PASSWORD
 * - Legacy 환경: REDIS_HOST, REDIS_PORT, REDIS_PASS
 *
 * 주의: 여러 Docker 인스턴스/PM2 클러스터 환경에서
 * - 모든 인스턴스가 같은 Redis를 사용하므로 동일한 큐 데이터를 볼 수 있습니다
 * - 각 인스턴스마다 Bull Board가 실행되지만, 모니터링하는 큐는 동일합니다
 * - 환경변수 ENABLE_BULL_BOARD로 특정 인스턴스에서만 활성화 가능
 */
const setupBullBoard = async () => {
	// 환경변수로 Bull Board 활성화 여부 제어 (선택사항)
	if (process.env.ENABLE_BULL_BOARD === 'false') {
		log.i('[BullBoard] Disabled by ENABLE_BULL_BOARD environment variable');
		return null;
	}
	const serverAdapter = new ExpressAdapter();
	serverAdapter.setBasePath(`/admin/queues`);

	const queues = [];

	// Redis 환경에 따라 큐 생성 방식 결정
	const isCluster = isRedisCluster();

	// Redis 연결을 한 번만 생성하여 재사용 (효율성 향상)
	let sharedConnection = null;
	let redisConfig = null;

	if (isCluster) {
		// Cluster 환경: 연결을 한 번만 생성
		sharedConnection = createRedisCluster();
		log.i('[BullBoard] Created shared Redis Cluster connection');
	} else {
		// Legacy 환경: 설정을 한 번만 생성
		redisConfig = createLegacyRedisClientConfig();
		log.i('[BullBoard] Created shared Redis Legacy config');
	}

	// 고정 큐들 추가
	const fixedQueues = [
		'normalize',
		'llm',
		'lifecycle',
		'lifecycleInit',
		'demo',
		'recycle',
		'contact-recycle',
		'reminder',
	];

	for (const queueName of fixedQueues) {
		try {
			if (isCluster) {
				// BullMQ 큐 (Cluster 환경) - 공유 연결 사용
				// 큐 이름 형식: {{tag}} (cluster.util.js 참고)
				const formattedName = `{{${queueName}}}`;
				const queue = new Queue(formattedName, { connection: sharedConnection });
				queues.push(new BullMQAdapter(queue));
				log.i(`[BullBoard] Added BullMQ queue: ${formattedName}`);
			} else {
				// Bull 큐 (Legacy 환경) - 공유 설정 사용
				const queue = new QueueLegacy(queueName, redisConfig);
				queues.push(new BullAdapter(queue));
				log.i(`[BullBoard] Added Bull queue: ${queueName}`);
			}
		} catch (err) {
			log.e(`[BullBoard] Failed to add queue ${queueName}: ${err.message}`);
		}
	}

	// 동적 recog 큐들 추가
	try {
		const tags = await transcribeEngineModel.getTranscribeEngineTag();
		const recogQueueNames = tags.map(item => `recog-${item.tag}`);

		for (const queueName of recogQueueNames) {
			try {
				if (isCluster) {
					// BullMQ 큐 (Cluster 환경) - 공유 연결 사용
					const formattedName = `{{${queueName}}}`;
					const queue = new Queue(formattedName, { connection: sharedConnection });
					queues.push(new BullMQAdapter(queue));
					log.i(`[BullBoard] Added BullMQ recog queue: ${formattedName}`);
				} else {
					// Bull 큐 (Legacy 환경) - 공유 설정 사용
					const queue = new QueueLegacy(queueName, redisConfig);
					queues.push(new BullAdapter(queue));
					log.i(`[BullBoard] Added Bull recog queue: ${queueName}`);
				}
			} catch (err) {
				log.e(`[BullBoard] Failed to add recog queue ${queueName}: ${err.message}`);
			}
		}
	} catch (err) {
		log.e(`[BullBoard] Error adding recog queues: ${err.message}`);
	}

	// Bull Board 생성
	createBullBoard({
		queues,
		serverAdapter,
	});

	log.i(`[BullBoard] Initialized with ${queues.length} queues`);

	return serverAdapter;
};

export default setupBullBoard;
