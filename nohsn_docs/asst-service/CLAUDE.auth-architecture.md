# 포털 인증(SSO/토큰) 아키텍처 — 현황 분석 및 개선 제안

> 목적: 멀티서비스 포털의 인증 체계를 **① 현재 구조 파악 → ② 문제점 → ③ 개선 제안** 순으로 정리한 분석 문서(최종 PPT의 원본).
> 근거: `http://106.242.165.142:32000`(Timbel AICC Portal) 을 브라우저로 직접 관찰(네트워크·스토리지·프론트 번들 실측). 실측 원본은 **부록 A**.
> 작성 기준: 2026-07-16 / 관찰 회사코드 POC4(단일), 계정 2종(SYSTEM·ADMIN, 둘 다 관리자급).

---

## 1. 현재 인증 구조 (실측 기반)

포털은 **여러 서비스를 조립하는 모듈형**(Module Federation 마이크로프론트엔드)이고, 납품 시 일부 서비스가 빠질 수 있다. 로그인은 서비스별이 아니라 **포털 단일 진입**으로 묶여 있다. 소비 주체가 섞여 있어서(어드바이저처럼 **BFF(NestJS)** 경유 + **프론트가 API 직접 호출**) 인증 경로가 하나가 아니다.

### 1.1 전체 인증 흐름
```
[로그인]  POST /auth/login {companyCode, account, passwd}
            → {accessToken, refreshToken, tokenType:"Bearer", passwordChangeRequired}   // 토큰만 내려옴

[로그인 직후 프론트가 자동 조회]
   GET /api/portal/v1/my-authority/tree-menus   → role별 메뉴 트리(인가)
   GET /api/user/get_user                        → 소속·권한·workspace(신원 상세)
   GET /api/portal/v1/menus, .../federation-apps → 마이크로프론트엔드 조립 정보

[이후 API 호출]  헤더 X-auth-token: <accessToken>
   - BFF(asst-service) 경유 요청 → BFF가 USER_HOST에 토큰 검증 위임(1.4)
   - 프론트 직접 호출 → 각 axios 인스턴스가 토큰 부착
```
핵심: **로그인 응답은 토큰만** 준다. role/메뉴/소속/workspace는 **로그인과 분리된 후속 조회**로 채운다.

### 1.2 토큰 구조·수명
- **JWT / RS256**, 헤더 `kid:"timbel-on-premise-v1"` (인증서버가 개인키로 서명, 서비스는 공개키로 검증하는 구조).
- payload: `{ sub, acc(계정), cId(회사id), cd(회사코드), ad(발급시퀀스), role, aName(표시명), tv(토큰버전), typ:"access"|"refresh", iat, exp, at }`
- **access 수명 60분 / refresh 수명 14일** (실측). refresh는 access와 동일 payload에 `typ:"refresh"`.
- **role은 토큰에 있으나, 소속/권한/workspace 등 세부·민감정보는 토큰에 없음** → 클레임 설계 자체는 현재 양호(2.6).

### 1.3 저장 방식 (프론트)
- **sessionStorage**: `accessToken`, `refreshToken`
- **localStorage**: `aicc-token`(=access 동일값), `aicc-refresh-token`(=refresh), `ecp-auth`(사용자정보 통째), `aicc-menu`, `ecp-conf` …
- 즉 **토큰이 session + local 양쪽에 이중 저장**된다.

### 1.4 검증 방식 (BFF 위임형)
- BFF(asst-service)는 토큰을 **자체 검증하지 않고** 매 요청 `USER_HOST`로 위임한다. (그 응답으로 테넌트 DB 접속정보 `get_configs?filters=db_config`도 함께 조회 → 멀티테넌트 라우팅)
- 즉 인증 판정(401)·갱신은 **인증서버 영역**에서 일어나고, BFF 로그에는 refresh 흔적이 남지 않는다.

