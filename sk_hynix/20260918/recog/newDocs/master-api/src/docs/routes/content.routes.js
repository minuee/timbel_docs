/**
 * @swagger
 * /contents/upload:
 *   post:
 *     summary: 콘텐츠 업로드
 *     tags: [Content]
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
 *               file:
 *                 type: string
 *                 format: binary
 *                 description: 업로드할 파일
 *               isRecord:
 *                 type: string
 *                 description: 녹음 여부
 *                 example: "true"
 *               lang:
 *                 type: string
 *                 description: 언어 코드
 *                 example: "ko"
 *               attendeeNum:
 *                 type: integer
 *                 description: 참석자 수
 *                 example: 99
 *               type:
 *                 type: string
 *                 description: 파일 타입
 *                 example: "audio"
 *               summary:
 *                 type: string
 *                 description: 요약 크기
 *                 example: "medium"
 *               folderId:
 *                 type: string
 *                 description: 폴더 ID
 *                 example: "folder-uuid"
 *     responses:
 *       200:
 *         description: 콘텐츠 업로드 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UploadContentResponse'
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
 */

/**
 * @swagger
 * /contents/upload:
 *   post:
 *     summary: 콘텐츠 업로드 (AX Template Ver)
 *     tags: [AX Template Ver]
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
 *               file:
 *                 type: string
 *                 format: binary
 *                 description: 업로드할 파일
 *               isRecord:
 *                 type: string
 *                 description: 녹음 여부
 *                 example: "true"
 *               lang:
 *                 type: string
 *                 description: 언어 코드
 *                 example: "ko"
 *               attendeeNum:
 *                 type: integer
 *                 description: 참석자 수
 *                 example: 99
 *               type:
 *                 type: string
 *                 description: 파일 타입
 *                 example: "audio"
 *               summary:
 *                 type: string
 *                 description: 요약 크기
 *                 example: "medium"
 *               folderId:
 *                 type: string
 *                 description: 폴더 ID
 *                 example: "folder-uuid"
 *               templateId:
 *                 type: string
 *                 description: 템플릿 ID
 *                 example: "DEF-DEFAULT-BASIC"
 *     responses:
 *       200:
 *         description: 콘텐츠 업로드 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UploadContentResponse'
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
 */

/**
 * @swagger
 * /contents/upload/encryption/files:
 *   post:
 *     summary: 암호화된 다중 파일 업로드
 *     tags: [Content]
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
 *               files:
 *                 type: array
 *                 items:
 *                   type: string
 *                   format: binary
 *                 description: 업로드할 암호화된 파일들
 *               lang:
 *                 type: string
 *                 description: 언어 코드
 *                 example: "ko"
 *               attendeeNum:
 *                 type: integer
 *                 description: 참석자 수
 *                 example: 99
 *     responses:
 *       200:
 *         description: 암호화된 다중 파일 업로드 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/upload/encryption:
 *   post:
 *     summary: 암호화된 단일 파일 업로드
 *     tags: [Content]
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
 *               file:
 *                 type: string
 *                 format: binary
 *                 description: 업로드할 암호화된 파일
 *               lang:
 *                 type: string
 *                 description: 언어 코드
 *                 example: "ko"
 *               attendeeNum:
 *                 type: integer
 *                 description: 참석자 수
 *                 example: 99
 *               deviceId:
 *                 type: string
 *                 description: 디바이스 ID
 *                 example: "device-uuid"
 *               fileName:
 *                 type: string
 *                 description: 파일명
 *                 example: "meeting.mp3"
 *               num:
 *                 type: integer
 *                 description: 파일 번호
 *                 example: 1
 *               totalNum:
 *                 type: integer
 *                 description: 전체 파일 수
 *                 example: 3
 *               end:
 *                 type: boolean
 *                 description: 마지막 파일 여부
 *                 example: false
 *     responses:
 *       200:
 *         description: 암호화된 파일 업로드 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/upload/text:
 *   post:
 *     summary: 텍스트 파일 업로드
 *     tags: [Content]
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
 *               file:
 *                 type: string
 *                 format: binary
 *                 description: 업로드할 텍스트 파일 (.txt 형식)
 *               lang:
 *                 type: string
 *                 description: 언어 코드
 *                 example: "ko"
 *                 default: "ko"
 *               templateId:
 *                 type: string
 *                 nullable: true
 *                 description: 템플릿 ID
 *                 example: null
 *                 default: null
 *               summary:
 *                 type: string
 *                 description: 요약 크기
 *                 example: "medium"
 *                 default: "medium"
 *               chunkSize:
 *                 type: integer
 *                 description: 청크 크기
 *                 example: 500
 *                 default: 500
 *     responses:
 *       200:
 *         description: 텍스트 파일 업로드 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UploadTextContentResponse'
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
 */

