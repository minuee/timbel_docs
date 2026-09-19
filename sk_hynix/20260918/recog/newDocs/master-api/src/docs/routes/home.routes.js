/**
 * @swagger
 * /home:
 *   get:
 *     summary: 대시보드 조회
 *     tags: [Home]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 대시보드 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/HomeResponse'
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
