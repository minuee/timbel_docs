# Swagger 문서 자동 업데이트 Agent 프롬프트

## 개요

이 프롬프트는 API 변경사항에 따라 Swagger 문서를 자동으로 업데이트하는 Agent 기능을 위한 것입니다. 사용자가 API 응답 데이터를 제공하면, 해당 API의 스키마를 생성하고 적절한 라우트 파일을 업데이트합니다.

## 사용 방법

### 1. API 정보 제공

다음 형식으로 API 정보를 제공해주세요:

```
API 경로: [HTTP 메서드] [경로]
예: GET /user/profile, POST /contents/upload, DELETE /bookmark/{id}

응답 데이터:
{
  "message": "Success",
  "httpCode": 200,
  "data": {
    // 실제 응답 데이터 구조
  }
}
```

### 2. Agent 실행 지침

다음 단계를 따라 Swagger 문서를 업데이트하세요:

#### 단계 1: 기존 스키마 분석 및 중복 검사

-   `src/docs/schemas/dataSchemas.js` 파일을 먼저 읽어서 기존 스키마 구조 파악
-   `src/docs/schemas/baseSchemas.js` 파일도 확인하여 재사용 가능한 기본 스키마 식별
-   제공된 응답 데이터와 유사한 구조의 기존 스키마가 있는지 분석
-   중복되는 부분이 있다면 기존 스키마를 재사용하거나 확장하는 방안 검토

#### 단계 2: API 경로 분석 및 파일 식별

-   제공된 API 경로를 분석하여 해당하는 라우트 파일을 식별
-   파일 위치: `src/docs/routes/[카테고리].routes.js`
-   예: `/user/*` → `user.routes.js`, `/contents/*` → `content.routes.js`

#### 단계 3: 스키마 구조 설계 및 중복 방지

-   **중복 방지 원칙**:
    -   동일한 데이터 구조가 이미 존재하는 경우 기존 스키마 재사용
    -   부분적으로 중복되는 경우 공통 부분을 별도 스키마로 분리
    -   배열 내 객체가 복잡한 경우 별도 스키마로 분리하여 재사용성 확보
-   **스키마 분리 기준**:
    -   3개 이상의 필드를 가진 객체는 별도 스키마로 분리
    -   다른 API에서도 사용될 가능성이 있는 공통 구조는 별도 스키마로 분리
    -   중첩 레벨이 2단계 이상인 경우 적절히 분리
-   **스키마 이름 규칙**:
    -   메인 응답: `[API명]Response` (예: `UserProfileResponse`)
    -   중첩 객체: `[객체명]` (예: `UserProfileData`, `BookmarkItem`)
    -   공통 구조: `[구조명]` (예: `SpeakerInfo`, `ContentItem`)

#### 단계 4: 응답 스키마 생성

-   제공된 응답 데이터를 분석하여 적절한 스키마 구조 생성
-   기존 스키마와의 중복을 최소화하고 재사용 가능한 구조로 설계
-   UUID, CUID, 실제 데이터는 설명문으로 변경

#### 단계 5: 스키마 파일 업데이트 (실행)

-   `src/docs/schemas/dataSchemas.js` 파일을 읽기
-   파일 끝부분의 `* */` 바로 앞에 새로운 스키마 추가
-   `search_replace` 도구를 사용하여 스키마 추가
-   기존 스키마와의 중복을 피하고 재사용 가능한 구조로 설계

#### 단계 6: 라우트 파일 업데이트 (실행)

-   해당 라우트 파일을 읽기
-   API 엔드포인트의 200 응답 스키마를 새로 생성한 스키마로 변경
-   `search_replace` 도구를 사용하여 스키마 참조 업데이트
-   400, 401, 404 등의 에러 응답은 적절한 에러 스키마 사용:
    -   400: `BadRequestError`
    -   401: `UnauthorizedError`
    -   404: `NotFoundError`

#### 단계 7: 검증 및 완료

-   생성된 스키마가 실제 응답 데이터와 일치하는지 확인
-   모든 필드에 적절한 타입, 예시, 설명 추가
-   한국어 설명 사용
-   기존 스키마와의 중복이 없는지 최종 확인

## 스키마 생성 규칙

### 기본 구조

```javascript
*     [SchemaName]Response:
*       allOf:
*         - $ref: '#/components/schemas/Success'
*         - type: object
*           properties:
*             data:
*               // 실제 데이터 구조
```

### 중복 방지 전략

#### 1. 공통 구조 식별

-   사용자 정보, 콘텐츠 정보, 화자 정보 등 공통적으로 사용되는 구조
-   날짜/시간 필드, ID 필드, 상태 필드 등 공통 필드 패턴

#### 2. 스키마 분리 기준

```javascript
// 분리해야 하는 경우
{
  "user": {
    "userId": "string",
    "nickname": "string",
    "email": "string",
    "profile": {
      "avatar": "string",
      "bio": "string",
      "settings": {
        "theme": "string",
        "language": "string"
      }
    }
  }
}

// 분리 결과
*     UserResponse:
*       allOf:
*         - $ref: '#/components/schemas/Success'
*         - type: object
*           properties:
*             data:
*               $ref: '#/components/schemas/UserProfile'

*     UserProfile:
*       type: object
*       properties:
*         userId:
*           type: string
*         nickname:
*           type: string
*         email:
*           type: string
*         profile:
*           $ref: '#/components/schemas/UserProfileDetail'

*     UserProfileDetail:
*       type: object
*       properties:
*         avatar:
*           type: string
*         bio:
*           type: string
*         settings:
*           $ref: '#/components/schemas/UserSettings'
```

