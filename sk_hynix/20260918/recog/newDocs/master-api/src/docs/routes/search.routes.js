/**
 * @swagger
 * /search:
 *   get:
 *     summary: 키워드로 콘텐츠 검색
 *     tags: [Search]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: keyword
 *         required: true
 *         schema:
 *           type: string
 *         description: 검색 키워드
 *         example: "회의록"
 *       - in: query
 *         name: filter
 *         schema:
 *           type: string
 *           enum: [all, title, hashTag, creator, detail, fileName]
 *           default: all
 *         description: "검색 필터 (기본값 all, all=전체, title=제목, hashTag=해시태그, creator=생성자, detail=상세내용, fileName=파일명)"
 *         example: "all"
 *       - in: query
 *         name: page
 *         schema:
 *           type: integer
 *           default: 1
 *         description: "페이지 번호 (기본값 1)(선택)"
 *       - in: query
 *         name: take
 *         schema:
 *           type: integer
 *         description: "페이지당 항목 수 (없거나 혹은 0일 때 전체 검색)"
 *         example: 0
 *       - in: query
 *         name: startDate
 *         schema:
 *           type: string
 *           format: date
 *         description: "시작 날짜 (선택사항, 없으면 전체 기간 검색)"
 *         example: "2024-01-01"
 *       - in: query
 *         name: endDate
 *         schema:
 *           type: string
 *           format: date
 *         description: "종료 날짜 (선택사항, 없으면 현재 날짜까지 검색)"
 *         example: "2025-12-31"
 *       - in: query
 *         name: attendee
 *         schema:
 *           type: string
 *         description: "참석자 검색 키워드 (선택사항)"
 *       - in: query
 *         name: folderId
 *         schema:
 *           type: string
 *         description: "폴더 ID (특정 폴더 내에서만 검색). 가상 폴더= root(전체), received(공유받은), sent(공유한), success(완료된), error(미완성)"
 *         example: "root"
 *       - in: query
 *         name: shared
 *         schema:
 *           type: string
 *           enum: [received, sent]
 *         description: "공유 여부 필터 (received=공유받은 콘텐츠, sent=공유한 콘텐츠)"
 *         example: "received"
 *       - in: query
 *         name: mediaType
 *         schema:
 *           type: string
 *           enum: [AUDIO, VIDEO, RECORD]
 *         description: "미디어 타입 필터"
 *         example: "AUDIO"
 *     responses:
 *       200:
 *         description: 검색 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/SearchResponse'
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

/**
 * @swagger
 * /search/history/keyword:
 *   get:
 *     summary: 검색 키워드 히스토리 조회
 *     tags: [Search]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 검색 키워드 히스토리 조회 성공
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
 * /search/history/keyword:
 *   delete:
 *     summary: 모든 검색 키워드 히스토리 삭제
 *     tags: [Search]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       204:
 *         description: 모든 검색 키워드 히스토리 삭제 성공
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */

/**
 * @swagger
 * /search/history/keyword/{keywordId}:
 *   delete:
 *     summary: 특정 검색 키워드 히스토리 삭제
 *     tags: [Search]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: keywordId
 *         required: true
 *         schema:
 *           type: string
 *         description: 키워드 ID
 *     responses:
 *       204:
 *         description: 검색 키워드 히스토리 삭제 성공
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 */
