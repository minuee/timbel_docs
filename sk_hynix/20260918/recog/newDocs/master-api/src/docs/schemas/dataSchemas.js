/**
 * @swagger
 * components:
 *   schemas:
 *     Success:
 *       type: object
 *       properties:
 *         message:
 *           type: string
 *           example: "Success"
 *           description: "응답 메시지"
 *         httpCode:
 *           type: integer
 *           example: 200
 *           description: "HTTP 상태 코드"
 *       required:
 *         - message
 *         - httpCode
 *
 *     BookmarkListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 type: object
 *                 properties:
 *                   contentId:
 *                     type: string
 *                     example: "콘텐츠 고유 식별자"
 *                     description: "콘텐츠 ID"
 *                   bookmarkTime:
 *                     type: string
 *                     format: date-time
 *                     example: "2025-09-15T06:42:48.988Z"
 *                     description: "북마크 생성 시간"
 *                   title:
 *                     type: string
 *                     example: "AI 가 생성한 주제 또는 파일명"
 *                     description: "콘텐츠 제목"
 *                   editedTitle:
 *                     type: string
 *                     nullable: true
 *                     example: null
 *                     description: "사용자가 편집한 주제"
 *                   contentType:
 *                     type: string
 *                     example: "AUDIO, RECORD, VIDEO"
 *                     description: "콘텐츠 타입"
 *                   createAt:
 *                     type: string
 *                     format: date-time
 *                     example: "2025-09-12T02:01:23.150Z"
 *                     description: "콘텐츠 생성 시간"
 *                   updateAt:
 *                     type: string
 *                     format: date-time
 *                     example: "2025-09-12T02:20:09.435Z"
 *                     description: "콘텐츠 수정 시간"
 *                   creatorNickName:
 *                     type: string
 *                     example: "회원닉네임"
 *                     description: "생성자 닉네임"
 *                   creatorPID:
 *                     type: string
 *                     example: "생성자 고유 식별자"
 *                     description: "생성자 PID"
 *                   lastUpdator:
 *                     type: string
 *                     example: "수정자닉네임"
 *                     description: "마지막 수정자 닉네임"
 *                   bookmarks:
 *                     $ref: '#/components/schemas/Bookmarks'
 *                   shareUsers:
 *                     $ref: '#/components/schemas/ShareUsers'

 *     HomeResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 keywords:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/Keyword'
 *                   description: "최근 검색 키워드 목록"
 *                 bookmarks:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/BookmarkItem'
 *                   description: "최근 북마크 목록"
 *                 contents:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/HomeContent'
 *                   description: "최근 콘텐츠 목록"

 *     Keyword:
 *       type: object
 *       properties:
 *         keywordId:
 *           type: integer
 *           example: 1135
 *           description: "키워드 ID"
 *         keyword:
 *           type: string
 *           example: "검색 키워드"
 *           description: "검색 키워드"
 *         searchAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-10T07:07:47.047Z"
 *           description: "검색 시간"

 *     BookmarkItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "mongodb._id 구조의 북마크 ID"
 *           description: "북마크 ID"
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         key:
 *           type: string
 *           example: "mergedSegments"
 *           description: "북마크 타입 (mergedSegments, summaryTime, tasks, issues, summary)"
 *         isAll:
 *           type: string
 *           example: "N"
 *           description: "전체 선택 여부 (Y/N)"
 *         time:
 *           type: string
 *           format: date-time
 *           example: "2025-09-15T06:56:10.563Z"
 *           description: "북마크 생성 시간"
 *         data:
 *           oneOf:
 *             - type: array
 *               items:
 *                 $ref: '#/components/schemas/BookmarkSegment'
 *               description: "mergedSegments 타입의 데이터"
 *             - type: array
 *               items:
 *                 $ref: '#/components/schemas/BookmarkSummaryTime'
 *               description: "summaryTime 타입의 데이터"
 *             - type: array
 *               items:
 *                 type: string
 *               description: "tasks, issues, summary 타입의 데이터"
 *           example: ["북마크 데이터"]
 *           description: "북마크 데이터 (타입에 따라 구조가 다름)"
 *         title:
 *           type: string
 *           example: "콘텐츠 제목"
 *           description: "콘텐츠 제목"

 *     Content:
 *       type: object
 *       properties:
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         folderId:
 *           type: string
 *           nullable: true
 *           example: "폴더 고유 식별자"
 *           description: "폴더 ID"
 *         title:
 *           type: string
 *           example: "콘텐츠 제목"
 *           description: "콘텐츠 제목"
 *         editedTitle:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "편집된 제목"
 *         fileName:
 *           type: string
 *           example: "파일명.flac"
 *           description: "파일명"
 *         type:
 *           type: string
 *           example: "AUDIO"
 *           description: "콘텐츠 타입 (AUDIO, VIDEO, RECORD, TEXT)"
 *         hashTag:
 *           type: array
 *           items:
 *             type: string
 *           example: ["해시태그1", "해시태그2"]
 *           description: "해시태그 목록"
 *         manualTag:
 *           type: array
 *           items:
 *             type: string
 *           example: []
 *           description: "수동 태그 목록"
 *         isRecord:
 *           type: boolean
 *           example: false
 *           description: "녹음 여부"
 *         duration:
 *           type: integer
 *           example: 10800909
 *           description: "재생 시간 (밀리초)"
 *         creatorPID:
 *           type: string
 *           example: "생성자 고유 식별자"
 *           description: "생성자 PID"
 *         creatorEmail:
 *           type: string
 *           example: "member@example.com"
 *           description: "생성자 이메일"
 *         creatorNickName:
 *           type: string
 *           example: "회원닉네임"
 *           description: "생성자 닉네임"
 *         creatorThumbnailUrl:
 *           type: string
 *           example: "https://example.com/member-thumbnail.jpg"
 *           description: "생성자 썸네일 URL"
 *         transcribeStatus:
 *           type: string
 *           example: "DONE"
 *           description: "전사 상태 (DONE, PROCESSING, FAILED)"
 *         meetingStartTime:
 *           type: string
 *           format: date-time
 *           example: "2025-09-12T02:01:23.150Z"
 *           description: "회의 시작 시간"
 *         meetingEndTime:
 *           type: string
 *           format: date-time
 *           example: "2025-09-12T05:01:24.057Z"
 *           description: "회의 종료 시간"
 *         isShared:
 *           type: boolean
 *           example: false
 *           description: "공유 여부"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-12T02:01:23.150Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-12T02:20:09.435Z"
 *           description: "수정 시간"
 *         userAccessRole:
 *           type: string
 *           example: "OWNER"
 *           description: "사용자 접근 권한 (OWNER, EDITOR, VIEWER)"
 *         folderName:
 *           type: string
 *           example: "폴더명"
 *           description: "폴더명"
 *         shareUsers:
 *           $ref: '#/components/schemas/ShareUsers'
 *         speakerInfo:
 *           $ref: '#/components/schemas/SpeakerInfoList'

 *     InboxListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/InboxItem'
 *               description: "인박스 목록"

 *     InboxItem:
 *       type: object
 *       properties:
 *         inboxId:
 *           type: string
 *           example: "인박스 고유 식별자"
 *           description: "인박스 ID"
 *         receiverId:
 *           type: string
 *           example: "수신자 고유 식별자"
 *           description: "수신자 ID"
 *         captureId:
 *           type: string
 *           example: "캡처 고유 식별자"
 *           description: "캡처 ID"
 *         captureType:
 *           type: string
 *           example: "CONTENT"
 *           description: "캡처 타입 (CONTENT, MEMO, HIGHLIGHT 등)"
 *         captureAction:
 *           type: string
 *           example: "CREATE"
 *           description: "캡처 액션 (CREATE, UPDATE, DELETE, RECYCLE, UPDATE_RESET_SEGMENTS 등)"
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         contentType:
 *           type: string
 *           example: "AUDIO"
 *           description: "콘텐츠 타입 (AUDIO, VIDEO, RECORD)"
 *         title:
 *           type: string
 *           example: "콘텐츠 제목"
 *           description: "콘텐츠 제목"
 *         duration:
 *           type: integer
 *           example: 10800909
 *           description: "재생 시간 (밀리초)"
 *         meetingStartTime:
 *           type: string
 *           format: date-time
 *           example: "2025-09-12T02:01:23.150Z"
 *           description: "회의 시작 시간"
 *         attendeeCount:
 *           type: integer
 *           example: 1
 *           description: "참석자 수"
 *         isRead:
 *           type: boolean
 *           example: false
 *           description: "읽음 여부"
 *         creatorId:
 *           type: string
 *           example: "생성자 고유 식별자"
 *           description: "생성자 ID"
 *         creatorNickName:
 *           type: string
 *           example: "회원닉네임"
 *           description: "생성자 닉네임"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-12T02:20:11.779Z"
 *           description: "생성 시간"

 *     InboxCountResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 count:
 *                   type: integer
 *                   example: 17
 *                   description: "처리된 인박스 수"
 *               description: "처리 결과"

 *     InboxUpdateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 inboxId:
 *                   type: string
 *                   example: "인박스 고유 식별자"
 *                   description: "인박스 ID"
 *                 captureId:
 *                   type: string
 *                   example: "캡처 고유 식별자"
 *                   description: "캡처 ID"
 *                 receiverId:
 *                   type: string
 *                   example: "수신자 고유 식별자"
 *                   description: "수신자 ID"
 *                 isRead:
 *                   type: boolean
 *                   example: true
 *                   description: "읽음 여부"
 *                 isVisible:
 *                   type: boolean
 *                   example: true
 *                   description: "표시 여부"
 *                 isDeleted:
 *                   type: boolean
 *                   example: false
 *                   description: "삭제 여부"
 *                 createAt:
 *                   type: string
 *                   format: date-time
 *                   example: "2025-09-15T07:14:00.960Z"
 *                   description: "생성 시간"
 *                 updateAt:
 *                   type: string
 *                   format: date-time
 *                   example: "2025-09-15T07:14:11.019Z"
 *                   description: "수정 시간"
 *               description: "업데이트된 인박스 정보"

 *     IntegrateSummaryResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 aiResult:
 *                   $ref: '#/components/schemas/AiResult'
 *                 summaryTime:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/SummaryTimeItem'
 *                   description: "시간별 요약 목록"
 *                 totalToken:
 *                   type: integer
 *                   example: 279189
 *                   description: "총 토큰 수"
 *               description: "통합 요약 결과"

 *     AiResult:
 *       type: object
 *       properties:
 *         tasks:
 *           type: array
 *           items:
 *             type: string
 *           example: ["작업 내용"]
 *           description: "작업 목록"
 *         issues:
 *           type: array
 *           items:
 *             type: string
 *           example: ["이슈 내용"]
 *           description: "이슈 목록"
 *         topics:
 *           type: array
 *           items:
 *             type: string
 *           example: ["토픽 내용"]
 *           description: "토픽 목록"
 *         summary:
 *           type: array
 *           items:
 *             type: string
 *           example: ["요약 내용"]
 *           description: "요약 목록"
 *         keywords:
 *           type: array
 *           items:
 *             type: string
 *           example: ["키워드"]
 *           description: "키워드 목록"

 *     SummaryTimeItem:
 *       type: object
 *       properties:
 *         index:
 *           type: integer
 *           example: 1
 *           description: "요약 인덱스"
 *         topic:
 *           type: string
 *           example: "요약 주제"
 *           description: "요약 주제"
 *         time:
 *           type: string
 *           example: "00:00:00 ~ 00:00:00"
 *           description: "시간 범위"
 *         summary:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               timestamp:
 *                 type: string
 *                 example: "00:00:00"
 *                 description: "타임스탬프"
 *               content:
 *                 type: string
 *                 example: "요약 내용"
 *                 description: "요약 내용"
 *           description: "요약 내용 목록"
 *         issues:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               timestamp:
 *                 type: string
 *                 example: "00:00:00"
 *                 description: "타임스탬프"
 *               content:
 *                 type: string
 *                 example: "이슈 내용"
 *                 description: "이슈 내용"
 *               reason:
 *                 type: string
 *                 example: "이슈 이유"
 *                 description: "이슈 이유"
 *           description: "이슈 목록"
 *         tasks:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               content:
 *                 type: string
 *                 example: "작업 내용"
 *                 description: "작업 내용"
 *               timestamp:
 *                 type: string
 *                 example: "00:00:00"
 *                 description: "타임스탬프"
 *           description: "작업 목록"

 *     SearchResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 keyword:
 *                   type: string
 *                   example: "검색 키워드"
 *                   description: "검색 키워드"
 *                 savedKeyword:
 *                   type: string
 *                   example: "저장된 키워드"
 *                   description: "저장된 키워드"
 *                 attendee:
 *                   type: string
 *                   nullable: true
 *                   example: "참석자 검색 키워드"
 *                   description: "참석자 검색 키워드"
 *                 _count:
 *                   type: integer
 *                   example: 0
 *                   description: "검색 결과 수"
 *                 currentPage:
 *                   type: integer
 *                   example: 1
 *                   description: "현재 페이지"
 *                 lastPage:
 *                   type: integer
 *                   example: 1
 *                   description: "마지막 페이지"
 *                 contents:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/SearchContent'
 *                   description: "검색 결과 콘텐츠 목록"
 *               description: "검색 결과"

 *     SearchContent:
 *       type: object
 *       properties:
 *         contentId:
 *           type: string
 *           example: "콘텐츠 ID"
 *           description: "콘텐츠 ID"
 *         folderId:
 *           type: string
 *           nullable: true
 *           example: "폴더 ID"
 *           description: "폴더 ID"
 *         title:
 *           type: string
 *           example: "콘텐츠 제목"
 *           description: "콘텐츠 제목"
 *         editedTitle:
 *           type: string
 *           nullable: true
 *           example: "편집된 제목"
 *           description: "편집된 제목"
 *         fileName:
 *           type: string
 *           example: "파일명"
 *           description: "파일명"
 *         type:
 *           type: string
 *           example: "AUDIO"
 *           description: "콘텐츠 타입 (AUDIO, VIDEO, RECORD)"
 *         hashTag:
 *           type: array
 *           items:
 *             type: string
 *           example: ["해시태그"]
 *           description: "해시태그 목록"
 *         isRecord:
 *           type: boolean
 *           example: false
 *           description: "녹음 여부"
 *         duration:
 *           type: integer
 *           example: 0
 *           description: "재생 시간 (밀리초)"
 *         creatorPID:
 *           type: string
 *           example: "생성자 PID"
 *           description: "생성자 PID"
 *         creatorEmail:
 *           type: string
 *           example: "생성자 이메일"
 *           description: "생성자 이메일"
 *         creatorNickName:
 *           type: string
 *           example: "회원닉네임"
 *           description: "생성자 닉네임"
 *         creatorThumbnailUrl:
 *           type: string
 *           example: "생성자 썸네일 URL"
 *           description: "생성자 썸네일 URL"
 *         transcribeStatus:
 *           type: string
 *           example: "DONE"
 *           description: "전사 상태 (DONE, PROCESSING, FAILED)"
 *         meetingStartTime:
 *           type: string
 *           format: date-time
 *           example: "회의 시작 시간"
 *           description: "회의 시작 시간"
 *         meetingEndTime:
 *           type: string
 *           format: date-time
 *           example: "회의 종료 시간"
 *           description: "회의 종료 시간"
 *         isShared:
 *           type: boolean
 *           example: false
 *           description: "공유 여부"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "생성 시간"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "수정 시간"
 *           description: "수정 시간"
 *         userAccessRole:
 *           type: string
 *           example: "OWNER"
 *           description: "사용자 접근 권한 (OWNER, EDITOR, VIEWER)"
 *         folderName:
 *           type: string
 *           example: "폴더명"
 *           description: "폴더명"
 *         shareUsers:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               email:
 *                 type: string
 *                 example: "member@example.com"
 *                 description: "공유 사용자 이메일"
 *               role:
 *                 type: string
 *                 example: "VIEWER"
 *                 description: "공유 사용자 권한 (OWNER, EDITOR, VIEWER)"
 *               nickName:
 *                 type: string
 *                 example: "공유자닉네임"
 *                 description: "공유 사용자 닉네임"
 *               thumbnailUrl:
 *                 type: string
 *                 example: "https://example.com/shared-user-thumbnail.jpg"
 *                 description: "공유 사용자 썸네일 URL"
 *           description: "공유 사용자 목록"
 *         speakerInfo:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               speakerId:
 *                 type: integer
 *                 example: 1
 *                 description: "화자 ID"
 *               name:
 *                 type: string
 *                 example: "화자 이름"
 *                 description: "화자 이름"
 *               displayName:
 *                 type: string
 *                 nullable: true
 *                 example: "화자 표시명"
 *                 description: "화자 표시명"
 *               pid:
 *                 type: string
 *                 nullable: true
 *                 example: "화자 PID"
 *                 description: "화자 PID"
 *           description: "화자 정보 목록"


 *     UsageTodayResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 registrationStats:
 *                   type: object
 *                   properties:
 *                     record:
 *                       type: integer
 *                       example: 0
 *                       description: "녹음 등록 수"
 *                     upload:
 *                       type: integer
 *                       example: 0
 *                       description: "업로드 등록 수"
 *                     total:
 *                       type: integer
 *                       example: 0
 *                       description: "총 등록 수"
 *                   description: "등록 통계"
 *                 durationStats:
 *                   type: object
 *                   properties:
 *                     unit:
 *                       type: string
 *                       example: "ms"
 *                       description: "시간 단위"
 *                     recordDuration:
 *                       type: integer
 *                       example: 0
 *                       description: "녹음 시간"
 *                     uploadDuration:
 *                       type: integer
 *                       example: 0
 *                       description: "업로드 시간"
 *                     total:
 *                       type: integer
 *                       example: 0
 *                       description: "총 시간"
 *                   description: "시간 통계"
 *                 statisticsData:
 *                   type: object
 *                   additionalProperties:
 *                     type: object
 *                     properties:
 *                       record:
 *                         type: integer
 *                         example: 0
 *                         description: "녹음 수"
 *                       upload:
 *                         type: integer
 *                         example: 0
 *                         description: "업로드 수"
 *                   example:
 *                     "00:00":
 *                       record: 0
 *                       upload: 0
 *                   description: "시간별 통계 데이터"
 *                 downloadStats:
 *                   type: object
 *                   properties:
 *                     media:
 *                       type: integer
 *                       example: 0
 *                       description: "미디어 다운로드 수"
 *                     document:
 *                       type: integer
 *                       example: 0
 *                       description: "문서 다운로드 수"
 *                     total:
 *                       type: integer
 *                       example: 0
 *                       description: "총 다운로드 수"
 *                   description: "다운로드 통계"
 *                 sharedStats:
 *                   type: object
 *                   properties:
 *                     incoming:
 *                       type: integer
 *                       example: 0
 *                       description: "받은 공유 수"
 *                     outgoing:
 *                       type: integer
 *                       example: 0
 *                       description: "보낸 공유 수"
 *                   description: "공유 통계"
 *                 reSummaryStats:
 *                   type: object
 *                   properties:
 *                     large:
 *                       type: integer
 *                       example: 0
 *                       description: "대용량 재요약 수"
 *                     medium:
 *                       type: integer
 *                       example: 0
 *                       description: "중용량 재요약 수"
 *                     small:
 *                       type: integer
 *                       example: 0
 *                       description: "소용량 재요약 수"
 *                     total:
 *                       type: integer
 *                       example: 0
 *                       description: "총 재요약 수"
 *                   description: "재요약 통계"
 *                 corpusStats:
 *                   type: object
 *                   properties:
 *                     periodCount:
 *                       type: integer
 *                       example: 0
 *                       description: "기간 내 코퍼스 수"
 *                     totalCount:
 *                       type: integer
 *                       example: 5
 *                       description: "총 코퍼스 수"
 *                   description: "코퍼스 통계"
 *                 contactStats:
 *                   type: object
 *                   properties:
 *                     periodCount:
 *                       type: integer
 *                       example: 0
 *                       description: "기간 내 연락처 수"
 *                     totalCount:
 *                       type: integer
 *                       example: 14
 *                       description: "총 연락처 수"
 *                   description: "연락처 통계"
 *                 statiscsChartData:
 *                   type: array
 *                   items:
 *                     type: object
 *                     properties:
 *                       date:
 *                         type: string
 *                         example: "2025-09-15"
 *                         description: "날짜"
 *                       datas:
 *                         type: array
 *                         items:
 *                           type: integer
 *                         example: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
 *                         description: "시간별 데이터 (24시간)"
 *                   description: "통계 차트 데이터"
 *               description: "오늘 사용량 통계"

 *     Usage1WeekResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 registrationStats:
 *                   $ref: '#/components/schemas/RegistrationStats'
 *                 durationStats:
 *                   $ref: '#/components/schemas/DurationStats'
 *                 statisticsData:
 *                   type: object
 *                   additionalProperties:
 *                     $ref: '#/components/schemas/DailyStats'
 *                   description: "일별 통계 데이터 (7일간)"
 *                 downloadStats:
 *                   $ref: '#/components/schemas/DownloadStats'
 *                 sharedStats:
 *                   $ref: '#/components/schemas/SharedStats'
 *                 reSummaryStats:
 *                   $ref: '#/components/schemas/ReSummaryStats'
 *                 corpusStats:
 *                   $ref: '#/components/schemas/CorpusStats'
 *                 contactStats:
 *                   $ref: '#/components/schemas/ContactStats'
 *                 statiscsChartData:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/WeeklyChartData'
 *                   description: "주간 통계 차트 데이터"
 *               description: "1주일 사용량 통계"

 *     UsageMonthResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 registrationStats:
 *                   $ref: '#/components/schemas/RegistrationStats'
 *                 durationStats:
 *                   $ref: '#/components/schemas/DurationStats'
 *                 statisticsData:
 *                   type: object
 *                   additionalProperties:
 *                     $ref: '#/components/schemas/DailyStats'
 *                   description: "일별 통계 데이터 (30일간)"
 *                 downloadStats:
 *                   $ref: '#/components/schemas/DownloadStats'
 *                 sharedStats:
 *                   $ref: '#/components/schemas/SharedStats'
 *                 reSummaryStats:
 *                   $ref: '#/components/schemas/ReSummaryStats'
 *                 corpusStats:
 *                   $ref: '#/components/schemas/CorpusStats'
 *                 contactStats:
 *                   $ref: '#/components/schemas/ContactStats'
 *                 statiscsChartData:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/MonthlyChartData'
 *                   description: "월간 통계 차트 데이터"
 *               description: "1개월 사용량 통계"

 *     Usage3MonthResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 registrationStats:
 *                   $ref: '#/components/schemas/RegistrationStats'
 *                 durationStats:
 *                   $ref: '#/components/schemas/DurationStats'
 *                 statisticsData:
 *                   type: object
 *                   additionalProperties:
 *                     $ref: '#/components/schemas/DailyStats'
 *                   description: "일별 통계 데이터 (90일간)"
 *                 downloadStats:
 *                   $ref: '#/components/schemas/DownloadStats'
 *                 sharedStats:
 *                   $ref: '#/components/schemas/SharedStats'
 *                 reSummaryStats:
 *                   $ref: '#/components/schemas/ReSummaryStats'
 *                 corpusStats:
 *                   $ref: '#/components/schemas/CorpusStats'
 *                 contactStats:
 *                   $ref: '#/components/schemas/ContactStats'
 *                 statiscsChartData:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/MonthlyChartData'
 *                   description: "3개월 통계 차트 데이터"
 *               description: "3개월 사용량 통계"

 *     Usage6MonthResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 registrationStats:
 *                   $ref: '#/components/schemas/RegistrationStats'
 *                 durationStats:
 *                   $ref: '#/components/schemas/DurationStats'
 *                 statisticsData:
 *                   type: object
 *                   additionalProperties:
 *                     $ref: '#/components/schemas/DailyStats'
 *                   description: "일별 통계 데이터 (180일간)"
 *                 downloadStats:
 *                   $ref: '#/components/schemas/DownloadStats'
 *                 sharedStats:
 *                   $ref: '#/components/schemas/SharedStats'
 *                 reSummaryStats:
 *                   $ref: '#/components/schemas/ReSummaryStats'
 *                 corpusStats:
 *                   $ref: '#/components/schemas/CorpusStats'
 *                 contactStats:
 *                   $ref: '#/components/schemas/ContactStats'
 *                 statiscsChartData:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/MonthlyChartData'
 *                   description: "6개월 통계 차트 데이터"
 *               description: "6개월 사용량 통계"

 *     RegistrationStats:
 *       type: object
 *       properties:
 *         record:
 *           type: integer
 *           example: 0
 *           description: "녹음 등록 수"
 *         upload:
 *           type: integer
 *           example: 4
 *           description: "업로드 등록 수"
 *         total:
 *           type: integer
 *           example: 4
 *           description: "총 등록 수"
 *       description: "등록 통계"

 *     DurationStats:
 *       type: object
 *       properties:
 *         unit:
 *           type: string
 *           example: "ms"
 *           description: "시간 단위"
 *         recordDuration:
 *           type: integer
 *           example: 0
 *           description: "녹음 시간"
 *         uploadDuration:
 *           type: integer
 *           example: 2317648
 *           description: "업로드 시간"
 *         total:
 *           type: integer
 *           example: 2317648
 *           description: "총 시간"
 *       description: "시간 통계"

 *     DailyStats:
 *       type: object
 *       properties:
 *         record:
 *           type: integer
 *           example: 0
 *           description: "녹음 수"
 *         upload:
 *           type: integer
 *           example: 0
 *           description: "업로드 수"
 *       description: "일별 통계"

 *     DownloadStats:
 *       type: object
 *       properties:
 *         media:
 *           type: integer
 *           example: 2
 *           description: "미디어 다운로드 수"
 *         document:
 *           type: integer
 *           example: 6
 *           description: "문서 다운로드 수"
 *         total:
 *           type: integer
 *           example: 8
 *           description: "총 다운로드 수"
 *       description: "다운로드 통계"

 *     SharedStats:
 *       type: object
 *       properties:
 *         incoming:
 *           type: integer
 *           example: 0
 *           description: "받은 공유 수"
 *         outgoing:
 *           type: integer
 *           example: 2
 *           description: "보낸 공유 수"
 *       description: "공유 통계"

 *     ReSummaryStats:
 *       type: object
 *       properties:
 *         large:
 *           type: integer
 *           example: 8
 *           description: "대용량 재요약 수"
 *         medium:
 *           type: integer
 *           example: 0
 *           description: "중용량 재요약 수"
 *         small:
 *           type: integer
 *           example: 2
 *           description: "소용량 재요약 수"
 *         total:
 *           type: integer
 *           example: 10
 *           description: "총 재요약 수"
 *       description: "재요약 통계"

 *     CorpusStats:
 *       type: object
 *       properties:
 *         periodCount:
 *           type: integer
 *           example: 1
 *           description: "기간 내 코퍼스 수"
 *         totalCount:
 *           type: integer
 *           example: 5
 *           description: "총 코퍼스 수"
 *       description: "코퍼스 통계"

 *     ContactStats:
 *       type: object
 *       properties:
 *         periodCount:
 *           type: integer
 *           example: 1
 *           description: "기간 내 연락처 수"
 *         totalCount:
 *           type: integer
 *           example: 14
 *           description: "총 연락처 수"
 *       description: "연락처 통계"

 *     TermsConsentResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 isAgreementEnforced:
 *                   type: boolean
 *                   example: true
 *                   description: "약관 동의 강제 여부"
 *                 needConsent:
 *                   type: boolean
 *                   example: false
 *                   description: "동의 필요 여부"
 *                 publishedTerms:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/TermsItem'
 *                   description: "발행된 약관 목록"
 *               description: "약관별 동의 상태 정보"

 *     TermsItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "약관 고유 식별자"
 *           description: "약관 ID"
 *         title:
 *           type: string
 *           example: "서비스 이용약관"
 *           description: "약관 제목"
 *         content:
 *           type: string
 *           example: "약관 내용"
 *           description: "약관 내용"
 *         isRequired:
 *           type: boolean
 *           example: true
 *           description: "필수 약관 여부"
 *         category:
 *           $ref: '#/components/schemas/TermsCategory'
 *         version:
 *           type: string
 *           example: "1.0"
 *           description: "약관 버전"
 *         publishedAt:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "약관 발행일"
 *         latestAgreement:
 *           $ref: '#/components/schemas/TermsAgreement'
 *         isConsented:
 *           type: boolean
 *           example: true
 *           description: "동의 여부"

 *     TermsCategory:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "카테고리 고유 식별자"
 *           description: "카테고리 ID"
 *         name:
 *           type: string
 *           example: "필수약관"
 *           description: "카테고리명"
 *         priority:
 *           type: integer
 *           example: 1
 *           description: "우선순위"

 *     TermsAgreement:
 *       type: object
 *       nullable: true
 *       properties:
 *         id:
 *           type: string
 *           example: "동의 고유 식별자"
 *           description: "동의 ID"
 *         status:
 *           type: string
 *           enum: [CONSENTED, DECLINED]
 *           example: "CONSENTED"
 *           description: "동의 상태"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "동의 생성 시간"

 *     TermsAgreementRequest:
 *       type: object
 *       required:
 *         - agreements
 *       properties:
 *         agreements:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/AgreementItem'
 *           description: "동의할 약관 목록"

 *     AgreementItem:
 *       type: object
 *       required:
 *         - termsId
 *         - status
 *       properties:
 *         termsId:
 *           type: string
 *           example: "약관 고유 식별자"
 *           description: "약관 ID"
 *         status:
 *           type: string
 *           enum: [CONSENTED, DECLINED]
 *           example: "CONSENTED"
 *           description: "동의 상태"

 *     TermsAgreementResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 createdCount:
 *                   type: integer
 *                   example: 2
 *                   description: "생성된 동의서 수"
 *                 skippedCount:
 *                   type: integer
 *                   example: 0
 *                   description: "건너뛴 동의서 수"
 *                 createdAgreements:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/CreatedAgreement'
 *                   description: "생성된 동의서 목록"
 *               description: "약관 동의서 제출 결과"

 *     CreatedAgreement:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "동의 고유 식별자"
 *           description: "동의 ID"
 *         termsId:
 *           type: string
 *           example: "약관 고유 식별자"
 *           description: "약관 ID"
 *         status:
 *           type: string
 *           enum: [CONSENTED, DECLINED]
 *           example: "CONSENTED"
 *           description: "동의 상태"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "동의 생성 시간"

 *     WeeklyChartData:
 *       type: object
 *       properties:
 *         date:
 *           type: string
 *           example: "2025-09-09"
 *           description: "날짜"
 *         datas:
 *           type: array
 *           items:
 *             type: integer
 *           example: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
 *           description: "시간별 데이터 (24시간)"
 *       description: "주간 차트 데이터"

 *     MonthlyChartData:
 *       type: object
 *       properties:
 *         date:
 *           type: string
 *           example: "2025-08-16"
 *           description: "날짜"
 *         data:
 *           type: integer
 *           example: 0
 *           description: "일별 데이터"
 *       description: "월간 차트 데이터"

 *     CorpusListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/CorpusItem'
 *               description: "코퍼스 목록"

 *     CorpusItem:
 *       type: object
 *       properties:
 *         id:
 *           type: integer
 *           example: 145
 *           description: "코퍼스 ID"
 *         workspaceId:
 *           type: string
 *           example: "워크스페이스 고유 식별자"
 *           description: "워크스페이스 ID"
 *         source:
 *           type: string
 *           example: "원문 텍스트"
 *           description: "원문"
 *         target:
 *           type: string
 *           example: "번역문 텍스트"
 *           description: "번역문"
 *         memo:
 *           type: string
 *           example: "메모 내용"
 *           description: "메모"
 *         lang:
 *           type: string
 *           example: "ko"
 *           description: "언어 코드"
 *         isUsed:
 *           type: boolean
 *           example: true
 *           description: "사용 여부"
 *         creatorId:
 *           type: string
 *           example: "생성자 고유 식별자"
 *           description: "생성자 ID"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-10T07:07:54.905Z"
 *           description: "생성 시간"
 *         updaterId:
 *           type: string
 *           example: "수정자 고유 식별자"
 *           description: "수정자 ID"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-10T07:07:54.905Z"
 *           description: "수정 시간"

 *     CorpusCheckResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/CorpusItem'
 *               description: "코퍼스 확인 결과"

 *     CorpusUpdateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/CorpusItem'
 *               description: "수정된 코퍼스 정보"

 *     ChatListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 count:
 *                   type: integer
 *                   example: 1
 *                   description: "총 채팅 수"
 *                 list:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/ChatItem'
 *                   description: "채팅 목록"
 *               description: "채팅 목록 데이터"

 *     ChatItem:
 *       type: object
 *       properties:
 *         chatId:
 *           type: string
 *           example: "채팅 세션 ID"
 *           description: "채팅 세션 ID"
 *         title:
 *           type: string
 *           example: "회의록 추진 방법"
 *           description: "채팅 제목"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-16T05:44:45.773Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-16T05:44:45.773Z"
 *           description: "수정 시간"

 *     ChatDetailResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 chatId:
 *                   type: string
 *                   example: "채팅 세션 ID"
 *                   description: "채팅 세션 ID"
 *                 createAt:
 *                   type: string
 *                   format: date-time
 *                   example: "2025-09-16T05:44:45.773Z"
 *                   description: "생성 시간"
 *                 updateAt:
 *                   type: string
 *                   format: date-time
 *                   example: "2025-09-16T05:44:45.773Z"
 *                   description: "수정 시간"
 *                 attachedContents:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/AttachedContent'
 *                   description: "첨부된 콘텐츠 목록"
 *                 messages:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/ChatMessage'
 *                   description: "채팅 메시지 목록"
 *               description: "채팅 상세 정보"

 *     AttachedContent:
 *       type: object
 *       properties:
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         type:
 *           type: string
 *           example: "AUDIO"
 *           description: "콘텐츠 타입 (AUDIO, VIDEO, RECORD)"
 *         title:
 *           type: string
 *           example: "인구 감소와 지역 소멸 문제에 대한 정책적 대응 방안 논의"
 *           description: "콘텐츠 제목"
 *         editedTitle:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "편집된 제목"
 *         isRecord:
 *           type: boolean
 *           example: false
 *           description: "녹음 여부"
 *         fileName:
 *           type: string
 *           example: "행안부 토론회.mp3"
 *           description: "파일명"
 *         shareUsers:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               email:
 *                 type: string
 *                 example: "member@example.com"
 *                 description: "공유 사용자 이메일"
 *               role:
 *                 type: string
 *                 example: "VIEWER"
 *                 description: "공유 사용자 권한 (OWNER, EDITOR, VIEWER)"
 *           description: "공유 사용자 목록"

 *     ChatMessage:
 *       type: object
 *       properties:
 *         idx:
 *           type: integer
 *           example: 0
 *           description: "메시지 인덱스"
 *         isBot:
 *           type: boolean
 *           example: false
 *           description: "봇 메시지 여부"
 *         message:
 *           type: string
 *           example: "첨부된 회의들에서 A프로젝트 이슈를 정리해줘"
 *           description: "메시지 내용"
 *         citations:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/Citation'
 *           description: "인용 정보 (봇 메시지에만 포함)"

 *     Citation:
 *       type: object
 *       properties:
 *         label:
 *           type: string
 *           example: "1"
 *           description: "인용 라벨"
 *         quote:
 *           type: string
 *           example: "외부 협력사 데이터 연동이 지연되어 일정 조정이 필요하다고 했으며"
 *           description: "인용된 텍스트"
 *         linkContentId:
 *           type: string
 *           example: "59493bb8-4a72-4586-9613-e547f3fc93ba"
 *           description: "연결된 콘텐츠 ID"

 *     NoticeListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/NoticeItem'
 *               description: "공지사항 목록"

 *     NoticeItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "공지사항 고유 식별자"
 *           description: "공지사항 ID"
 *         title:
 *           type: string
 *           example: "공지사항 제목"
 *           description: "공지사항 제목"
 *         content:
 *           type: string
 *           example: "<p>공지사항 내용</p>"
 *           description: "공지사항 내용 (HTML 형식)"
 *         level:
 *           type: string
 *           enum: [WORKSPACE, SYSTEM]
 *           example: "WORKSPACE"
 *           description: "공지사항 레벨 (WORKSPACE: 워크스페이스, SYSTEM: 시스템)"
 *         isOnce:
 *           type: boolean
 *           example: true
 *           description: "일회성 공지 여부"
 *         ignoreDays:
 *           type: integer
 *           example: 1
 *           description: "무시 가능 일수"
 *         postAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-11T17:10:00.000Z"
 *           description: "게시 시작 시간"
 *         withdrawalAt:
 *           type: string
 *           format: date-time
 *           nullable: true
 *           example: "2025-09-18T16:05:00.000Z"
 *           description: "게시 종료 시간 (null이면 무제한)"

 *     FolderItemsResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 folderId:
 *                   type: string
 *                   example: "폴더 고유 식별자"
 *                   description: "폴더 ID"
 *                 folderName:
 *                   type: string
 *                   example: "폴더명"
 *                   description: "폴더명"
 *                 folderType:
 *                   type: string
 *                   enum: [root, received, sent, error, success]
 *                   example: "root"
 *                   description: "폴더 타입 (root: 내회의록, received: 공유받은, sent: 공유한, error: 미완성, success: 완료된)"
 *                 items:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/FolderContentItem'
 *                   description: "폴더 내 콘텐츠 목록"
 *                 pagination:
 *                   $ref: '#/components/schemas/FolderPagination'
 *               description: "폴더 아이템 목록"

 *     FolderContentItem:
 *       type: object
 *       properties:
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         title:
 *           type: string
 *           example: "콘텐츠 제목"
 *           description: "콘텐츠 제목"
 *         editedTitle:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "편집된 제목"
 *         fileName:
 *           type: string
 *           example: "파일명.flac"
 *           description: "파일명"
 *         type:
 *           type: string
 *           example: "AUDIO"
 *           description: "콘텐츠 타입 (AUDIO, VIDEO, RECORD)"
 *         hashTag:
 *           type: array
 *           items:
 *             type: string
 *           example: ["해시태그1", "해시태그2"]
 *           description: "해시태그 목록"
 *         isRecord:
 *           type: boolean
 *           example: false
 *           description: "녹음 여부"
 *         duration:
 *           type: integer
 *           example: 10800909
 *           description: "재생 시간 (밀리초)"
 *         creatorPID:
 *           type: string
 *           example: "생성자 고유 식별자"
 *           description: "생성자 PID"
 *         creatorEmail:
 *           type: string
 *           example: "member@example.com"
 *           description: "생성자 이메일"
 *         creatorNickName:
 *           type: string
 *           example: "회원닉네임"
 *           description: "생성자 닉네임"
 *         creatorThumbnailUrl:
 *           type: string
 *           example: "https://example.com/member-thumbnail.jpg"
 *           description: "생성자 썸네일 URL"
 *         transcribeStatus:
 *           type: string
 *           example: "DONE"
 *           description: "전사 상태 (DONE, PROCESSING, FAILED)"
 *         meetingStartTime:
 *           type: string
 *           format: date-time
 *           example: "2025-09-12T02:01:23.150Z"
 *           description: "회의 시작 시간"
 *         meetingEndTime:
 *           type: string
 *           format: date-time
 *           example: "2025-09-12T05:01:24.057Z"
 *           description: "회의 종료 시간"
 *         isShared:
 *           type: boolean
 *           example: false
 *           description: "공유 여부"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-12T02:01:23.150Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-12T02:20:09.435Z"
 *           description: "수정 시간"
 *         userAccessRole:
 *           type: string
 *           example: "OWNER"
 *           description: "사용자 접근 권한 (OWNER, EDITOR, VIEWER)"
 *         shareUsers:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               nickName:
 *                 type: string
 *                 example: "공유자닉네임"
 *                 description: "공유 사용자 닉네임"
 *               thumbnailUrl:
 *                 type: string
 *                 example: "https://example.com/shared-user-thumbnail.jpg"
 *                 description: "공유 사용자 썸네일 URL"
 *               role:
 *                 type: string
 *                 example: "VIEWER"
 *                 description: "공유 사용자 권한 (OWNER, EDITOR, VIEWER)"
 *           description: "공유 사용자 목록"
 *         speakerInfo:
 *           $ref: '#/components/schemas/SpeakerInfoList'

 *     FolderPagination:
 *       type: object
 *       properties:
 *         currentPage:
 *           type: integer
 *           example: 1
 *           description: "현재 페이지"
 *         lastPage:
 *           type: integer
 *           example: 5
 *           description: "마지막 페이지"
 *         _count:
 *           type: integer
 *           example: 50
 *           description: "총 아이템 수"
 *         hasNext:
 *           type: boolean
 *           example: true
 *           description: "다음 페이지 존재 여부"
 *         hasPrev:
 *           type: boolean
 *           example: false
 *           description: "이전 페이지 존재 여부"

 *     FolderListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/FolderItem'
 *               description: "폴더 목록 (가상 폴더: root, success, error, received + 사용자 생성 폴더)"

 *     FolderItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "폴더 고유 식별자"
 *           description: "폴더 ID (가상 폴더: root, success, error, received)"
 *         name:
 *           type: string
 *           example: "프로젝트 회의록"
 *           description: "폴더명"
 *         createAt:
 *           type: string
 *           format: date-time
 *           nullable: true
 *           example: "2025-09-15T06:42:48.988Z"
 *           description: "폴더 생성 시간 (실제 폴더에만 존재)"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           nullable: true
 *           example: "2025-09-15T06:42:48.988Z"
 *           description: "폴더 수정 시간 (실제 폴더에만 존재)"
 *         _count:
 *           type: integer
 *           example: 15
 *           description: "폴더 내 콘텐츠 개수"

 *     FolderCreateRequest:
 *       type: object
 *       required:
 *         - name
 *       properties:
 *         name:
 *           type: string
 *           minLength: 1
 *           maxLength: 20
 *           example: "새 프로젝트"
 *           description: "폴더명 (1-20자)"

 *     FolderCreateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/FolderItem'
 *               description: "생성된 폴더 정보"

 *     ContentMoveRequest:
 *       type: object
 *       required:
 *         - folderId
 *         - contentIds
 *       properties:
 *         folderId:
 *           type: string
 *           example: "폴더 고유 식별자"
 *           description: "이동할 폴더 ID (root, received, success, 실제 폴더 ID만 가능, sent/error 폴더로 이동 불가)"
 *         contentIds:
 *           type: array
 *           items:
 *             type: string
 *           minItems: 1
 *           example: ["콘텐츠 고유 식별자1", "콘텐츠 고유 식별자2"]
 *           description: "이동할 콘텐츠 ID 목록"

 *     FolderUpdateRequest:
 *       type: object
 *       required:
 *         - name
 *       properties:
 *         name:
 *           type: string
 *           minLength: 1
 *           maxLength: 20
 *           example: "수정된 폴더명"
 *           description: "폴더명 (1-20자)"

 *     FolderUpdateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/FolderItem'
 *               description: "수정된 폴더 정보"

 *     FolderDeleteResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               description: "폴더 삭제 결과 (빈 객체)"

 *     ContentListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/ContentListItem'
 *               description: "콘텐츠 목록"

 *     ContentListItem:
 *       type: object
 *       properties:
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         title:
 *           type: string
 *           example: "콘텐츠 제목"
 *           description: "콘텐츠 제목"
 *         editedTitle:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "편집된 제목"
 *         fileName:
 *           type: string
 *           example: "파일명.flac"
 *           description: "파일명"
 *         type:
 *           type: string
 *           example: "RECORD"
 *           description: "콘텐츠 타입 (AUDIO, VIDEO, RECORD)"
 *         hashTag:
 *           type: array
 *           items:
 *             type: string
 *           example: ["해시태그1", "해시태그2"]
 *           description: "해시태그 목록"
 *         manualTag:
 *           type: array
 *           items:
 *             type: string
 *           example: []
 *           description: "수동 태그 목록"
 *         isRecord:
 *           type: boolean
 *           example: true
 *           description: "녹음 여부"
 *         duration:
 *           type: integer
 *           example: 3596800
 *           description: "재생 시간 (밀리초)"
 *         creatorPID:
 *           type: string
 *           example: "생성자 고유 식별자"
 *           description: "생성자 PID"
 *         creatorEmail:
 *           type: string
 *           example: "member@example.com"
 *           description: "생성자 이메일"
 *         creatorNickName:
 *           type: string
 *           example: "회원닉네임"
 *           description: "생성자 닉네임"
 *         creatorThumbnailUrl:
 *           type: string
 *           example: "https://example.com/member-thumbnail.jpg"
 *           description: "생성자 썸네일 URL"
 *         transcribeStatus:
 *           type: string
 *           example: "DONE"
 *           description: "전사 상태 (DONE, PROCESSING, ERROR)"
 *         meetingStartTime:
 *           type: string
 *           format: date-time
 *           example: "2025-08-06T07:30:00.000Z"
 *           description: "회의 시작 시간"
 *         meetingEndTime:
 *           type: string
 *           format: date-time
 *           example: "2025-08-11T08:30:05.800Z"
 *           description: "회의 종료 시간"
 *         isShared:
 *           type: boolean
 *           example: true
 *           description: "공유 여부"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-08-11T08:31:16.579Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-17T09:43:08.108Z"
 *           description: "수정 시간"
 *         userAccessRole:
 *           type: string
 *           example: "EDITOR"
 *           description: "사용자 접근 권한 (OWNER, EDITOR, VIEWER)"
 *         folderName:
 *           type: string
 *           example: "/"
 *           description: "폴더명"
 *         shareUsers:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ShareUser'
 *           description: "공유 사용자 목록"
 *         speakerInfo:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/SpeakerInfo'
 *           description: "화자 정보 목록"

 *     ShareUser:
 *       type: object
 *       properties:
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         role:
 *           type: string
 *           example: "EDITOR"
 *           description: "공유 권한 (OWNER, EDITOR, VIEWER)"
 *         email:
 *           type: string
 *           example: "member@example.com"
 *           description: "사용자 이메일"
 *         nickName:
 *           type: string
 *           example: "회원닉네임"
 *           description: "사용자 닉네임"
 *         thumbnailUrl:
 *           type: string
 *           example: "https://example.com/member-thumbnail.jpg"
 *           description: "사용자 썸네일 URL"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-08-20T03:21:19.809Z"
 *           description: "공유 생성 시간"

 *     SpeakerInfo:
 *       type: object
 *       properties:
 *         speakerId:
 *           type: integer
 *           example: 1
 *           description: "화자 ID"
 *         name:
 *           type: string
 *           example: "참석자 1"
 *           description: "화자 이름"
 *         displayName:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "화자 표시명"
 *         pid:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "화자 PID"

 *     HomeContent:
 *       allOf:
 *         - $ref: '#/components/schemas/Content'
 *         - type: object
 *           properties:
 *             manualTag:
 *               type: array
 *               items:
 *                 type: string
 *               example: []
 *               description: "수동 태그 목록"

 *     BookmarkSegment:
 *       type: object
 *       properties:
 *         segmentId:
 *           type: string
 *           example: "세그먼트 고유 식별자"
 *           description: "세그먼트 ID"
 *         speakerId:
 *           type: integer
 *           example: 1
 *           description: "화자 ID"
 *         startTime:
 *           type: integer
 *           example: 160
 *           description: "시작 시간 (밀리초)"
 *         endTime:
 *           type: integer
 *           example: 28520
 *           description: "종료 시간 (밀리초)"
 *         duration:
 *           type: integer
 *           example: 22610
 *           description: "지속 시간 (밀리초)"
 *         text:
 *           type: string
 *           example: "북마크 된 세그먼트 텍스트"
 *           description: "세그먼트 텍스트"
 *         name:
 *           type: string
 *           example: "참석자 1"
 *           description: "화자 이름"

 *     BookmarkSummaryTime:
 *       type: object
 *       properties:
 *         index:
 *           type: integer
 *           example: 1
 *           description: "요약 인덱스"
 *         topic:
 *           type: string
 *           example: "북마크 된 주제"
 *           description: "요약 주제"
 *         time:
 *           type: string
 *           example: "00:00:00 ~ 00:01:25"
 *           description: "시간 범위"
 *         summary:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/BookmarkSummaryItem'
 *           description: "요약 내용 목록"
 *         issues:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/BookmarkIssueItem'
 *           description: "이슈 목록"
 *         tasks:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/BookmarkTaskItem'
 *           description: "작업 목록"

 *     BookmarkSummaryItem:
 *       type: object
 *       properties:
 *         timestamp:
 *           type: string
 *           example: "00:00:00"
 *           description: "타임스탬프"
 *         content:
 *           type: string
 *           example: "북마크 된 요약 내용"
 *           description: "요약 내용"

 *     BookmarkIssueItem:
 *       type: object
 *       properties:
 *         timestamp:
 *           type: string
 *           example: "00:00:56"
 *           description: "타임스탬프"
 *         content:
 *           type: string
 *           example: "북마크 된 이슈 내용"
 *           description: "이슈 내용"
 *         reason:
 *           type: string
 *           example: "북마크 된 이슈 이유"
 *           description: "이슈 이유"

 *     BookmarkTaskItem:
 *       type: object
 *       properties:
 *         content:
 *           type: string
 *           example: "북마크 된 작업 내용"
 *           description: "작업 내용"
 *         timestamp:
 *           type: string
 *           example: "00:00:56"
 *           description: "타임스탬프"

 *     ContentDetailResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/ContentDetailData'
 *               description: "콘텐츠 상세 정보"

 *     ContentDetailData:
 *       type: object
 *       properties:
 *         status:
 *           type: string
 *           example: "DONE"
 *           description: "처리 상태"
 *         summarySize:
 *           type: string
 *           example: "large"
 *           description: "요약 크기"
 *         aiResult:
 *           $ref: '#/components/schemas/AiResult'
 *         speakerInfo:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/SpeakerInfo'
 *           description: "화자 정보 목록"
 *         summaryTime:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentSummaryTimeItem'
 *           description: "시간별 요약 목록"
 *         mergedSegments:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentMergedSegment'
 *           description: "병합된 세그먼트 목록"
 *         file:
 *           $ref: '#/components/schemas/ContentFile'
 *         bookmarks:
 *           type: array
 *           items:
 *             type: object
 *           example: []
 *           description: "북마크 목록"
 *         memos:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentMemo'
 *           description: "메모 목록"
 *         meta:
 *           $ref: '#/components/schemas/ContentMeta'
 *         highlights:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentHighlight'
 *           description: "하이라이트 목록"
 *         contentLifecycleActions:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentLifecycleAction'
 *           description: "라이프사이클 액션 목록"

 *     ContentSummaryTimeItem:
 *       type: object
 *       properties:
 *         index:
 *           type: integer
 *           example: 1
 *           description: "요약 인덱스"
 *         time:
 *           type: string
 *           example: "00:07:52 ~ 00:11:30"
 *           description: "시간 범위"
 *         topic:
 *           type: string
 *           example: "A6000과 월비드 비교 및 사용성 논의"
 *           description: "요약 주제"
 *         summary:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentSummaryItem'
 *           description: "요약 내용 목록"
 *         issues:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentIssueItem'
 *           description: "이슈 목록"
 *         tasks:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentTaskItem'
 *           description: "작업 목록"

 *     ContentSummaryItem:
 *       type: object
 *       properties:
 *         timestamp:
 *           type: string
 *           example: "00:07:52"
 *           description: "타임스탬프"
 *         content:
 *           type: string
 *           example: "A6000과 월비드의 비교 필요성에 대한 논의가 있었음."
 *           description: "요약 내용"

 *     ContentIssueItem:
 *       type: object
 *       properties:
 *         timestamp:
 *           type: string
 *           example: "00:27:00"
 *           description: "타임스탬프"
 *         content:
 *           type: string
 *           example: "컴퓨터 교체의 목적이 불명확하여 개선 여부가 불확실함."
 *           description: "이슈 내용"
 *         reason:
 *           type: string
 *           example: "컴퓨터 교체의 목적이 명확하지 않으면, 교체 후에도 문제 해결이 어려울 수 있음."
 *           description: "이슈 이유"

 *     ContentTaskItem:
 *       type: object
 *       properties:
 *         content:
 *           type: string
 *           example: "작업 내용"
 *           description: "작업 내용"
 *         timestamp:
 *           type: string
 *           example: "00:00:56"
 *           description: "타임스탬프"

 *     ContentMergedSegment:
 *       type: object
 *       properties:
 *         segmentId:
 *           type: string
 *           example: "세그먼트 고유 식별자"
 *           description: "세그먼트 ID"
 *         speakerId:
 *           type: integer
 *           example: 2
 *           description: "화자 ID"
 *         text:
 *           type: string
 *           example: "A6000이랑 월비드 그 올이나 송년 어떻게 보면 비교를 하시겠습니까?"
 *           description: "세그먼트 텍스트"
 *         startTime:
 *           type: integer
 *           example: 472360
 *           description: "시작 시간 (밀리초)"
 *         endTime:
 *           type: integer
 *           example: 485460
 *           description: "종료 시간 (밀리초)"
 *         duration:
 *           type: integer
 *           example: 4330
 *           description: "지속 시간 (밀리초)"

 *     ContentFile:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "파일 고유 식별자"
 *           description: "파일 ID"
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         fileName:
 *           type: string
 *           example: "A.Biz_w_rec_20250811_163009.flac"
 *           description: "파일명"
 *         fileKey:
 *           type: string
 *           example: "파일 키"
 *           description: "파일 키"
 *         mimeType:
 *           type: string
 *           example: "audio/flac"
 *           description: "MIME 타입"
 *         sttStatus:
 *           type: string
 *           example: "WAITING"
 *           description: "STT 상태"
 *         duration:
 *           type: integer
 *           example: 3596800
 *           description: "재생 시간 (밀리초)"
 *         isLock:
 *           type: boolean
 *           example: false
 *           description: "잠금 여부"
 *         linkNoteId:
 *           type: string
 *           example: "노트 고유 식별자"
 *           description: "연결된 노트 ID"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-08-11T08:31:16.637Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-17T09:43:08.108Z"
 *           description: "수정 시간"

 *     ContentMemo:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "메모 고유 식별자"
 *           description: "메모 ID"
 *         key:
 *           type: string
 *           example: "topics"
 *           description: "메모 키"
 *         itemId:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "아이템 ID"
 *         text:
 *           type: string
 *           example: "ggg"
 *           description: "메모 텍스트"
 *         time:
 *           type: string
 *           format: date-time
 *           example: "2025-09-23T02:21:43.061Z"
 *           description: "메모 시간"
 *         data:
 *           type: array
 *           items:
 *             type: string
 *           example: ["A6000과 월비드 비교 및 사용성 논의", "노트북 사용 및 통일 필요성"]
 *           description: "메모 데이터"

 *     ContentMeta:
 *       type: object
 *       properties:
 *         shareUsers:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentShareUser'
 *           description: "공유 사용자 목록"
 *         permission:
 *           type: string
 *           example: "EDITOR"
 *           description: "사용자 권한"
 *         clientLanguage:
 *           type: string
 *           example: "ko"
 *           description: "클라이언트 언어"
 *         type:
 *           type: string
 *           example: "RECORD"
 *           description: "콘텐츠 타입"
 *         title:
 *           type: string
 *           example: "A6000과 월비드 비교 및 노트북 사용 통일 논의"
 *           description: "콘텐츠 제목"
 *         isMobile:
 *           type: boolean
 *           example: false
 *           description: "모바일 여부"
 *         isRecord:
 *           type: boolean
 *           example: true
 *           description: "녹음 여부"
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         creatorPID:
 *           type: string
 *           example: "생성자 고유 식별자"
 *           description: "생성자 PID"
 *         editedTitle:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "편집된 제목"
 *         lastUpdator:
 *           type: string
 *           example: "김사용자"
 *           description: "마지막 수정자"
 *         meetingEndTime:
 *           type: string
 *           format: date-time
 *           example: "2025-08-11T08:30:05.800Z"
 *           description: "회의 종료 시간"
 *         meetingStartTime:
 *           type: string
 *           format: date-time
 *           example: "2025-08-06T07:30:00.000Z"
 *           description: "회의 시작 시간"
 *         isTimeChangeNeeded:
 *           type: boolean
 *           example: false
 *           description: "시간 변경 필요 여부"

 *     ContentShareUser:
 *       type: object
 *       properties:
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         role:
 *           type: string
 *           example: "EDITOR"
 *           description: "공유 권한"
 *         email:
 *           type: string
 *           example: "user@example.com"
 *           description: "사용자 이메일"
 *         nickName:
 *           type: string
 *           example: "사용자1234"
 *           description: "사용자 닉네임"
 *         thumbnailUrl:
 *           type: string
 *           example: "https://example.com/user-avatar.jpg"
 *           description: "사용자 썸네일 URL"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-08-20T03:21:19.809Z"
 *           description: "공유 생성 시간"

 *     ContentHighlight:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "하이라이트 고유 식별자"
 *           description: "하이라이트 ID"
 *         startTime:
 *           type: number
 *           example: 0.0
 *           description: "시작 시간"
 *         endTime:
 *           type: number
 *           example: 5.0
 *           description: "종료 시간"
 *         text:
 *           type: string
 *           example: "중요한 내용"
 *           description: "하이라이트 텍스트"
 *         color:
 *           type: string
 *           example: "#ffff00"
 *           description: "하이라이트 색상"

 *     ContentLifecycleAction:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "액션 고유 식별자"
 *           description: "액션 ID"
 *         action:
 *           type: string
 *           example: "CREATE"
 *           description: "액션 타입"
 *         timestamp:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "액션 시간"

 *     CalendarListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/CalendarItem'
 *               description: "캘린더 목록"

 *     CalendarItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "캘린더 고유 식별자"
 *           description: "캘린더 ID"
 *         meetingStartDate:
 *           type: string
 *           format: date-time
 *           example: "2025-10-15T01:30:00.000Z"
 *           description: "회의 시작 시간"
 *         provider:
 *           type: string
 *           enum: [OUTLOOK, TIMBLO]
 *           example: "TIMBLO"
 *           description: "캘린더 제공자 (OUTLOOK: 외부 캘린더, TIMBLO: 내부 캘린더)"
 *         summary:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "회의 요약 정보"
 *         title:
 *           type: string
 *           example: "생성한 캘린더"
 *           description: "회의 제목"
 *         reminderMinutes:
 *           type: integer
 *           example: 0
 *           description: "알림 시간 (분 단위)"
 *         content:
 *           $ref: '#/components/schemas/CalendarContent'
 *           description: "연결된 콘텐츠 정보 ( NULL -> 아직 연결되지 않음 )"
 *         attachedContents:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/CalendarAttachedContent'
 *           description: "첨부된 콘텐츠 목록"

 *     CalendarContent:
 *       type: object
 *       nullable: true
 *       properties:
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         title:
 *           type: string
 *           example: "인구 감소와 지역 소멸 문제에 대한 정책적 대응 방안 논의"
 *           description: "콘텐츠 제목"
 *         editedTitle:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "편집된 제목"
 *         type:
 *           type: string
 *           enum: [VIDEO, AUDIO, RECORD]
 *           example: "VIDEO"
 *           description: "콘텐츠 타입"
 *         hashTag:
 *           type: array
 *           items:
 *             type: string
 *           example: ["인구 감소", "지역 소멸", "정책 대응"]
 *           description: "해시태그 목록"
 *         manualTag:
 *           type: array
 *           items:
 *             type: string
 *           example: []
 *           description: "수동 태그 목록"
 *         duration:
 *           type: integer
 *           example: 579412
 *           description: "재생 시간 (밀리초)"
 *         transcribeStatus:
 *           type: string
 *           enum: [DONE, PROCESSING, FAILED]
 *           example: "DONE"
 *           description: "전사 상태"
 *         meetingStartTime:
 *           type: string
 *           format: date-time
 *           example: "2025-10-13T00:39:00.000Z"
 *           description: "회의 시작 시간"
 *         creatorPID:
 *           type: string
 *           example: "생성자 고유 식별자"
 *           description: "생성자 PID"
 *         creatorNickName:
 *           type: string
 *           example: "사용자1234"
 *           description: "생성자 닉네임"
 *         creatorEmail:
 *           type: string
 *           example: "user@example.com"
 *           description: "생성자 이메일"
 *         creatorThumbnailUrl:
 *           type: string
 *           example: "https://example.com/user-avatar.jpg"
 *           description: "생성자 썸네일 URL"
 *         userAccessRole:
 *           type: string
 *           enum: [OWNER, EDITOR, VIEWER]
 *           example: "OWNER"
 *           description: "사용자 접근 권한"
 *         folderName:
 *           type: string
 *           example: "내 회의록"
 *           description: "폴더명"
 *         shareUsers:
 *           $ref: '#/components/schemas/ShareUsers'
 *         speakerInfo:
 *           $ref: '#/components/schemas/SpeakerInfoList'
 *         isShared:
 *           type: boolean
 *           example: false
 *           description: "공유 여부"

 *     CalendarAttachedContent:
 *       type: object
 *       properties:
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         type:
 *           type: string
 *           enum: [RECORD, VIDEO, AUDIO]
 *           example: "RECORD"
 *           description: "콘텐츠 타입"
 *         title:
 *           type: string
 *           example: "재요약이 필요한 콘텐츠"
 *           description: "콘텐츠 제목"
 *         editedTitle:
 *           type: string
 *           nullable: true
 *           example: "재요약이 필요한 콘텐츠-변경-2=-"
 *           description: "편집된 제목"
 *         isRecord:
 *           type: boolean
 *           example: true
 *           description: "녹음 여부"
 *         fileName:
 *           type: string
 *           example: "A.Biz_w_rec_20250930_174724.flac"
 *           description: "파일명"
 *         shareUsers:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               email:
 *                 type: string
 *                 example: "test@example.com"
 *                 description: "공유 사용자 이메일"
 *               role:
 *                 type: string
 *                 enum: [VIEWER, EDITOR, OWNER]
 *                 example: "VIEWER"
 *                 description: "공유 사용자 권한"
 *           description: "공유 사용자 목록"

 *     UploadContentRequest:
 *       type: object
 *       properties:
 *         isRecord:
 *           type: string
 *           description: 녹음 여부
 *           example: "true"
 *         lang:
 *           type: string
 *           description: 언어 코드
 *           example: "ko"
 *         attendeeNum:
 *           type: integer
 *           description: 참석자 수
 *           example: 99
 *         type:
 *           type: string
 *           description: 파일 타입
 *           example: "audio"
 *         summary:
 *           type: string
 *           description: 요약 크기
 *           example: "medium"
 *         folderId:
 *           type: string
 *           description: 폴더 ID
 *           example: "folder-uuid"
 *       required:
 *         - lang

 *     UploadContentResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 content:
 *                   $ref: '#/components/schemas/Content'
 *                 uploadId:
 *                   type: string
 *                   example: "업로드 고유 식별자"
 *                   description: "업로드 ID"

 *     ChatNewResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/ChatNewData'
 *               description: "새로운 채팅 생성 결과"

 *     ChatNewData:
 *       type: object
 *       properties:
 *         chatId:
 *           type: string
 *           example: "채팅 세션 ID"
 *           description: "채팅 세션 ID"
 *         title:
 *           type: string
 *           example: "새로운 챗봇"
 *           description: "채팅 제목"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-26T03:18:21.853Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-26T03:18:21.853Z"
 *           description: "수정 시간"
 *         response:
 *           $ref: '#/components/schemas/ChatResponse'
 *           description: "채팅 응답 정보"

 *     ChatResponse:
 *       type: object
 *       properties:
 *         idx:
 *           type: integer
 *           example: 1
 *           description: "메시지 인덱스"
 *         isBot:
 *           type: boolean
 *           example: true
 *           description: "봇 메시지 여부"
 *         message:
 *           type: string
 *           example: "AI가 생성한 응답 메시지"
 *           description: "메시지 내용"
 *         citations:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/Citation'
 *           description: "인용 정보 목록"

 *     ChatQueryResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/ChatQueryData'
 *               description: "채팅 쿼리 응답 데이터"

 *     ChatQueryData:
 *       type: object
 *       properties:
 *         chatId:
 *           type: string
 *           example: "채팅 세션 고유 식별자"
 *           description: "채팅 세션 ID"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-26T03:11:33.390Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-09-26T03:11:33.390Z"
 *           description: "수정 시간"
 *         response:
 *           $ref: '#/components/schemas/ChatResponse'
 *           description: "채팅 응답 정보"

 *     ChatDeleteResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               description: "채팅 삭제 결과 (빈 객체)"

 *     NotificationManagementResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/NotificationSetting'
 *               description: "알림 설정 목록"

 *     NotificationSetting:
 *       type: object
 *       properties:
 *         channel:
 *           type: string
 *           enum: [PUSH, EMAIL]
 *           example: "PUSH"
 *           description: "알림 채널 (PUSH: 푸시 알림, EMAIL: 이메일 알림)"
 *         eventType:
 *           type: string
 *           enum: [CONTENT_CREATE, CONTENT_SHARE, CONTENT_RECYCLE, CONTENT_RESUMMARY, CALENDAR_REMIND]
 *           example: "CONTENT_CREATE"
 *           description: "이벤트 타입 (CONTENT_CREATE: 콘텐츠 생성, CONTENT_SHARE: 콘텐츠 공유, CONTENT_RECYCLE: 콘텐츠 삭제, CONTENT_RESUMMARY: 콘텐츠 재요약, CALENDAR_REMIND: 캘린더 알림)"
 *         isUsed:
 *           type: boolean
 *           example: false
 *           description: "알림 사용 여부"

 *     NotificationManagementUpdateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 notifications:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/NotificationSetting'
 *                   description: "알림 설정 목록"

 *     NotificationSettingDetail:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "알림 설정 고유 식별자"
 *           description: "알림 설정 ID"
 *         pid:
 *           type: string
 *           example: "회원 고유 식별자"
 *           description: "사용자 PID"
 *         channel:
 *           type: string
 *           enum: [PUSH, EMAIL]
 *           example: "PUSH"
 *           description: "알림 채널 (PUSH: 푸시 알림, EMAIL: 이메일 알림)"
 *         eventType:
 *           type: string
 *           enum: [CONTENT_CREATE, CONTENT_SHARE, CONTENT_DELETE, CONTENT_RESUMMARY, CALENDAR_REMIND]
 *           example: "CONTENT_DELETE"
 *           description: "이벤트 타입 (CONTENT_CREATE: 콘텐츠 생성, CONTENT_SHARE: 콘텐츠 공유, CONTENT_DELETE: 콘텐츠 삭제, CONTENT_RESUMMARY: 콘텐츠 재요약, CALENDAR_REMIND: 캘린더 알림)"
 *         isUsed:
 *           type: boolean
 *           example: true
 *           description: "알림 사용 여부"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-10-10T06:33:41.781Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-10-10T06:33:41.781Z"
 *           description: "수정 시간"

 *     CalendarCreateRequest:
 *       type: object
 *       required:
 *         - title
 *         - meetingStartDate
 *       properties:
 *         title:
 *           type: string
 *           example: "생성한 캘린더"
 *           description: "회의 제목"
 *         meetingStartDate:
 *           type: string
 *           example: "2025-10-10 08:47:24"
 *           description: "회의 시작 시간 (YYYY-MM-DD HH:mm:ss 형식)"
 *         attachedContents:
 *           type: array
 *           items:
 *             type: string
 *           example: ["354a5028-d737-40ec-a489-cda53c0c1322"]
 *           description: "첨부할 콘텐츠 ID 목록"
 *         reminderMinutes:
 *           type: integer
 *           enum: [0, 10, 30, 60, 180, 1440]
 *           example: 0
 *           description: "알림 시간 (분 단위, 0, 10, 30, 60, 180, 1440 값 사용 가능)"

 *     CalendarCreateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/CalendarCreateData'
 *               description: "생성된 캘린더 정보"

 *     CalendarCreateData:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "캘린더 고유 식별자"
 *           description: "캘린더 ID"
 *         meetingStartDate:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "회의 시작 시간"
 *         provider:
 *           type: string
 *           enum: [OUTLOOK, TIMBLO]
 *           example: "TIMBLO"
 *           description: "캘린더 제공자 (OUTLOOK: 외부 캘린더, TIMBLO: 내부 캘린더)"
 *         summary:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "회의 요약 정보"
 *         title:
 *           type: string
 *           example: "회의 제목"
 *           description: "회의 제목"
 *         reminderMinutes:
 *           type: integer
 *           example: 0
 *           description: "알림 시간 (분 단위, 0, 10, 30, 60, 180, 1440 값 사용 가능)"
 *         content:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "회의 내용"
 *         attachedContents:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/CalendarAttachedContent'
 *           description: "첨부된 콘텐츠 목록"

 *     WebcalIntegrateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/WebcalIntegrateItem'
 *               description: "Webcal 통합 목록"

 *     WebcalIntegrateItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "통합 설정 고유 식별자"
 *           description: "통합 설정 ID"
 *         pid:
 *           type: string
 *           example: "회원 고유 식별자"
 *           description: "사용자 PID"
 *         url:
 *           type: string
 *           example: "https://calendar.google.com/calendar/ical/user@example.com/private-abc123/basic.ics"
 *           description: "Webcal URL"
 *         type:
 *           type: string
 *           enum: [WEBCAL]
 *           example: "WEBCAL"
 *           description: "통합 타입"
 *         provider:
 *           type: string
 *           enum: [GOOGLE, OUTLOOK, APPLE, OTHER]
 *           example: "GOOGLE"
 *           description: "캘린더 제공자"
 *         lastSyncedAt:
 *           type: string
 *           format: date-time
 *           example: "2025-10-14T05:32:31.540Z"
 *           description: "마지막 동기화 시간"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-10-14T05:32:31.541Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-10-14T05:32:31.541Z"
 *           description: "수정 시간"

 *     CalendarDisconnectResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/WebcalIntegrateItem'
 *               description: "연결 해제된 캘린더 통합 설정 목록"

*     CalendarSyncResponse:
*       allOf:
*         - $ref: '#/components/schemas/Success'
*         - type: object
*           properties:
*             data:
*               $ref: '#/components/schemas/CalendarIntegrateData'
*               description: "캘린더 동기화 데이터"


 *     CalendarIntegrateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/CalendarIntegrateData'
 *               description: "캘린더 통합 데이터"

 *     CalendarIntegrateData:
 *       type: object
 *       properties:
 *         lastSyncedAt:
 *           type: string
 *           format: date-time
 *           example: "2025-10-16T00:48:28.492Z"
 *           description: "마지막 동기화 시간"
 *         integrateCalendars:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/CalendarIntegrateItem'
 *           description: "통합 캘린더 이벤트 목록"

 *     CalendarIntegrateItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "이벤트 고유 식별자"
 *           description: "캘린더 이벤트 ID"
 *         provider:
 *           type: string
 *           enum: [OUTLOOK, GOOGLE, APPLE, OTHER]
 *           example: "OUTLOOK"
 *           description: "캘린더 제공자"
 *         description:
 *           type: string
 *           nullable: true
 *           example: "회의 상세 설명"
 *           description: "이벤트 설명"
 *         start:
 *           type: string
 *           format: date-time
 *           example: "2025-10-15T01:30:00.000Z"
 *           description: "이벤트 시작 시간"
 *         summary:
 *           type: string
 *           example: "산돌3층|회의록 녹음기앱 개발회의"
 *           description: "이벤트 제목"
 *         isLoaded:
 *           type: boolean
 *           example: false
 *           description: "로드 완료 여부"

 *     CalendarDeleteResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               description: "캘린더 삭제 결과 (빈 객체)"

 *     CalendarUpdateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/CalendarItem'
 *               description: "업데이트된 캘린더 정보"

 *     CalendarUpdateRequest:
 *       type: object
 *       properties:
 *         reminderMinutes:
 *           type: integer
 *           minimum: 0
 *           example: 14
 *           description: "알림 시간 (분 단위, 0 이상의 값)"

 *     ContactListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 _count:
 *                   type: integer
 *                   example: 100
 *                   description: "전체 주소록 수"
 *                 currentPage:
 *                   type: integer
 *                   example: 1
 *                   description: "현재 페이지 번호"
 *                 lastPage:
 *                   type: integer
 *                   example: 5
 *                   description: "마지막 페이지 번호"
 *                 contacts:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/ContactItem'
 *                   description: "주소록 목록"

 *     ContactItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "연락처 고유 식별자"
 *           description: "연락처 ID"
 *         pid:
 *           type: string
 *           example: "사용자 고유 식별자"
 *           description: "사용자 PID"
 *         name:
 *           type: string
 *           nullable: true
 *           example: "홍길동"
 *           description: "사용자 이름"
 *         nickName:
 *           type: string
 *           nullable: true
 *           example: "홍길동"
 *           description: "사용자 닉네임"
 *         thumbnailUrl:
 *           type: string
 *           nullable: true
 *           example: "https://example.com/thumbnail.jpg"
 *           description: "사용자 썸네일 URL"
 *         email:
 *           type: string
 *           format: email
 *           nullable: true
 *           example: "hong@example.com"
 *           description: "연락처 이메일"
 *         department:
 *           type: string
 *           nullable: true
 *           example: "개발팀"
 *           description: "부서"
 *         position:
 *           type: string
 *           nullable: true
 *           example: "부장"
 *           description: "직책"
 *         memo:
 *           type: string
 *           nullable: true
 *           example: "메모 내용"
 *           description: "메모"
 *         isFavorite:
 *           type: boolean
 *           example: false
 *           description: "즐겨찾기 여부"
 *         isRecycle:
 *           type: boolean
 *           example: false
 *           description: "휴지통 이동 여부"
 *         labels:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContactLabel'
 *           description: "연결된 라벨 목록 (createAt 오름차순 정렬)"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "수정 시간"

 *     ContactLabel:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "라벨 고유 식별자"
 *           description: "라벨 ID"
 *         name:
 *           type: string
 *           example: "업무"
 *           description: "라벨 이름"
 *         color:
 *           type: string
 *           example: "#FFFFFF"
 *           description: "라벨 색상"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "수정 시간"

 *     ContactTargetUser:
 *       type: object
 *       nullable: true
 *       properties:
 *         pid:
 *           type: string
 *           example: "사용자 고유 식별자"
 *           description: "사용자 PID"
 *         email:
 *           type: string
 *           format: email
 *           example: "hong@example.com"
 *           description: "사용자 이메일"
 *         nickName:
 *           type: string
 *           nullable: true
 *           example: "홍길동"
 *           description: "사용자 닉네임"
 *         thumbnailUrl:
 *           type: string
 *           nullable: true
 *           example: "https://example.com/thumbnail.jpg"
 *           description: "사용자 썸네일 URL"

 *     ContactCreateRequest:
 *       type: object
 *       required:
 *         - email
 *       properties:
 *         email:
 *           type: string
 *           format: email
 *           example: "hong@example.com"
 *           description: "이메일"
 *         department:
 *           type: string
 *           maxLength: 64
 *           example: "개발팀"
 *           description: "부서 (최대 64자)"
 *         position:
 *           type: string
 *           maxLength: 64
 *           example: "부장"
 *           description: "직책 (최대 64자)"
 *         memo:
 *           type: string
 *           maxLength: 512
 *           example: "메모 내용"
 *           description: "메모 (최대 512자)"
 *         labelIds:
 *           type: array
 *           items:
 *             type: string
 *           example: ["라벨 고유 식별자1", "라벨 고유 식별자2"]
 *           description: "라벨 ID 목록"

 *     ContactCreateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/ContactItem'
 *               description: "생성된 연락처 정보"
 *
 *     ContactLabelingRequest:
 *       type: object
 *       required:
 *         - contactId
 *         - labelIds
 *       properties:
 *         contactId:
 *           type: string
 *           example: "주소록 고유 식별자"
 *           description: "라벨을 연결할 주소록 ID"
 *         labelIds:
 *           type: array
 *           items:
 *             type: string
 *           example: ["라벨 고유 식별자1", "라벨 고유 식별자2"]
 *           description: "연결할 라벨 ID 목록 (빈 배열 전달 시 모든 라벨 연결 해제)"
 *
 *     ContactDeleteRequest:
 *       type: object
 *       required:
 *         - contactIds
 *       properties:
 *         contactIds:
 *           type: array
 *           items:
 *             type: string
 *           minItems: 1
 *           example: ["주소록 고유 식별자1", "주소록 고유 식별자2"]
 *           description: "삭제할 주소록 ID 목록"
 *
 *     ContactBulkCreateRequest:
 *       type: object
 *       properties:
 *         emails:
 *           type: array
 *           items:
 *             type: string
 *             format: email
 *           example: ["user1@example.com", "user2@example.com"]
 *           description: "등록할 이메일 목록 (선택사항)"
 *         users:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               email:
 *                 type: string
 *                 format: email
 *                 example: "user@example.com"
 *                 description: "이메일 주소"
 *               department:
 *                 type: string
 *                 example: "개발팀"
 *                 description: "부서"
 *               position:
 *                 type: string
 *                 example: "시니어 개발자"
 *                 description: "직급"
 *               memo:
 *                 type: string
 *                 example: "우수 개발자"
 *                 description: "메모"
 *           example: [{"email": "user@example.com", "department": "개발팀", "position": "시니어 개발자", "memo": "우수 개발자"}]
 *           description: "등록할 사용자 정보 목록 (선택사항)"
 *         labelIds:
 *           type: array
 *           items:
 *             type: string
 *           example: ["라벨 고유 식별자1", "라벨 고유 식별자2"]
 *           description: "연결할 라벨 ID 목록 (선택사항)"
 *         file:
 *           type: string
 *           format: binary
 *           description: "엑셀 파일 (.xlsx만 지원) - 첫 번째 행은 헤더(이메일(필수), 라벨1(선택) ~ 라벨5(선택), 비고(선택))"
 *
 *     ContactBulkItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "주소록 고유 식별자"
 *           description: "주소록 ID"
 *         pid:
 *           type: string
 *           example: "사용자 고유 식별자"
 *           description: "대상 사용자 PID (targetUser에서 펼쳐짐)"
 *         name:
 *           type: string
 *           example: "홍길동"
 *           description: "사용자 이름 (targetUser에서 펼쳐짐)"
 *         nickName:
 *           type: string
 *           example: "길동이"
 *           description: "사용자 닉네임 (targetUser에서 펼쳐짐)"
 *         thumbnailUrl:
 *           type: string
 *           nullable: true
 *           example: "https://example.com/thumbnail.jpg"
 *           description: "사용자 썸네일 URL (targetUser에서 펼쳐짐)"
 *         email:
 *           type: string
 *           format: email
 *           example: "user@example.com"
 *           description: "이메일 주소"
 *         department:
 *           type: string
 *           example: "개발팀"
 *           description: "부서"
 *         position:
 *           type: string
 *           example: "시니어 개발자"
 *           description: "직급"
 *         memo:
 *           type: string
 *           example: "우수 개발자"
 *           description: "메모"
 *         isFavorite:
 *           type: boolean
 *           example: false
 *           description: "즐겨찾기 여부"
 *         isRecycle:
 *           type: boolean
 *           example: false
 *           description: "휴지통 여부"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-01-01T00:00:00.000Z"
 *           description: "수정 시간"
 *         labels:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               id:
 *                 type: string
 *                 example: "라벨 고유 식별자"
 *                 description: "라벨 ID"
 *               name:
 *                 type: string
 *                 example: "중요한 연락처"
 *                 description: "라벨 이름"
 *           example: [{"id": "라벨 고유 식별자", "name": "중요한 연락처"}]
 *           description: "연결된 라벨 목록 (label.label로 변환됨)"
 *
 *     BulkContactItem:
 *       type: object
 *       properties:
 *         email:
 *           type: string
 *           example: "user@example.com"
 *           description: "이메일 주소"
 *         label1:
 *           type: string
 *           example: "스페셜팀"
 *           description: "라벨 1"
 *         label2:
 *           type: string
 *           example: "개발팀"
 *           description: "라벨 2"
 *         label3:
 *           type: string
 *           example: ""
 *           description: "라벨 3"
 *         label4:
 *           type: string
 *           example: ""
 *           description: "라벨 4"
 *         label5:
 *           type: string
 *           example: ""
 *           description: "라벨 5"
 *         memo:
 *           type: string
 *           example: "비고 내용"
 *           description: "메모"
 *
 *     BulkContactRowError:
 *       type: object
 *       properties:
 *         field:
 *           type: string
 *           example: "이메일"
 *           description: "에러가 발생한 필드"
 *         reason:
 *           type: string
 *           example: "워크스페이스에 가입되지 않은 이메일입니다"
 *           description: "에러 이유"
 *
 *     BulkContactRowResult:
 *       type: object
 *       description: "데이터 행 결과 (index: 2부터)"
 *       properties:
 *         index:
 *           type: integer
 *           example: 2
 *           description: "엑셀 행 번호 (2부터 시작)"
 *         isPassed:
 *           type: boolean
 *           example: true
 *           description: "검증 통과 여부"
 *         contact:
 *           $ref: '#/components/schemas/BulkContactItem'
 *         errors:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/BulkContactRowError'
 *           description: "행별 에러 목록 (isPassed가 false인 경우에만 존재)"
 *
 *     BulkContactSummary:
 *       type: object
 *       properties:
 *         totalCount:
 *           type: integer
 *           example: 10
 *           description: "전체 요청 행 수"
 *         successCount:
 *           type: integer
 *           example: 7
 *           description: "성공한 행 수"
 *         failedCount:
 *           type: integer
 *           example: 3
 *           description: "실패한 행 수"
 *
 *     ContactBulkCreateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 summary:
 *                   $ref: '#/components/schemas/BulkContactSummary'
 *                 columns:
 *                   type: object
 *                   properties:
 *                     email:
 *                       type: string
 *                       example: "이메일"
 *                     label1:
 *                       type: string
 *                       example: "라벨1"
 *                     label2:
 *                       type: string
 *                       example: "라벨2"
 *                     label3:
 *                       type: string
 *                       example: "라벨3"
 *                     label4:
 *                       type: string
 *                       example: "라벨4"
 *                     label5:
 *                       type: string
 *                       example: "라벨5"
 *                     memo:
 *                       type: string
 *                       example: "비고"
 *                   description: "컬럼명 매핑 (필드명: 한글명)"
 *                 results:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/BulkContactRowResult'
 *                   description: "행별 처리 결과"
 *                 errors:
 *                   type: array
 *                   items:
 *                     type: string
 *                   example: ["2번 행 '이메일': 워크스페이스에 가입되지 않은 이메일입니다. 회원가입 여부 확인 후 다시 등록해주세요.", "3번 행 '라벨2': 존재하지 않은 라벨입니다. 사전에 라벨을 등록해주세요."]
 *                   description: "전체 에러 메시지 목록"
 *
 *     # 템플릿 관련 스키마
 *     Template:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "템플릿 고유 식별자"
 *           description: "템플릿 ID"
 *         inputType:
 *           type: string
 *           example: "timbel_stt"
 *           description: "입력 타입"
 *         name:
 *           type: string
 *           example: "기본 회의록"
 *           description: "템플릿 이름"
 *         description:
 *           type: string
 *           example: "기본으로 제공되는 회의록"
 *           description: "템플릿 설명"
 *         preview:
 *           type: string
 *           example: "기본 회의록"
 *           description: "템플릿 미리보기"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-03T05:27:03.386Z"
 *           description: "생성 시간"
 *         isFavorite:
 *           type: boolean
 *           example: true
 *           description: "즐겨찾기 여부"
 *
 *     TemplateCategory:
 *       type: object
 *       properties:
 *         categoryId:
 *           type: string
 *           example: "DEFAULT-CATEGORY"
 *           description: "카테고리 ID"
 *         name:
 *           type: string
 *           example: "기본 템플릿"
 *           description: "카테고리 이름"
 *         templates:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/Template'
 *           description: "템플릿 목록"
 *
 *     TemplateCategoryResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/TemplateCategory'
 *               description: "템플릿 카테고리 목록"
 *
 *     TemplateFavorite:
 *       type: object
 *       properties:
 *         idx:
 *           type: integer
 *           example: 8
 *           description: "템플릿 즐겨찾기 인덱스"
 *         templateId:
 *           type: string
 *           example: "템플릿 고유 식별자"
 *           description: "템플릿 ID"
 *         version:
 *           type: string
 *           example: "DEFAULT"
 *           description: "템플릿 버전"
 *         memberId:
 *           type: string
 *           example: "회원 고유 식별자"
 *           description: "회원 ID"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-06T01:32:53.523Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-06T01:32:53.523Z"
 *           description: "수정 시간"
 *
 *     TemplateFavoriteResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/TemplateFavorite'
 *               description: "템플릿 즐겨찾기 정보"
 *
 *     MergedContentInfo:
 *       type: object
 *       properties:
 *         title:
 *           type: string
 *           example: "회의록 합치기 - 2025-11-10 15:16:49"
 *           description: "콘텐츠 제목"
 *         type:
 *           type: string
 *           example: "MERGED_CONTENT"
 *           description: "콘텐츠 타입"
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         hashTag:
 *           type: array
 *           items:
 *             type: string
 *           example: []
 *           description: "해시태그 목록"
 *         manualTag:
 *           type: array
 *           items:
 *             type: string
 *           example: []
 *           description: "수동 태그 목록"
 *         duration:
 *           type: integer
 *           example: 27809
 *           description: "재생 시간 (밀리초)"
 *         isShared:
 *           type: boolean
 *           example: false
 *           description: "공유 여부"
 *         meetingStartTime:
 *           type: string
 *           format: date-time
 *           example: "2025-11-10T06:16:49.376Z"
 *           description: "회의 시작 시간"
 *         meetingEndTime:
 *           type: string
 *           format: date-time
 *           example: "2025-11-10T06:16:49.375Z"
 *           description: "회의 종료 시간"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-10T06:16:49.376Z"
 *           description: "생성 시간"
 *
 *     MergeContentData:
 *       type: object
 *       properties:
 *         content:
 *           $ref: '#/components/schemas/MergedContentInfo'
 *           description: "합쳐진 콘텐츠 정보"
 *         transcribe:
 *           type: object
 *           nullable: true
 *           example: null
 *           description: "전사 정보"
 *
 *     MergeContentResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/MergeContentData'
 *               description: "콘텐츠 합치기 결과"
 *
 *     ContentDetailTemplateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/ContentDetailTemplateData'
 *               description: "콘텐츠 상세 정보 (템플릿 버전)"
 *
 *     # 콘텐츠 상세 정보 스키마
 *     ContentDetailTemplateData:
 *       type: object
 *       properties:
 *         status:
 *           type: string
 *           example: "DONE"
 *           description: "처리 상태"
 *         summarySize:
 *           type: string
 *           example: "medium"
 *           description: "요약 크기"
 *         aiResult:
 *           $ref: '#/components/schemas/AiResultTemplate'
 *         speakerInfo:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/SpeakerInfo'
 *           description: "화자 정보 목록"
 *         summaryTime:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentSummaryTimeItem'
 *           description: "시간별 요약 목록"
 *         mergedSegments:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentMergedSegment'
 *           description: "병합된 세그먼트 목록"
 *         file:
 *           $ref: '#/components/schemas/ContentFile'
 *         bookmarks:
 *           type: array
 *           items:
 *             type: object
 *           example: []
 *           description: "북마크 목록"
 *         memos:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentMemo'
 *           description: "메모 목록"
 *         meta:
 *           $ref: '#/components/schemas/ContentMetaTemplate'
 *         highlights:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentHighlight'
 *           description: "하이라이트 목록"
 *         contentLifecycleActions:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentLifecycleAction'
 *           description: "라이프사이클 액션 목록"
 *
 *     AiResultTemplate:
 *       type: object
 *       properties:
 *         summary:
 *           type: array
 *           items:
 *             type: string
 *           example: ["short summary 테스트 데이터 입니다."]
 *           description: "요약 목록"
 *         keywords:
 *           type: array
 *           items:
 *             type: string
 *           example: ["keyword_1", "keyword_2", "keyword_3"]
 *           description: "키워드 목록"
 *         templateSummary:
 *           type: string
 *           example: "## AI 혁명과 반도체 산업의 혁신 기회 및 전략\n- 키워드: AI, 반도체, 혁신..."
 *           description: "템플릿 기반 요약 (마크다운 형식)"
 *         issues:
 *           type: array
 *           items:
 *             type: string
 *           example: ["해당 회의록에 생성된 데이터는 현재 테스트 데이터로 실제 전송예정인 정보를 표시 합니다."]
 *           description: "이슈 목록"
 *
 *     LinkedContent:
 *       type: object
 *       properties:
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         fileName:
 *           type: string
 *           example: "A.Biz_w_rec_20250827_093440.flac"
 *           description: "파일명"
 *         title:
 *           type: string
 *           example: "short summary 테스트 데이터 입니다."
 *           description: "콘텐츠 제목"
 *         editedTitle:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "편집된 제목"
 *         type:
 *           type: string
 *           enum: [AUDIO, VIDEO, RECORD, MERGED_CONTENT]
 *           example: "AUDIO"
 *           description: "콘텐츠 타입"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-06T00:34:09.454Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-06T00:35:31.823Z"
 *           description: "수정 시간"
 *         lastUpdator:
 *           type: string
 *           example: "jwpark1234"
 *           description: "마지막 수정자"
 *         speakerInfo:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/SpeakerInfo'
 *           description: "화자 정보 목록"
 *         shareUsers:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentShareUser'
 *           description: "공유 사용자 목록"
 *         mergedSegments:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentMergedSegment'
 *           description: "병합된 세그먼트 목록"
 *         contentLifecycleActions:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentLifecycleAction'
 *           description: "라이프사이클 액션 목록"
 *
 *     ContentMetaTemplate:
 *       type: object
 *       properties:
 *         shareUsers:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/ContentShareUser'
 *           description: "공유 사용자 목록"
 *         permission:
 *           type: string
 *           example: "OWNER"
 *           description: "사용자 권한"
 *         clientLanguage:
 *           type: string
 *           example: "ko"
 *           description: "클라이언트 언어"
 *         type:
 *           type: string
 *           example: "MERGED_CONTENT"
 *           description: "콘텐츠 타입"
 *         title:
 *           type: string
 *           example: "short summary 테스트 데이터 입니다."
 *           description: "콘텐츠 제목"
 *         isMobile:
 *           type: boolean
 *           example: false
 *           description: "모바일 여부"
 *         isRecord:
 *           type: boolean
 *           example: false
 *           description: "녹음 여부"
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         creatorPID:
 *           type: string
 *           example: "생성자 고유 식별자"
 *           description: "생성자 PID"
 *         editedTitle:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "편집된 제목"
 *         lastUpdator:
 *           type: string
 *           example: "jwpark1234"
 *           description: "마지막 수정자"
 *         meetingEndTime:
 *           type: string
 *           format: date-time
 *           example: "2025-11-10T06:06:36.740Z"
 *           description: "회의 종료 시간"
 *         linkedContents:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/LinkedContent'
 *           description: "연결된 콘텐츠 목록 (MERGED_CONTENT 타입인 경우)"
 *         meetingStartTime:
 *           type: string
 *           format: date-time
 *           example: "2025-11-10T06:06:36.742Z"
 *           description: "회의 시작 시간"
 *         isTimeChangeNeeded:
 *           type: boolean
 *           example: true
 *           description: "시간 변경 필요 여부"
 *
 *     MemoCreateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/MemoData'
 *               description: "생성된 메모 정보"
 *
 *     MemoData:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "메모 고유 식별자"
 *           description: "메모 ID"
 *         contentId:
 *           type: string
 *           example: "콘텐츠 고유 식별자"
 *           description: "콘텐츠 ID"
 *         item:
 *           type: string
 *           example: "summaryTime"
 *           description: "메모 아이템 타입 (summaryTime, mergedSegments, topics, tasks, issues, summary 등)"
 *         itemId:
 *           type: string
 *           nullable: true
 *           example: null
 *           description: "아이템 ID"
 *         startTime:
 *           type: integer
 *           nullable: true
 *           example: null
 *           description: "시작 시간 (밀리초)"
 *         text:
 *           type: string
 *           example: "메모 내용"
 *           description: "메모 텍스트"
 *         isSecret:
 *           type: boolean
 *           example: false
 *           description: "비공개 여부"
 *         creatorId:
 *           type: string
 *           example: "생성자 고유 식별자"
 *           description: "생성자 ID"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-12T02:19:10.000Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-12T02:19:10.000Z"
 *           description: "수정 시간"
 *         deleteAt:
 *           type: string
 *           format: date-time
 *           nullable: true
 *           example: null
 *           description: "삭제 시간"
 *
 *     MemoSecretUpdateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 count:
 *                   type: integer
 *                   example: 1
 *                   description: "업데이트된 메모 수"
 *               description: "메모 비공개 설정 업데이트 결과"
 *
 *     MemoSecretUpdateByIdResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/MemoData'
 *               description: "업데이트된 메모 정보"
 *
 *     MemoTextUpdateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/MemoData'
 *               description: "업데이트된 메모 정보"
 *
 *     MemoCommentCreateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/MemoCommentData'
 *               description: "생성된 메모 댓글 정보"
 *
 *     MemoCommentData:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "댓글 고유 식별자"
 *           description: "댓글 ID"
 *         memoId:
 *           type: string
 *           example: "메모 고유 식별자"
 *           description: "메모 ID"
 *         text:
 *           type: string
 *           example: "댓글 내용"
 *           description: "댓글 텍스트"
 *         creatorId:
 *           type: string
 *           example: "생성자 고유 식별자"
 *           description: "생성자 ID"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-12T02:35:52.000Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-12T02:35:52.000Z"
 *           description: "수정 시간"
 *         deleteAt:
 *           type: string
 *           format: date-time
 *           nullable: true
 *           example: null
 *           description: "삭제 시간"
 *
 *     MemoCommentTextUpdateResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               $ref: '#/components/schemas/MemoCommentData'
 *               description: "업데이트된 메모 댓글 정보"
 *
 *     # 키워드 부스팅 관련 스키마
 *     KeywordBoostingItem:
 *       type: object
 *       properties:
 *         id:
 *           type: integer
 *           example: 1
 *           description: "키워드 부스팅 ID"
 *         keyword:
 *           type: string
 *           example: "키워드"
 *           description: "키워드"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-12T03:12:47.735Z"
 *           description: "생성 시간"
 *
 *     KeywordListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 keywords:
 *                   type: array
 *                   items:
 *                     $ref: '#/components/schemas/KeywordBoostingItem'
 *                   description: "키워드 부스팅 목록"
 *                 totalCount:
 *                   type: integer
 *                   example: 6
 *                   description: "전체 키워드 개수"
 *
 *     CreateKeywordBoostingRequest:
 *       type: object
 *       required:
 *         - keyword
 *       properties:
 *         keyword:
 *           type: string
 *           example: "한글"
 *           description: "키워드 (영어 문자 포함 불가)"
 *         isPostProcess:
 *           type: boolean
 *           example: false
 *           description: "후처리 여부 (기본값: false)"
 *         weight:
 *           type: number
 *           format: float
 *           example: 0.0
 *           description: "가중치 (기본값: 0.0)"
 *
 *     # 메모 목록 조회 관련 스키마
 *     MemoListResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 $ref: '#/components/schemas/MemoItem'
 *               description: "메모 목록"
 *
 *     MemoItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "메모 고유 식별자"
 *           description: "메모 ID"
 *         item:
 *           type: string
 *           example: "summaryTime"
 *           description: "메모 아이템 타입"
 *         itemId:
 *           type: string
 *           nullable: true
 *           example: "1"
 *           description: "아이템 ID"
 *         startTime:
 *           type: integer
 *           nullable: true
 *           example: null
 *           description: "시작 시간 (밀리초)"
 *         text:
 *           type: string
 *           example: "메모 내용"
 *           description: "메모 텍스트"
 *         isSecret:
 *           type: boolean
 *           example: false
 *           description: "비공개 여부"
 *         creator:
 *           $ref: '#/components/schemas/MemoCreator'
 *           description: "생성자 정보"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-13T01:08:36.000Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-13T01:09:19.000Z"
 *           description: "수정 시간"
 *         deleteAt:
 *           type: string
 *           format: date-time
 *           nullable: true
 *           example: null
 *           description: "삭제 시간"
 *         comments:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/MemoCommentItem'
 *           description: "댓글 목록"
 *
 *     MemoCreator:
 *       type: object
 *       properties:
 *         user:
 *           type: object
 *           properties:
 *             profile:
 *               $ref: '#/components/schemas/UserProfile'
 *               description: "사용자 프로필 정보"
 *
 *     UserProfile:
 *       type: object
 *       properties:
 *         pid:
 *           type: string
 *           example: "사용자 고유 식별자"
 *           description: "사용자 PID"
 *         name:
 *           type: string
 *           example: ""
 *           description: "사용자 이름"
 *         nickName:
 *           type: string
 *           example: "사용자 닉네임"
 *           description: "사용자 닉네임"
 *
 *     MemoCommentItem:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "댓글 고유 식별자"
 *           description: "댓글 ID"
 *         text:
 *           type: string
 *           example: "댓글 내용"
 *           description: "댓글 텍스트"
 *         creator:
 *           $ref: '#/components/schemas/MemoCreator'
 *           description: "생성자 정보"
 *         createAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-13T07:26:35.000Z"
 *           description: "생성 시간"
 *         updateAt:
 *           type: string
 *           format: date-time
 *           example: "2025-11-13T07:26:35.000Z"
 *           description: "수정 시간"
 *         deleteAt:
 *           type: string
 *           format: date-time
 *           nullable: true
 *           example: null
 *           description: "삭제 시간"
 *
 *     ContentRetryResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               example: {}
 *               description: "응답 데이터 (빈 객체)"
 *
 *     UploadTextContentResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               properties:
 *                 content:
 *                   $ref: '#/components/schemas/Content'
 *                   description: "업로드된 텍스트 콘텐츠 정보"
 *                 transcribe:
 *                   type: object
 *                   nullable: true
 *                   example: null
 *                   description: "전사 정보 (텍스트 업로드 시 null)"
 *
 * */