#### 3. 재사용 가능한 스키마 설계

-   `SpeakerInfo`: 화자 정보 (speakerId, name, displayName, pid)
-   `ContentItem`: 콘텐츠 기본 정보 (contentId, title, type, duration 등)
-   `UserInfo`: 사용자 기본 정보 (userId, nickname, email)
-   `TimeRange`: 시간 범위 (startTime, endTime, duration)
-   `PaginationInfo`: 페이지네이션 정보 (currentPage, lastPage, \_count)

### 필드 타입 매핑

-   `string` (UUID/CUID): "고유 식별자" 형태의 설명문
-   `string` (date-time): "2025-01-01T00:00:00.000Z" 형태의 예시
-   `integer`: 실제 숫자 값 유지
-   `boolean`: true/false 유지
-   `array`: 단일 아이템으로 예시 생성
-   `object`: 중첩된 경우 별도 스키마로 분리

### 예시 값 변환

-   UUID: `"7ca969b0-fcb7-48df-908e-fced2c7985ee"` → `"콘텐츠 고유 식별자"`
-   실제 텍스트: `"윤석열 전 대통령 체포영장"` → `"콘텐츠 제목"`
-   날짜: `"2025-09-15T06:42:48.988Z"` → `"2025-09-15T06:42:48.988Z"` (유지)

## 에러 처리

### 일반적인 에러 응답

```javascript
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
```

### DELETE API 특별 처리

-   DELETE API는 204 No Content 응답 사용
-   content 섹션 제거

## 파일 구조

```
src/docs/
├── routes/
│   ├── user.routes.js
│   ├── content.routes.js
│   ├── bookmark.routes.js
│   └── ...
├── schemas/
│   ├── dataSchemas.js      # 새로운 응답 스키마 추가
│   ├── baseSchemas.js      # 재사용 가능한 기본 스키마
│   └── timbloErrorSchemas.js
└── AGENT_PROMPT.md         # 이 파일
```

## 중복 검사 및 구조 설계 예시

### 예시 1: 사용자 프로필 API

```json
// 입력 데이터
{
	"message": "Success",
	"httpCode": 200,
	"data": {
		"userId": "7ca969b0-fcb7-48df-908e-fced2c7985ee",
		"nickname": "사용자123",
		"email": "user@example.com",
		"profile": {
			"avatar": "https://example.com/avatar.jpg",
			"bio": "사용자 소개",
			"settings": {
				"theme": "dark",
				"language": "ko"
			}
		},
		"createdAt": "2025-09-15T06:42:48.988Z"
	}
}
```

### 중복 검사 결과

-   기존에 `UserInfo` 스키마가 있는지 확인
-   `profile` 객체가 다른 API에서도 사용되는지 확인
-   `settings` 객체가 재사용 가능한지 확인

### 구조 설계 결과

```javascript
// 1. 기존 UserInfo 스키마가 있다면 재사용
*     UserProfileResponse:
*       allOf:
*         - $ref: '#/components/schemas/Success'
*         - type: object
*           properties:
*             data:
*               allOf:
*                 - $ref: '#/components/schemas/UserInfo'  // 기존 스키마 재사용
*                 - type: object
*                   properties:
*                     profile:
*                       $ref: '#/components/schemas/UserProfileDetail'

// 2. 새로운 UserProfileDetail 스키마 생성
*     UserProfileDetail:
*       type: object
*       properties:
*         avatar:
*           type: string
*           example: "프로필 이미지 URL"
*           description: "프로필 이미지"
*         bio:
*           type: string
*           example: "사용자 소개"
*           description: "자기소개"
*         settings:
*           $ref: '#/components/schemas/UserSettings'

// 3. 재사용 가능한 UserSettings 스키마 생성
*     UserSettings:
*       type: object
*       properties:
*         theme:
*           type: string
*           example: "dark"
*           description: "테마 설정"
*         language:
*           type: string
*           example: "ko"
*           description: "언어 설정"
```

## 실행 예시

### 1. 스키마 생성

```javascript
// dataSchemas.js에 추가할 스키마 구조
*     UserProfileResponse:
*       allOf:
*         - $ref: '#/components/schemas/Success'
*         - type: object
*           properties:
*             data:
*               allOf:
*                 - $ref: '#/components/schemas/UserInfo'
*                 - type: object
*                   properties:
*                     profile:
*                       $ref: '#/components/schemas/UserProfileDetail'
```

### 2. 도구 사용법

1. `read_file`로 `dataSchemas.js` 파일 읽기
2. 기존 스키마와 중복 검사 수행
3. `search_replace`로 스키마 추가 (중복되지 않는 부분만)
4. `read_file`로 라우트 파일 읽기
5. `search_replace`로 API 응답 스키마 업데이트

## 주의사항

1. **중복 방지 우선**: 새로운 스키마 생성 전에 기존 스키마와의 중복을 반드시 확인
2. **재사용성 고려**: 다른 API에서도 사용될 가능성이 있는 구조는 별도 스키마로 분리
3. **일관성 유지**: 다른 API와 동일한 네이밍 규칙과 구조 사용
4. **한국어 설명**: 모든 필드에 한국어 설명 추가
5. **타입 정확성**: 실제 데이터 타입과 일치하는 스키마 타입 사용
6. **예시 값**: 실제 데이터 대신 설명적인 예시 값 사용
7. **스키마 분리**: 복잡한 중첩 구조는 적절히 분리하여 가독성과 재사용성 확보

이 프롬프트를 사용하여 API 변경사항에 따라 Swagger 문서를 자동으로 업데이트할 수 있습니다.
