/**
 * @swagger
 * /template:
 *   get:
 *     summary: 템플릿 목록 조회
 *     tags: [Template]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: type
 *         required: false
 *         schema:
 *           type: string
 *           enum: [normal, merged]
 *           default: normal
 *         description: 템플릿 타입 (normal=일반 회의록 템플릿, merged=회의록 합치기 템플릿)
 *     responses:
 *       200:
 *         description: 템플릿 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/TemplateCategoryResponse'
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
 *
 * /template/{templateId}/favorite:
 *   post:
 *     summary: 템플릿 즐겨찾기 추가
 *     tags: [Template]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: templateId
 *         required: true
 *         schema:
 *           type: string
 *         description: 템플릿 ID
 *     responses:
 *       200:
 *         description: 템플릿 즐겨찾기 추가 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/TemplateFavoriteResponse'
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