/**
 * @swagger
 * /contents/thumbnail:
 *   post:
 *     summary: 썸네일 업로드
 *     tags: [Content]
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
 *               file:
 *                 type: string
 *                 format: binary
 *                 description: 업로드할 이미지 파일
 *     responses:
 *       200:
 *         description: 썸네일 업로드 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/download:
 *   get:
 *     summary: 콘텐츠 다운로드
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: contentId
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 콘텐츠 다운로드 성공
 *         content:
 *           application/octet-stream:
 *             schema:
 *               type: string
 *               format: binary
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/recycle:
 *   post:
 *     summary: 다중 콘텐츠 휴지통 이동
 *     tags: [Content]
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
 *               - contentIds
 *             properties:
 *               contentIds:
 *                 type: array
 *                 items:
 *                   type: string
 *                 description: 콘텐츠 ID 배열
 *                 example: ["content-uuid-1", "content-uuid-2"]
 *     responses:
 *       200:
 *         description: 다중 콘텐츠 휴지통 이동 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/recycle/clear:
 *   delete:
 *     summary: 휴지통 전체 비우기
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       204:
 *         description: 휴지통 전체 비우기 성공
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/recycle/{contentId}:
 *   delete:
 *     summary: 특정 콘텐츠 휴지통 이동 (deprecated)
 *     tags: [Content]
 *     deprecated: true
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 콘텐츠 휴지통 이동 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/truncate:
 *   delete:
 *     summary: 콘텐츠 완전 삭제
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: contentId
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       204:
 *         description: 콘텐츠 완전 삭제 성공
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/recycle:
 *   get:
 *     summary: 휴지통 콘텐츠 목록 조회
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 휴지통 콘텐츠 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/restore:
 *   delete:
 *     summary: 콘텐츠 복원
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: contentId
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 콘텐츠 복원 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents:
 *   get:
 *     summary: 콘텐츠 목록 조회
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: page
 *         schema:
 *           type: integer
 *         description: 페이지 번호
 *         example: 1
 *       - in: query
 *         name: limit
 *         schema:
 *           type: integer
 *         description: 페이지당 항목 수
 *         example: 10
 *       - in: query
 *         name: folderId
 *         schema:
 *           type: string
 *         description: 폴더 ID
 *     responses:
 *       200:
 *         description: 콘텐츠 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ContentListResponse'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/calendar:
 *   get:
 *     summary: 캘린더 콘텐츠 조회
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: startDate
 *         schema:
 *           type: string
 *           format: date
 *         description: 시작 날짜
 *         example: "2024-01-01"
 *       - in: query
 *         name: endDate
 *         schema:
 *           type: string
 *           format: date
 *         description: 종료 날짜
 *         example: "2024-12-31"
 *     responses:
 *       200:
 *         description: 캘린더 콘텐츠 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/share/{contentId}:
 *   get:
 *     summary: 콘텐츠 공유 사용자 목록 조회
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 콘텐츠 공유 사용자 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/share:
 *   post:
 *     summary: 콘텐츠 공유 사용자 추가
 *     tags: [Content]
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
 *               - contentId
 *               - email
 *               - role
 *             properties:
 *               contentId:
 *                 type: string
 *                 description: 콘텐츠 ID
 *                 example: "content-uuid"
 *               email:
 *                 type: string
 *                 format: email
 *                 description: 공유할 사용자 이메일
 *                 example: "user@example.com"
 *               role:
 *                 type: string
 *                 enum: [VIEWER, DOWNLOADER, EDITOR, OWNER]
 *                 description: 공유 권한
 *                 example: "VIEWER"
 *     responses:
 *       200:
 *         description: 콘텐츠 공유 사용자 추가 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/share:
 *   put:
 *     summary: 콘텐츠 공유 사용자 권한 수정
 *     tags: [Content]
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
 *               - contentId
 *               - email
 *               - role
 *             properties:
 *               contentId:
 *                 type: string
 *                 description: 콘텐츠 ID
 *                 example: "content-uuid"
 *               email:
 *                 type: string
 *                 format: email
 *                 description: 사용자 이메일
 *                 example: "user@example.com"
 *               role:
 *                 type: string
 *                 enum: [VIEWER, DOWNLOADER, EDITOR, OWNER]
 *                 description: 새로운 공유 권한
 *                 example: "EDITOR"
 *     responses:
 *       200:
 *         description: 콘텐츠 공유 사용자 권한 수정 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/share/bulk:
 *   post:
 *     summary: 콘텐츠 다중 공유 사용자 추가
 *     tags: [Content]
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
 *               - contentId
 *               - emails
 *             properties:
 *               contentId:
 *                 type: string
 *                 description: 콘텐츠 ID
 *                 example: "콘텐츠 고유 식별자"
 *               emails:
 *                 type: array
 *                 items:
 *                   type: string
 *                   format: email
 *                 description: 공유할 사용자 이메일 배열
 *                 example: ["user1@example.com", "user2@example.com"]
 *               role:
 *                 type: string
 *                 enum: [VIEWER, DOWNLOADER, EDITOR]
 *                 default: VIEWER
 *                 description: 공유 권한 (기본값-> VIEWER, OWNER는 사용 불가)
 *                 example: "VIEWER"
 *     responses:
 *       200:
 *         description: 콘텐츠 다중 공유 사용자 추가 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/share/{contentId}/{email}:
 *   delete:
 *     summary: 콘텐츠 공유 사용자 삭제
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: email
 *         required: true
 *         schema:
 *           type: string
 *           format: email
 *         description: 사용자 이메일
 *     responses:
 *       204:
 *         description: 콘텐츠 공유 사용자 삭제 성공
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/title:
 *   patch:
 *     summary: 콘텐츠 제목 수정
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - title
 *             properties:
 *               title:
 *                 type: string
 *                 description: 새로운 제목
 *                 example: "수정된 회의록 제목"
 *     responses:
 *       200:
 *         description: 콘텐츠 제목 수정 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}:
 *   get:
 *     summary: 콘텐츠 상세 조회 lagarcy
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 콘텐츠 상세 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ContentDetailResponse'
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
 *         description: 콘텐츠를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 */

/**
 * @swagger
 * /contents/{contentId}?v=ax:
 *   get:
 *     summary: 콘텐츠 상세 조회 (AX Template Ver)
 *     description: |
 *       콘텐츠 상세 정보를 조회합니다.
 *
 *       회의록 합치기 된 회의록 조회 버전을 구분하기 위해 v 쿼리 스트링이 있습니다.
 *
 *       요청 값은 기존과 동일 합니다.
 *
 *       응답 값에 `linkedContents` 부분이 추가되었습니다.
 *     tags: [AX Template Ver]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 콘텐츠 상세 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ContentDetailTemplateResponse'
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
 *         description: 콘텐츠를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 */

/**
 * @swagger
 * /contents/{contentId}/memo:
 *   get:
 *     summary: 메모 목록 조회
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 메모 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MemoListResponse'
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
 *         description: 콘텐츠를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 */

/**
 * @swagger
 * /contents/{contentId}/memo:
 *   post:
 *     summary: 메모 생성
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - content
 *             properties:
 *               content:
 *                 type: string
 *                 description: 메모 내용
 *                 example: "중요한 포인트 메모"
 *     responses:
 *       201:
 *         description: 메모 생성 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MemoCreateResponse'
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
 */

/**
 * @swagger
 * /contents/{contentId}/memo/{memoId}:
 *   delete:
 *     summary: 메모 삭제
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: memoId
 *         required: true
 *         schema:
 *           type: string
 *         description: 메모 ID
 *     responses:
 *       204:
 *         description: 메모 삭제 성공
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/memo/{memoId}/secret:
 *   patch:
 *     summary: 특정 메모 비공개 설정 업데이트
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: memoId
 *         required: true
 *         schema:
 *           type: string
 *         description: 메모 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - isSecret
 *             properties:
 *               isSecret:
 *                 type: boolean
 *                 description: 비공개 여부
 *                 example: true
 *     responses:
 *       200:
 *         description: 메모 비공개 설정 업데이트 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MemoSecretUpdateByIdResponse'
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
 */

/**
 * @swagger
 * /contents/{contentId}/memo/{memoId}/text:
 *   patch:
 *     summary: 특정 메모 텍스트 업데이트
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: memoId
 *         required: true
 *         schema:
 *           type: string
 *         description: 메모 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - text
 *             properties:
 *               text:
 *                 type: string
 *                 description: 수정된 메모 텍스트
 *                 example: "비밀일까?"
 *     responses:
 *       200:
 *         description: 메모 텍스트 업데이트 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MemoTextUpdateResponse'
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
 */

/**
 * @swagger
 * /contents/{contentId}/memo/{memoId}/comment:
 *   post:
 *     summary: 메모 댓글 생성
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: memoId
 *         required: true
 *         schema:
 *           type: string
 *         description: 메모 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - text
 *             properties:
 *               text:
 *                 type: string
 *                 description: 댓글 내용
 *                 example: "댓글 내용"
 *     responses:
 *       201:
 *         description: 메모 댓글 생성 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MemoCommentCreateResponse'
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
 */

/**
 * @swagger
 * /contents/{contentId}/memo/{memoId}/comment/{commentId}/text:
 *   patch:
 *     summary: 메모 댓글 텍스트 업데이트
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: memoId
 *         required: true
 *         schema:
 *           type: string
 *         description: 메모 ID
 *       - in: path
 *         name: commentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 댓글 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - text
 *             properties:
 *               text:
 *                 type: string
 *                 description: 수정된 댓글 텍스트
 *                 example: "댓글1"
 *     responses:
 *       200:
 *         description: 메모 댓글 텍스트 업데이트 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MemoCommentTextUpdateResponse'
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
 */

/**
 * @swagger
 * /contents/{contentId}/memo/{memoId}/comment/{commentId}:
 *   delete:
 *     summary: 메모 댓글 삭제
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: memoId
 *         required: true
 *         schema:
 *           type: string
 *         description: 메모 ID
 *       - in: path
 *         name: commentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 댓글 ID
 *     responses:
 *       204:
 *         description: 메모 댓글 삭제 성공
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/memo/secret:
 *   patch:
 *     summary: 메모 비공개 설정 업데이트
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - isSecret
 *             properties:
 *               isSecret:
 *                 type: boolean
 *                 description: 비공개 여부
 *                 example: true
 *     responses:
 *       200:
 *         description: 메모 비공개 설정 업데이트 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MemoSecretUpdateResponse'
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
 * */

