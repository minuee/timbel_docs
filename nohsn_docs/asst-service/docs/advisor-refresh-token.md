# Advisor 토큰 갱신(refresh token) 정리

> 고객사 시연 중 실시간 VOC가 "한 번 찍히고 멈춘" 이슈에서 출발해, 토큰 만료/갱신 구조를 분석한 기록.
> 결론: **access 토큰 수명이 매우 짧은데(약 17분) 만료 시 refreshToken으로 자동 갱신이 안 되는 것**이 원인. 코드 버그가 아니라 인증 세션/갱신 배선 문제.

---

## 1. 발단 — 실시간 VOC "한 번 찍히고 멈춤"

- 증상: 콜 상담 시연에서 VOC(감정/민원/이탈)가 첫 발화에 1번 찍힌 뒤 이후 변화 없음.
- 로그: `voc-realtime.service.ts:393` `실시간 VOC 처리 실패(무시): ...`
- 위치: `POST /api/asst/v1/assist-stream` (프론트가 상담 중 발화마다 호출) → `handleUtterance` catch.
  - `assist-stream`은 `AuthMiddleware` 제외 경로라, 컨트롤러가 `x-auth-token` 헤더에서 토큰을 직접 추출해 사용(`assist-stream.controller.ts:62-68`).
  - fire-and-forget(`setImmediate`)이라 **SSE 상담 보조 스트림 자체는 안 막히고 VOC 분석만 조용히 스킵**됨.

### 왜 catch까지 왔나 (원인 지점)
`handleUtterance` try 블록 4단계 중 실제로 throw를 올리는 건 사실상 하나뿐:
- `acquireVocLock` / `publishVoc` / `persistVoc` → 각자 내부 try/catch로 삼키고 `false` 반환(throw 안 함)
- **`summaryService.analyzeEmotion()` → `getCompanyIdFromToken()`** (`summary.service.ts:322-342`) → 여기서만 throw
  - 토큰 없음 → `LLM 호출을 위한 인증 토큰이 필요합니다.`
  - `getCurrentUser(token)` 실패(만료/401) → axios HTTP 에러(`status code 401`)
  - 응답에 `agent.company_id` 없음 → `사용자 tenant_id를 조회할 수 없습니다.`
- 참고: CE emotion 분석(`analyzeVocByCeApi`)은 실패해도 중립 fallback을 반환하므로 throw 안 함 → VOC 에러의 원인이 아님.

→ 즉 **VOC 에러 ≈ "토큰으로 사용자/테넌트를 못 뽑음" = 토큰 문제.**

---

## 2. 근본 원인 — 짧은 access + 재발급 불가(엔드포인트 부재)

### 토큰 실측 (payload 디코드)
JWT는 RS256 서명 + payload는 base64(암호화 아님) → **누구나 읽고, 아무도 못 고침(리드온리)**. `iat`(발급시각)는 미포함, `exp`만 있음 → TTL은 로그인(발급) 시각을 알아야 계산 가능.

**시연 때 만료된 토큰(agent41, sub 1232):**
- `exp` = 2026-07-01 **14:19:38 KST** (05:19:38 UTC)
- 사용 로그 = 2026-07-01 **14:21:06 KST** (05:21:06 UTC)
- → **만료 약 1분 28초 뒤에 사용됨** = 이미 만료된 토큰으로 호출.

**확정 실측 — 17:55 로그인의 access·refresh를 같은 로그인에서 둘 다 확보(가정 없음):**
| 토큰 | 만료(KST) | 로그인 17:55 기준 실제 TTL | `ad` |
|---|---|---|---|
| **accessToken** | 18:14:48 | **약 20분** (19분 48초) | 926721 |
| **refreshToken** | 18:59:48 | **약 1시간 5분** | 927534 |

- **access와 refresh 만료 간격 = 정확히 45분**, 두 번의 로그인 모두 동일(16:xx 로그인도 17:12:17 / 17:57:17 = 45분). → 우연이 아니라 **고정 발급 패턴**(access ≈ 20분, refresh ≈ access+45분 ≈ 65분).
- 앞선 잠정치 "access 약 17분"은 발급시각을 추정한 값이었으나, 로그인 시각(17:55)을 알고 재측정한 결과 **access ≈ 20분으로 사실상 일치**. (담당자 "1시간"이 실제와 다른 것으로 확정.)

