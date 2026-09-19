import ical from 'node-ical';
import { isWithinWebcalRange } from '../../date.util.js';

// https://outlook.office365.com/owa/calendar/7c4d70c64dd5440abbaeacb503671ff2@alibizgroup.com/ea976afcdf2b45aab3a3b4a517e804f713780018115043726529/calendar.ics

const validateWebcalUrlAndProvider = url => {
	const googleRegex =
		/^(https?:\/\/)?(www\.)?calendar\.google\.com\/calendar\/ical\/[^\/]+\/(public|private-[a-f0-9]+)\/basic\.ics$/;

	const outlookRegex = /^https?:\/\/outlook\.office365\.com\/owa\/calendar\/[^\/]+\/[^\/]+\/calendar\.ics$/;

	if (googleRegex.test(url)) {
		return 'GOOGLE';
	} else if (outlookRegex.test(url)) {
		return 'OUTLOOK';
	} else {
		return null;
	}
};

const parseWebcalData = (data, provider) => {
	const keys = Object.keys(data);
	return keys.reduce((acc, key) => {
		const { uid, description, start, summary } = data[key];
		if (uid) {
			// 항상 환경변수 기반으로 날짜 필터링 적용
			const isWithinRange = isWithinWebcalRange(start);

			if (isWithinRange) {
				acc.push({
					uid,
					provider,
					description,
					start,
					summary,
				});
			}
		}
		return acc;
	}, []);
};

export const getWebcalData = async (webcal, timeoutMs = 30000) => {
	try {
		// 타임아웃 설정: Promise.race를 사용하여 무한 대기 방지
		const timeoutPromise = new Promise((_, reject) => {
			setTimeout(() => {
				reject(new Error(`Webcal request timeout after ${timeoutMs}ms: ${webcal.url}`));
			}, timeoutMs);
		});

		const data = await Promise.race([ical.async.fromURL(webcal.url), timeoutPromise]);

		return parseWebcalData(data, webcal.provider);
	} catch (err) {
		if (err.message?.includes('timeout')) {
			log.w('[getWebcalData]', `타임아웃: ${webcal.url}`);
		} else {
			log.e('[getWebcalData]', `오류 발생: ${webcal.url}`, err.message);
		}
		return null;
	}
};

export const validateWebcalAndProvider = async url => {
	try {
		const provider = validateWebcalUrlAndProvider(url);
		if (!provider) {
			return null;
		}
		log.d('[validateWebcalUrlWithParsing]', `validateWebcalUrl : ${url}`);

		const data = await ical.async.fromURL(url);
		if (!data || Object.keys(data).length === 0) {
			return null;
		}

		return provider;
	} catch (err) {
		log.e('[validateWebcalUrlWithParsing]', err);
		return null;
	}
};

export default { validateWebcalAndProvider, getWebcalData };
