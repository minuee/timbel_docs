/**
 * @swagger
 * /keyword:
 *   post:
 *     summary: 키워드 부스팅 생성
 *     tags: [Keyword]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/CreateKeywordBoostingRequest'
 *           example:
 *             keyword: "한글"
 *     responses:
 *       200:
 *         description: 키워드 부스팅 생성 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/KeywordListResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               missing_keyword:
 *                 summary: 키워드 필수 파라미터 누락
 *                 value:
 *                   message: "필수 파라미터가 부족합니다."
 *                   httpCode: 400
 *                   errorCode: "E1000"
 *               keyword_contains_english:
 *                 summary: 키워드에 영어 문자 포함
 *                 value:
 *                   message: "키워드에 영어 문자가 포함되어있습니다."
 *                   httpCode: 400
 *                   errorCode: "E14402"
 *               keyword_already_exists:
 *                 summary: 이미 존재하는 키워드
 *                 value:
 *                   message: "이미 존재하는 키워드 입니다."
 *                   httpCode: 400
 *                   errorCode: "E14501"
 *               keyword_max_count_exceeded:
 *                 summary: 키워드 최대 개수 초과
 *                 value:
 *                   message: "키워드 최대 개수를 초과했습니다."
 *                   httpCode: 400
 *                   errorCode: "E14505"
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
 *             examples:
 *               keyword_creation_failed:
 *                 summary: 키워드 생성 실패
 *                 value:
 *                   message: "키워드 생성 실패"
 *                   httpCode: 500
 *                   errorCode: "E14503"
 *   get:
 *     summary: 키워드 부스팅 목록 조회
 *     tags: [Keyword]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: sortOrder
 *         schema:
 *           type: string
 *           enum: [latest, alphabetical]
 *         description: 정렬 순서
 *         example: latest
 *         default: latest
 *     responses:
 *       200:
 *         description: 키워드 부스팅 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/KeywordListResponse'
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
 * /keyword/{keywordId}:
 *   delete:
 *     summary: 키워드 부스팅 삭제
 *     tags: [Keyword]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: keywordId
 *         required: true
 *         schema:
 *           type: integer
 *         description: 삭제할 키워드 부스팅 ID
 *         example: 1
 *     responses:
 *       200:
 *         description: 키워드 부스팅 삭제 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/KeywordListResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/BadRequestError'
 *             examples:
 *               missing_keyword_id:
 *                 summary: 키워드 ID 파라미터 누락
 *                 value:
 *                   message: "필수 파라미터가 부족합니다."
 *                   httpCode: 400
 *                   errorCode: "E1000"
 *               keyword_not_found:
 *                 summary: 존재하지 않는 키워드
 *                 value:
 *                   message: "존재하지 않는 키워드 입니다."
 *                   httpCode: 400
 *                   errorCode: "E14506"
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
 *             examples:
 *               keyword_delete_failed:
 *                 summary: 키워드 삭제 실패
 *                 value:
 *                   message: "키워드 삭제 실패"
 *                   httpCode: 500
 *                   errorCode: "E14504"
 */