/**
 * @swagger
 * /contents/{contentId}/note:
 *   get:
 *     summary: 노트 내용 조회
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 노트 내용 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/note:
 *   post:
 *     summary: 노트에 텍스트 붙여넣기
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - text
 *             properties:
 *               text:
 *                 type: string
 *                 description: 붙여넣을 텍스트
 *                 example: "회의록 내용을 노트에 붙여넣기"
 *     responses:
 *       200:
 *         description: 노트 텍스트 붙여넣기 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/note:
 *   patch:
 *     summary: 노트 내용 수정
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - content
 *             properties:
 *               content:
 *                 type: string
 *                 description: 수정된 노트 내용
 *                 example: "수정된 노트 내용"
 *     responses:
 *       200:
 *         description: 노트 내용 수정 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/mynote:
 *   get:
 *     summary: 내 노트 내용 조회
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 내 노트 내용 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/myNote:
 *   patch:
 *     summary: 내 노트 내용 수정
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - content
 *             properties:
 *               content:
 *                 type: string
 *                 description: 수정된 내 노트 내용
 *                 example: "수정된 내 노트 내용"
 *     responses:
 *       200:
 *         description: 내 노트 내용 수정 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/template:
 *   get:
 *     summary: 노트 템플릿 조회
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 노트 템플릿 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/attendees:
 *   get:
 *     summary: 참석자 목록 조회
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 참석자 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/attendees:
 *   post:
 *     summary: 참석자 추가
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - name
 *             properties:
 *               name:
 *                 type: string
 *                 description: 참석자 이름
 *                 example: "김철수"
 *               email:
 *                 type: string
 *                 format: email
 *                 description: 참석자 이메일
 *                 example: "kim@example.com"
 *     responses:
 *       200:
 *         description: 참석자 추가 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/attendees:
 *   put:
 *     summary: 참석자 목록 변경
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - attendees
 *             properties:
 *               attendees:
 *                 type: array
 *                 items:
 *                   type: object
 *                   required:
 *                     - name
 *                   properties:
 *                     name:
 *                       type: string
 *                       description: 참석자 이름
 *                       example: "김철수"
 *                     email:
 *                       type: string
 *                       format: email
 *                       description: 참석자 이메일
 *                       example: "kim@example.com"
 *     responses:
 *       200:
 *         description: 참석자 목록 변경 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/attendees/{speakerId}:
 *   delete:
 *     summary: 참석자 삭제
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: speakerId
 *         required: true
 *         schema:
 *           type: string
 *         description: 화자 ID
 *     responses:
 *       204:
 *         description: 참석자 삭제 성공
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/attendees/{speakerId}:
 *   patch:
 *     summary: 참석자 이름 변경
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: speakerId
 *         required: true
 *         schema:
 *           type: string
 *         description: 화자 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - name
 *             properties:
 *               name:
 *                 type: string
 *                 description: 새로운 참석자 이름
 *                 example: "김영희"
 *     responses:
 *       200:
 *         description: 참석자 이름 변경 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/keywords:
 *   patch:
 *     summary: 콘텐츠 키워드 수정
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - keywords
 *             properties:
 *               keywords:
 *                 type: array
 *                 items:
 *                   type: string
 *                 description: 키워드 배열
 *                 example: ["회의", "프로젝트", "계획"]
 *     responses:
 *       200:
 *         description: 콘텐츠 키워드 수정 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/transcription/reset:
 *   post:
 *     summary: 전사 세그먼트 리셋
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 전사 세그먼트 리셋 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/retry:
 *   post:
 *     summary: 콘텐츠 음성인식 재시도
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 콘텐츠 음성인식 재시도 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ContentRetryResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/OriginalFileNotFoundError'
 *                 - $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               originalFileNotFound:
 *                 summary: 원본 파일 정보를 찾을 수 없음
 *                 value:
 *                   httpCode: 400
 *                   message: "원본 파일 정보를 찾을 수 없습니다."
 *                   errorCode: "E2122"
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/OwnerPermissionRequiredError'
 *                 - $ref: '#/components/schemas/UnauthorizedError'
 *             examples:
 *               ownerPermissionRequired:
 *                 summary: 소유자 권한 필요
 *                 value:
 *                   httpCode: 401
 *                   message: "소유자 권한이 필요합니다."
 *                   errorCode: "E1003"
 *       500:
 *         description: 서버 내부 오류
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/RecognitionRetryQueueNotFoundError'
 *                 - $ref: '#/components/schemas/RecognitionAlreadyInProgressError'
 *                 - $ref: '#/components/schemas/RecognitionRetryFailedError'
 *                 - $ref: '#/components/schemas/InternalServerError'
 *             examples:
 *               queueNotFound:
 *                 summary: 음성인식 재시도 큐가 존재하지 않음
 *                 value:
 *                   httpCode: 500
 *                   message: "음성인식 재시도 큐가 존재하지 않습니다."
 *                   errorCode: "E2186"
 *               alreadyInProgress:
 *                 summary: 이미 음성인식 진행중
 *                 value:
 *                   httpCode: 500
 *                   message: "이미 음성인식 진행중입니다."
 *                   errorCode: "E2187"
 *               retryFailed:
 *                 summary: 음성인식 재시도 실패
 *                 value:
 *                   httpCode: 500
 *                   message: "음성인식 재시도 실패"
 *                   errorCode: "E2188"
 */

