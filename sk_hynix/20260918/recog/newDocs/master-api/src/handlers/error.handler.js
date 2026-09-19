const mappingError = {
	// Default Errors
	400: { code: 400, errorCode: 'E0400', message: 'Bad Request' },
	401: { code: 401, errorCode: 'E0401', message: 'Unauthorized' },
	403: { code: 403, errorCode: 'E0403', message: 'Forbidden' },
	404: { code: 404, errorCode: 'E0404', message: 'Not Found' },
	405: { code: 405, errorCode: 'E0405', message: 'Method Not Allowed' },
	406: { code: 406, errorCode: 'E0406', message: 'Not Acceptable' },
	408: { code: 408, errorCode: 'E0408', message: 'Request Timeout' },
	414: { code: 414, errorCode: 'E0414', message: 'URI Too Long' },
	415: { code: 415, errorCode: 'E0415', message: 'Unsupported Media Type' },
	422: { code: 422, errorCode: 'E0422', message: 'Unprocessable Content' },
	429: { code: 429, errorCode: 'E0429', message: 'Too Many Requests' },
	500: { code: 500, errorCode: 'E0500', message: 'Internal Server Error' },

	// Common Errors (E1xxx)
	1000: { code: 400, errorCode: 'E1000', message: '필수 파라미터가 부족합니다.' },
	1001: { code: 401, errorCode: 'E1001', message: '뷰어 이상의 권한이 필요합니다.' },
	1002: { code: 401, errorCode: 'E1002', message: '편집자 이상의 권한이 필요합니다.' },
	1003: { code: 401, errorCode: 'E1003', message: '소유자 권한이 필요합니다.' },
	1004: { code: 401, errorCode: 'E1004', message: '게스트 권한으로 할 수 없습니다.' },
	1005: { code: 401, errorCode: 'E1005', message: '다운로드 이상의 권한이 필요합니다.' },

	// Content Errors (E2xxx)
	1101: { code: 500, errorCode: 'E2101', message: '콘텐츠 업로드 실패' },
	1102: { code: 500, errorCode: 'E2102', message: 'S3 getObject 호출 실패' },
	1103: { code: 500, errorCode: 'E2103', message: '음성인식 요청 실패' },
	1104: { code: 500, errorCode: 'E2104', message: '음성인식 결과가 없습니다.' },
	1105: { code: 500, errorCode: 'E2105', message: '음성인식 진행중인 파일 입니다.' },
	1106: { code: 500, errorCode: 'E2106', message: '음성인식 중 오류가 발생했습니다.' },
	1107: { code: 500, errorCode: 'E2107', message: '사용 불가능한 엔진 코드입니다.' },
	1108: { code: 500, errorCode: 'E2108', message: '전사 파일이 없습니다.' },
	1109: { code: 500, errorCode: 'E2109', message: '이미지 파일만 업로드 가능합니다.' },
	1110: { code: 400, errorCode: 'E2110', message: '타입이 올바르지 않습니다.' },
	1111: { code: 413, errorCode: 'E2111', message: '휴지통으로 이동된 컨텐츠입니다. 복원 후 요청해주세요.' },
	1112: { code: 501, errorCode: 'E2112', message: '자기 자신은 추가할 수 없습니다.' },
	1113: { code: 400, errorCode: 'E2113', message: '파라미터가 너무 많습니다. 약속된 형태로 구성 및 요청해주세요.' },
	1114: { code: 422, errorCode: 'E2114', message: '현재 전사 및 AI 처리 중인 컨텐츠 입니다.' },
	1115: { code: 423, errorCode: 'E2115', message: '완전히 삭제되어 조회할 수 없는 컨텐츠 입니다.' },
	1116: { code: 400, errorCode: 'E2116', message: '정의되지 않은 권한입니다.' },
	1117: { code: 400, errorCode: 'E2117', message: '날짜 형식이 올바르지 않습니다.' },
	1118: { code: 400, errorCode: 'E2118', message: '이메일 형식이 올바르지 않습니다.' },
	1119: { code: 421, errorCode: 'E2119', message: '전사 처리가 실패하여 조회할 수 없는 컨텐츠입니다.' },
	1120: { code: 434, errorCode: 'E2120', message: '해당 시간대의 음성 기록을 찾을 수 없습니다.' },
	1121: { code: 404, errorCode: 'E2121', message: '아직 전사된 결과가 없습니다. 잠시 후 다시 시도해주세요.' },
	1122: { code: 400, errorCode: 'E2122', message: '원본 파일 정보를 찾을 수 없습니다.' },
	1123: { code: 504, errorCode: 'E2123', message: 'Object Storage 업로드 중 오류 발생' },
	1124: { code: 500, errorCode: 'E2124', message: 'File 데이터 조회 실패' },
	1125: { code: 500, errorCode: 'E2125', message: 'Object Storage 파일 삭제 실패' },
	1126: { code: 500, errorCode: 'E2126', message: '음성 길이 확인이 불가능한 파일 입니다.' },
	1127: { code: 500, errorCode: 'E2127', message: '요약이 진행 중인 회의록 입니다.' },
	1128: { code: 410, errorCode: 'E2128', message: '보존기간이 만료되어 원본 파일이 삭제된 회의록은 재시도할 수 없습니다.' },
	1129: { code: 500, errorCode: 'E2129', message: '파일 삭제 실패' },
	1130: { code: 500, errorCode: 'E2130', message: '회의시간 변경에 실패 하였습니다.' },
	1131: { code: 500, errorCode: 'E2131', message: '회의 시작 시간이 종료 시간보다 늦습니다.' },
	1132: { code: 500, errorCode: 'E2132', message: 'Wave To Flac 압축 변환 중 오류 발생' },
	1133: { code: 500, errorCode: 'E2133', message: '이미 업로드된 녹음 파일입니다.' },
	1170: { code: 500, errorCode: 'E2170', message: '데모 원본 기록이 없습니다.' },
	1171: { code: 500, errorCode: 'E2171', message: '키워드 수정에 실패 하였습니다.' },
	1172: { code: 400, errorCode: 'E2172', message: '변경 사항이 전혀 없는 요청입니다.' },
	1173: { code: 500, errorCode: 'E2173', message: '교정할 세그먼트가 없습니다.' },
	1174: { code: 500, errorCode: 'E2174', message: 'LLM 요청 중 오류 발생 했습니다.' },
	1175: { code: 500, errorCode: 'E2175', message: '허용 되지 않은 카테고리 입니다.' },
	1176: { code: 500, errorCode: 'E2176', message: '텍스트를 찾을 수 없습니다.' },
	1177: { code: 500, errorCode: 'E2177', message: '이미 하이라이트 된 텍스트 입니다.' },
	1178: { code: 500, errorCode: 'E2178', message: '하이라이트 정보를 찾을 수 없습니다.' },
	1179: { code: 400, errorCode: 'E2179', message: '파라미터가 너무 적습니다.' },
	1180: { code: 500, errorCode: 'E2180', message: '허용되지 않은 카테고리 필드 입니다.' },
	1181: { code: 500, errorCode: 'E2181', message: '카테고리 필드가 Undefined 입니다.' },
	1182: { code: 500, errorCode: 'E2182', message: 'SummaryTime 카테고리에 sub 필드가 없습니다.' },
	1183: { code: 500, errorCode: 'E2183', message: 'SummaryTime.sub 필드가 올바르지 않습니다.' },
	1184: { code: 500, errorCode: 'E2184', message: '카테고리 필수 필드가 누락 되었습니다.' },
	1185: { code: 400, errorCode: 'E2185', message: '접근 불가능한 콘텐츠가 포함되어 있습니다.' },
	1186: { code: 500, errorCode: 'E2186', message: '음성인식 재시도 큐가 존재하지 않습니다.' },
	1187: { code: 500, errorCode: 'E2187', message: '이미 음성인식 진행중입니다.' },
	1188: { code: 500, errorCode: 'E2188', message: '음성인식 재시도 실패' },
	1189: { code: 400, errorCode: 'E2189', message: '텍스트 업로드 실패' },

	// Member Errors (E3xxx)
	1201: { code: 401, errorCode: 'E3201', message: '회원 정보가 없습니다.' },

	// Shared Errors (E4xxx)
	1301: { code: 500, errorCode: 'E4301', message: '이미 공유된 이메일 계정 입니다.' },
	1302: { code: 401, errorCode: 'E4302', message: '권한이 없습니다.' },
	1303: { code: 500, errorCode: 'E4303', message: '존재하지 않는 이메일 계정 입니다.' },
	1304: { code: 400, errorCode: 'E4304', message: '해당 컨텐츠에 공유된 Email 을 찾을 수 없습니다.' },
	1305: { code: 400, errorCode: 'E4305', message: '소유자 권한으로 공유자를 추가할 수 없습니다.' },

	// Notice Errors (E5xxx)
	1401: { code: 400, errorCode: 'E5401', message: '1 미만의 페이지는 조회할 수 없습니다.' },
	1402: { code: 400, errorCode: 'E5402', message: '1 미만의 row는 조회할 수 없습니다.' },
	1403: { code: 400, errorCode: 'E5403', message: 'flag 중에 약속된 Y/N 값이 아닌 항목이 있습니다.' },
	1404: { code: 400, errorCode: 'E5404', message: '요청 ID에 따른 데이터는 존재하지 않거나 조회할 수 없습니다.' },

	// Attendee Errors (E6xxx)
	1500: { code: 400, errorCode: 'E6500', message: '사용자 정보를 조회할 수 없는 pid입니다.' },
	1501: { code: 424, errorCode: 'E6501', message: 'speakerId에 해당하는 참석자를 찾을 수 없습니다.' },
	1502: { code: 425, errorCode: 'E6502', message: '변경하려는 이름이 기존 이름과 동일합니다.' },
	1503: { code: 400, errorCode: 'E6503', message: '화자로 설정된 기본 참석자는 완전히 삭제할 수 없습니다.' },
	1504: { code: 410, errorCode: 'E6504', message: '이미 참석자로 설정한 pid를 중복 요청했습니다.' },
	1505: { code: 400, errorCode: 'E6505', message: '초기화에 필요한 참석자 수가 부족합니다. 참석자를 추가해주세요.' },
	1506: { code: 400, errorCode: 'E6506', message: 'displayName은 20자 이내의 한글, 영문, 숫자, 공백만 가능합니다.' },
	1507: { code: 400, errorCode: 'E6507', message: 'displayName에는 예약된 명칭(참석자 등)을 포함할 수 없습니다.' },
	1508: { code: 400, errorCode: 'E6508', message: '공백을 연속으로 두 번 이상 입력할 수 없습니다.' },

	// Integration Errors (E7xxx)
	1601: { code: 401, errorCode: 'E7601', message: '연동 요청 사용자가 아닙니다.' },

	// Inbox Errors (E8xxx)
	1701: { code: 400, errorCode: 'E8701', message: '존재하지 않는 알림 메시지입니다.' },

	// Dictionary Errors (E9xxx)
	1801: { code: 400, errorCode: 'E9801', message: '존재하지 않는 사전 정보입니다.' },
	1802: { code: 400, errorCode: 'E9802', message: '이미 등록된 사전 정보입니다.' },
	1803: { code: 400, errorCode: 'E9803', message: '변경 전 단어와 변경 후 단어가 동일합니다.' },

	// User Errors (E10xxx) (contact, folder)
	1901: { code: 400, errorCode: 'E10901', message: '이미 주소록에 등록된 이메일입니다.' },
	1902: { code: 400, errorCode: 'E10902', message: '존재하지 않는 주소록 정보입니다.' },
	1903: { code: 400, errorCode: 'E10903', message: '존재하지 않는 폴더 정보입니다.' },
	1904: { code: 400, errorCode: 'E10904', message: '존재하지 않거나 휴지통으로 이동된 콘텐츠가 포함되어있습니다.' },
	1905: { code: 400, errorCode: 'E10905', message: '이미 요청 폴더에 포함된 콘텐츠입니다.' },
	1906: { code: 400, errorCode: 'E10906', message: '이미 동일한 폴더명이 존재합니다.' },
	1907: { code: 400, errorCode: 'E10907', message: '더 이상 폴더를 생성할 수 없습니다.' },
	1908: { code: 400, errorCode: 'E10908', message: '삭제할 컨텐츠가 더 이상 없습니다.' },
	1909: { code: 400, errorCode: 'E10909', message: '내가 생성한 콘텐츠는 이 폴더로 이동할 수 없습니다.' },
	1910: { code: 400, errorCode: 'E10910', message: '이 폴더는 삭제할 수 없습니다.' },
	1911: { code: 400, errorCode: 'E10911', message: '이 폴더로 이동할 수 없습니다.' },
	1912: { code: 400, errorCode: 'E10912', message: '공유 받은 콘텐츠는 이 폴더로 이동할 수 없습니다.' },
	1913: { code: 400, errorCode: 'E10913', message: '이 폴더는 수정할 수 없습니다.' },
	1914: { code: 400, errorCode: 'E10914', message: '에러 콘텐츠는 이동할 수 없습니다.' },
	1915: { code: 400, errorCode: 'E10915', message: '이미 존재하는 라벨 이름입니다.' },
	1916: { code: 400, errorCode: 'E10916', message: '존재하지 않는 라벨을 요청했습니다.' },
	1917: { code: 400, errorCode: 'E10917', message: '휴지통으로 이동된 주소록에 중복된 이메일이 있습니다.' },

	// Chatbot Errors (E11xxx)
	2001: { code: 400, errorCode: 'E11101', message: '존재하지 않는 챗봇 정보입니다.' },

	// Calendar Errors (E12xxx)
	2101: { code: 400, errorCode: 'E12201', message: '첨부 콘텐츠는 최대 5개까지 첨부할 수 있습니다.' },
	2102: { code: 400, errorCode: 'E12202', message: '첨부 콘텐츠에 중복된 콘텐츠가 있습니다.' },
	2103: { code: 400, errorCode: 'E12203', message: '웹캘린더 주소가 올바르지 않습니다.' },
	2104: { code: 500, errorCode: 'E12204', message: '웹캘린더 연동 실패' },
	2105: { code: 500, errorCode: 'E12205', message: '존재하지 않는 연동 정보 입니다.' },
	2106: { code: 500, errorCode: 'E12206', message: '동기화 된 일정이 없습니다.' },
	2107: { code: 500, errorCode: 'E12207', message: '존재하지 않는 캘린더 정보입니다.' },
	2108: { code: 400, errorCode: 'E12208', message: '알림 시간은 0 이상이어야 합니다.' },
	2109: { code: 400, errorCode: 'E12209', message: '첨부 회의록이 사용자 접근이 불가능한 회의록 입니다.' },
	2110: { code: 501, errorCode: 'E12210', message: '알림 설정이 불가능합니다.' },
	2111: { code: 410, errorCode: 'E12211', message: '회의 시작 시간이 지났습니다.' },

	// Template Errors (E13xxx)
	2201: { code: 400, errorCode: 'E13301', message: '존재하지 않는 템플릿 정보입니다.' },
	2202: { code: 400, errorCode: 'E13302', message: '존재하지 않는 워크스페이스 정보입니다.' },
	2203: { code: 500, errorCode: 'E13303', message: '템플릿 ID가 필요합니다.' },

	// Memo Errors (E14xxx)
	2301: { code: 404, errorCode: 'E14401', message: '회의록에 존재하지 않는 메모입니다.' },
	2302: { code: 401, errorCode: 'E14402', message: '메모 작성자가 아닙니다.' },
	2303: { code: 404, errorCode: 'E14403', message: '전사 결과에 존재하지 않는 itemId입니다.' },
	2304: { code: 404, errorCode: 'E14404', message: '회의록에 직접 작성한 메모가 없습니다.' },
	2305: { code: 404, errorCode: 'E14405', message: '회의록에 존재하지 않는 메모 댓글입니다.' },

	// Keyword Errors (E15xxx)
	2401: { code: 400, errorCode: 'E14501', message: '이미 존재하는 키워드 입니다.' },
	2402: { code: 400, errorCode: 'E14402', message: '키워드에 영어 문자가 포함되어있습니다.' },
	2403: { code: 500, errorCode: 'E14503', message: '키워드 생성 실패' },
	2404: { code: 500, errorCode: 'E14504', message: '키워드 삭제 실패' },
	2405: { code: 400, errorCode: 'E14505', message: '키워드 최대 개수를 초과했습니다.' },
	2406: { code: 400, errorCode: 'E14506', message: '존재하지 않는 키워드 입니다.' },
};

class ErrorHandler {
	async exception(err, req, res, next) {
		const { code = 500, result = {} } = err;
		const errorResponse = errorDetails => {
			const { code: httpCode, errorCode, message } = errorDetails;
			log.e('[ErrorHandler : exception] error:', message);
			console.log(err);
			res.json({ httpCode, message, errorCode, result });
		};

		try {
			const errorDetails = mappingError[code] || mappingError[500];
			errorResponse(errorDetails);
		} catch (error) {
			const fallbackErrorDetails = mappingError[500];
			log.e('[ErrorHandler : exception] fallback error:', error.message);
			errorResponse(fallbackErrorDetails);
		}
	}
}

export const HttpError = class extends Error {
	constructor(httpCode, data) {
		super();
		this.code = httpCode;
		this.result = data;
	}
};

export const QueueError = (errorCode, errorInfo = null) => {
	const errorDetails = mappingError[errorCode] || mappingError[500];
	errorDetails.reason = typeof errorInfo === 'string' || errorInfo === null ? { message: errorInfo } : errorInfo;
	return errorDetails;
};

export default new ErrorHandler();
