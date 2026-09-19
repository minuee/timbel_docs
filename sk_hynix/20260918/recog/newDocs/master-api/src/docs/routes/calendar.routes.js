/**
 * @swagger
 * /calendar:
 *   get:
 *     summary: 캘린더 목록 조회
 *     tags: [Calendar]
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
 *         example: "20251001"
 *       - in: query
 *         name: endDate
 *         schema:
 *           type: string
 *           format: date
 *         description: 종료 날짜
 *         example: "20251031"
 *     responses:
 *       200:
 *         description: 캘린더 목록 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/CalendarListResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/BadRequestError'
 *                 - $ref: '#/components/schemas/CalendarValidationError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *   post:
 *     summary: 캘린더 생성
 *     tags: [Calendar]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/CalendarCreateRequest'
 *     responses:
 *       200:
 *         description: 캘린더 생성 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/CalendarCreateResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/BadRequestError'
 *                 - $ref: '#/components/schemas/CalendarValidationError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *
 * /calendar/integrate/webcal:
 *   post:
 *     summary: Webcal 연동
 *     tags: [Calendar]
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
 *               - url
 *             properties:
 *               url:
 *                 type: string
 *                 format: uri
 *                 example: "https://calendar.google.com/calendar/ical/user@example.com/private-abc123def456/basic.ics"
 *                 description: "Webcal URL (Google Calendar, Outlook 등 지원)"
 *     responses:
 *       200:
 *         description: Webcal 통합 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/WebcalIntegrateResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/BadRequestError'
 *                 - $ref: '#/components/schemas/CalendarValidationError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *
 * /calendar/integrate/settings:
 *   get:
 *     summary: 캘린더 통합 설정 조회
 *     tags: [Calendar]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 캘린더 통합 설정 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               allOf:
 *                 - $ref: '#/components/schemas/Success'
 *                 - type: object
 *                   properties:
 *                     data:
 *                       type: array
 *                       items:
 *                         $ref: '#/components/schemas/WebcalIntegrateItem'
 *                       description: "캘린더 통합 설정 목록"
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/BadRequestError'
 *                 - $ref: '#/components/schemas/CalendarValidationError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'

 * /calendar/integrate/disconnect/{provider}:
 *   delete:
 *     summary: 캘린더 통합 연결 해제
 *     tags: [Calendar]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: provider
 *         required: true
 *         schema:
 *           type: string
 *           enum: [outlook, google]
 *         description: 캘린더 제공자
 *         example: "google"
 *     responses:
 *       200:
 *         description: 캘린더 통합 연결 해제 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/CalendarDisconnectResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/BadRequestError'
 *                 - $ref: '#/components/schemas/CalendarValidationError'
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

 * /calendar/integrate/sync:
 *   post:
 *     summary: 캘린더 동기화
 *     tags: [Calendar]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: query
 *         name: force
 *         schema:
 *           type: boolean
 *           default: false
 *         description: 강제 동기화 여부
 *         example: false
 *     responses:
 *       200:
 *         description: 캘린더 동기화 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/CalendarSyncResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/BadRequestError'
 *                 - $ref: '#/components/schemas/CalendarValidationError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'

 * /calendar/integrate/load:
 *   post:
 *     summary: 연동 데이터 캘린더로 불러오기
 *     tags: [Calendar]
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
 *               - ids
 *             properties:
 *               ids:
 *                 type: array
 *                 items:
 *                   type: string
 *                   format: uuid
 *                 example: ["ad761f41-9517-4b65-8b28-639cfbce1e96"]
 *                 description: "캘린더 통합 ID 목록 (최소 1개 이상)"
 *     responses:
 *       200:
 *         description: 캘린더 통합 로드 성공
 *         content:
 *           application/json:
 *             schema:
 *               allOf:
 *                 - $ref: '#/components/schemas/Success'
 *                 - type: object
 *                   properties:
 *                     data:
 *                       type: object
 *                       properties:
 *                         count:
 *                           type: integer
 *                           example: 1
 *                           description: "로드된 캘린더 통합 개수"
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/BadRequestError'
 *                 - $ref: '#/components/schemas/CalendarValidationError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'

 * /calendar/integrate/:
 *   get:
 *     summary: 캘린더 통합 이벤트 조회
 *     tags: [Calendar]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     responses:
 *       200:
 *         description: 캘린더 통합 이벤트 조회 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/CalendarIntegrateResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/BadRequestError'
 *                 - $ref: '#/components/schemas/CalendarValidationError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'

 * /calendar/{id}:
 *   put:
 *     summary: 캘린더 일정 수정 ( 알림 시간 변경 )
 *     description: |
 *       ### 지정된 ID의 캘린더 알림 시간을 수정합니다.
 *       
 *       **주요 기능:**
 *       - 캘린더 일정의 알림 시간(reminderMinutes)을 수정
 *       - 알림 시간이 0보다 큰 경우 알림 작업을 스케줄링
 *       - 기존 알림이 있는 경우 취소 후 새로 설정
 * 
 *     tags: [Calendar]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: string
 *           format: uuid
 *         description: 수정할 캘린더 이벤트의 고유 식별자
 *         example: "2b124408-f448-45ab-a7a9-f178f2ecd6cf"
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/CalendarUpdateRequest'
 *     responses:
 *       200:
 *         description: 캘린더 일정 수정 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/CalendarUpdateResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/BadRequestError'
 *                 - $ref: '#/components/schemas/CalendarValidationError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       404:
 *         description: 캘린더 이벤트를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 *       410:
 *         description: 회의 시작 시간이 지남
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/MeetingTimePassedError'
 *   delete:
 *     summary: 캘린더 일정 삭제
 *     description: |
 *       ### 지정된 ID의 캘린더 일정을 삭제합니다.
 *       
 *       **주요 기능:**
 *       ( 기본 기능은 일반 recycle API와 동일 )
 *       - 연결된 회의록이 있는 경우 회의록이 삭제
 *       - 연결된 회의록이 공유 받은 회의록의 경우, 공유가 취소됨
 * 
 *       **연결된 회의록이 없는 경우:**
 *       - 캘린더 일정 자체가 삭제됨
 *       - 연동으로 추가된 회의록의 경우 불러온 일정만 제거됨
 *       - 연동에서 다시 불러오기가 가능 한 상태
 *     tags: [Calendar]
 *     security:
 *       - bearerAuth: []
 *       - timbloTokenAuth: []
 *       - sessionAuth: []
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: string
 *           format: uuid
 *         description: 삭제할 캘린더 이벤트의 고유 식별자
 *         example: "7ca969b0-fcb7-48df-908e-fced2c7985ee"
 *     responses:
 *       204:
 *         description: 캘린더 이벤트 삭제 성공
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/CalendarDeleteResponse'
 *       400:
 *         description: 잘못된 요청
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/BadRequestError'
 *                 - $ref: '#/components/schemas/CalendarValidationError'
 *       401:
 *         description: 인증 실패
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/UnauthorizedError'
 *       403:
 *         description: 권한 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ForbiddenError'
 *       404:
 *         description: 캘린더 이벤트를 찾을 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/NotFoundError'
 *       409:
 *         description: 외부 캘린더 이벤트는 삭제할 수 없음
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: "외부 캘린더 이벤트는 삭제할 수 없습니다"
 *                   description: "에러 메시지"
 *                 httpCode:
 *                   type: integer
 *                   example: 409
 *                   description: "HTTP 상태 코드"
 *                 error:
 *                   type: string
 *                   example: "EXTERNAL_CALENDAR_DELETE_NOT_ALLOWED"
 *                   description: "에러 코드"
 */
