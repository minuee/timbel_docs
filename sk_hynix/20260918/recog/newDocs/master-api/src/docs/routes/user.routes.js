/**
 * @swagger
 * components:
 *   schemas:
 *     UsageResponse:
 *       type: object
 *       properties:
 *         message:
 *           type: string
 *           example: Success
 *         httpCode:
 *           type: integer
 *           example: 200
 *         data:
 *           type: object
 *           properties:
 *             totalUsage:
 *               type: integer
 *               example: 1000
 *             remainingUsage:
 *               type: integer
 *               example: 500
 */

/**
 * @swagger
 * /user/usage:
 *   get:
 *     summary: 사용량 조회
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: type
 *         required: true
 *         schema:
 *           type: string
 *           enum: [today, 1week, month, 3month, 6month]
 *         description: 조회 기간 타입
 *     responses:
 *       200:
 *         description: 사용량 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/UsageTodayResponse'
 *                 - $ref: '#/components/schemas/Usage1WeekResponse'
 *                 - $ref: '#/components/schemas/UsageMonthResponse'
 *                 - $ref: '#/components/schemas/Usage3MonthResponse'
 *                 - $ref: '#/components/schemas/Usage6MonthResponse'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /user/corpus:
 *   get:
 *     summary: 코퍼스 목록 조회
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: search
 *         schema:
 *           type: string
 *         description: 검색어
 *     responses:
 *       200:
 *         description: 코퍼스 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/CorpusListResponse'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /user/corpus/check:
 *   get:
 *     summary: 코퍼스 소스 확인
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: source
 *         required: true
 *         schema:
 *           type: string
 *         description: 확인할 소스 텍스트
 *     responses:
 *       200:
 *         description: 코퍼스 소스 확인 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/CorpusCheckResponse'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /user/corpus:
 *   post:
 *     summary: 코퍼스 생성
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - source
 *               - target
 *             properties:
 *               source:
 *                 type: string
 *                 description: 원문
 *                 example: "안녕하세요"
 *               target:
 *                 type: string
 *                 description: 번역문
 *                 example: "Hello"
 *               memo:
 *                 type: string
 *                 description: 메모
 *                 example: "인사말"
 *     responses:
 *       200:
 *         description: 코퍼스 생성 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MissingRequiredParameterError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       404:
 *         description: 리소스를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/corpus/{corpusId}:
 *   patch:
 *     summary: 코퍼스 수정
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: corpusId
 *         required: true
 *         schema:
 *           type: string
 *         description: 코퍼스 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - source
 *               - target
 *             properties:
 *               source:
 *                 type: string
 *                 description: 원문
 *                 example: "안녕하세요"
 *               target:
 *                 type: string
 *                 description: 번역문
 *                 example: "Hello"
 *               memo:
 *                 type: string
 *                 description: 메모
 *                 example: "인사말"
 *     responses:
 *       200:
 *         description: 코퍼스 수정 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/CorpusUpdateResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MissingRequiredParameterError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       404:
 *         description: 리소스를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/corpus/{corpusId}:
 *   delete:
 *     summary: 코퍼스 삭제
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: corpusId
 *         required: true
 *         schema:
 *           type: string
 *         description: 코퍼스 ID
 *     responses:
 *       204:
 *         description: 코퍼스 삭제 성공
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MissingRequiredParameterError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       404:
 *         description: 리소스를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/terms/consent:
 *   get:
 *     summary: 약관별 동의 상태 조회
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 약관별 동의 상태 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/TermsConsentResponse'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/terms/agreement:
 *   post:
 *     summary: 약관별 동의서 제출
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/TermsAgreementRequest'
 *           example:
 *             agreements:
 *               - termsId: "약관 고유 식별자"
 *                 status: "CONSENTED"
 *               - termsId: "약관 고유 식별자2"
 *                 status: "DECLINED"
 *     responses:
 *       200:
 *         description: 약관별 동의서 제출 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/TermsAgreementResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MissingRequiredParameterError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/folder:
 *   get:
 *     summary: 폴더 목록 조회
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 폴더 목록 조회 성공 (가상 폴더 + 사용자 생성 폴더)
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/FolderListResponse'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 *   post:
 *     summary: 폴더 생성
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/FolderCreateRequest'
 *           example:
 *             name: "새 프로젝트"
 *     responses:
 *       200:
 *         description: 폴더 생성 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/FolderCreateResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/folder/item:
 *   patch:
 *     summary: 콘텐츠를 폴더로 이동 (root, received, success, 실제 폴더만 가능)
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/ContentMoveRequest'
 *           example:
 *             folderId: "폴더 고유 식별자"
 *             contentIds: ["콘텐츠 고유 식별자1", "콘텐츠 고유 식별자2"]
 *           description: "folderId는 root, received, success, 실제 폴더 ID만 가능 (sent, error 폴더로 이동 불가)"
 *     responses:
 *       204:
 *         description: 콘텐츠 이동 성공
 *       400:
 *         description: 잘못된 요청 (폴더 이동 불가, 접근 권한 없음, 필수 파라미터 누락 등)
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               folder_move_restricted:
 *                 summary: 폴더 이동 제한
 *                 value:
 *                   errorCode: "E10911"
 *                   message: "이 폴더로 이동할 수 없습니다."
 *               shared_content_restricted:
 *                 summary: 공유 콘텐츠 이동 제한
 *                 value:
 *                   errorCode: "E10912"
 *                   message: "공유 받은 콘텐츠는 이 폴더로 이동할 수 없습니다."
 *               own_content_restricted:
 *                 summary: 자체 콘텐츠 이동 제한
 *                 value:
 *                   errorCode: "E10909"
 *                   message: "내가 생성한 콘텐츠는 이 폴더로 이동할 수 없습니다."
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       404:
 *         description: 폴더 또는 콘텐츠를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/folder/{folderId}:
 *   get:
 *     summary: 폴더 아이템 조회
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: folderId
 *         required: true
 *         schema:
 *           type: string
 *         description: 폴더 ID (root, received, sent, error, success 중 하나)
 *         example: "root"
 *       - in: query
 *         name: page
 *         schema:
 *           type: integer
 *           minimum: 1
 *           default: 1
 *         description: 페이지 번호
 *       - in: query
 *         name: limit
 *         schema:
 *           type: integer
 *           minimum: 1
 *           maximum: 100
 *           default: 20
 *         description: 페이지당 아이템 수
 *       - in: query
 *         name: search
 *         schema:
 *           type: string
 *         description: 검색어 (제목, 파일명, 해시태그 검색)
 *       - in: query
 *         name: type
 *         schema:
 *           type: string
 *           enum: [AUDIO, VIDEO, RECORD]
 *         description: 콘텐츠 타입 필터
 *       - in: query
 *         name: sortBy
 *         schema:
 *           type: string
 *           enum: [createAt, updateAt, title, duration]
 *           default: "createAt"
 *         description: 정렬 기준
 *       - in: query
 *         name: sortOrder
 *         schema:
 *           type: string
 *           enum: [asc, desc]
 *           default: "desc"
 *         description: 정렬 순서
 *     responses:
 *       200:
 *         description: 폴더 아이템 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/FolderItemsResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       404:
 *         description: 폴더를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 *   patch:
 *     summary: 폴더 수정
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: folderId
 *         required: true
 *         schema:
 *           type: string
 *         description: 수정할 폴더 ID
 *         example: "폴더 고유 식별자"
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/FolderUpdateRequest'
 *           example:
 *             name: "수정된 폴더명"
 *     responses:
 *       200:
 *         description: 폴더 수정 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/FolderUpdateResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       404:
 *         description: 폴더를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 *   delete:
 *     summary: 폴더 삭제
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: folderId
 *         required: true
 *         schema:
 *           type: string
 *         description: 삭제할 폴더 ID (가상 폴더 root, received, success, error, sent는 삭제 불가)
 *         example: "폴더 고유 식별자"
 *     responses:
 *       204:
 *         description: 폴더 삭제 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/FolderDeleteResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       404:
 *         description: 폴더를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/notification/management:
 *   get:
 *     summary: 알림 관리 설정 조회
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 알림 관리 설정 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotificationManagementResponse'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 *   patch:
 *     summary: 알림 관리 설정 업데이트
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - notifications
 *             properties:
 *               notifications:
 *                 type: array
 *                 minItems: 1
 *                 items:
 *                   type: object
 *                   required:
 *                     - channel
 *                     - eventType
 *                     - isUsed
 *                   properties:
 *                     channel:
 *                       type: string
 *                       enum: [PUSH, EMAIL]
 *                       example: "PUSH"
 *                       description: "알림 채널 (PUSH: 푸시 알림, EMAIL: 이메일 알림)"
 *                     eventType:
 *                       type: string
 *                       enum: [CONTENT_CREATE, CONTENT_SHARE, CONTENT_RECYCLE, CONTENT_RECYCLE, CONTENT_RESUMMARY, CALENDAR_REMIND]
 *                       example: "CONTENT_CREATE"
 *                       description: "이벤트 타입 (CONTENT_CREATE: 콘텐츠 생성, CONTENT_SHARE: 콘텐츠 공유, CONTENT_DELETE: 콘텐츠 삭제, CONTENT_RECYCLE: 콘텐츠 휴지통 이동, CONTENT_RESUMMARY: 콘텐츠 재요약, CALENDAR_REMIND: 캘린더 알림)"
 *                     isUsed:
 *                       type: boolean
 *                       example: true
 *                       description: "알림 사용 여부"
 *                 description: "알림 설정 목록"
 *           example:
 *             notifications:
 *               - channel: "PUSH"
 *                 eventType: "CONTENT_CREATE"
 *                 isUsed: true
 *               - channel: "PUSH"
 *                 eventType: "CONTENT_SHARE"
 *                 isUsed: true
 *     responses:
 *       200:
 *         description: 알림 관리 설정 업데이트 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotificationManagementUpdateResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/contact/label:
 *   get:
 *     summary: 라벨 목록 조회
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 라벨 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Success
 *                 httpCode:
 *                   type: integer
 *                   example: 200
 *                 data:
 *                   type: array
 *                   items:
 *                     type: object
 *                     properties:
 *                       id:
 *                         type: string
 *                         example: "clx1234567890abcdef"
 *                       name:
 *                         type: string
 *                         example: "업무"
 *                       color:
 *                         type: string
 *                         example: "#FFFFFF"
 *                       createAt:
 *                         type: string
 *                         format: date-time
 *                         example: "2024-01-15T10:30:00.000Z"
 *                       updateAt:
 *                         type: string
 *                         format: date-time
 *                         example: "2024-01-15T10:30:00.000Z"
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 *   post:
 *     summary: 라벨 생성
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - name
 *               - color
 *             properties:
 *               name:
 *                 type: string
 *                 maxLength: 64
 *                 example: "업무"
 *                 description: 라벨 이름
 *               color:
 *                 type: string
 *                 example: "#FFFFFF"
 *                 description: 라벨 색상
 *           example:
 *             name: "업무"
 *             color: "#FFFFFF"
 *     responses:
 *       200:
 *         description: 라벨 생성 성공
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Success
 *                 httpCode:
 *                   type: integer
 *                   example: 200
 *                 data:
 *                   type: object
 *                   properties:
 *                     id:
 *                       type: string
 *                       example: "clx1234567890abcdef"
 *                     pid:
 *                       type: string
 *                       example: 5966b342-5564-5600-aa25-afc65955d196"
 *                     name:
 *                       type: string
 *                       example: "업무"
 *                     color:
 *                       type: string
 *                       example: "#FFFFFF"
 *                     createAt:
 *                       type: string
 *                       format: date-time
 *                       example: "2024-01-15T10:30:00.000Z"
 *                     updateAt:
 *                       type: string
 *                       format: date-time
 *                       example: "2024-01-15T10:30:00.000Z"
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: "라벨 이름을 입력해주세요"
 *                 httpCode:
 *                   type: integer
 *                   example: 1000
 *             examples:
 *               missing_name:
 *                 summary: 라벨 이름 누락
 *                 value:
 *                   message: "라벨 이름을 입력해주세요"
 *                   httpCode: 1000
 *               duplicate_name:
 *                 summary: 중복된 라벨 이름
 *                 value:
 *                   message: "이미 존재하는 라벨 이름입니다"
 *                   httpCode: "E1903"
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/contact/label/{labelId}:
 *   put:
 *     summary: 라벨 수정
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: labelId
 *         required: true
 *         schema:
 *           type: string
 *         description: 라벨 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - name
 *               - color
 *             properties:
 *               name:
 *                 type: string
 *                 maxLength: 64
 *                 example: "개인"
 *                 description: 새로운 라벨 이름
 *               color:
 *                 type: string
 *                 example: "#FFFFFF"
 *                 description: 새로운 라벨 색상
 *     responses:
 *       200:
 *         description: 라벨 수정 성공
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Success
 *                 httpCode:
 *                   type: integer
 *                   example: 200
 *                 data:
 *                   type: object
 *                   properties:
 *                     id:
 *                       type: string
 *                       example: "clx1234567890abcdef"
 *                     name:
 *                       type: string
 *                       example: "개인"
 *                     color:
 *                       type: string
 *                       example: "#FFFFFF"
 *                     createAt:
 *                       type: string
 *                       format: date-time
 *                       example: "2024-01-15T10:30:00.000Z"
 *                     updateAt:
 *                       type: string
 *                       format: date-time
 *                       example: "2024-01-15T10:30:00.000Z"
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               missing_name:
 *                 summary: 라벨 이름 누락
 *                 value:
 *                   message: "라벨 이름을 입력해주세요"
 *                   httpCode: 1000
 *               label_not_found:
 *                 summary: 해당 라벨을 찾을 수 없음
 *                 value:
 *                   message: "해당 라벨을 찾을 수 없습니다"
 *                   httpCode: 1916
 *               duplicate_name:
 *                 summary: 이미 존재하는 라벨 이름
 *                 value:
 *                   message: "이미 존재하는 라벨 이름입니다"
 *                   httpCode: 1915
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 *   delete:
 *     summary: 라벨 삭제
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: labelId
 *         required: true
 *         schema:
 *           type: string
 *         description: 라벨 ID
 *     responses:
 *       204:
 *         description: 라벨 삭제 성공
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Success
 *                 httpCode:
 *                   type: integer
 *                   example: 204
 *                 data:
 *                   type: object
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: "라벨 아이디를 전달해주세요"
 *                 httpCode:
 *                   type: integer
 *                   example: 1000
 *       404:
 *         description: 라벨을 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: "라벨을 찾을 수 없습니다"
 *                 httpCode:
 *                   type: integer
 *                   example: 1904
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/contact/favorite:
 *   patch:
 *     summary: 주소록 즐겨찾기 상태 변경
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - contactIds
 *               - isFavorite
 *             properties:
 *               contactIds:
 *                 type: array
 *                 items:
 *                   type: string
 *                 minItems: 1
 *                 example: ["연락처 고유 식별자1", "연락처 고유 식별자2"]
 *                 description: 즐겨찾기 상태를 변경할 연락처 ID 목록
 *               isFavorite:
 *                 type: boolean
 *                 example: true
 *                 description: 즐겨찾기 여부 (true는 즐겨찾기 추가, false는 즐겨찾기 제거)
 *           example:
 *             contactIds: ["연락처 고유 식별자1", "연락처 고유 식별자2"]
 *             isFavorite: true
 *     responses:
 *       204:
 *         description: 주소록 즐겨찾기 상태 변경 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               missing_contact_ids:
 *                 summary: 연락처 ID 누락
 *                 value:
 *                   message: "주소록 아이디는 배열로 전달해주세요"
 *                   httpCode: 1000
 *               invalid_favorite_type:
 *                 summary: 즐겨찾기 타입 오류
 *                 value:
 *                   message: "즐겨찾기 여부를 boolean 타입으로 전달해주세요"
 *                   httpCode: 1000
 *               contact_not_found:
 *                 summary: 주소록을 찾을 수 없음
 *                 value:
 *                   message: "주소록을 찾을 수 없습니다"
 *                   httpCode: 1902
 *               unauthorized_contact:
 *                 summary: 권한이 없는 연락처
 *                 value:
 *                   message: "접근 권한이 없는 연락처입니다"
 *                   httpCode: 1903
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/contact/recycle:
 *   patch:
 *     summary: 주소록 휴지통 이동 상태 변경(지정일 이후 자동 삭제)
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - contactIds
 *               - isRecycle
 *             properties:
 *               contactIds:
 *                 type: array
 *                 items:
 *                   type: string
 *                 minItems: 1
 *                 example: ["연락처 고유 식별자1", "연락처 고유 식별자2"]
 *                 description: 휴지통 이동 상태를 변경할 연락처 ID 목록
 *               isRecycle:
 *                 type: boolean
 *                 example: true
 *                 description: 휴지통 이동 여부 (true는 휴지통으로 이동, false는 휴지통에서 복구)
 *           example:
 *             contactIds: ["연락처 고유 식별자1", "연락처 고유 식별자2"]
 *             isRecycle: true
 *     responses:
 *       204:
 *         description: 주소록 휴지통 이동 상태 변경 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               missing_contact_ids:
 *                 summary: 연락처 ID 누락
 *                 value:
 *                   message: "주소록 아이디는 배열로 전달해주세요"
 *                   httpCode: 1000
 *               invalid_recycle_type:
 *                 summary: 휴지통 이동 타입 오류
 *                 value:
 *                   message: "휴지통 이동 여부를 boolean 타입으로 전달해주세요"
 *                   httpCode: 1000
 *               contact_not_found:
 *                 summary: 주소록을 찾을 수 없음
 *                 value:
 *                   message: "주소록을 찾을 수 없습니다"
 *                   httpCode: 1902
 *               unauthorized_contact:
 *                 summary: 권한이 없는 연락처
 *                 value:
 *                   message: "접근 권한이 없는 연락처입니다"
 *                   httpCode: 1903
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/contact/labeling:
 *   patch:
 *     summary: 주소록에 라벨 연결 관리
 *     description: |
 *       여러 주소록에 동시에 여러 라벨을 연결하거나 연결 해제합니다.
 *
 *       **주요 동작:**
 *       - 기존에 연결된 모든 라벨을 제거하고 새로운 라벨 목록으로 대체합니다
 *       - `labelIds`에 빈 배열을 전달하면 모든 라벨 연결이 해제됩니다
 *       - 트랜잭션으로 처리되어 데이터 일관성을 보장합니다
 *       - 여러 주소록에 동일한 라벨 세트를 한 번에 적용합니다
 *
 *       **필수 파라미터:**
 *       - `contactIds` (array, required): 라벨을 연결할 주소록 ID 목록
 *       - `labelIds` (array, required): 연결할 라벨 ID 목록
 *
 *       **참고사항:**
 *       - 존재하지 않는 주소록 ID가 포함된 경우 에러가 발생합니다
 *       - 다른 사용자의 주소록에 접근 시 권한 에러가 발생합니다
 *       - 존재하지 않거나 권한이 없는 라벨 ID가 포함된 경우 에러가 발생합니다
 *       - 모든 주소록에 동일한 라벨 세트가 적용됩니다
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - contactIds
 *               - labelIds
 *             properties:
 *               contactIds:
 *                 type: array
 *                 items:
 *                   type: string
 *                 minItems: 1
 *                 example: ["주소록 고유 식별자1", "주소록 고유 식별자2"]
 *                 description: 라벨을 연결할 주소록 ID 목록
 *               labelIds:
 *                 type: array
 *                 items:
 *                   type: string
 *                 example: ["라벨 고유 식별자1", "라벨 고유 식별자2"]
 *                 description: 연결할 라벨 ID 목록
 *           examples:
 *             with_labels:
 *               summary: 여러 주소록에 라벨 연결
 *               value:
 *                 contactIds: ["주소록 고유 식별자1", "주소록 고유 식별자2"]
 *                 labelIds: ["라벨 고유 식별자1", "라벨 고유 식별자2"]
 *             remove_all_labels:
 *               summary: 여러 주소록에서 모든 라벨 연결 해제
 *               value:
 *                 contactIds: ["주소록 고유 식별자1", "주소록 고유 식별자2"]
 *                 labelIds: []
 *             single_contact:
 *               summary: 단일 주소록에 라벨 연결
 *               value:
 *                 contactIds: ["주소록 고유 식별자"]
 *                 labelIds: ["라벨 고유 식별자1", "라벨 고유 식별자2"]
 *     responses:
 *       204:
 *         description: 주소록 라벨 연결 성공
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Success
 *                 httpCode:
 *                   type: integer
 *                   example: 204
 *                 data:
 *                   type: object
 *                   example: {}
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               missing_contact_ids:
 *                 summary: 주소록 ID 배열 누락
 *                 value:
 *                   message: "주소록 ID는 배열로 전달해주세요"
 *                   httpCode: 1000
 *               invalid_label_ids:
 *                 summary: 라벨 ID 배열 형식 오류
 *                 value:
 *                   message: "라벨 ID는 배열로 전달해주세요"
 *                   httpCode: 1400
 *               label_not_found:
 *                 summary: 존재하지 않는 라벨
 *                 value:
 *                   message: "존재하지 않는 라벨입니다"
 *                   httpCode: 1916
 *               unauthorized_label:
 *                 summary: 권한이 없는 라벨
 *                 value:
 *                   message: "권한이 없는 라벨입니다"
 *                   httpCode: 1302
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       404:
 *         description: 주소록을 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 *             examples:
 *               contact_not_found:
 *                 summary: 주소록을 찾을 수 없음
 *                 value:
 *                   message: "주소록을 찾을 수 없습니다"
 *                   httpCode: 1902
 *               unauthorized_contact:
 *                 summary: 권한이 없는 주소록
 *                 value:
 *                   message: "접근 권한이 없는 주소록입니다"
 *                   httpCode: 1302
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/contact:
 *   get:
 *     summary: 주소록 목록 조회
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: page
 *         schema:
 *           type: integer
 *           minimum: 1
 *           default: 1
 *         description: 페이지 번호
 *       - in: query
 *         name: take
 *         schema:
 *           type: integer
 *           minimum: 0
 *           maximum: 100
 *           default: 20
 *         description: 페이지당 아이템 수 (0이면 전체 조회)
 *       - in: query
 *         name: search
 *         schema:
 *           type: string
 *         description: 검색어 (이메일, 부서, 직책, 메모 검색)
 *       - in: query
 *         name: labelId
 *         schema:
 *           type: string
 *         description: 라벨 ID로 필터링
 *       - in: query
 *         name: isFavorite
 *         schema:
 *           type: boolean
 *         description: |
 *           즐겨찾기 여부로 필터링
 *           - true: 즐겨찾기된 주소록만 조회
 *           - false: 즐겨찾기되지 않은 주소록만 조회
 *           - 미전달: 전체 주소록 조회 (기본값)
 *       - in: query
 *         name: isRecycle
 *         schema:
 *           type: boolean
 *           default: false
 *         description: |
 *           휴지통 이동 여부로 필터링 (기본값: false)
 *           - true: 휴지통으로 이동된 주소록만 조회
 *           - false: 휴지통으로 이동되지 않은 주소록만 조회 (기본값)
 *           - 미전달: false로 처리되어 휴지통 항목 제외
 *       - in: query
 *         name: sort
 *         schema:
 *           type: string
 *           enum: [createAt, updateAt, email]
 *           default: "createAt"
 *         description: 정렬 기준
 *       - in: query
 *         name: direction
 *         schema:
 *           type: string
 *           enum: [asc, desc]
 *           default: "desc"
 *         description: 정렬 순서
 *     responses:
 *       200:
 *         description: 주소록 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ContactListResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/contact/template:
 *   get:
 *     summary: 주소록 일괄 등록용 엑셀 양식 다운로드
 *     description: |
 *       주소록 일괄 등록을 위한 엑셀 양식 파일을 다운로드합니다.
 *
 *       **양식 구성:**
 *       - 헤더 행: 이메일(필수), 라벨1(선택) ~ 라벨5(선택), 비고(선택)
 *       - 예시 데이터 행 포함
 *       - 노란색 헤더 배경, 테두리 등 스타일 적용
 *       - 경고 메시지 및 버전 정보 포함
 *
 *       **지원하는 프로그램:**
 *       - Microsoft Excel
 *       - Google Sheets
 *       - LibreOffice Calc
 *       - 기타 .xlsx 형식을 지원하는 스프레드시트 프로그램
 *
 *       **주의사항:**
 *       - 양식의 헤더 이름은 변경하지 마세요
 *       - 헤더 위치(열 순서)는 변경해도 됩니다
 *       - 양식의 스타일은 변경하지 마세요
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: |
 *           엑셀 양식 다운로드 성공
 *
 *           **파일 다운로드:**
 *           - 이 API는 엑셀 파일(.xlsx)을 직접 다운로드합니다
 *           - Swagger UI에서 "Execute" 버튼을 클릭하면 파일이 자동으로 다운로드됩니다
 *           - 브라우저의 다운로드 폴더에 `contact_bulk_v0.0.1.xlsx` 파일이 저장됩니다
 *           - 응답 본문은 바이너리 데이터이므로 JSON이 아닙니다
 *           - Swagger UI가 바이너리 본문을 렌더링하지 못해 `😱 Could not render responses_Responses` 경고가 표시될 수 있지만, 파일 다운로드는 정상 동작합니다. 경고를 무시하고 다운로드 결과를 확인해주세요.
 *         headers:
 *           Content-Disposition:
 *             description: 파일 다운로드 헤더
 *             schema:
 *               type: string
 *             example: 'attachment; filename="contact_bulk_v0.0.1.xlsx"'
 *           Content-Type:
 *             description: 파일 MIME 타입
 *             schema:
 *               type: string
 *             example: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
 *           Content-Length:
 *             description: 파일 크기 (바이트)
 *             schema:
 *               type: integer
 *             example: 12345
 *         content:
 *           application/vnd.openxmlformats-officedocument.spreadsheetml.sheet:
 *             schema:
 *               type: string
 *               format: binary
 *             description: 엑셀 파일 바이너리 데이터 (다운로드됨)
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/contact:
 *   post:
 *     summary: 주소록 등록
 *     description: |
 *       주소록에 새로운 연락처를 등록합니다.
 *
 *       **필수 파라미터:**
 *       - `email` (string, required): 연락처 이메일 주소
 *
 *       **선택 파라미터:**
 *       - `department` (string, optional): 부서명 (최대 64자)
 *       - `position` (string, optional): 직책 (최대 64자)
 *       - `memo` (string, optional): 메모 (최대 512자)
 *       - `labelIds` (array, optional): 연결할 라벨 ID 목록
 *
 *       **참고사항:**
 *       - 동일한 이메일로 이미 등록된 연락처가 있는 경우 에러가 발생합니다
 *       - 등록된 이메일이 시스템에 존재하는 사용자인 경우, 해당 사용자 정보가 자동으로 연결됩니다
 *       - labelIds에 존재하지 않는 라벨 ID가 포함된 경우 에러가 발생합니다
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/ContactCreateRequest'
 *           examples:
 *             minimal:
 *               summary: 최소 필수값만 포함 (이메일만)
 *               value:
 *                 email: "hong@example.com"
 *             full:
 *               summary: 모든 파라미터 포함
 *               value:
 *                 email: "hong@example.com"
 *                 department: "개발팀"
 *                 position: "부장"
 *                 memo: "메모 내용"
 *                 labelIds: ["라벨 고유 식별자1", "라벨 고유 식별자2"]
 *     responses:
 *       200:
 *         description: 주소록 등록 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ContactCreateResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               missing_required_fields:
 *                 summary: 필수 필드 누락
 *                 value:
 *                   message: "이메일을 입력해주세요"
 *                   httpCode: 1000
 *               invalid_email_format:
 *                 summary: 이메일 형식 오류
 *                 value:
 *                   message: "이메일 형식이 올바르지 않습니다"
 *                   httpCode: 1000
 *               duplicate_email:
 *                 summary: 중복된 이메일
 *                 value:
 *                   message: "이미 주소록에 등록된 이메일입니다"
 *                   httpCode: 1901
 *               duplicate_email_in_recycle:
 *                 summary: 주소록 휴지통에 중복된 이메일
 *                 value:
 *                   message: "주소록 휴지통에 중복된 이메일이 있습니다"
 *                   httpCode: 1917
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 *   delete:
 *     summary: 주소록 다중 삭제
 *     description: |
 *       여러 주소록을 한 번에 삭제합니다.
 *
 *       **필수 파라미터:**
 *       - `contactIds` (array, required): 삭제할 주소록 ID 목록
 *
 *       **주요 동작:**
 *       - 배열로 전달된 모든 주소록을 삭제합니다
 *       - 주소록과 연결된 모든 라벨 관계도 함께 삭제됩니다
 *       - 삭제된 주소록은 복구할 수 없습니다
 *
 *       **참고사항:**
 *       - 존재하지 않는 주소록 ID가 포함된 경우 에러가 발생합니다
 *       - 다른 사용자의 주소록을 삭제하려고 하면 권한 에러가 발생합니다
 *       - 빈 배열을 전달하면 에러가 발생합니다
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/ContactDeleteRequest'
 *           examples:
 *             single:
 *               summary: 단일 주소록 삭제
 *               value:
 *                 contactIds: ["주소록 고유 식별자"]
 *             multiple:
 *               summary: 여러 주소록 삭제
 *               value:
 *                 contactIds: ["주소록 고유 식별자1", "주소록 고유 식별자2", "주소록 고유 식별자3"]
 *     responses:
 *       204:
 *         description: 주소록 삭제 성공
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Success
 *                 httpCode:
 *                   type: integer
 *                   example: 204
 *                 data:
 *                   type: object
 *                   example: {}
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               missing_contact_ids:
 *                 summary: 주소록 ID 배열 누락
 *                 value:
 *                   message: "주소록 아이디는 배열로 전달해주세요"
 *                   httpCode: 1000
 *               empty_array:
 *                 summary: 빈 배열 전달
 *                 value:
 *                   message: "주소록 아이디는 배열로 전달해주세요"
 *                   httpCode: 1000
 *               contact_not_found:
 *                 summary: 존재하지 않는 주소록
 *                 value:
 *                   message: "존재하지 않는 주소록입니다"
 *                   httpCode: 1902
 *               unauthorized_contact:
 *                 summary: 권한이 없는 주소록
 *                 value:
 *                   message: "삭제 권한이 없는 주소록이 포함되어 있습니다"
 *                   httpCode: 1903
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/contact/bulk:
 *   post:
 *     summary: 주소록 일괄 등록 (행별 검증)
 *     description: |
 *       엑셀 파일 또는 배열로 여러 주소록을 한 번에 등록합니다. 각 행별로 개별 검증하여 부분 성공/실패를 지원합니다.
 *
 *       **지원하는 입력 방식:**
 *       1. **이메일 배열**: `emails` 필드에 이메일 목록 제공
 *       2. **사용자 정보 배열**: `users` 필드에 상세 정보 제공 (index, email, label1~5, memo 포함)
 *       3. **엑셀 파일**: `file` 필드에 엑셀 파일 업로드 (.xlsx, .xls, .csv)
 *       4. **혼합**: 위 방식들을 조합하여 사용 가능
 *
 *       **엑셀 파일 형식 (1번 행은 헤더):**
 *       - 헤더: `email`, `label1`, `label2`, `label3`, `label4`, `label5`, `memo`
 *       - 데이터: 2번 행부터 시작
 *       - 이메일은 필수, 나머지는 선택사항
 *       - 라벨 중복은 자동으로 제거됩니다
 *
 *       **행별 검증 규칙:**
 *       - 각 행별로 독립적으로 검증하여 부분 성공 가능
 *       - 이메일 필수 체크
 *       - 이메일 형식 체크
 *       - 워크스페이스 가입 여부 확인
 *       - 자기 자신 등록 방지
 *       - 이미 등록된 이메일 중복 체크
 *       - 라벨 이름 존재 여부 확인
 *
 *       **응답 구조:**
 *       - `summary`: 전체 처리 요약 (totalCount, successCount, failedCount)
 *       - `results`: 각 행별 처리 결과 (index, isPassed, contact, errors)
 *       - `errors`: 전체 에러 메시지 목록 (사용자에게 보여줄 메시지)
 *
 *       **트랜잭션 처리:**
 *       - 검증 통과한 행들만 DB에 저장
 *       - 각 행의 라벨은 개별적으로 연결
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         multipart/form-data:
 *           schema:
 *             type: object
 *             properties:
 *               emails:
 *                 type: array
 *                 items:
 *                   type: string
 *                 description: "이메일 배열 (JSON 문자열)"
 *                 example: '["user1@example.com", "user2@example.com"]'
 *               users:
 *                 type: array
 *                 items:
 *                   type: object
 *                 description: "사용자 정보 배열 (JSON 문자열)"
 *                 example: '[{"index":2,"email":"user@example.com","label1":"스페셜팀","label2":"","label3":"","label4":"","label5":"","memo":""}]'
 *               file:
 *                 type: string
 *                 format: binary
 *                 description: "엑셀 파일 (.xlsx, .xls, .csv)"
 *           examples:
 *             emails_only:
 *               summary: 이메일 배열만 사용
 *               value:
 *                 emails: '["user1@example.com", "user2@example.com"]'
 *             excel_file:
 *               summary: 엑셀 파일 업로드
 *               value:
 *                 file: "contact.xlsx"
 *     responses:
 *       200:
 *         description: 주소록 일괄 등록 처리 완료 (부분 성공 포함)
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ContactBulkCreateResponse'
 *             examples:
 *               partial_success:
 *                 summary: 부분 성공 (일부 행 실패)
 *                 value:
 *                   message: "Success"
 *                   httpCode: 200
 *                   data:
 *                     summary:
 *                       totalCount: 10
 *                       successCount: 7
 *                       failedCount: 3
 *                     columns:
 *                       email: "이메일"
 *                       label1: "라벨1"
 *                       label2: "라벨2"
 *                       label3: "라벨3"
 *                       label4: "라벨4"
 *                       label5: "라벨5"
 *                       memo: "비고"
 *                     results:
 *                       - index: 2
 *                         isPassed: true
 *                         contact:
 *                           email: "user1@example.com"
 *                           label1: "스페셜팀"
 *                           label2: "개발팀"
 *                           label3: ""
 *                           label4: ""
 *                           label5: ""
 *                           memo: "우수 개발자"
 *                       - index: 3
 *                         isPassed: false
 *                         errors:
 *                           - field: "이메일"
 *                             reason: "워크스페이스에 가입되지 않은 이메일입니다"
 *                         contact:
 *                           email: "invalid@example.com"
 *                           label1: "스페셜팀"
 *                           label2: ""
 *                           label3: ""
 *                           label4: ""
 *                           label5: ""
 *                           memo: ""
 *                       - index: 4
 *                         isPassed: false
 *                         errors:
 *                           - field: "이메일"
 *                             reason: "이미 주소록에 등록된 이메일입니다"
 *                           - field: "라벨2"
 *                             reason: "존재하지 않은 라벨입니다"
 *                         contact:
 *                           email: "duplicate@example.com"
 *                           label1: "팀장"
 *                           label2: "없는라벨"
 *                           label3: ""
 *                           label4: ""
 *                           label5: ""
 *                           memo: ""
 *                     errors:
 *                       - "3번 행 '이메일(invalid@example.com)': 워크스페이스에 가입되지 않은 이메일입니다. 회원가입 여부 확인 후 다시 등록해주세요."
 *                       - "4번 행 '이메일(duplicate@example.com)': 이미 주소록에 등록된 이메일입니다."
 *                       - "4번 행 '라벨2(없는라벨)': 존재하지 않은 라벨입니다. 사전에 라벨을 등록해주세요."
 *               all_success:
 *                 summary: 전체 성공
 *                 value:
 *                   message: "Success"
 *                   httpCode: 200
 *                   data:
 *                     summary:
 *                       totalCount: 5
 *                       successCount: 5
 *                       failedCount: 0
 *                     columns:
 *                       email: "이메일"
 *                       label1: "라벨1"
 *                       label2: "라벨2"
 *                       label3: "라벨3"
 *                       label4: "라벨4"
 *                       label5: "라벨5"
 *                       memo: "비고"
 *                     results:
 *                       - index: 2
 *                         isPassed: true
 *                         contact:
 *                           email: "user1@example.com"
 *                           label1: "스페셜팀"
 *                           label2: ""
 *                           label3: ""
 *                           label4: ""
 *                           label5: ""
 *                           memo: ""
 *                       - index: 3
 *                         isPassed: true
 *                         contact:
 *                           email: "user2@example.com"
 *                           label1: "개발팀"
 *                           label2: "백엔드"
 *                           label3: ""
 *                           label4: ""
 *                           label5: ""
 *                           memo: "신입"
 *                     errors: []
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               no_data:
 *                 summary: 입력 데이터 없음
 *                 value:
 *                   message: "사용자 정보, 이메일 배열 또는 엑셀 파일을 입력해주세요"
 *                   httpCode: 1000
 *               invalid_file:
 *                 summary: 잘못된 파일 형식
 *                 value:
 *                   message: "지원하지 않는 파일 형식입니다. (.xlsx, .xls, .csv만 가능)"
 *                   httpCode: 1000
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /user/contact/{contactId}:
 *   patch:
 *     summary: 주소록 수정
 *     description: |
 *       주소록의 메모와 라벨 정보를 부분적으로 수정합니다.
 *
 *       **선택 파라미터 (최소 1개 이상 필수):**
 *       - `memo` (string, optional): 메모 (최대 512자)
 *       - `labelIds` (array, optional): 연결할 라벨 ID 목록 (빈 배열 전달 시 모든 라벨 연결 해제, 최대 5개)
 *
 *       **참고사항:**
 *       - memo 또는 labelIds 중 최소 1개 이상 전달해야 합니다
 *       - 존재하지 않는 주소록 ID인 경우 에러가 발생합니다
 *       - 다른 사용자의 주소록을 수정하려고 하면 권한 에러가 발생합니다
 *       - 이메일, 부서, 직책은 수정할 수 없습니다 (사용자가 직접 수정 불가)
 *       - `labelIds`에 존재하지 않거나 권한이 없는 라벨 ID가 포함된 경우 에러가 발생합니다
 *       - `labelIds`는 최대 5개까지 지정할 수 있습니다
 *     tags: [User]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contactId
 *         required: true
 *         schema:
 *           type: string
 *         description: 주소록 ID
 *         example: "주소록 고유 식별자"
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               memo:
 *                 type: string
 *                 maxLength: 512
 *                 example: "업데이트된 메모 내용"
 *                 description: 메모 (최대 512자)
 *               labelIds:
 *                 type: array
 *                 items:
 *                   type: string
 *                 maxItems: 5
 *                 example: ["라벨 고유 식별자1", "라벨 고유 식별자2"]
 *                 description: 연결할 라벨 ID 목록 (빈 배열 전달 시 모든 라벨 연결 해제, 최대 5개)
 *           examples:
 *             update_memo_only:
 *               summary: 메모만 수정
 *               value:
 *                 memo: "중요 거래처"
 *             update_labels_only:
 *               summary: 라벨만 수정
 *               value:
 *                 labelIds: ["라벨 고유 식별자1", "라벨 고유 식별자2"]
 *             update_both:
 *               summary: 메모와 라벨 모두 수정
 *               value:
 *                 memo: "프로젝트 리더"
 *                 labelIds: ["라벨 고유 식별자1", "라벨 고유 식별자2"]
 *             remove_all_labels:
 *               summary: 모든 라벨 연결 해제
 *               value:
 *                 labelIds: []
 *     responses:
 *       200:
 *         description: 주소록 수정 성공
 *         content:
 *           application/json:
 *             schema:
 *               allOf:
 *                 - $ref: '#/components/schemas/Success'
 *                 - type: object
 *                   properties:
 *                     data:
 *                       $ref: '#/components/schemas/ContactItem'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               missing_contact_id:
 *                 summary: 주소록 ID 누락
 *                 value:
 *                   message: "주소록 ID를 입력해주세요"
 *                   httpCode: 1000
 *               missing_fields:
 *                 summary: 수정할 필드 누락
 *                 value:
 *                   message: "수정할 내용을 전달해주세요 (memo 또는 labelIds)"
 *                   httpCode: 1000
 *               invalid_labelIds:
 *                 summary: labelIds 배열 형식 오류
 *                 value:
 *                   message: "라벨 ID는 배열로 전달해주세요"
 *                   httpCode: 1000
 *               too_many_labels:
 *                 summary: 라벨 개수 초과
 *                 value:
 *                   message: "라벨 ID는 최대 5개까지 전달할 수 있습니다"
 *                   httpCode: 1000
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       403:
 *         description: 권한 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             example:
 *               message: "접근 권한이 없습니다"
 *               httpCode: 1302
 *       404:
 *         description: 주소록을 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             example:
 *               message: "주소록을 찾을 수 없습니다"
 *               httpCode: 1902
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */
