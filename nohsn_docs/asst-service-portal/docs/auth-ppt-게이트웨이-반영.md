# auth_architecture_0721_확정.pptx — API Gateway 반영 수정안

> 2026-07-21 asst-service 게이트웨이 인바운드 전환 작업 결과를 PPT에 반영하기 위한 문서.
> 대상: **8p「앱 서비스 공통 (백엔드)」**, **9p「부록 E — 어드바이저 구체 작업 체크리스트」의 백엔드 파트**
>
> 관련: `api-gateway-integration-guide.md`(적용 가이드), `auth-ppt-수정사항.md`(0720 보완), `CLAUDE.todo.md`(작업 이력)

---

## 0. 왜 고쳐야 하나 — 전제가 바뀌었다

| | 원안 (0721 확정본) | 현재 (게이트웨이 도입) |
|---|---|---|
| 부제 | "게이트웨이 없음 기준 (직접 접속)" | **API Gateway 경유** (`:32099/aicc/<서비스라벨>/**`) |
| 토큰 검증 | **각 앱 백엔드가 JWKS로 자체 검증** | **게이트웨이가 단일 검증** |
| 쿠키 관리 | 각 앱 백엔드가 Set-Cookie | 게이트웨이가 관리 |
| 갱신(silent refresh) | 각 앱 백엔드가 single-flight | 게이트웨이가 선제 갱신 |
| CSRF | 각 앱 백엔드 | 게이트웨이 공통 정책 |
| CORS | 각 앱 백엔드 | **게이트웨이 단일 처리 (백엔드는 꺼야 함)** |

> 7p 아키텍처 도식에 이미 `API Gateway — 선제갱신 · 라우팅 · 검증 · 쿠키관리 · 공통정책` 이라고 명시돼 있다.
> **8·9p만 게이트웨이 이전 전제로 남아 있어 도식과 모순된다.**

**핵심 메시지 (발표용 한 줄):**
> 앱 백엔드가 인증을 **구현**하는 게 아니라, 게이트웨이가 넣어준 것을 **신뢰하고 받는다**. 백엔드 작업량은 오히려 줄었다.

---

## 1. 8페이지 「앱 서비스 공통 (백엔드)」 교체안

### 현재 문구 (삭제 대상)

```
▸ 쿠키(httpOnly·Secure·SameSite) 세팅 + CSRF 방어
▸ JWKS 로컬 검증 도입 (시작 시 취득·캐시, kid 매칭)
▸ 갱신 single-flight (내부 동시 요청 → Promise 1개 공유)
▸ 검증 실패(만료·위조) → 401 일관 반환
```

→ **4개 항목 전부 게이트웨이 책임으로 이관.** 백엔드 슬라이드에서 뺀다.

### 교체 문구 (6개 — asst-service 실작업 기준)

**슬라이드에 넣을 문구 (쉬운 말 버전)**

```
앱 서비스 공통 (백엔드)   ※ 게이트웨이를 거쳐 들어오는 구조

▸ 우리 서비스 주소가 그대로 도착하는지 확인한다
   게이트웨이가 앞부분만 바꿔서 넘겨주므로 대부분 고칠 게 없다 (어드바이저: 수정 0건)

▸ 실시간 통신(socket.io)도 같은 규칙으로 오는지 확인한다

▸ 백엔드의 CORS 설정은 끈다
   게이트웨이가 대신 해준다. 양쪽 다 켜면 브라우저가 요청을 막는다

▸ 로그인 확인은 게이트웨이가 한다
   백엔드는 게이트웨이가 넣어준 사용자 정보를 받아 쓰기만 하면 된다

▸ 다른 서비스를 부르는 주소를 점검한다   ← 유일하게 조심할 곳
   주소를 코드에 직접 적어두면 주소가 겹쳐서 호출이 깨진다

▸ 기존 직접 접속 포트는 지우지 않고 남겨둔다
   문제가 생겼을 때 게이트웨이 탓인지 우리 탓인지 가려내려면 필요하다
```

> **발표 시 강조 포인트:** 앞의 4개는 "확인만 하면 끝나는 일"이고,
> 실제 위험은 **5번(다른 서비스 호출 주소)** 하나다. 어드바이저도 여기서 걸려 이 부분은 보류했다.

**발표자 노트 (질문 나오면 쓸 정확한 용어)**

| 슬라이드 문구 | 정확한 표현 |
|---|---|
| 주소가 그대로 도착 | 게이트웨이가 `/aicc/asst-service` 라벨을 떼고 컨텍스트 경로 `/api/asst/v1` 을 재부여 → `setGlobalPrefix` 와 일치 |
| 실시간 통신 규칙 | socket.io `path` 정합 + WebSocket Upgrade 통과 (`/aicc/asst-service/socket.io` → `/api/asst/v1/socket.io`) |
| 양쪽 다 켜면 막힘 | `Access-Control-Allow-Origin` 헤더 중복 → 브라우저가 차단 |
| 사용자 정보를 받아 쓴다 | 게이트웨이가 주입한 `x-auth-token` 헤더 (쿠키·JWKS 검증·갱신·CSRF는 게이트웨이 담당) |
| 주소가 겹친다 | 컨텍스트 경로 하드코딩 시 이중 prefix (`/api/user/api/user/...`)<br>권장: base URL(env) + 상대 path / 금지: `${HOST}/api/user/...` |
| 직접 접속 포트 | 직결 포트(32025) 유지 — 게이트웨이 우회·헬스체크용 |

