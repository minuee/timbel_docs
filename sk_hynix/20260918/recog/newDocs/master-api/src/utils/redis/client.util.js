import generate from '../generate.util.js';
import { createClient } from 'redis';

class RedisClientUtil {
	constructor() {
		this.EXPIRE_TIME = process.env.CACHE_EXP || 3 * 60 * 60;

		const config = {
			socket: {
				port: process.env.REDIS_PORT,
				host: process.env.REDIS_HOST,
			},
			password: process.env.REDIS_PASS,
			legacyMode: false,
		};

		log.i('[RedisConfig]', config);
		this.client = createClient(config);

		// error 리스너가 이미 추가되어 있으면 제거 후 재추가 (중복 방지)
		this.client.removeAllListeners('error');
		this.client.on('error', err => {
			log.e('[RedisClientUtil] ❌ Client Error:', err.message);
		});

		this.connectWithRetry();
	}

	async connectWithRetry(retries = 5) {
		for (let i = 0; i < retries; i++) {
			try {
				await this.client.connect();
				log.i('[RedisClientUtil] ✅ Redis Connection Success');
				return;
			} catch (err) {
				log.e(`[RedisClientUtil] ❌ Redis connection failed (attempt ${i + 1}/${retries}):`, err.message);
				if (i < retries - 1) {
					await generate.delayWithRandom('RedisClientUtil');
				} else {
					log.e('[RedisClientUtil] ❌ All retries exhausted. Redis connection failed permanently.');
				}
			}
		}
	}

	async get(key) {
		const result = await this.client.get(key);
		return JSON.parse(result);
	}

	setTmpFileAndAutoRemove(key, tmpFile) {
		this.set(`driveTmpFileCache:${key}`, tmpFile);
		setTimeout(() => {
			log.d('[setTmpFileAndAutoRemove] TmpFile Remove => ', key);
			tmpFile.removeCallback();
		}, this.EXPIRE_TIME * 1000);
	}

	set(key, value, ex = this.EXPIRE_TIME) {
		this.client.set(key, JSON.stringify(value), { EX: ex });
	}
}

export default new RedisClientUtil();
