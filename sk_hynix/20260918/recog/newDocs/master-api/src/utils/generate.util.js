import cryptoV1 from 'crypto';
import { randomInt } from 'crypto';
import { toDate } from './date.util.js';

const defaultBucketPath = process.env.DEFAULT_BUCKET_PATH || '';

class GenerateUtil {
	getRandomDelay(minMilliseconds, maxMilliseconds) {
		return randomInt(minMilliseconds, maxMilliseconds + 1);
	}

	delayWithRandom(engine = 'RTZ') {
		const delay = this.getRandomDelay(0, 1500);
		log.i('[delayWithRandom]', `${engine} 호출 무작위 지연 ${delay / 1000}초 이후 수행`);

		return new Promise(resolve => setTimeout(resolve, delay));
	}
	fileKey() {
		const randomStr = cryptoV1.randomBytes(10).toString('base64url');
		const timeStr = ((Date.now() / 1000) | 0).toString(36);
		return `${timeStr}-${randomStr}`.substring(0, 32);
	}

	keyFromString(str, option = 'hex') {
		const hash = cryptoV1.createHash('sha256');
		hash.update(str);
		return defaultBucketPath + hash.digest(option);
	}

	ticketId() {
		return cryptoV1
			.randomBytes(15)
			.toString('base64')
			.replace(/[^a-zA-Z0-9]/g, '')
			.substring(0, 20);
	}

	recordStartTime(title, titleFormat) {
		if (title.indexOf(titleFormat) !== 0) return null;

		const regex = /A\.Biz_[wm]_rec_(\d{8})_(\d{6})\.[a-zA-Z0-9]+$/;
		const match = title.match(regex);

		if (match) return toDate('YYYYMMDDHHmmss', match[1], match[2]);
		return null;
	}

	meetingTime(data) {
		let { duration, title, createAt, isMobile, creationTime } = data;
		data.isParseDate = true;

		const validDuration = duration && !isNaN(duration) ? duration : 0;
		log.i('[GenerateUtil : meetingTime] validDuration : ', validDuration);

		const recordStartTime = this.recordStartTime(title, isMobile ? 'A.Biz_m_rec_' : 'A.Biz_w_rec_');

		if (recordStartTime) {
			data.startTime = recordStartTime;
			data.endTime = new Date(data.startTime.getTime() + validDuration);
		} else if (creationTime) {
			data.endTime = new Date(creationTime);
			data.startTime = new Date(data.endTime.getTime() - validDuration);
			log.i('[GenerateUtil : meetingTime] creationTime : ', creationTime);
		} else if (createAt) {
			data.startTime = new Date(createAt);
			data.endTime = new Date(data.startTime.getTime() + validDuration);
			data.isParseDate = false;
			log.i('[GenerateUtil : meetingTime] createAt : ', createAt);
		} else {
			data.startTime = new Date();
			data.endTime = new Date(data.startTime.getTime() + validDuration);
			data.isParseDate = false;
		}

		return {
			startTime: data.startTime,
			endTime: data.endTime,
		};
	}

	uuid() {
		return cryptoV1.randomUUID().toString();
	}
}

export default new GenerateUtil();
