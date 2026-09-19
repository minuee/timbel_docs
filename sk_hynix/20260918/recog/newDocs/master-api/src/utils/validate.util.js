import contentModel from '../models/content.model.js';
import { HttpError } from '../handlers/error.handler.js';
import { isAfter, isValid, toDate } from './date.util.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';

const SortConfig = {
	domain: {
		contact: {
			fields: ['nickName', 'email', 'position', 'department', 'createAt', 'updateAt'],
			defaultField: 'nickName',
			defaultDirection: 'asc',
		},
	},
	direction: ['asc', 'desc'],
	paging: {
		default: {
			page: 1,
			take: 0, // 0은 모든 데이터 조회
		},
	},
};
class validateUtil {
	constructor() {
		this.sortConfig = SortConfig;
	}

	isMeetingTimeData(data) {
		const format = 'YYYYMMDDHHmm';
		const { meetingStartTime, meetingEndTime } = data;
		if (!meetingStartTime) {
			throw new HttpError(1000);
		}

		if (!isValid(meetingStartTime, format)) {
			throw new HttpError(1117);
		}

		if (meetingEndTime) {
			if (!isValid(meetingEndTime, format)) throw new HttpError(1117);
			data.meetingEndTime = toDate(format, meetingEndTime);
		}

		data.meetingStartTime = toDate(format, meetingStartTime);

		return true;
	}

	async checkDuplicateMobileRecordContent(creatorId, fileName) {
		const content = await contentModel.getMobileRecordContentByCreatorIdAndFileName(creatorId, fileName);
		if (content) {
			throw new HttpError(1133);
		}
	}

	sortValidate(sort, domain) {
		if (!this.sortConfig.domain[domain].fields.includes(sort)) {
			throw new HttpError(1000, `sort은 ${this.sortConfig.domain[domain].fields.join(', ')} 중에 선택해주세요.`);
		}
	}

	sortDirectionValidate(direction) {
		if (!this.sortConfig.direction.includes(direction)) {
			throw new HttpError(1000, `direction은 ${this.sortConfig.direction.join(', ')} 중에 선택해주세요.`);
		}
	}

	// 이메일 형식 검증
	emailRegexValidate(email) {
		const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
		if (!emailRegex.test(email)) {
			throw new HttpError(1118);
		}
	}

	isValidPeriod(type) {
		if (type === 'today') return true;

		const [number, unit] = type.match(/^(\d+)?(week|month)$/)?.slice(1) || [];
		if (!unit) return false;

		const isValidUnit = ['week', 'month'].includes(unit);
		const isValidNumber = !number || parseInt(number) > 0;

		return isValidUnit && isValidNumber;
	}

	// 컨텐츠 조회 옵션
	parseContentsQueryOptions(query) {
		let { limit = 0, date = null, contentFilter = Enums.ContentFilter.ALL, statusFilter = null } = query;
		let options = { ...query };

		options['take'] = isNaN(limit) ? 0 : parseInt(limit, 10);
		options['contentFilter'] = contentFilter;

		const contentFilterValues = Object.values(Enums.ContentFilter);
		if (!contentFilterValues.includes(contentFilter)) {
			throw new HttpError(1000, `contentFilter는 ${contentFilterValues.join(', ')} 중 하나여야 합니다.`);
		}

		if (date) {
			const isValidFormat = /^\d{8}$/.test(date);
			if (!isValidFormat) {
				throw new HttpError(1117);
			}

			const year = parseInt(date.substring(0, 4), 10);
			const month = parseInt(date.substring(4, 6), 10);
			const day = parseInt(date.substring(6, 8), 10);

			const monthStr = String(month).padStart(2, '0');
			const dayStr = String(day).padStart(2, '0');

			options['startDate'] = new Date(`${year}-${monthStr}-${dayStr}T00:00:00.000+09:00`);
			options['endDate'] = new Date(`${year}-${monthStr}-${dayStr}T23:59:59.999+09:00`);
		}

		if (statusFilter) options['statusFilter'] = statusFilter;

		return options;
	}

	validateMagicByte({ buffer, mimetype }) {
		if (!buffer || buffer.length < 4) return false;

		const magicBytes = buffer.slice(0, 4);
		log.i('mimetype', mimetype);

		// 각 이미지 타입별 매직 바이트 검증
		switch (mimetype) {
			case 'image/jpeg':
			case 'image/jpg':
				return magicBytes[0] === 0xff && magicBytes[1] === 0xd8;
			case 'image/png':
				return (
					magicBytes[0] === 0x89 && magicBytes[1] === 0x50 && magicBytes[2] === 0x4e && magicBytes[3] === 0x47
				);
			case 'image/gif':
				return (
					magicBytes[0] === 0x47 && magicBytes[1] === 0x49 && magicBytes[2] === 0x46 && magicBytes[3] === 0x38
				);
			case 'image/bmp':
				return magicBytes[0] === 0x42 && magicBytes[1] === 0x4d;
			default:
				return false;
		}
	}
}

export default new validateUtil();
