/**
 * @swagger
 * components:
 *   schemas:
 *     # 콘텐츠 관련 스키마
 *     Content:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "content-uuid"
 *         title:
 *           type: string
 *           example: "회의록 제목"
 *         type:
 *           type: string
 *           example: "audio"
 *         status:
 *           type: string
 *           example: "completed"
 *         createdAt:
 *           type: string
 *           format: date-time
 *           example: "2024-01-01T00:00:00Z"
 *         updatedAt:
 *           type: string
 *           format: date-time
 *           example: "2024-01-01T00:00:00Z"
 *         fileSize:
 *           type: integer
 *           example: 1024000
 *         duration:
 *           type: number
 *           example: 3600.5
 *         language:
 *           type: string
 *           example: "ko"
 *         folderId:
 *           type: string
 *           example: "folder-uuid"
 *         isShared:
 *           type: boolean
 *           example: false
 *         shareUsers:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               email:
 *                 type: string
 *                 example: "user@example.com"
 *               role:
 *                 type: string
 *                 example: "VIEWER"
 *
 *     # 폴더 관련 스키마
 *     Folder:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "folder-uuid"
 *         name:
 *           type: string
 *           example: "폴더명"
 *         parentId:
 *           type: string
 *           nullable: true
 *           example: "parent-folder-uuid"
 *         createdAt:
 *           type: string
 *           format: date-time
 *           example: "2024-01-01T00:00:00Z"
 *         updatedAt:
 *           type: string
 *           format: date-time
 *           example: "2024-01-01T00:00:00Z"
 *         contentCount:
 *           type: integer
 *           example: 10
 *
 *     # 사용자 관련 스키마
 *     User:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "user-uuid"
 *         email:
 *           type: string
 *           example: "user@example.com"
 *         name:
 *           type: string
 *           example: "사용자명"
 *         role:
 *           type: string
 *           example: "MEMBER"
 *         createdAt:
 *           type: string
 *           format: date-time
 *           example: "2024-01-01T00:00:00Z"
 *         lastLoginAt:
 *           type: string
 *           format: date-time
 *           example: "2024-01-01T00:00:00Z"
 *
 *     # 공지사항 관련 스키마
 *     Notice:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "notice-uuid"
 *         title:
 *           type: string
 *           example: "공지사항 제목"
 *         content:
 *           type: string
 *           example: "공지사항 내용"
 *         isImportant:
 *           type: string
 *           enum: [Y, N]
 *           example: "Y"
 *         createdAt:
 *           type: string
 *           format: date-time
 *           example: "2024-01-01T00:00:00Z"
 *         updatedAt:
 *           type: string
 *           format: date-time
 *           example: "2024-01-01T00:00:00Z"
 *
 *     # 인박스 관련 스키마
 *     Inbox:
 *       type: object
 *       properties:
 *         id:
 *           type: string
 *           example: "inbox-uuid"
 *         title:
 *           type: string
 *           example: "알림 제목"
 *         message:
 *           type: string
 *           example: "알림 메시지"
 *         type:
 *           type: string
 *           example: "info"
 *         isRead:
 *           type: boolean
 *           example: false
 *         createdAt:
 *           type: string
 *           format: date-time
 *           example: "2024-01-01T00:00:00Z"
 *
 *     # 검색 관련 스키마
 *     SearchResult:
 *       type: object
 *       properties:
 *         contents:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/Content'
 *         totalCount:
 *           type: integer
 *           example: 100
 *         page:
 *           type: integer
 *           example: 1
 *         limit:
 *           type: integer
 *           example: 10
 *         totalPages:
 *           type: integer
 *           example: 10
 *
 *     # 페이징 관련 스키마
 *     Pagination:
 *       type: object
 *       properties:
 *         page:
 *           type: integer
 *           example: 1
 *         limit:
 *           type: integer
 *           example: 10
 *         totalCount:
 *           type: integer
 *           example: 100
 *         totalPages:
 *           type: integer
 *           example: 10
 *         hasNext:
 *           type: boolean
 *           example: true
 *         hasPrev:
 *           type: boolean
 *           example: false
 */