### 결론
- **access 토큰이 매우 짧다(약 20분)** → 시연 준비/진행이 조금만 길어도 만료.
- 만료 후 갱신 불가(**/refresh 엔드포인트 부재** — 4장 참조) → 프론트가 만료된 access를 계속 재사용 → 그 시점부터 401 → VOC 스킵 / 요약 에러.
- 첫 발화만 찍힌 이유: 그때는 access가 아직 살아있었기 때문.
- **asst-service/어드바이저 코드 버그 아님.** 만료 토큰에 401 나는 건 정상 동작.

---

## 3. 현재 토큰 구조

- 프론트가 **accessToken / refreshToken 둘 다 `sessionStorage`** 에 보관.
- API 호출 시 프론트가 **직접** `x-auth-token` 헤더에 실어 보냄(쿠키 자동첨부 방식 아님).
- 시스템 전체가 **헤더 기반**(게이트웨이 → asst `AuthMiddleware` 헤더 추출 → proxy가 하위 서비스로 헤더 전달).
- 전체 아키텍처는 **BFF 구조이며, 그 BFF가 asst-service(어드바이저)** 다.
  - 단, 현재 asst는 토큰을 **발급/재발급하지 않고 검증·중계만** 하는 "패스스루 BFF" 상태. 토큰 관리를 프론트(sessionStorage)가 대신 하고 있어 BFF 이점을 못 살리는 중.

### refresh 토큰 저장 방식 비교
| | ① HttpOnly 쿠키 | ② sessionStorage(현재) |
|---|---|---|
| XSS 안전성 | 강함(JS가 못 읽음) | 약함(JS로 접근 가능) |
| 전달 | 쿠키 자동 첨부 | 프론트가 헤더에 직접 |
| CSRF | 방어 필요(SameSite+CSRF 토큰) | 자연 면역 |
| 마이크로서비스/게이트웨이 | 쿠키 스코프 까다로움 | 헤더라 단순 |
| BFF 적합성 | **정석(서버 주도 갱신)** | BFF 이점 미활용 |

### asst의 user-service 의존 (매 요청 토큰→테넌트 조회)
- **왜 있나**: 토큰(JWT) payload엔 `cId:60`(숫자 회사ID)·`cd:"POC4"`(회사코드)만 있고 **company UUID가 없음**. 그런데 하위 서비스(LLM 오케스트레이터·CE(VOC) 서버)는 `X-Tenant-Id`로 **company UUID**를 요구. → asst가 **매 요청마다 토큰 → user-service(`GET {USER_HOST}/api/user/get_user`) → `agent.company_id`(UUID)** 로 해석해야 함(`summary.service.ts:322` `getCompanyIdFromToken`). 즉 user-service는 **"토큰→테넌트UUID 번역기"** 역할.
- **VOC/외부 호출 경로 구분**: VOC 서버 호출 자체는 asst → CE 서버 **직통**(`summary.service.ts:793` axios.post, `CE_API_LLM_URL`+`/ai-apps/advisor-emotion/runs`). user-service를 **경유(relay)하지 않음.** 다만 호출 직전 테넌트 해석을 위해 user-service를 **1회 조회**하는 의존이 있음(경유 ≠ 조회).
- **왜 /summary·VOC 둘 다 401이 나나 (같은 뿌리)**:
  - `AuthMiddleware`는 토큰 **존재만 확인**하고 **만료/서명은 검증 안 함**(코드에 `🔍 토큰 검증 생략` 명시). 토큰이 있으면 통과시킴.
  - 그 뒤 `getCompanyIdFromToken → getCurrentUser`가 **만료 토큰으로 user-service를 호출** → **user-service가 401** → 그 401이 올라옴. (동적 DB 연결용 `get_configs?filters=db_config` 호출도 동일하게 만료 토큰에 401.)
  - 차이: **VOC**는 fire-and-forget이라 401을 삼키고 조용히 스킵(로그만) / **/summary**는 동기 응답이라 그 실패가 클라이언트에 에러로 노출.
  - → 근본 해결은 토큰 갱신(아래 4장)과 동일. 되면 VOC·/summary 같이 해결.
- **(별개) 최적화**: `token(or cId)→UUID`는 통화/세션 중 안 바뀌므로 캐싱 가능(실시간 VOC 경로엔 이미 `companyUuidByVendor` 캐시 존재). 근본적으로는 **JWT에 company UUID 포함**을 인증서버에 요청하면 user-service 조회 자체가 불필요. 단 이는 성능/결합도 개선이지 401의 근본해결은 아님(만료 토큰은 결국 다른 지점에서 걸림).

---

## 4. 해결 방향

### 단기 (당장 시연 사고 방지) — 변경 최소
현 sessionStorage 구조 유지 + **프론트가 access 만료 시 refreshToken으로 자동 갱신** 배선.
- 담당: **프론트 + 인증서버(재발급 API 제공)**. asst 코드 변경 없음.
- 핵심: 401 인터셉터 + single-flight(동시 401에도 refresh 1번만) + 실패 시 재로그인.
- **주의: `/assist-stream`(SSE) 경로**는 axios 인터셉터가 자동으로 못 잡음 → 여기도 만료 시 갱신 로직을 별도로 태워야 함(이번 VOC 끊김이 바로 이 경로).

프론트 인터셉터 예시(개념):
```ts
// single-flight: 동시 401이 와도 refresh는 1번만
let refreshing: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  const refreshToken = sessionStorage.getItem('refreshToken');
  if (!refreshToken) throw new Error('no refresh token');
  // ⚠️ URL/refresh 전달 위치/응답 필드/rotation 여부는 인증서버 규격 확인 후 채움
  const res = await axios.post(`${AUTH_HOST}/api/auth/reissue`, {}, {
    headers: { 'x-auth-token': refreshToken },
  });
  sessionStorage.setItem('accessToken', res.data.accessToken);
  if (res.data.refreshToken) sessionStorage.setItem('refreshToken', res.data.refreshToken);
  return res.data.accessToken;
}

api.interceptors.response.use((r) => r, async (error) => {
  const original = error.config;
  if (error.response?.status === 401 && !original._retried) {
    original._retried = true;               // 재시도 후 또 401이면 무한루프 차단
    try {
      refreshing = refreshing ?? refreshAccessToken();
      const newAccess = await refreshing;
      refreshing = null;
      original.headers['x-auth-token'] = newAccess;
      return api(original);                  // 새 토큰으로 원요청 재시도
    } catch (e) {
      refreshing = null;
      /* refresh도 만료 → 로그인 페이지로 */
      throw e;
    }
  }
  throw error;
});
```
(선택) 프로액티브: 요청/SSE 시작 직전에 `exp`가 임박(예: 60초 이내)이면 미리 갱신 → 401 왕복 제거.

### 중장기 (정석) — BFF가 HttpOnly 쿠키로 refresh 주도
asst-service(BFF)가 토큰 갱신을 맡는 구조. **처음 제안했던 "HttpOnly로 서버가 알아서 갱신"이 BFF 구조의 정석 정답.**
```
[프론트] ─HttpOnly 쿠키(refresh)→ [asst=BFF] ─→ [인증서버]
프론트는 토큰을 안 만짐 / asst가 만료 감지·재발급·쿠키 재설정
```
asst에 필요한 작업:
1. **재발급 프록시 엔드포인트**(예: `POST /auth/reissue`) — 쿠키의 refresh로 인증서버 호출 → 새 토큰 `Set-Cookie`.
2. **`AuthMiddleware` 수정** — 토큰을 헤더뿐 아니라 **쿠키에서도** 읽기(`cookie-parser`).
3. **경계 변환** — 프론트↔asst는 쿠키, **asst↔하위 서비스(USER/LLM/CE)는 여전히 헤더** → asst가 쿠키→헤더 변환해서 전달.
4. **CSRF 방어** — SameSite + CSRF 토큰.

주의(선결 확인):
- **게이트웨이가 쿠키를 포워딩하는지** 확인 필요(라우팅은 되지만 쿠키 전달은 별도).
- asst 인증 계층을 손대는 일이라 가볍지 않음 → CLAUDE.md 지침대로 **확정 후 진행**.

---

## 5. 담당자 회신 대조 — 정책 vs 실적용 갭 (확정)