### 1.5 갱신(refresh) 방식 — 프론트 번들 실측
- 엔드포인트 `POST /auth/refresh {refreshToken}` (일부 청크는 `/api/auth/refresh` — 경로가 갈림).
- 방식: **순수 401-reactive(=lazy)**. 응답 인터셉터에서 **401을 받은 뒤에야** refresh 시도.
```js
interceptors.response.use(r=>r.data, async e=>{
  if (status===401 && !config._retried) {
    config._retried = true;                 // 재시도 딱 1회
    const tok = await refresh();            // singleflight (진행중 promise 재사용)
    if (tok) { config.headers['X-auth-token']=tok; return retry(config); }
    logout(); redirect('/login');           // refresh도 실패 → 강제 로그아웃
  }
  return Promise.reject(e);
});
```
- 갱신 성공 시 새 토큰을 **local + session 양쪽에** 다시 저장.
- **만료 임박 선제 갱신(exp 기반 타이머/잔여시간 체크)은 코드에 전혀 없음.**
- 이 인터셉터·refresh 로직이 **마이크로프론트엔드 청크마다 개별 복붙**되어 있음.

### 1.6 인가(메뉴·권한)
- 메뉴는 토큰이 아니라 **서버 조회**(`/my-authority/tree-menus`)로 role별 트리를 받는다. 각 노드가 `routeType:FEDERATION / component / remoteName` 을 담아 **마이크로프론트엔드를 동적 조립**한다.
- 권한 세부는 `get_user.agent.permissions{advisor,ta,ce,aicm,qa}` + `workspace_ids` 로 구성. **토큰=신원(who), 서버조회=인가 세부(what)** 로 역할이 나뉜다.

---

## 2. 구조의 문제점

### 2.1 lazy refresh — 선제 갱신 부재 (최우선)
갱신이 **401을 맞아야만** 작동한다(1.5). 유효기간 중 미리 갱신하는 로직이 없어서:
- **장시간 작업 중 토큰이 만료되면 진행 중이던 요청이 401로 튕긴다.** 인터셉터가 1회 재시도로 구제하지만,
- **SSE/스트리밍 등 응답 인터셉터를 타지 않는 경로는 이 구제 밖** → 만료된 토큰으로 요청이 계속되어 조용히 실패할 수 있다.

### 2.2 토큰 이중 저장 · localStorage 영속 (XSS 노출면)
- 토큰이 **sessionStorage + localStorage 양쪽**에 저장(1.3). localStorage는 탭 종료·브라우저 재시작에도 **영속** → **XSS 발생 시 access·refresh를 동시에·지속적으로 탈취**당할 표면이 크다.
- 게다가 refresh 14일 수명이라 탈취 시 장기간 악용 가능.

### 2.3 초기 비밀번호 평문 노출
- `ecp-conf.companyConf.defaultPassword` 가 **localStorage에 평문**으로 저장됨. 초기/기본 비번이라도 클라이언트에 내려주는 것은 지적사항.

### 2.4 매 요청 USER_HOST 검증 위임 (성능·의존성)
- BFF가 요청마다 인증서버로 검증을 왕복(1.4). **인증서버가 단일 장애점**이 되고, 서비스가 흩어진 포털에서 **왕복 지연·부하**가 누적된다. (RS256인데도 로컬 검증 이점을 못 살림 — 2.6 참조)

### 2.5 refresh/인터셉터 표준 부재
- 갱신 로직이 **마이크로프론트엔드마다 중복 구현**되고 경로도 `/auth/refresh` vs `/api/auth/refresh` 로 **제각각**(1.5). BFF 경유와 프론트 직접호출이 섞인 **혼합 소비** 환경에서 일관된 갱신·재시도·만료대응을 보장하기 어렵다.

