import { getDate } from './date.util.js';

export const getContentsRegistrationStats = contents => {
	const { record, upload, recordDuration, uploadDuration, total } = contents.reduce(
		(acc, { isRecord, duration }) => {
			if (isRecord) {
				acc.record++;
				acc.recordDuration += duration;
			} else {
				acc.upload++;
				acc.uploadDuration += duration;
			}
			acc.total++;
			return acc;
		},
		{
			record: 0,
			upload: 0,
			recordDuration: 0,
			uploadDuration: 0,
			total: 0,
		}
	);

	return {
		registrationStats: {
			record,
			upload,
			total,
		},
		durationStats: {
			unit: 'ms',
			recordDuration,
			uploadDuration,
			total: recordDuration + uploadDuration,
		},
	};
};

export const getDownloadStats = downloadHistory => {
	return downloadHistory.reduce(
		(acc, history) => {
			if (history.type === 'MEDIA_FILE') acc.media++;
			else acc.document++;
			acc.total++;
			return acc;
		},
		{
			media: 0,
			document: 0,
			total: 0,
		}
	);
};

export const getStatisticsByType = (contents, type, dateRange, isMonthPeriod = false) => {
	if (type === 'today') return getContentsByHourStats(contents);
	else {
		return getContentsByDateStats(contents, dateRange, isMonthPeriod);
	}
};

export const getContentsByDateStats = (contents, dateRange, isMonthPeriod = false) => {
	const start = new Date(dateRange.startDate);
	const end = new Date(dateRange.endDate);
	const dailyStats = {};

	const current = new Date(start);
	while (current <= end) {
		const dateKey = current.toISOString().split('T')[0];
		dailyStats[dateKey] = {
			record: 0,
			upload: 0,
		};
		current.setDate(current.getDate() + 1);
	}

	if (isMonthPeriod) {
		contents.forEach(content => {
			const dateKey = new Date(content.createAt).toISOString().split('T')[0];
			const stat = dailyStats[dateKey];
			if (stat) {
				if (content.isRecord) {
					stat.record += content.duration || 0;
				} else {
					stat.upload += content.duration || 0;
				}
			}
		});
	} else {
		contents.forEach(content => {
			const date = new Date(content.createAt);
			const dateKey = date.toISOString().split('T')[0];

			if (dailyStats[dateKey]) {
				if (content.isRecord) {
					dailyStats[dateKey].record += content.duration;
				} else {
					dailyStats[dateKey].upload += content.duration;
				}
			}
		});
	}

	return dailyStats;
};

export const getContentsByHourStats = contents => {
	const hourlyStats = {};

	for (let i = 0; i < 24; i++) {
		const hour = i.toString().padStart(2, '0');
		hourlyStats[`${hour}:00`] = {
			record: 0,
			upload: 0,
		};
	}

	contents.forEach(content => {
		const date = new Date(content.createAt);
		const hour = date.getHours().toString().padStart(2, '0');
		const timeKey = `${hour}:00`;

		if (content.isRecord) {
			hourlyStats[timeKey].record += content.duration;
		} else {
			hourlyStats[timeKey].upload += content.duration;
		}
	});

	return hourlyStats;
};

export const getReSummaryStats = reSummaryHistory => {
	return reSummaryHistory.reduce(
		(acc, history) => {
			acc[history.summarySize.toLowerCase()]++;
			acc.total++;
			return acc;
		},
		{
			large: 0,
			medium: 0,
			small: 0,
			total: 0,
		}
	);
};

export const getRecordChartDataByHour = (contents, targetDate = Date.now()) => {
	const hourlyStats = Array(24).fill(0);
	const formattedDate = getDate(targetDate);

	contents.forEach(content => {
		const date = new Date(content.createAt);
		const hour = date.getHours();

		if (getDate(targetDate) === getDate(content.createAt)) {
			hourlyStats[hour] += content.duration;
		}
	});

	return {
		date: formattedDate,
		datas: hourlyStats,
	};
};

export const getRecordChartDataByWeek = (contents, dateRange) => {
	const start = new Date(dateRange.startDate);
	const end = new Date(dateRange.endDate);
	const dailyStats = [];

	const contentsByDate = new Map();
	contents.forEach(content => {
		if (!content.isRecord) return;
		const dateKey = getDate(content.createAt);
		if (!contentsByDate.has(dateKey)) {
			contentsByDate.set(dateKey, []);
		}
		contentsByDate.get(dateKey).push(content);
	});

	const current = new Date(start);
	while (current <= end) {
		const dateKey = current.toISOString().split('T')[0];
		const dateContents = contentsByDate.get(getDate(dateKey)) || [];
		dailyStats.push(getRecordChartDataByHour(dateContents, dateKey));
		current.setDate(current.getDate() + 1);
	}

	return dailyStats;
};

export const getRecordChartDataByMonth = (contents, dateRange) => {
	const start = new Date(dateRange.startDate);
	const end = new Date(dateRange.endDate);

	const statsMap = new Map();
	const dailyStats = [];

	const current = new Date(start);
	while (current <= end) {
		const dateKey = current.toISOString().split('T')[0];
		const statItem = {
			date: dateKey,
			data: 0,
		};
		dailyStats.push(statItem);
		statsMap.set(dateKey, statItem);
		current.setDate(current.getDate() + 1);
	}

	contents.forEach(content => {
		if (!content.isRecord || !content.duration) return;

		const dateKey = new Date(content.createAt).toISOString().split('T')[0];
		const statItem = statsMap.get(dateKey);

		if (statItem) {
			statItem.data += content.duration;
		}
	});
	return dailyStats;
};

export const getStatisticsRecordChartData = (contents, type, dateRange, isMonthPeriod = false) => {
	if (type === 'today') return [getRecordChartDataByHour(contents)];
	else if (type.indexOf('week') !== -1) return getRecordChartDataByWeek(contents, dateRange);
	else {
		if (isMonthPeriod) {
			return getRecordChartDataByMonth(contents, dateRange);
		}
		return getRecordChartDataByMonth(contents, dateRange);
	}
};

export default {
	getDownloadStats,
	getContentsRegistrationStats,
	getStatisticsByType,
	getReSummaryStats,
	getStatisticsRecordChartData,
};
