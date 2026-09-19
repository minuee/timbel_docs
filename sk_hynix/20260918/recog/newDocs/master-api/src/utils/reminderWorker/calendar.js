import notify from '../../utils/notify.util.js';
import convert from '../../utils/convert/index.js';
import calendarModel from '../../models/calendar.model.js';
import { QueueError } from '../../handlers/error.handler.js';
import { toKoreanDateTimeSimple } from '../../utils/date.util.js';

const TAG = '[ReminderWorker] ';

const generatePayload = (user, calendar) => {
	const { email, nickName } = user;
	const { title, summary, meetingStartDate, reminderMinutes } = calendar;
	const { HOME_URL } = process.env;
	const homeLink = `${HOME_URL}/home`;

	log.i(TAG, `reminderEmail Send`);

	const summaryText = !summary ? '### 요약 내용이 없습니다.' : summary;
	const payload = {
		data: {
			email,
			title,
			reminderMinutes,
			meetingStartDate: toKoreanDateTimeSimple(meetingStartDate),
			summary: convert.convertSummaryToHtml(summaryText),
			homeLink,
		},
		channel: 'email',
		title: `[AI회의록 리마인더] ${nickName}(${email})님의 '${title}' 일정이 ${reminderMinutes}분 후에 시작됩니다.`,
		type: 'REMINDER',
	};
	return payload;
};

const worker = async ({ calendarId, user }) => {
	log.i(TAG, `calendarId : ${calendarId}, user : ${JSON.stringify(user)}`);
	try {
		const calendar = await calendarModel.getCalendarById(calendarId);
		if (!calendar) throw QueueError(2107);
		log.i(TAG, `calendar : ${JSON.stringify(calendar)}`);
		const payload = generatePayload(user, calendar);
		await notify.reminderEmail(user, payload);
	} catch (err) {
		throw err;
	}
};

export default worker;