### 2.6 (참고) JWT payload가 보이는 건 문제 아님
- "토큰이 그냥 디코드된다"는 취약점이 아니다. JWT payload는 base64url 인코딩(암호화 아님)이라 **누구나 보는 게 설계상 정상**이고, RS256 개인키의 목적은 **은닉이 아니라 위조 방지(서명)**다.
- 함의는 **"토큰에 민감정보를 담지 말 것"** — 현재는 role 정도만 담고 소속/개인정보는 조회로 유지하므로 **이 부분은 양호**. (개선안 3.4에서 원칙만 고정)

---

## 3. 개선 제안

> **준거**: 특정 사례가 아니라 **현행 OAuth 보안 표준**에 정렬한다.
> - **RFC 9700** *Best Current Practice for OAuth 2.0 Security* (IETF, 2025-01) — 모든 플로우 **PKCE 필수**, **refresh token rotation + 재사용 감지**를 표준(옵션 아님)으로, **sender-constrained token(DPoP)** 권고.
> - **IETF *OAuth 2.0 for Browser-Based Apps* BCP** — 보안 순위 **BFF > Token-Mediating Backend > 브라우저 OAuth 클라이언트**. BFF는 토큰을 서버사이드 보관하고 브라우저엔 httpOnly 세션쿠키만 준다.
> 핵심 방향 = **토큰을 브라우저에서 치우고(BFF) · refresh는 회전+재사용감지 · access는 짧게+silent refresh · 검증은 로컬(JWKS) · 플로우는 Code+PKCE**.

### 3.0 전제 — 인증 세션(로그인 유지) 정책 (개선안 도입 전 결정 사항)

개선안(특히 쿠키·refresh 관련)은 아래 **"로그인 유지 정책"을 파라미터로** 구현된다. 즉 **먼저 이 정책값을 정한 뒤 그에 맞춰** 쿠키·토큰 수명을 설정한다. 특히 **쿠키 종류(세션/지속)는 코드 구조 변경이 아니라 설정값**이므로, 정책이 바뀌면 전환만 하면 된다.

| 정책 항목 | 정하는 것 | 예시 | 비고 |
|---|---|---|---|
| **쿠키 종류** | 브라우저를 닫으면? | 세션(닫으면 폐기) / 지속(유지) | 설정값 — 전환 용이 |
| **refresh 수명** | 재로그인 없이 유지되는 최대 기간 | 예: 1~3일 | 로그인 유지의 실질 상한 |
| **access 수명** | 토큰 재발급 주기 | 예: 5~15분 | silent refresh로 사용자 체감 없음 |
| **유휴(idle) 타임아웃** | 무조작 방치 시 만료 | 예: 30분 | 공용 PC 보안 |
| **절대 만료** | 로그인 후 무조건 재로그인 | 예: 8~12시간 | 선택 |
| **role/근무형태별 차등** | 상담사·관리자·공용/전용 PC 구분 | 상담석=세션+짧은 유휴 / 개인=지속 | 선택 |

- **공용 상담석(자리 공유)**: 세션 쿠키 + 유휴 타임아웃 권장 → 자리를 비우거나 브라우저를 닫으면 다음 사용자가 세션을 이어받지 못한다.
- **개인 전용 PC**: 지속 쿠키로 재접속 시 로그인 유지(편의) → "상담사가 다시 접속하면 바로 이어보게" 요구 시 이 값으로 전환한다.
- 위 값들은 **보안팀·현업과 합의해 확정**하며, 확정 전에는 개선안 구현 시 기본값으로 두고 이후 정책에 따라 조정한다. → 이 정책이 §3.1(쿠키 저장)·§3.2(refresh 수명·회전)·§3.3(access 수명)의 구현 파라미터가 된다.

### 3.0.1 목표 요청 플로우 (제안 한 장 요약)