인증서버 담당 회신(정책):
> - 로그인 시 2종 토큰 발급: **Access Token(1시간) + Refresh Token(14일)**
> - RS256 비대칭키 서명(개인키 서명 / 공개키 검증)
> - 중복 로그인 차단 장치 있으나 기본 꺼짐(허용)
> - **단, Refresh 토큰을 실제로 쓸 `/refresh` 재발급 엔드포인트가 없음 → 정책상 미완성**

이 정책을 **실제 발급 토큰 디코드로 대조**(17:55 로그인, 같은 로그인의 access·refresh 둘 다 확보 → 가정 없음):

| 항목 | 정책(문서) | **실측** | 판정 |
|---|---|---|---|
| access TTL | 1시간 | **약 20분** (17:55→18:14:48) | ❌ 3배 짧음 |
| refresh TTL | 14일 | **약 1시간 5분** (17:55→18:59:48) | ❌ 약 300배 짧음 |
| `/refresh` 엔드포인트 | (미완성) | **없음** | ❌ 재발급 불가 |

**결론: "정책은 있으나 서버 실제 설정/구현에 반영 안 됨."** 데이터 근거:
- access·refresh 만료 간격이 **두 로그인 모두 정확히 45분**(16:xx: 17:12:17/17:57:17, 17:55: 18:14:48/18:59:48) → 우연 아닌 고정 발급 패턴(access ≈ 20분, refresh ≈ 65분).
- 즉 **access ~20분 만료 + 재발급 엔드포인트 부재 + refresh도 ~1시간** → 로그인 20분 후 복구 불가로 세션 사망. 시연 중 VOC/요약이 401로 끊긴 근본원인이 이걸로 **확정**.
- (참고) 앞서 잠정치로 낸 "access 17분"은 발급시각 추정치였고, 로그인 시각을 알고 재측정하니 **약 20분으로 사실상 일치**. "1시간"은 실제와 다름.

---

## 6. 담당자 전달 요약

> **refresh token 구조** — ECS portal에 이미 구축돼 있음(sessionStorage에 access·refresh 둘 다 보유).
> 다만 **17:55 로그인 토큰 실측 기준 access 약 20분 / refresh 약 1시간**으로, 정책(access 1시간 / refresh 14일)과 크게 다릅니다. **서버 TTL 실설정 확인** 필요(현 20분은 시연/상담에 너무 짧음).
> 또한 **`/refresh` 재발급 엔드포인트가 없어** refresh 토큰이 있어도 갱신 불가 → 로그인 20분 후 세션이 복구 불가로 만료(시연 중 VOC/요약 401 원인).
> 필요: ①access/refresh TTL 실설정을 정책대로 반영 ②`/refresh` 엔드포인트 구현 ③(그 후) 프론트 자동 갱신 배선.
> 중장기로는 BFF(asst)에서 **refreshToken을 HttpOnly 쿠키로 옮겨 서버 주도 갱신**이 보안상 안정적(단 현 시스템 헤더 기반이라 게이트웨이·서비스 전반 검토 필요).

---

## 7. 다음 액션 / 미결정

인증서버(별도 서버) 담당에게 **선결 확인/요청**:
1. **`/refresh` 재발급 엔드포인트 구현** — 현재 부재(담당자 확인). refresh 토큰을 실제로 쓰려면 필수. **1순위.**
   - 구현 시 스펙 필요: 엔드포인트 URL / refreshToken 전달 방식(바디 vs 헤더) / 응답 필드명(새 access·refresh) / rotation 여부.
2. **TTL 실설정 확인·정정** — 정책(access 1시간 / refresh 14일)이 실제 발급(약 20분 / 약 1시간)에 반영 안 됨. 서버 설정을 정책대로 맞출지 결정.

그 외 결정할 것:
- **게이트웨이 쿠키 포워딩** 여부(HttpOnly 전환 전제).
- **전환 범위** — 단기(프론트 자동 갱신)만 먼저 vs 바로 HttpOnly BFF까지.

### 역할 분담
| 항목 | 담당 |
|---|---|
| 재발급 API 제공, TTL 설정 | 인증서버 담당(별도 서버) |
| (단기) 프론트 401 자동 갱신 + SSE 경로 갱신 | 프론트 |
| (중장기) asst(BFF) HttpOnly 쿠키 재발급 프록시 | asst / 어드바이저 |
| 쿠키 포워딩 | 게이트웨이 담당 |
