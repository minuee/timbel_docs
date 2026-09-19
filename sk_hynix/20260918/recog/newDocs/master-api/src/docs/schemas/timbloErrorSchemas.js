/**
 * @swagger
 * components:
 *   schemas:
 *     # 기본 HTTP 에러 (4xx, 5xx)
 *     BadRequestError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "Bad Request"
 *         errorCode:
 *           type: string
 *           example: "E0400"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     UnauthorizedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 401
 *         message:
 *           type: string
 *           example: "Unauthorized"
 *         errorCode:
 *           type: string
 *           example: "E0401"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ForbiddenError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 403
 *         message:
 *           type: string
 *           example: "Forbidden"
 *         errorCode:
 *           type: string
 *           example: "E0403"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 404
 *         message:
 *           type: string
 *           example: "Not Found"
 *         errorCode:
 *           type: string
 *           example: "E0404"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     MethodNotAllowedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 405
 *         message:
 *           type: string
 *           example: "Method Not Allowed"
 *         errorCode:
 *           type: string
 *           example: "E0405"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NotAcceptableError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 406
 *         message:
 *           type: string
 *           example: "Not Acceptable"
 *         errorCode:
 *           type: string
 *           example: "E0406"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     RequestTimeoutError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 408
 *         message:
 *           type: string
 *           example: "Request Timeout"
 *         errorCode:
 *           type: string
 *           example: "E0408"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     URITooLongError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 414
 *         message:
 *           type: string
 *           example: "URI Too Long"
 *         errorCode:
 *           type: string
 *           example: "E0414"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     UnsupportedMediaTypeError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 415
 *         message:
 *           type: string
 *           example: "Unsupported Media Type"
 *         errorCode:
 *           type: string
 *           example: "E0415"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     UnprocessableContentError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 422
 *         message:
 *           type: string
 *           example: "Unprocessable Content"
 *         errorCode:
 *           type: string
 *           example: "E0422"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     TooManyRequestsError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 429
 *         message:
 *           type: string
 *           example: "Too Many Requests"
 *         errorCode:
 *           type: string
 *           example: "E0429"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InternalServerError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "Internal Server Error"
 *         errorCode:
 *           type: string
 *           example: "E0500"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 공통 에러 (E1xxx)
 *     MissingRequiredParameterError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "필수 파라미터가 부족합니다."
 *         errorCode:
 *           type: string
 *           example: "E1000"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ViewerPermissionRequiredError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 401
 *         message:
 *           type: string
 *           example: "뷰어 이상의 권한이 필요합니다."
 *         errorCode:
 *           type: string
 *           example: "E1001"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     EditorPermissionRequiredError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 401
 *         message:
 *           type: string
 *           example: "편집자 이상의 권한이 필요합니다."
 *         errorCode:
 *           type: string
 *           example: "E1002"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     OwnerPermissionRequiredError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 401
 *         message:
 *           type: string
 *           example: "소유자 권한이 필요합니다."
 *         errorCode:
 *           type: string
 *           example: "E1003"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     GuestPermissionDeniedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 401
 *         message:
 *           type: string
 *           example: "게스트 권한으로 할 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E1004"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     DownloaderPermissionRequiredError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 401
 *         message:
 *           type: string
 *           example: "다운로드 이상의 권한이 필요합니다."
 *         errorCode:
 *           type: string
 *           example: "E1005"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 콘텐츠 에러 (E2xxx)
 *     ContentUploadFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "콘텐츠 업로드 실패"
 *         errorCode:
 *           type: string
 *           example: "E2101"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     S3GetObjectFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "S3 getObject 호출 실패"
 *         errorCode:
 *           type: string
 *           example: "E2102"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     SpeechRecognitionRequestFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "음성인식 요청 실패"
 *         errorCode:
 *           type: string
 *           example: "E2103"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NoSpeechRecognitionResultError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "음성인식 결과가 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E2104"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     SpeechRecognitionInProgressError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "음성인식 진행중인 파일 입니다."
 *         errorCode:
 *           type: string
 *           example: "E2105"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     SpeechRecognitionError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "음성인식 중 오류가 발생했습니다."
 *         errorCode:
 *           type: string
 *           example: "E2106"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InvalidEngineCodeError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "사용 불가능한 엔진 코드입니다."
 *         errorCode:
 *           type: string
 *           example: "E2107"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NoTranscriptionFileError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "전사 파일이 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E2108"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ImageFileOnlyError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "이미지 파일만 업로드 가능합니다."
 *         errorCode:
 *           type: string
 *           example: "E2109"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InvalidTypeError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "타입이 올바르지 않습니다."
 *         errorCode:
 *           type: string
 *           example: "E2110"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ContentInRecycleBinError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 413
 *         message:
 *           type: string
 *           example: "휴지통으로 이동된 컨텐츠입니다. 복원 후 요청해주세요."
 *         errorCode:
 *           type: string
 *           example: "E2111"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     CannotAddSelfError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 501
 *         message:
 *           type: string
 *           example: "자기 자신은 추가할 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E2112"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     TooManyParametersError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "파라미터가 너무 많습니다. 약속된 형태로 구성 및 요청해주세요."
 *         errorCode:
 *           type: string
 *           example: "E2113"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ContentProcessingError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 422
 *         message:
 *           type: string
 *           example: "현재 전사 및 AI 처리 중인 컨텐츠 입니다."
 *         errorCode:
 *           type: string
 *           example: "E2114"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ContentCompletelyDeletedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 423
 *         message:
 *           type: string
 *           example: "완전히 삭제되어 조회할 수 없는 컨텐츠 입니다."
 *         errorCode:
 *           type: string
 *           example: "E2115"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     UndefinedPermissionError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "정의되지 않은 권한입니다."
 *         errorCode:
 *           type: string
 *           example: "E2116"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InvalidDateFormatError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "날짜 형식이 올바르지 않습니다."
 *         errorCode:
 *           type: string
 *           example: "E2117"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InvalidEmailFormatError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "이메일 형식이 올바르지 않습니다."
 *         errorCode:
 *           type: string
 *           example: "E2118"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     TranscriptionFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 421
 *         message:
 *           type: string
 *           example: "전사 처리가 실패하여 조회할 수 없는 컨텐츠입니다."
 *         errorCode:
 *           type: string
 *           example: "E2119"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NoVoiceRecordInTimeRangeError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 434
 *         message:
 *           type: string
 *           example: "해당 시간대의 음성 기록을 찾을 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E2120"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NoTranscriptionResultError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 404
 *         message:
 *           type: string
 *           example: "아직 전사된 결과가 없습니다. 잠시 후 다시 시도해주세요."
 *         errorCode:
 *           type: string
 *           example: "E2121"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     OriginalFileNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "원본 파일 정보를 찾을 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E2122"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ObjectStorageUploadError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 504
 *         message:
 *           type: string
 *           example: "Object Storage 업로드 중 오류 발생"
 *         errorCode:
 *           type: string
 *           example: "E2123"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     FileDataRetrievalFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "File 데이터 조회 실패"
 *         errorCode:
 *           type: string
 *           example: "E2124"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ObjectStorageFileDeleteFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "Object Storage 파일 삭제 실패"
 *         errorCode:
 *           type: string
 *           example: "E2125"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     VoiceLengthCheckFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "음성 길이 확인이 불가능한 파일 입니다."
 *         errorCode:
 *           type: string
 *           example: "E2126"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     SummaryInProgressError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "요약이 진행 중인 회의록 입니다."
 *         errorCode:
 *           type: string
 *           example: "E2127"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     FileDeleteFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "파일 삭제 실패"
 *         errorCode:
 *           type: string
 *           example: "E2129"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     MeetingTimeChangeFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "회의시간 변경에 실패 하였습니다."
 *         errorCode:
 *           type: string
 *           example: "E2130"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InvalidMeetingTimeError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "회의 시작 시간이 종료 시간보다 늦습니다."
 *         errorCode:
 *           type: string
 *           example: "E2131"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     WaveToFlacConversionError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "Wave To Flac 압축 변환 중 오류 발생"
 *         errorCode:
 *           type: string
 *           example: "E2132"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     DuplicateRecordingFileError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "이미 업로드된 녹음 파일입니다."
 *         errorCode:
 *           type: string
 *           example: "E2133"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     DemoOriginalRecordNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "데모 원본 기록이 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E2170"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     KeywordModificationFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "키워드 수정에 실패 하였습니다."
 *         errorCode:
 *           type: string
 *           example: "E2171"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NoChangesRequestError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "변경 사항이 전혀 없는 요청입니다."
 *         errorCode:
 *           type: string
 *           example: "E2172"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NoSegmentToCorrectError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "교정할 세그먼트가 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E2173"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     LLMRequestError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "LLM 요청 중 오류 발생 했습니다."
 *         errorCode:
 *           type: string
 *           example: "E2174"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     UnauthorizedCategoryError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "허용 되지 않은 카테고리 입니다."
 *         errorCode:
 *           type: string
 *           example: "E2175"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     TextNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "텍스트를 찾을 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E2176"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     AlreadyHighlightedTextError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "이미 하이라이트 된 텍스트 입니다."
 *         errorCode:
 *           type: string
 *           example: "E2177"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     HighlightInfoNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "하이라이트 정보를 찾을 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E2178"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     TooFewParametersError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "파라미터가 너무 적습니다."
 *         errorCode:
 *           type: string
 *           example: "E2179"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     UnauthorizedCategoryFieldError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "허용되지 않은 카테고리 필드 입니다."
 *         errorCode:
 *           type: string
 *           example: "E2180"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     UndefinedCategoryFieldError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "카테고리 필드가 Undefined 입니다."
 *         errorCode:
 *           type: string
 *           example: "E2181"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     SummaryTimeSubFieldMissingError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "SummaryTime 카테고리에 sub 필드가 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E2182"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InvalidSummaryTimeSubFieldError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "SummaryTime.sub 필드가 올바르지 않습니다."
 *         errorCode:
 *           type: string
 *           example: "E2183"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     MissingCategoryRequiredFieldError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "카테고리 필수 필드가 누락 되었습니다."
 *         errorCode:
 *           type: string
 *           example: "E2184"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InaccessibleContentIncludedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "접근 불가능한 콘텐츠가 포함되어 있습니다."
 *         errorCode:
 *           type: string
 *           example: "E2185"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     RecognitionRetryQueueNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "음성인식 재시도 큐가 존재하지 않습니다."
 *         errorCode:
 *           type: string
 *           example: "E2186"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     RecognitionAlreadyInProgressError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "이미 음성인식 진행중입니다."
 *         errorCode:
 *           type: string
 *           example: "E2187"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     RecognitionRetryFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "음성인식 재시도 실패"
 *         errorCode:
 *           type: string
 *           example: "E2188"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 회원 에러 (E3xxx)
 *     MemberNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 401
 *         message:
 *           type: string
 *           example: "회원 정보가 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E3201"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 공유 에러 (E4xxx)
 *     AlreadySharedEmailError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "이미 공유된 이메일 계정 입니다."
 *         errorCode:
 *           type: string
 *           example: "E4301"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NoPermissionError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 401
 *         message:
 *           type: string
 *           example: "권한이 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E4302"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NonExistentEmailError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "존재하지 않는 이메일 계정 입니다."
 *         errorCode:
 *           type: string
 *           example: "E4303"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     SharedEmailNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "해당 컨텐츠에 공유된 Email 을 찾을 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E4304"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     CannotAddOwnerAsSharedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "소유자 권한으로 공유자를 추가할 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E4305"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 알림 에러 (E5xxx)
 *     InvalidPageNumberError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "1 미만의 페이지는 조회할 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E5401"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InvalidRowNumberError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "1 미만의 row는 조회할 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E5402"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InvalidFlagValueError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "flag 중에 약속된 Y/N 값이 아닌 항목이 있습니다."
 *         errorCode:
 *           type: string
 *           example: "E5403"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     RequestDataNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "요청 ID에 따른 데이터는 존재하지 않거나 조회할 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E5404"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 참석자 에러 (E6xxx)
 *     InvalidPidError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "사용자 정보를 조회할 수 없는 pid입니다."
 *         errorCode:
 *           type: string
 *           example: "E6500"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     SpeakerNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 424
 *         message:
 *           type: string
 *           example: "speakerId에 해당하는 참석자를 찾을 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E6501"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     SameNameChangeError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 425
 *         message:
 *           type: string
 *           example: "변경하려는 이름이 기존 이름과 동일합니다."
 *         errorCode:
 *           type: string
 *           example: "E6502"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     CannotDeleteDefaultSpeakerError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "화자로 설정된 기본 참석자는 완전히 삭제할 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E6503"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     DuplicateAttendeeError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 410
 *         message:
 *           type: string
 *           example: "이미 참석자로 설정한 pid를 중복 요청했습니다."
 *         errorCode:
 *           type: string
 *           example: "E6504"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InsufficientAttendeesError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "초기화에 필요한 참석자 수가 부족합니다. 참석자를 추가해주세요."
 *         errorCode:
 *           type: string
 *           example: "E6505"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InvalidDisplayNameError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "displayName은 20자 이내의 한글, 영문, 숫자, 공백만 가능합니다."
 *         errorCode:
 *           type: string
 *           example: "E6506"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ReservedDisplayNameError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "displayName에는 예약된 명칭(참석자 등)을 포함할 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E6507"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ConsecutiveSpacesError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "공백을 연속으로 두 번 이상 입력할 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E6508"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 연동 에러 (E7xxx)
 *     InvalidIntegrationUserError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 401
 *         message:
 *           type: string
 *           example: "연동 요청 사용자가 아닙니다."
 *         errorCode:
 *           type: string
 *           example: "E7601"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 인박스 에러 (E8xxx)
 *     NotificationNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "존재하지 않는 알림 메시지입니다."
 *         errorCode:
 *           type: string
 *           example: "E8701"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 사전 에러 (E9xxx)
 *     DictionaryNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "존재하지 않는 사전 정보입니다."
 *         errorCode:
 *           type: string
 *           example: "E9801"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     DictionaryAlreadyExistsError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "이미 등록된 사전 정보입니다."
 *         errorCode:
 *           type: string
 *           example: "E9802"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     SameWordChangeError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "변경 전 단어와 변경 후 단어가 동일합니다."
 *         errorCode:
 *           type: string
 *           example: "E9803"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 사용자 에러 (E10xxx) - 연락처, 폴더
 *     ContactEmailAlreadyExistsError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "이미 주소록에 등록된 이메일입니다."
 *         errorCode:
 *           type: string
 *           example: "E10901"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ContactNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "존재하지 않는 주소록 정보입니다."
 *         errorCode:
 *           type: string
 *           example: "E10902"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     FolderNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "존재하지 않는 폴더 정보입니다."
 *         errorCode:
 *           type: string
 *           example: "E10903"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ContentInRecycleBinOrNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "존재하지 않거나 휴지통으로 이동된 콘텐츠가 포함되어있습니다."
 *         errorCode:
 *           type: string
 *           example: "E10904"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     ContentAlreadyInFolderError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "이미 요청 폴더에 포함된 콘텐츠입니다."
 *         errorCode:
 *           type: string
 *           example: "E10905"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     DuplicateFolderNameError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "이미 동일한 폴더명이 존재합니다."
 *         errorCode:
 *           type: string
 *           example: "E10906"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     FolderCreationLimitExceededError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "더 이상 폴더를 생성할 수 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E10907"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NoContentToDeleteError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "삭제할 컨텐츠가 더 이상 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E10908"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 챗봇 에러 (E11xxx)
 *     ChatbotNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "존재하지 않는 챗봇 정보입니다."
 *         errorCode:
 *           type: string
 *           example: "E11101"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 캘린더 에러 (E12xxx)
 *     CalendarValidationError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "첨부 콘텐츠는 최대 5개까지 첨부할 수 있습니다."
 *         errorCode:
 *           type: string
 *           example: "E12201"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     DuplicateAttachedContentError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "첨부 콘텐츠에 중복된 콘텐츠가 있습니다."
 *         errorCode:
 *           type: string
 *           example: "E12202"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     InvalidWebcalUrlError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "웹캘린더 주소가 올바르지 않습니다."
 *         errorCode:
 *           type: string
 *           example: "E12203"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     WebcalIntegrationFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "웹캘린더 연동 실패"
 *         errorCode:
 *           type: string
 *           example: "E12204"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     WebcalIntegrationNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "존재하지 않는 연동 정보입니다."
 *         errorCode:
 *           type: string
 *           example: "E12205"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     NoSyncedCalendarError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "동기화 된 일정이 없습니다."
 *         errorCode:
 *           type: string
 *           example: "E12206"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     MeetingTimePassedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 410
 *         message:
 *           type: string
 *           example: "회의 시작 시간이 지났습니다."
 *         errorCode:
 *           type: string
 *           example: "E12211"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     # 키워드 에러 (E14xxx, E15xxx)
 *     KeywordAlreadyExistsError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "이미 존재하는 키워드 입니다."
 *         errorCode:
 *           type: string
 *           example: "E14501"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     KeywordContainsEnglishError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "키워드에 영어 문자가 포함되어있습니다."
 *         errorCode:
 *           type: string
 *           example: "E14402"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     KeywordCreationFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "키워드 생성 실패"
 *         errorCode:
 *           type: string
 *           example: "E14503"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     KeywordDeletionFailedError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 500
 *         message:
 *           type: string
 *           example: "키워드 삭제 실패"
 *         errorCode:
 *           type: string
 *           example: "E14504"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     KeywordMaxCountExceededError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "키워드 최대 개수를 초과했습니다."
 *         errorCode:
 *           type: string
 *           example: "E14505"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 *
 *     KeywordNotFoundError:
 *       type: object
 *       properties:
 *         httpCode:
 *           type: integer
 *           example: 400
 *         message:
 *           type: string
 *           example: "존재하지 않는 키워드 입니다."
 *         errorCode:
 *           type: string
 *           example: "E14506"
 *         result:
 *           type: object
 *           description: 추가 에러 정보
 */