> **역할 분리**: 토큰 **발급·갱신 = 포털 인증서비스(개인키 보유)만**, 토큰 **검증 = 각 서비스 백엔드가 공개키(JWKS)로 로컬 처리**(인증서비스 왕복 없음).
> *비유*: 중앙정부(인증서비스)가 위조 못 할 도장(개인키)으로 신분증 발급 → 각 시도(각 서비스)가 공개된 도장 원본(공개키)으로 자체 검증해 출입(API) 허용.

**[현재 as-is]** — 검증하러 매 요청 인증서비스로, 프론트는 서비스에 다이렉트
```
로그인:  브라우저 → 인증서비스(/auth/login) → 토큰 → sessionStorage+localStorage 저장
API:    브라우저 --토큰(헤더)--> 어드바이저 BFF --?토큰 유효?--> 인증서비스(USER_HOST)   ← 매 요청 왕복
        브라우저 --토큰(헤더)--> 파일API(다이렉트) --?토큰 유효?--> 인증서비스
```

**[개선 to-be / a안]** — 브라우저는 쿠키만, 검증은 로컬, 호출은 게이트웨이/BFF 경유
```
로그인·갱신:  브라우저 <--httpOnly 쿠키--> BFF <--Code+PKCE--> 인증서비스   (발급·갱신만 등장)

API 호출:  브라우저 --쿠키--> 게이트웨이/BFF --토큰(헤더)--> 내부서비스(어드바이저 API·파일 API…)
                              └ 여기서 공개키(JWKS)로 자체 검증 → 인증서비스 안 감
```
- 브라우저엔 **httpOnly 쿠키만**(토큰 JS 노출 0). 게이트웨이/BFF가 쿠키→토큰 변환+검증 후 내부로 전달.
- **직접호출(파일 API 등)도 게이트웨이/BFF 뒤로** 두어 쿠키로 인증(a안). 내부망·서비스명 접근이라 자연스럽게 가능.

> **적용 범위 주의**: 현재 소스는 프론트→서비스 **다이렉트**라 a안 미적용 상태. 본 문서는 **제안**이며, 우선 **어드바이저 대상**으로 그리고 타 서비스(파일 API 등) 담당자 협의·이의 반영 후 **최종 확정 시 적용**한다.

### 3.1 토큰을 브라우저에서 제거 — BFF 패턴 (2.2·2.3 대응)
- Browser-Based Apps BCP의 **보안 최상위 패턴**. BFF가 confidential OAuth client로서 **access/refresh를 서버사이드 보관**하고, 브라우저엔 **httpOnly·Secure·SameSite 세션쿠키만** 발급 → 토큰이 JS에 노출되지 않아 **XSS로도 탈취 불가**.
- 현 2.2(session+local 이중저장·영속)·2.3(민감값 클라 노출)을 정면 해결. 어드바이저가 이미 BFF(NestJS)를 쓰므로 확장 여지가 크다.

### 3.2 Refresh token rotation + 재사용 감지 (장수명 refresh 대응)
- RFC 9700 표준: **갱신 때마다 refresh를 새로 발급(rotation)**, 폐기된 옛 refresh가 다시 나타나면 **탈취로 간주 → 세션 전체 무효화 + 재인증**(reuse detection). 정상 재시도 흡수를 위한 짧은 **grace 윈도우** 병행.
- 현 refresh **14일 장수명**은 탈취 시 장기 악용 위험 → **수명 단축 + 회전 + 재사용감지**로 전환.

### 3.3 Short-lived access + silent refresh (2.1 대응)
- **access 수명 단축**(현 60분 → 수 분 수준) + **백그라운드 silent refresh**로 UX 유지. 잔여 수명이 임계값 이하면 선제 갱신, **현행 401 재시도는 최후 폴백**으로만.
- **인터셉터를 타지 않는 경로(SSE/스트리밍)도 갱신 대상에 포함**(§1.5 실측 근거). 짧은 access는 3.5 로컬검증의 "즉시 폐기 어려움" 약점도 함께 보완한다.

