import { HttpError } from '../handlers/error.handler.js';
import { Enums } from '@timbel-timblo-onpremise/prisma';
// 언어별 접두사 설정
export const LANG_PREFIX_CONFIG = {
	ko: '참석자',
	en: 'participant',
	none: 'participant', // 기본값
};

class attendeeUtil {
	// 언어 코드에 해당하는 접두사 반환 함수
	getLangPrefix(langCode = Enums.SupportLang.none) {
		return LANG_PREFIX_CONFIG[langCode];
	}

	// 참석자 validation Controller
	async validateAttendee(body) {
		try {
			// body 객체에 필드가 존재하는지 확인
			const hasPidField = 'pid' in body;
			const hasDisplayNameField = 'displayName' in body;
			// 실제 값 (필드가 없으면 undefined가 됨)
			const pidValue = body.pid;
			const displayNameValue = body.displayName;

			// 에러 조건 1: pid 필드와 displayName 필드가 모두 존재하지 않는 경우
			if (!hasPidField && !hasDisplayNameField) {
				throw new HttpError(
					1000, // 필드 부재 관련 에러 코드 (기존 로직 참고)
					'pid 또는 displayName 필드 중 하나는 반드시 포함되어야 합니다.'
				);
			}

			// 에러 조건 2: 두 필드가 모두 존재하고, 둘 다 null/undefined가 아닌 값을 가지는 경우
			if (hasPidField && hasDisplayNameField && pidValue != null && displayNameValue != null) {
				throw new HttpError(
					1113, // 동시 값 존재 관련 에러 코드 (기존 로직 참고)
					'pid와 displayName은 동시에 값을 가질 수 없습니다.'
				);
			}

			// displayName에 대한 추가 유효성 검사 (필드가 존재하고 값이 null/undefined가 아닐 때만 수행)
			if (hasDisplayNameField && displayNameValue != null) {
				const displayNameTrimmed = String(displayNameValue).trim();
				const displayNameLower = displayNameTrimmed.toLowerCase();
				const disablePrefixList = Object.values(LANG_PREFIX_CONFIG)
					.map(prefix => prefix.toLowerCase())
					.filter(prefix => prefix);

				const nameRegex = /^[ㄱ-ㅎㅏ-ㅣ가-힣a-zA-Z0-9 ]{1,20}$/;

				if (!nameRegex.test(displayNameTrimmed)) {
					throw new HttpError(1506); // 참석자 이름 유효성 검사 에러
				}

				for (const prefix of disablePrefixList) {
					if (displayNameLower.includes(prefix)) {
						throw new HttpError(1507, prefix); // 참석자 이름 예약어 검사 에러
					}
				}

				if (displayNameTrimmed.includes('  ')) {
					throw new HttpError(1508); // 참석자 이름 공백 검사 에러
				}
			}
		} catch (err) {
			throw err;
		}
	}
}

export default new attendeeUtil();
