# get_user 호출 제거 — 프론트엔드 전달 필드 정리

## 결정 사항

백엔드는 **더 이상 `get_user` API 를 호출하지 않는다.** 사용자 정보가 필요한 API 는
프론트엔드가 payload 로 전달한 값만 사용한다.

- 백엔드는 토큰으로 사용자 정보를 조회하지 않는다 (토큰 검증도 하지 않는다)
- `UserInfoService.getCurrentUser()` **함수 자체는 남겨둔다.** 호출부만 제거한다
- 필요한 값이 payload 에 없으면 해당 부가기능만 동작하지 않는다 (본 기능은 계속 동작해야 한다)

배경: `get_user` 응답 스키마가 변경되어 백엔드가 읽던 필드
(`company.id`, `agent.company_id`, `agent.cc_cti_id`, `company.vendor_tenant_id`)가
전부 사라졌다. 그 결과 실시간 VOC 등이 동작하지 않았다.

---

## 새 get_user 응답 → payload 필드 매핑

프론트엔드는 로그인 시 받은 `get_user` 응답에서 아래 경로의 값을 꺼내
각 API payload 에 담아 보낸다.

| payload 필드 | 새 get_user 경로 | 예시 |
|---|---|---|
| `company.vendor_tenant_id` | `agent.organization.tenant.id` | `"4609686"` |
| `company.code` | `company.code` | `"POC4"` |
| `company.name` | `company.name` | `"Timbel Corp"` |
| `cc_cti_id` | `agent.cti.ctiId` | `"56356659"` |
| `agent_id` | `agent.id` | `"4d763ac5-fec5-4d36-82c0-202d6edb1c37"` |
| `agent_name` | `agent.name` | `"홍길순"` |
| `workspace_id` | `agent.workspace.list[].id` | `"019eca26-837d-77b8-bd77-d90f97d6defc"` |
| `company.id` (회사 UUID) | **새 응답에 없음 — 아래 "미해결" 참고** | `company_ea847481_...` |

> `vendor_tenant_id` 는 숫자로 내려오지만 **문자열로 변환해서** 보낸다.
> Redis 채널명 조립에 그대로 쓰이므로 타입이 섞이면 채널이 어긋난다.

---

## API 별 필요 필드

### 1. `POST /assist-stream` — 실시간 발화

| 필드 | 필요 여부 | 없으면 |
|---|---|---|
| `callId` | **필수** | 실시간 VOC·감지어 탐지가 전부 동작하지 않음 |
| `turnIdx` | 권장 | VOC 결과가 발화와 매칭되지 않아 저장 안 됨 |
| `company.vendor_tenant_id` | **필수** | VOC 실시간 표시(소켓 채널) 불가 |
| `cc_cti_id` | **필수** | VOC 실시간 표시(소켓 채널) 불가 |
| `company.id` | 필요 | VOC 감정분석 불가 (미해결 항목) |
| `workspace_id` | **필수** | AICM 검색 실패(422) |

이미 DTO 에 정의돼 있어 프론트 수정만으로 적용된다. 정의되지 않은 필드를 추가로 보내도
이 엔드포인트는 400 을 내지 않는다(무시하고 통과).

### 2. `POST /summary/**` — 상담 요약 / VOC 분석

| 필드 | 필요 여부 | 없으면 |
|---|---|---|
| `company.id` | 필요 | LLM 호출 불가 (미해결 항목) |
| `company.vendor_tenant_id` | 권장 | 토큰 만료 시 DB 저장 실패 |

이미 DTO(`SummaryCompanyDto`)에 정의돼 있다.

### 3. `POST /coachings/**` — 코칭 / 코칭 요청 생성

| 필드 | 필요 여부 | 없으면 |
|---|---|---|
| `vendor_tenant_id` | 필요 | 코칭 알림 소켓이 상대에게 전달되지 않음 (생성 자체는 성공) |

**DTO 추가 필요** — 현재 받지 않는다.

### 4. `POST /todos/auto-create` — 할 일 자동생성 (CE 호출)

| 필드 | 필요 여부 | 없으면 |
|---|---|---|
| `company.id` | **필수** | CE 호출용 X-Tenant-Id 를 못 구해 자동생성이 실패한다 |

```json
{
  "callstats_id": "...", "maxLength": 100, "includeSimple": true, "user_key": "...",
  "company": { "id": "company_71900448_1b8a_4ab1_96b3_9f2c1de46740" }
}
```

**백엔드 DTO 반영 완료** — `company` 를 받아 `company.id` 를 X-Tenant-Id 로 쓴다.

> `POST /todos`(수동 생성)에는 **넣지 않는다.** DB 저장만 하고 CE 를 부르지 않아 필요 없으며,
> 정의되지 않은 필드라 보내면 400 이 난다.

### 5. `POST /postcall/**` — 대상 아님

CE 원본 응답을 확인하는 **테스트용 엔드포인트**다(Swagger 설명·DTO 이름에 Test 표기).
프론트가 호출하지 않으므로 변경하지 않는다.

### 6. `GET /agents/assignable?favorite_only=true` — 관리자 상담원 목록 (즐겨찾기 필터)