#### 3.3.1 실시간 세션 서비스 보호 (지속 세션이 필요한 서비스 공통)
실시간 상담 등 **세션이 오래 지속돼야 하는 서비스**는 인증 때문에 작업이 중단되면 안 되므로 아래를 함께 적용한다.
- **평시 무중단**: silent refresh(위)로 access 만료를 자동 처리 → 세션 유지 중 인증 끊김 없음.
- **절대 만료 회피 설계**: 절대상한(§3.0)은 근무시간보다 **길게** 잡고, 임박 시 **사전 경고**로 유휴 시점에 재인증을 유도하며, 실시간 서비스는 **role/근무형태별 정책 차등**(§3.0)을 적용한다. 활동(진행 중 세션)은 유휴 타임아웃 리셋 신호로 처리한다.
- **만료 시에도 코어 보존**: 인증이 만료돼도 **실시간 코어 기능은 인증과 분리**해 유지하고, 부가 API는 **자동 갱신+재시도(필요 시 큐잉)**로 데이터 유실을 막는다. → 인증 만료가 "기능 중단"이 아니라 "재인증"으로만 이어지게 설계.

### 3.4 표준 플로우: Authorization Code + PKCE (RFC 9700)
- 현재는 자격증명을 직접 POST하는 자체 `/auth/login`. → **OIDC/OAuth Authorization Code flow + PKCE**(RFC 9700이 모든 플로우에 PKCE 필수)로 표준화. 기존 MFA(부록 A.7)·SSO를 표준 프로토콜 위에서 일관되게 태운다.

### 3.5 검증: JWKS 로컬 검증 (2.4 대응)
- 매 요청 `USER_HOST` 위임 → **공개키(JWKS)로 각 서비스/BFF가 로컬 검증**(RS256 본래 이점). 인증서버 왕복·단일 장애점·지연 감소. 로컬검증의 즉시폐기 약점은 **짧은 access(3.3) + BFF 서버사이드 세션(3.1)** 으로 보완.

### 3.6 클레임 최소화 + 공통 인증 클라이언트 (2.5·2.6 대응)
- 토큰엔 **신원·role 등 최소 클레임만**, 민감·가변 정보는 조회 유지(현 상태 양호 → 원칙으로 고정).
- BFF·프론트 직접호출 양 경로를 **공통 인증 모듈**로 표준화(갱신·재시도·경로 통일) → 마이크로프론트엔드마다 복붙하던 구조(2.5) 제거.

### 3.7 (선택) Sender-constrained token: DPoP (고보안 옵션)
- RFC 9700의 **DPoP/mTLS로 토큰을 클라이언트에 바인딩** → 토큰이 탈취돼도 다른 클라이언트가 못 씀. 온프레미스·구현비용을 감안해 **고보안 요건이 있을 때 선택 적용**.

### 3.8 실제 적용 로드맵
표준을 한 번에 다 넣지 말고 **효과·비용 순으로 단계 도입**(온프레미스·조립형·하위호환 감안).

| 단계 | 항목 | 해결 문제 | 표준 근거 | 특징 |
|---|---|---|---|---|
| **Phase 1** | 3.3 short access+silent refresh · 3.6 공통 클라이언트 · 2.3 평문 제거 | 2.1·2.5·2.3 | — | 프론트 위주·무중단·회귀 최소 |
| **Phase 2** | 3.1 BFF 서버사이드+httpOnly · 3.2 refresh 회전+재사용감지 | 2.2·장수명 refresh | Browser-Apps BCP · RFC 9700 | 쿠키·CSRF·CORS 동반 |
| **Phase 3** | 3.4 Code+PKCE(OIDC) · 3.5 JWKS 로컬검증 | 2.4·플로우 표준화 | RFC 9700 | 인증서버·게이트웨이 협업 |
| **선택** | 3.7 DPoP | bearer 탈취 | RFC 9700 | 고보안 요건 시 |

