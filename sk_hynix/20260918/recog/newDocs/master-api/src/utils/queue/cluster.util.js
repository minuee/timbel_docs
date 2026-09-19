import { Queue, Worker, QueueEvents } from 'bullmq';
import { createRedisCluster } from '../redis/connect.util.js';

class QueueClusterUtil {
	constructor(tag = 'recog', worker, concurrency = 1, isRetry = false) {
		this.queueName = `{{${tag}}}`;
		this.TAG = `[[${process.env.INSTANCE_ID ?? '0'}] QueueClusterUtil : ${tag}] `;

		// Redis Cluster 연결 (혹은 단일 노드로 바꿀 수 있음)
		this.connection = createRedisCluster();

		this.queue = new Queue(this.queueName, {
			connection: this.connection,
		});

		this.queueEvents = new QueueEvents(this.queueName, {
			connection: this.connection,
		});

		this.workerFunction = worker;
		log.i(this.TAG, `created with concurrency ${concurrency}`);

		this.worker = new Worker(
			this.queueName,
			async job => {
				try {
					log.i(`Processing job with ID: ${job.id}`);
					if (job?.data?.isPrintStatus) await this.printQueueStatus(this.queueName);
					await this.workerFunction(job.data);
					log.i(`Job with ID ${job.id} processed successfully`);
				} catch (err) {
					log.e(this.TAG, `Error processing task ${job.data?.ticketId}: ${err.message}`);
					log.e(this.TAG, `isRetry: ${isRetry}, err.errorCode: ${err.errorCode}`);
					if (isRetry && err.errorCode !== 'E2104') {
						throw err;
					}
				}
			},
			{
				connection: this.connection,
				concurrency: Number(concurrency),
			}
		);

		// completed 이벤트 연결
		this.queueEvents.on('completed', async ({ jobId }) => {
			log.i(this.TAG, `Task ${jobId} completed`);
			const job = await this.queue.getJob(jobId);

			if (job?.data?.isPrintStatus) {
				await this.printQueueStatus(this.queueName);
			}

			if ((await this.queue.count()) === 0) {
				log.i(this.TAG, 'All tasks completed: Queue is idle');
			}
		});

		this.checkIncompleteTasks();
	}

	async isTaskRunning(taskId) {
		const job = await this.queue.getJob(taskId);
		if (!job) return false;
		// 잡 레코드 존재 != 실행 중. failed(removeOnFail:false로 보존)/완료 잔여 잡이
		// 재요약을 영구 차단하지 않도록 실제 in-flight 상태일 때만 true.
		return (await job.isActive()) || (await job.isWaiting()) || (await job.isDelayed());
	}

	async printQueueStatus(queueName = this.queueName) {
		const counts = await this.queue.getJobCounts();
		log.i(`
-------- ${queueName} Queue Status --------
Waiting     : ${counts.waiting}
Active      : ${counts.active}
Completed   : ${counts.completed}
Failed      : ${counts.failed}
Delayed     : ${counts.delayed}
---------------------------------------------
`);
	}

	async addTask(task, delay = 300) {
		try {
			const { taskId } = task;
			task.isPrintStatus = process.env.IS_QUEUE_LOGS || true;

			const existingJob = await this.queue.getJob(taskId);

			if (existingJob) {
				if (
					(await existingJob.isActive()) ||
					(await existingJob.isWaiting()) ||
					(await existingJob.isDelayed())
				) {
					log.e(this.TAG, `Task with id ${taskId} is already running or waiting.`);
					return false;
				}
				// 실행 중이 아닌 스테일 잡(failed/완료 잔여)은 동일 jobId 재등록을 막으므로 제거 후 재등록.
				// (사용자가 재요약을 명시했으므로 옛 failed 기록은 새 실행으로 대체)
				await existingJob.remove();
			}

			await this.queue.add(taskId || 'task', task, {
				delay,
				jobId: taskId,
				removeOnFail: false,
				removeOnComplete: true,
			});

			if (task.isPrintStatus) await this.printQueueStatus(this.queueName);
			return true;
		} catch (err) {
			log.e(this.TAG, `Error adding task ${task?.ticketId}: ${err.message}`);
			return false;
		}
	}

	async checkIncompleteTasks() {
		try {
			const waitingJobs = await this.queue.getWaiting();
			const activeJobs = await this.queue.getActive();

			if (waitingJobs.length > 0 || activeJobs.length > 0) {
				log.i(this.TAG, `Resuming ${waitingJobs.length} waiting jobs and ${activeJobs.length} active jobs.`);
			}
		} catch (err) {
			log.e(this.TAG, `Error checking incomplete tasks: ${err.message}`);
		}
	}

	async cancelTask(taskId) {
		try {
			const job = await this.queue.getJob(taskId);
			if (job) {
				await job.remove();
				log.i(this.TAG, `Task ${taskId} removed`);
				return true;
			}
			return false;
		} catch (err) {
			log.e(this.TAG, `Error removing task ${taskId}: ${err.message}`);
			return false;
		}
	}

	async addFastTask(task) {
		try {
			const { taskId } = task;
			task.isPrintStatus = false;

			const job = await this.queue.getJob(taskId);
			if (job) await job.remove();

			await this.queue.add(taskId || 'fast-task', task, {
				jobId: taskId,
				removeOnFail: false,
				removeOnComplete: true,
			});
		} catch (err) {
			log.e(this.TAG, `Error adding fast task ${task?.ticketId}: ${err.message}`);
			return false;
		}
	}

	async addBulkTasks(tasks, name = 'default') {
		try {
			log.i(this.TAG, `Adding ${tasks.length} tasks to ${name} queue`);
			const jobsToAdd = [];

			for (const task of tasks) {
				const jobId = task.ticketId;

				const existingJob = await this.queue.getJob(jobId);
				if (existingJob) await existingJob.remove();

				jobsToAdd.push({
					data: task,
					opts: {
						jobId,
						removeOnFail: false,
						removeOnComplete: true,
					},
				});
			}

			if (jobsToAdd.length > 0) {
				log.i(this.TAG, `Added ${JSON.stringify(jobsToAdd)} tasks to ${name} queue`);
				await this.queue.addBulk(jobsToAdd);
			}

			return true;
		} catch (err) {
			log.e(this.TAG, `Error adding fast tasks: ${err.message}`);
			return false;
		}
	}

	async getJob(jobId) {
		return await this.queue.getJob(jobId);
	}
}

export default QueueClusterUtil;