/**
 * @swagger
 * components:
 *   schemas:
 *     Bookmarks:
 *       type: object
 *       properties:
 *         mergedSegments:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               segmentId:
 *                 type: string
 *                 example: "세그먼트 고유 식별자"
 *                 description: "세그먼트 ID"
 *               speakerId:
 *                 type: integer
 *                 example: 1
 *                 description: "화자 ID"
 *               startTime:
 *                 type: integer
 *                 example: 160
 *                 description: "시작 시간 (밀리초)"
 *               endTime:
 *                 type: integer
 *                 example: 28520
 *                 description: "종료 시간 (밀리초)"
 *               duration:
 *                 type: integer
 *                 example: 22610
 *                 description: "지속 시간 (밀리초)"
 *               text:
 *                 type: string
 *                 example: "북마크 된 세그먼트 텍스트"
 *                 description: "세그먼트 텍스트"
 *               name:
 *                 type: string
 *                 example: "참석자 1"
 *                 description: "화자 이름"
 *           description: "병합된 세그먼트 목록"
 *         summaryTime:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               index:
 *                 type: integer
 *                 example: 1
 *                 description: "요약 인덱스"
 *               topic:
 *                 type: string
 *                 example: "북마크 된 주제"
 *                 description: "요약 주제"
 *               time:
 *                 type: string
 *                 example: "00:00:00 ~ 00:01:25"
 *                 description: "시간 범위"
 *               summary:
 *                 type: array
 *                 items:
 *                   type: object
 *                   properties:
 *                     timestamp:
 *                       type: string
 *                       example: "00:00:00"
 *                       description: "타임스탬프"
 *                     content:
 *                       type: string
 *                       example: "북마크 된 요약 내용"
 *                       description: "요약 내용"
 *                 description: "요약 내용 목록"
 *               issues:
 *                 type: array
 *                 items:
 *                   type: object
 *                   properties:
 *                     timestamp:
 *                       type: string
 *                       example: "00:00:56"
 *                       description: "타임스탬프"
 *                     content:
 *                       type: string
 *                       example: "북마크 된 이슈 내용"
 *                       description: "이슈 내용"
 *                     reason:
 *                       type: string
 *                       example: "북마크 된 이슈 이유"
 *                       description: "이슈 이유"
 *                 description: "이슈 목록"
 *               tasks:
 *                 type: array
 *                 items:
 *                   type: object
 *                   properties:
 *                     content:
 *                       type: string
 *                       example: "북마크 된 작업 내용"
 *                       description: "작업 내용"
 *                     timestamp:
 *                       type: string
 *                       example: "00:00:56"
 *                       description: "타임스탬프"
 *                 description: "작업 목록"
 *             description: "시간별 요약 목록"
 *         tasks:
 *           type: array
 *           items:
 *             type: string
 *           example: ["북마크 된 작업 내용"]
 *           description: "작업 목록"
 *         issues:
 *           type: array
 *           items:
 *             type: string
 *           example: ["북마크 된 이슈 내용"]
 *           description: "이슈 목록"
 *         summary:
 *           type: array
 *           items:
 *             type: string
 *           example: ["북마크 된 요약 내용"]
 *           description: "요약 목록"
 *         keywords:
 *           type: array
 *           items:
 *             type: string
 *           example: ["북마크 된 키워드 내용"]
 *           description: "키워드 목록"
 *         topics:
 *           type: array
 *           items:
 *             type: string
 *           example: ["북마크 된 토픽 내용"]
 *           description: "토픽 목록"
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
 *                 example: "참석자 1"
 *                 description: "화자 이름"
 *           description: "화자 정보 목록"

 *     # 공통 필드 스키마
 *     TimestampFields:
 *       type: object
 *       properties:
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

 *     # 공유 사용자 스키마
 *     ShareUser:
 *       type: object
 *       properties:
 *         email:
 *           type: string
 *           format: email
 *           example: "user@example.com"
 *           description: "사용자 이메일"
 *         role:
 *           type: string
 *           enum: [VIEWER, DOWNLOADER, EDITOR, OWNER]
 *           example: "VIEWER"
 *           description: "공유 권한"

 *     # 공유 사용자 목록 스키마
 *     ShareUsers:
 *       type: array
 *       items:
 *         $ref: '#/components/schemas/ShareUser'
 *       example: []
 *       description: "공유 사용자 목록"

 *     # 화자 정보 스키마 (확장된 버전)
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
 *           example: "화자 고유 식별자"
 *           description: "화자 PID"

 *     # 화자 정보 목록 스키마
 *     SpeakerInfoList:
 *       type: array
 *       items:
 *         $ref: '#/components/schemas/SpeakerInfo'
 *       example: []
 *       description: "화자 정보 목록"

 *     # 기본 Response 스키마 템플릿
 *     BaseResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: object
 *               description: "응답 데이터"

 *     # 배열 Response 스키마 템플릿
 *     BaseArrayResponse:
 *       allOf:
 *         - $ref: '#/components/schemas/Success'
 *         - type: object
 *           properties:
 *             data:
 *               type: array
 *               items:
 *                 type: object
 *               description: "응답 데이터 배열"
 */