**현실 제약(반드시 감안)**
- **온프레미스·단일회사** → 외부 IdP를 새로 세우기보다 **현 `/auth/*`를 표준(Code+PKCE·rotation·JWKS)으로 강화**하는 게 현실적. 키 배포도 폐쇄망 내에서.
- **서비스 조립형** → 인증은 개별 서비스가 아니라 **BFF/공통 클라이언트 계층**에 둔다(3.1·3.6이 충족).
- **혼합 소비(BFF+직접호출)** → BFF 쿠키화 시 **직접호출 경로의 CORS/withCredentials**를 반드시 함께 조정.
- **하위호환** → 쿠키 우선 + 헤더 폴백 병행으로 단계 전환(빅뱅 교체 회피).

---

## 부록 A. 실측 원본 (근거 데이터)

**A.1 계정·role**
| 계정 | role | agent_id | 랜딩 |
|---|---|---|---|
| `system` | SYSTEM | ecp-1 | `/admin/menu` |
| `timbel_super4` | ADMIN | ecp-3 | `/admin/menu` |

두 계정 모두 `permissions{advisor,ta,ce,aicm,qa}` 전부 `null`, `workspace_ids: []`(관리자라 워크스페이스 배정 없음). → **상담사(ADVISOR/AGENT) role 화면은 계정 미확보로 미확인**.

**A.2 로그인 요청/응답**
```
POST /auth/login
 req: {companyCode:"POC4", account, passwd}   // companyCode는 폼에 없고 클라가 자동 주입(단일회사)
 res: {success:true, data:{accessToken, refreshToken, tokenType:"Bearer", passwordChangeRequired:false}}
```

**A.3 accessToken payload**
```json
{ "sub":"<uuid>", "acc":"system", "cId":1, "cd":"POC4", "ad":"17841690101",
  "role":"SYSTEM", "aName":"System Administrator", "tv":2,
  "typ":"access", "iat":1784169010, "exp":1784172610, "at":1784169010 }
```
access `exp-iat=3600s(60분)`, refresh `1209600s(14일)`.

**A.4 get_user 응답**
```
GET /api/user/get_user
 → { company:{id,company_id:"POC4",vendor_tenant_id,name},
     agent:{ id, role, agent_id, name,
             permissions:{advisor,ta,ce,aicm,qa}, workspace_ids:[], assigned_workspace_id,
             organization_names:{company,tenant,center,team,part} } }
```

**A.5 refresh (프론트 번들 `8512/7105/5905/648/168.chunk.js`)** — 1.5의 인터셉터 코드가 원문. 엔드포인트 `POST /auth/refresh` (일부 `/api/auth/refresh`), 갱신 토큰 local+session 양쪽 저장, 선제갱신 로직 없음.

**A.6 스토리지 키** — session: `accessToken`,`refreshToken` / local: `aicc-token`,`aicc-refresh-token`,`ecp-auth`,`aicc-menu`,`ecp-conf`(내 `defaultPassword` 평문),`ecp-global`,`ecp-last-account` 등.

**A.7 부수** — 로그인 플로우에 **MFA 분기 존재**(`POST /auth/mfa/verify`, `/auth/companies/{c}/accounts/{a}/authentication-method`; 현 계정 미적용). `passwordChangeRequired`로 비번 강제변경 유도.

## 부록 B. 관찰 환경 (되돌리기용)
- CDP 크롬: `--remote-debugging-port=9222 --user-data-dir=~/chrome-cdp-profile` (이 창 끄면 세션 끊김).
- `.mcp.json`(playwright → CDP 9222) 등록. 정리 시 9222 크롬 종료 + 불필요 시 `.mcp.json`·`~/chrome-cdp-profile` 제거.
- 남은 확인거리: 상담사 role 계정으로 role별 메뉴/권한 차이 실측 / SSO가 별도 IdP인지(개인키 보관 주체) — `/auth/login`은 포털 자체 경로로 관찰됨.