---

## 2. 9페이지 「부록 E — 어드바이저 구체 작업 체크리스트」 백엔드 파트 교체안

### 2-1. 부제 변경 (필수)

```
현재: asst-service (백엔드) + asst-web (프론트) · 게이트웨이 없음 기준 (직접 접속)
변경: asst-service (백엔드) + asst-web (프론트) · API Gateway 경유 기준
      (게이트웨이 :32099 /aicc/asst-service/** — 2026-07-21 인바운드 전환 완료)
```

### 2-2. 기존 8개 항목의 처리 (이 표를 슬라이드 노트나 별도 장으로 두면 "왜 사라졌나" 질문을 방어할 수 있다)

| 원안 항목 | 처리 | 사유 |
|---|---|---|
| httpOnly·Secure·SameSite 쿠키 세팅 | **삭제** | 게이트웨이가 쿠키 관리 |
| 쿠키 직접형 채택(세션스토어형 비채택) | **이동** | 백엔드 작업이 아니라 게이트웨이/인증 정책 항목 |
| 쿠키 → X-auth-token 헤더 부착 | **삭제** | 게이트웨이가 주입. 백엔드는 **이미 수신 중**(현행 유지) |
| Silent refresh + single-flight | **삭제** | 게이트웨이 선제 갱신 |
| JWKS 로컬 검증 적용 + USER_HOST 위임 제거 | **축소** | 검증은 게이트웨이. **`USER_HOST` 왕복 제거만 백엔드 몫으로 잔존** |
| CSRF 방어 (SameSite + CSRF 토큰) | **삭제** | 게이트웨이 공통 정책 |
| SSE 시작 직전 선제 갱신 | **주체 변경** | 갱신은 게이트웨이. 백엔드는 **스트리밍 버퍼링·타임아웃** 대응만 |
| DynamicDatabaseService 정리 | **유지** | 게이트웨이와 무관. 단일 테넌트 확정에 따른 별건 |

### 2-3. 교체 문구 (백엔드 파트)

```
백엔드 — 게이트웨이 연동 (2026-07-21 완료)

[v] 게이트웨이 경로 규칙 확인 — /aicc/asst-service 라벨 제거 후 /api/asst/v1 재부여
    → main.ts setGlobalPrefix 와 일치, 애플리케이션 코드 수정 불필요

[v] socket.io path 정합 확인 — socket.gateway.ts path=/api/asst/v1/socket.io 그대로 사용

[v] 백엔드 CORS 비활성화 — CORS_ALLOWED_ORIGINS 주석 처리 (게이트웨이 단일 처리)
    → 직결(32025) 브라우저 접근이 다시 필요하면 주석 해제로 복귀

[v] 직결 포트 32025 유지 — 게이트웨이 우회 및 헬스체크용

[ ] 아웃바운드 게이트웨이 전환 — 보류 (담당 부서 회신 대기)
    ${USER_HOST}/api/user/... 등 컨텍스트 경로 하드코딩 15곳, prefix 3종류
    → 재부여 방식이면 이중 prefix 발생. passthrough 확인 시 env 1줄로 전환 가능

[ ] USER_HOST 토큰 위임 검증 제거 — 검증 주체가 게이트웨이로 이동
    (현재 user-info.service 가 매 요청 get_user 왕복 / 단일 테넌트 확정으로 불필요)

[ ] SSE(/assist-stream) 게이트웨이 통과 검증 — 버퍼링 off, 유휴 타임아웃 조정 요청

[ ] DynamicDatabaseService 정리 — 단일 테넌트 확정으로 정적 DB 연결 전환
    (106 개발기는 DB_DIRECT_CON=1 로 이미 우회 중)
```

> 프론트(asst-web) 파트도 같은 전제로 "직접 접속 → 게이트웨이 진입점" 변경이 필요하다.
> (호출 base URL 을 `:32099/aicc/asst-service`, socket.io `path=/aicc/asst-service/socket.io` 로 교체)

---

## 3. 근거 (질문 대비)

| 주장 | 근거 위치 |
|---|---|
| 게이트웨이가 컨텍스트 경로 재부여 | 담당 부서 회신 2026-07-21 / `CLAUDE.todo.md` |
| 코드 수정 불필요 | `src/main.ts:98-99`, `src/common/gateways/socket.gateway.ts:32-35` |
| CORS 중복 차단 | `src/main.ts:65-76` (`corsEnabled` 분기), `docker-compose.dev.106.yml:21-24` |
| 백엔드가 토큰을 검증하지 않음 | `src/common/middleware/auth.middleware.ts:135-136` — 추출만 하고 검증 생략 |
| 토큰 검증을 USER_HOST에 위임 중 | `src/common/services/user-info.service.ts:113` `get_user` 왕복 |
| 아웃바운드 이중 prefix 위험 | `src/common/proxy/user-proxy.controller.ts`(13곳), `:48`(organization), `src/common/services/tenant-config.service.ts:16`(configs) |
| 권장 패턴(base+path)은 이미 전환됨 | `CE_API_LLM_URL`, `LLM_ORCHESTRATOR_HOST` = `ecpad.etaas.co.kr/aicc/**` |
