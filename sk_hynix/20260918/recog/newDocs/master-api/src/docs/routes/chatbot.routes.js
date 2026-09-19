/**
 * @swagger
 * /chat/list:
 *   get:
 *     summary: 채팅 목록 조회
 *     tags: [Chatbot]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 채팅 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ChatListResponse'
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
 * /chat/new:
 *   post:
 *     summary: 새로운 채팅 생성
 *     tags: [Chatbot]
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
 *             properties:
 *               attachedContents:
 *                 type: array
 *                 items:
 *                   type: string
 *                   description: "첨부된 회의 ContentID 문자열 배열"
 *               query:
 *                 type: string
 *                 example: "첨부된 회의들에서 A프로젝트 이슈를 정리해줘"
 *                 description: "사용자 메시지"
 *             required:
 *               - query
 *               - attachedContents
 *     responses:
 *       200:
 *         description: 새로운 채팅 생성 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ChatNewResponse'
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
 * /chat/{chatId}:
 *   get:
 *     summary: 채팅 상세 조회
 *     tags: [Chatbot]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: chatId
 *         required: true
 *         schema:
 *           type: string
 *         description: 채팅 ID
 *     responses:
 *       200:
 *         description: 채팅 상세 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ChatDetailResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ChatbotNotFoundError'
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
 * /chat/{chatId}/query:
 *   post:
 *     summary: 채팅 쿼리 전송
 *     tags: [Chatbot]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: chatId
 *         required: true
 *         schema:
 *           type: string
 *         description: 채팅 세션 ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               query:
 *                 type: string
 *                 example: "첨부된 회의들에서 A프로젝트 이슈를 정리해줘"
 *                 description: "사용자 메시지"
 *             required:
 *               - query
 *     responses:
 *       200:
 *         description: 채팅 쿼리 전송 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ChatQueryResponse'
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
 *         description: 채팅을 찾을 수 없음
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
 * /chat/{chatId}:
 *   delete:
 *     summary: 채팅 삭제
 *     tags: [Chatbot]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: chatId
 *         required: true
 *         schema:
 *           type: string
 *         description: 채팅 세션 ID
 *     responses:
 *       204:
 *         description: 채팅 삭제 성공
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
 *         description: 채팅을 찾을 수 없음
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
