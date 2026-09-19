import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc.js';
import timezone from 'dayjs/plugin/timezone.js';
import { HttpError } from '../handlers/error.handler.js';
import customParseFormat from 'dayjs/plugin/customParseFormat.js';

dayjs.extend(customParseFormat);
dayjs.extend(utc);
dayjs.extend(timezone);

export const isAfter = (date1, date2) => {
	if (!date1 || !date2) return false;
	return dayjs(date1).isAfter(date2);
};

export const isSame = (date1, date2) => {
	if (!date1 || !date2) return false;
	return dayjs(date1).isSame(date2);
};

export const isValid = (date, format = 'YYYYMMDDHHmmss') => {
	if (!date) return false;
	return dayjs(date, format, true).isValid();
};

export const isValidDate = (startDate, endDate) => {
	const regex = /^\d{8}$/;
	const isValidDate = { startDate: regex.test(startDate), endDate: regex.test(endDate) };

	if (!isValidDate.startDate || !isValidDate.endDate) {
		throw new HttpError(1110);
	}

	return isValidDate;
};

export const isDate = date => {
	if (!date) return false;
	return dayjs(date).isValid();
};

export const parse = (dateString, format = 'HH:mm:ss') => {
	if (!dateString) return null;
	return dayjs(dateString, format).toDate();
};

export const toDate = (format = 'YYYYMMDDHHmmss', ...matches) => {
	if (!matches) return false;
	return dayjs(matches.join(''), format).toDate();
};

export const getDateTime = (dateString, format = 'YYYY-MM-DD HH:mm:ss') => {
	if (!dateString) return null;
	return dayjs(dateString).format(format);
};

export const getSearchRange = type => {
	const today = dayjs().utc();
	let startDate, endDate;

	if (type === 'today') {
		return {
			startDate: today.startOf('day').subtract(9, 'hour').toISOString(),
			endDate: today.endOf('day').subtract(9, 'hour').toISOString(),
		};
	}

	const [number, unit] = type.match(/^(\d+)?(week|month)$/)?.slice(1) || [];
	const count = number ? parseInt(number) : 1;

	if (unit === 'week') {
		startDate = today.subtract(count * 7 - 1, 'day').startOf('day');
		endDate = today.endOf('day');
	} else if (unit === 'month') {
		startDate = today.subtract(count, 'month').startOf('day').add(1, 'day');
		endDate = today.endOf('day');
	}

	if (startDate && endDate) {
		return {
			startDate: startDate.add(15, 'hour').toISOString(),
			endDate: endDate.add(15, 'hour').toISOString(),
		};
	}
};

export const getDelayUntil = (afterDays, hour) => {
	if (afterDays < 1) throw new Error('afterDays 값은 1 이상이어야 합니다.');
	if (hour < 0 || hour > 24) throw new Error('hour 값은 0부터 24 사이여야 합니다.');

	const zone = 'Asia/Seoul';

	const now = dayjs().tz(zone);
	const target = now.add(afterDays, 'day').startOf('day').add(hour, 'hour');

	return Math.max(0, target.valueOf() - now.valueOf());
};

export const getDelayUntilMinutes = (minutes, { meetingStartDate }) => {
	if (minutes < 0) throw new Error('minutes 값은 0 이상이어야 합니다.');
	if (!meetingStartDate) throw new Error('meetingStartDate 값이 필요합니다.');

	const zone = 'Asia/Seoul';
	const now = dayjs().tz(zone);

	const reminderTime = dayjs(meetingStartDate).tz(zone).subtract(minutes, 'minute');

	return Math.max(0, reminderTime.valueOf() - now.valueOf());
};

export const isBeforeMeetingStartDate = (minutes, { meetingStartDate }) => {
	if (minutes === 0) return false;
	return getDelayUntilMinutes(minutes, { meetingStartDate }) <= 0;
};
export const getDate = (date, format = 'YYYY-MM-DD') => {
	return dayjs(date).format(format);
};

export const getDateOptions = (startDate, endDate) => {
	return {
		startDate: {
			year: parseInt(startDate.substring(0, 4), 10),
			month: parseInt(startDate.substring(4, 6), 10) - 1,
			day: parseInt(startDate.substring(6, 8), 10),
		},
		endDate: {
			year: parseInt(endDate.substring(0, 4), 10),
			month: parseInt(endDate.substring(4, 6), 10) - 1,
			day: parseInt(endDate.substring(6, 8), 10),
		},
	};
};

export const formatDateRange = (startDate, endDate) => {
	if (!startDate || !endDate) {
		throw new HttpError(1000);
	}

	isValidDate(startDate, endDate);

	const start = dayjs(startDate, 'YYYYMMDD').utc().startOf('day').subtract(9, 'hour');
	const end = dayjs(endDate, 'YYYYMMDD').utc().endOf('day').subtract(9, 'hour');

	return {
		startDate: start.toISOString(),
		endDate: end.toISOString(),
	};
};

export const toISOString = (date, utc = true) => {
	if (!date) return null;

	const dayjsDate = dayjs(date);
	if (!dayjsDate.isValid()) return null;

	return utc ? dayjsDate.utc().toISOString() : dayjsDate.toISOString();
};

export const isWithinDateRange = (targetDate, daysBefore = 30, daysAfter = 30) => {
	if (!targetDate) return false;

	const today = dayjs();
	const startDate = today.subtract(daysBefore, 'day');
	const endDate = today.add(daysAfter, 'day');
	const date = dayjs(targetDate);

	return date.isAfter(startDate) && date.isBefore(endDate);
};

export const isWithinMonthRange = (targetDate, monthsBefore = 1, monthsAfter = 1) => {
	if (!targetDate) return false;

	const today = dayjs();
	const startDate = today.subtract(monthsBefore, 'month');
	const endDate = today.add(monthsAfter, 'month');
	const date = dayjs(targetDate);

	return date.isAfter(startDate) && date.isBefore(endDate);
};

export const getWebcalFilterRange = () => {
	const filterMonths = process.env.WEBCAL_FILTER_MONTHS || '1';
	const months = parseInt(filterMonths, 10);
	return Math.max(1, months);
};

export const isWithinWebcalRange = targetDate => {
	if (!targetDate) return false;

	const filterMonths = getWebcalFilterRange();
	return isWithinMonthRange(targetDate, filterMonths, filterMonths);
};

export const toKoreanDateTimeSimple = utcDateString => {
	if (!utcDateString) return null;

	const seoulTime = dayjs(utcDateString).tz('Asia/Seoul');

	return seoulTime.format('YYYY년 M월 D일 A h:mm');
};

export default {
	isAfter,
	isSame,
	toDate,
	isValid,
	getDateTime,
	getSearchRange,
	getDelayUntil,
	formatDateRange,
	toISOString,
	isValidDate,
	isWithinDateRange,
	isWithinMonthRange,
	getWebcalFilterRange,
	isWithinWebcalRange,
	getDelayUntilMinutes,
	isBeforeMeetingStartDate,
	toKoreanDateTimeSimple,
};
