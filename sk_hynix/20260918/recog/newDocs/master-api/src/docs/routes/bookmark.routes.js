/**
 * @swagger
 * /bookmark:
 *   get:
 *     summary: 북마크 목록 조회
 *     tags: [Bookmark]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 북마크 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BookmarkListResponse'
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
 * /bookmark/{contentId}:
 *   post:
 *     summary: 북마크 추가
 *     tags: [Bookmark]
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
 *         name: item
 *         required: true
 *         schema:
 *           type: string
 *           enum: [segments, mergedSegments, summaryTime, summary, memo, highlight]
 *         description: 북마크할 항목 타입
 *       - in: query
 *         name: itemId
 *         required: false
 *         schema:
 *           type: string
 *         description: 특정 항목 ID (segments, mergedSegments, summaryTime의 경우 필수)
 *     responses:
 *       200:
 *         description: 북마크 추가 성공
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
 *       500:
 *         description: 서버 오류
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/InternalServerError'
 */

/**
 * @swagger
 * /bookmark/{contentId}:
 *   delete:
 *     summary: 북마크 삭제
 *     tags: [Bookmark]
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
 *         name: item
 *         required: true
 *         schema:
 *           type: string
 *           enum: [segments, mergedSegments, summaryTime, summary, memo, highlight]
 *         description: 북마크할 항목 타입
 *       - in: query
 *         name: itemId
 *         required: false
 *         schema:
 *           type: string
 *         description: 특정 항목 ID (segments, mergedSegments, summaryTime의 경우 필수)
 *     responses:
 *       204:
 *         description: 북마크 삭제 성공
 *       400:
 *         description: 잘못된 요청 (필수 파라미터 부족 또는 잘못된 요청)
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *       401:
 *         description: 인증 실패 (인증 실패, 편집 권한 필요, 또는 멤버를 찾을 수 없음)
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