| 파라미터 | 필요 여부 | 없으면 |
|---|---|---|
| `agent_id` | `favorite_only=true` 일 때 **필수** | 즐겨찾기 필터가 동작하지 않음 |

**쿼리 파라미터 추가 필요** — 현재는 토큰으로 본인을 식별한다.

```
GET /aicc/asst-service/agents/assignable?favorite_only=true
      &agent_id=4d763ac5-fec5-4d36-82c0-202d6edb1c37
```

- 값: 새 get_user 의 `agent.id`
- `favorite_only` 가 false 이거나 없으면 보내지 않아도 된다

> 이 값이 "누구의 즐겨찾기인가"를 정한다. 프론트가 보내는 값을 그대로 쓰므로 다른 상담사의
> `agent_id` 를 넣으면 그 사람 즐겨찾기가 조회된다. AuthMiddleware 가 이미 토큰을 검증하지
> 않으므로 현재와 보안 수준은 같다.

### 7. `GET {USER_HOST}/api/user/assignable` — 백엔드가 계속 호출한다

배정 가능 상담원 목록 조회다. "로그인한 내 정보"가 아니고, 백엔드가 응답을 가공
(필터·페이징·즐겨찾기 결합)하므로 그대로 둔다. **프론트가 할 일 없음.**

---

## 범위에 포함되지 않는 것

### user-proxy (그대로 둔다)

`src/common/proxy/user-proxy.controller.ts` 가 user-service API 14개를 프론트로 그대로
프록시한다(`get_user` 포함). 백엔드가 응답을 파싱하지 않고 통과만 시키므로 스키마 변경과 무관하다.

### 토큰은 계속 필요하다

get_user 를 호출하지 않는 것과 토큰을 쓰지 않는 것은 다르다.
**프론트는 지금처럼 `X-auth-token` 헤더를 계속 보내야 한다.**

1. **DB 연결 키** — `getRepository(entity, token)` 가 거의 모든 서비스에 있고, 토큰이 없으면
   `인증 토큰이 필요합니다` 로 실패한다. 현재 `DB_DIRECT_CON=1` 이라 값 자체는 쓰지 않지만
   존재는 해야 한다(멀티테넌트 전환 시 값도 사용).
2. **업스트림 인증** — CE / AICM / LLM / postcall 호출에 토큰을 그대로 전달한다. 상대 서비스 요구사항이다.
3. **세션 만료 알림** — assist-stream 이 토큰 `exp` 를 읽어 만료 임박을 SSE 로 알린다.

---

## 미해결: 회사 UUID (`company.id`)

`company_ea847481_5835_4429_8e9e_85e0d1667984` 형식의 값으로, LLM·VOC 오케스트레이터의
`X-Tenant-Id` 헤더에 쓰인다.

**이 값은 새 get_user 응답에 없다.** JWT 클레임에도 없다. 따라서 프론트도 보낼 수 없다.
현재 이 값이 필요한 기능(실시간 VOC 감정분석 / 상담 요약 / postcall / todo LLM)은 동작하지 않는다.

가능한 방향:

1. **JWT 클레임에 추가** (권장) — user-service 가 토큰에 회사 UUID 를 넣어준다.
   위조 불가하고, 프론트가 신경 쓸 것도 없고, 멀티테넌트에서도 그대로 동작한다.
   현재 토큰에는 `cd: "POC4"`(회사 코드)까지만 있다.
2. **get_user 응답에 다시 포함** — 프론트가 payload 로 전달한다. 다만 프론트가 보내는 값을
   그대로 테넌트 식별에 쓰게 되어, 위조 시 다른 테넌트로 LLM 을 호출할 여지가 생긴다.
3. **환경변수 주입** — 단일 테넌트인 동안만 유효한 임시 방편.

---

## 적용 순서

프론트 수정 전에 백엔드가 먼저 호출을 제거하면 그 사이 기능이 죽는다. 아래 순서로 간다.

1. 백엔드: 위 표의 **DTO 필드를 선택값으로 먼저 추가** (프론트가 보내도 400 안 나게)
2. 프론트: 각 API payload 에 필드 추가
3. 백엔드: `getCurrentUser()` 호출부 제거 (함수는 유지)
4. 회사 UUID 방향이 정해지면 해당 기능 복구

---

## 참고: 새 get_user 응답 전문

```json
{
  "company": { "code": "POC4", "name": "Timbel Corp" },
  "agent": {
    "id": "4d763ac5-fec5-4d36-82c0-202d6edb1c37",
    "name": "홍길순",
    "role": "AGENT",
    "status": "ACTIVE",
    "email": "agent01@timbel.net",
    "account": { "id": 4, "loginId": "agent01" },
    "organization": {
      "tenant": { "id": 4609686, "name": null },
      "center": { "id": null, "name": null },
      "team":   { "id": null, "name": null },
      "part":   { "id": null, "name": null }
    },
    "cti": { "ctiId": "56356659" },
    "workspace": {
      "assignedId": null,
      "list": [
        { "id": "019eca26-837d-77b8-bd77-d90f97d6defc", "name": "한국투자증권" }
      ]
    },
    "permissions": { "ce": null, "qa": null, "ta": null, "aicm": { }, "advisor": null }
  }
}
```
