/**
 * @swagger
 * /notice:
 *   get:
 *     summary: 공지사항 목록 조회
 *     tags: [Notice]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 공지사항 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NoticeListResponse'
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