/**
 * @swagger
 * /contents/{contentId}/transcription/segments/text:
 *   patch:
 *     summary: 전사 세그먼트 텍스트 변경
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - segments
 *             properties:
 *               segments:
 *                 type: array
 *                 items:
 *                   type: object
 *                   required:
 *                     - id
 *                     - text
 *                   properties:
 *                     id:
 *                       type: string
 *                       description: 세그먼트 ID
 *                       example: "segment-uuid"
 *                     text:
 *                       type: string
 *                       description: 수정된 텍스트
 *                       example: "수정된 전사 내용"
 *     responses:
 *       200:
 *         description: 전사 세그먼트 텍스트 변경 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/transcription/{startTime}/speaker:
 *   patch:
 *     summary: 세그먼트 화자 변경
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: startTime
 *         required: true
 *         schema:
 *           type: number
 *         description: 시작 시간
 *         example: 0.0
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - speakerId
 *             properties:
 *               speakerId:
 *                 type: string
 *                 description: 새로운 화자 ID
 *                 example: "speaker-uuid"
 *     responses:
 *       200:
 *         description: 세그먼트 화자 변경 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/correction:
 *   get:
 *     summary: 교정 정보 조회
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     responses:
 *       200:
 *         description: 교정 정보 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Success'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/correction:
 *   post:
 *     summary: 교정 요청
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - segments
 *             properties:
 *               segments:
 *                 type: array
 *                 items:
 *                   type: object
 *                   required:
 *                     - id
 *                     - originalText
 *                     - correctedText
 *                   properties:
 *                     id:
 *                       type: string
 *                       description: 세그먼트 ID
 *                       example: "segment-uuid"
 *                     originalText:
 *                       type: string
 *                       description: 원본 텍스트
 *                       example: "원본 전사 내용"
 *                     correctedText:
 *                       type: string
 *                       description: 교정된 텍스트
 *                       example: "교정된 전사 내용"
 *     responses:
 *       200:
 *         description: 교정 요청 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/correction/history:
 *   post:
 *     summary: 교정 히스토리 생성
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - correctionData
 *             properties:
 *               correctionData:
 *                 type: object
 *                 description: 교정 데이터
 *                 example: {"corrections": []}
 *     responses:
 *       200:
 *         description: 교정 히스토리 생성 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/reSummary:
 *   post:
 *     summary: 콘텐츠 재요약
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               summaryType:
 *                 type: string
 *                 description: 요약 타입
 *                 example: "detailed"
 *               language:
 *                 type: string
 *                 description: 요약 언어
 *                 example: "ko"
 *               templateId:
 *                 type: string
 *                 description: 템플릿 ID
 *                 example: "DEF-DEFAULT-BASIC"
 *     responses:
 *       200:
 *         description: 콘텐츠 재요약 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/meetingTime:
 *   patch:
 *     summary: 회의 시간 수정
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - startTime
 *               - endTime
 *             properties:
 *               startTime:
 *                 type: string
 *                 format: date-time
 *                 description: 회의 시작 시간
 *                 example: "2024-01-01T09:00:00Z"
 *               endTime:
 *                 type: string
 *                 format: date-time
 *                 description: 회의 종료 시간
 *                 example: "2024-01-01T10:00:00Z"
 *     responses:
 *       200:
 *         description: 회의 시간 수정 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/dictionary:
 *   post:
 *     summary: 단어 사전에 단어 추가
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - words
 *             properties:
 *               words:
 *                 type: array
 *                 items:
 *                   type: string
 *                 description: 추가할 단어 배열
 *                 example: ["전문용어", "고유명사"]
 *     responses:
 *       200:
 *         description: 단어 사전 추가 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/proofreading:
 *   post:
 *     summary: 세그먼트 교정
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - segments
 *             properties:
 *               segments:
 *                 type: array
 *                 items:
 *                   type: object
 *                   required:
 *                     - id
 *                     - text
 *                   properties:
 *                     id:
 *                       type: string
 *                       description: 세그먼트 ID
 *                       example: "segment-uuid"
 *                     text:
 *                       type: string
 *                       description: 교정할 텍스트
 *                       example: "교정할 전사 내용"
 *     responses:
 *       200:
 *         description: 세그먼트 교정 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/export:
 *   get:
 *     summary: 콘텐츠 문서 내보내기
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: query
 *         name: format
 *         schema:
 *           type: string
 *           enum: [pdf, docx, txt]
 *         description: 내보내기 형식
 *         example: "pdf"
 *     responses:
 *       200:
 *         description: 콘텐츠 문서 내보내기 성공
 *         content:
 *           application/octet-stream:
 *             schema:
 *               type: string
 *               format: binary
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/highlight:
 *   post:
 *     summary: 하이라이트 추가
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - startTime
 *               - endTime
 *               - text
 *             properties:
 *               startTime:
 *                 type: number
 *                 description: 시작 시간
 *                 example: 0.0
 *               endTime:
 *                 type: number
 *                 description: 종료 시간
 *                 example: 5.0
 *               text:
 *                 type: string
 *                 description: 하이라이트할 텍스트
 *                 example: "중요한 내용"
 *               color:
 *                 type: string
 *                 description: 하이라이트 색상
 *                 example: "#ffff00"
 *     responses:
 *       200:
 *         description: 하이라이트 추가 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/highlight/{highlightId}:
 *   delete:
 *     summary: 하이라이트 삭제
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *       - in: path
 *         name: highlightId
 *         required: true
 *         schema:
 *           type: string
 *         description: 하이라이트 ID
 *     responses:
 *       204:
 *         description: 하이라이트 삭제 성공
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/{contentId}/summary:
 *   patch:
 *     summary: 요약 내용 수정
 *     tags: [Content]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: contentId
 *         required: true
 *         schema:
 *           type: string
 *         description: 콘텐츠 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - summary
 *             properties:
 *               summary:
 *                 type: string
 *                 description: 수정된 요약 내용
 *                 example: "수정된 요약 내용"
 *     responses:
 *       200:
 *         description: 요약 내용 수정 성공
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
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /contents/merge:
 *   post:
 *     summary: 콘텐츠 합치기
 *     tags: [AX Template Ver]
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
 *               - contentIds
 *             properties:
 *               contentIds:
 *                 type: array
 *                 items:
 *                   type: string
 *                 minItems: 1
 *                 maxItems: 3
 *                 description: 합칠 콘텐츠 ID 배열 (최대 3개)
 *                 example: ["콘텐츠 고유 식별자1", "콘텐츠 고유 식별자2", "콘텐츠 고유 식별자3"]
 *     responses:
 *       200:
 *         description: 콘텐츠 합치기 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MergeContentResponse'
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
 */
