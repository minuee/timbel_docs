/**
 * @swagger
 * components:
 *   schemas:
 *     SegmentToSummaryRequest:
 *       type: object
 *       required:
 *         - speakerMap
 *         - segments
 *       properties:
 *         speakerMap:
 *           type: object
 *           description: 화자 매핑 정보
 *           example: {"speaker1": "김철수", "speaker2": "이영희"}
 *         segments:
 *           type: array
 *           description: 세그먼트 배열
 *           items:
 *             type: object
 *             properties:
 *               speaker:
 *                 type: string
 *                 description: 화자
 *                 example: "speaker1"
 *               text:
 *                 type: string
 *                 description: 텍스트 내용
 *                 example: "안녕하세요"
 *               startTime:
 *                 type: number
 *                 description: 시작 시간
 *                 example: 0.0
 *               endTime:
 *                 type: number
 *                 description: 종료 시간
 *                 example: 2.5
 */

/**
 * @swagger
 * /integrate/summary:
 *   post:
 *     summary: 세그먼트를 요약으로 변환
 *     tags: [Integrate]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/SegmentToSummaryRequest'
 *     responses:
 *       200:
 *         description: 세그먼트 요약 변환 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/IntegrateSummaryResponse'
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
