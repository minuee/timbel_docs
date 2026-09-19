/**
 * @swagger
 * /queue:
 *   get:
 *     summary: 인식 큐 목록 조회 (관리자 전용)
 *     tags: [Queue]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: queueName
 *         schema:
 *           type: string
 *         description: 큐 이름 필터
 *         example: "transcription"
 *     responses:
 *       200:
 *         description: 큐 목록 조회 성공
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
 *       403:
 *         description: 권한 없음 (관리자만 접근 가능)
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ForbiddenError'
 */

/**
 * @swagger
 * /queue/{queueName}/pause:
 *   post:
 *     summary: 큐 일시정지 (관리자 전용)
 *     tags: [Queue]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: queueName
 *         required: true
 *         schema:
 *           type: string
 *         description: 큐 이름
 *         example: "transcription"
 *     responses:
 *       200:
 *         description: 큐 일시정지 성공
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
 *       403:
 *         description: 권한 없음 (관리자만 접근 가능)
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ForbiddenError'
 */

/**
 * @swagger
 * /queue/{queueName}/resume:
 *   post:
 *     summary: 큐 재시작 (관리자 전용)
 *     tags: [Queue]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: queueName
 *         required: true
 *         schema:
 *           type: string
 *         description: 큐 이름
 *         example: "transcription"
 *     responses:
 *       200:
 *         description: 큐 재시작 성공
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
 *       403:
 *         description: 권한 없음 (관리자만 접근 가능)
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ForbiddenError'
 */

/**
 * @swagger
 * /queue/{queueName}/job/moveToFailed:
 *   post:
 *     summary: 작업을 실패 상태로 이동 (관리자 전용)
 *     tags: [Queue]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: queueName
 *         required: true
 *         schema:
 *           type: string
 *         description: 큐 이름
 *         example: "transcription"
 *     responses:
 *       200:
 *         description: 작업 실패 상태 이동 성공
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
 *       403:
 *         description: 권한 없음 (관리자만 접근 가능)
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ForbiddenError'
 */

/**
 * @swagger
 * /queue/{queueName}/job/retry:
 *   post:
 *     summary: 작업 재시도 (관리자 전용)
 *     tags: [Queue]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: queueName
 *         required: true
 *         schema:
 *           type: string
 *         description: 큐 이름
 *         example: "transcription"
 *     responses:
 *       200:
 *         description: 작업 재시도 성공
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
 *       403:
 *         description: 권한 없음 (관리자만 접근 가능)
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ForbiddenError'
 */
