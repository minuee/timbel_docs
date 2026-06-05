# BFF (Backend-For-Frontend) 전환 계획서

> 작성일: 2026-04-16
> 상태: 검토 대기

---

## 1. 목표

프론트엔드(`asst-web`)에서 외부 서비스로 직접 호출하는 REST API를 백엔드(`asst-service`)를 경유하도록 전환한다.
이를 통해 토큰 관리 일원화, 보안 강화, API 응답 가공의 유연성을 확보한다.

---

## 2. 현황 분석

### 2.1 프론트엔드 직접 호출 서비스 (8개 axios 인스턴스)

| 인스턴스 | 대상 서비스 | 환경변수 | 용도 |
|----------|------------|----------|------|
| `advisor` | Advisor 백엔드 | `VITE_API_ADVISOR_*` | 자체 백엔드 (전환 불필요) |
| `knowledge` | Knowledge 서비스 | `VITE_API_KNOWLEDGE_*` | 지식베이스 검색/관리 |
| `auth` | Auth 서비스 | `VITE_API_AUTH_*` | 인증/토큰 발급 |
| `user` | User 서비스 | `VITE_API_USER_*` | 사용자 정보 |
| `ce` | CE 서비스 | `VITE_API_CE_*` | 대화 엔진 |
| `audio` | Audio 서비스 | `VITE_API_AUDIO_*` | 오디오 처리 |
| `ta` | TA 서비스 | `VITE_API_TA_*` | 텍스트 분석 |
| `nlp` | NLP 서비스 | `VITE_API_NLP_*` | 자연어 처리 (미사용) |

### 2.2 apiPlugin 우회 직접 호출

| 파일 | 대상 | 내용 |
|------|------|------|
| `common/interface/user.ts` | User 서비스 (`VITE_NEW_USER_SERVICE_API_URL`) | 8개 엔드포인트 직접 호출 |
| `components/.../CounselingStatus.vue` | QA 서비스 (`VITE_QA_API_URL`) | 통화 종료 알림 |
| `api/modules/request.ts` | 레거시 (`http://10.1.1.1:3030`) | 하드코딩된 개발 URL |

### 2.3 실시간 연결 (WebSocket / Socket.IO)

| 파일 | 프로토콜 | 대상 | 전환 여부 |
|------|----------|------|-----------|
| `socketIOPlugin.ts` | Socket.IO | Advisor 백엔드 | 유지 (자체 백엔드) |
| `AdvisorbotClient.ts` | Socket.IO | CE Advisorbot | **유지** (실시간 스트리밍) |
| `utils/common.ts` | Native WebSocket | Call Audio Streamer | **유지** (바이너리 오디오) |
| `stores/modules/websocket.ts` | SockJS/STOMP | CCAAS Gateway | **유지** (브로드캐스트) |

### 2.4 백엔드 기존 연동

| 서비스 | 파일 | 호출 엔드포인트 |
|--------|------|----------------|
| User 서비스 | `user-info.service.ts` | `GET /api/user/get_user`, `GET /api/user/assignable` |
| Tenant Config | `tenant-config.service.ts` | `GET /api/configs/get_configs` |
| CE 서비스 | `summary.service.ts` | `GET /api/ce/v1/nlu-catalog/intents/:id/external-category` |
| LLM | `llm-orchestrator.service.ts` | `POST /llm/complete` |

---

## 3. 전환 범위

### 3.1 전환 대상 (REST API → BFF 경유)

| 우선순위 | 서비스 | 사유 |
|----------|--------|------|
| **P0** | User 서비스 | 프론트/백엔드 중복 호출, 헤더 불일치 (`X-auth-token` vs `X-Auth-token`) |
| **P1** | Knowledge 서비스 | REST API, 백엔드 경유로 응답 필터링 가능 |
| **P1** | TA 서비스 | REST API, 분석 결과 후처리 가능 |
| **P2** | CE 서비스 (REST만) | REST API 부분만 전환, Socket.IO는 유지 |
| **P2** | QA 서비스 | 단일 엔드포인트, 전환 간단 |
| **P3** | Auth 서비스 | 인증 흐름 리팩토링과 함께 진행 |

### 3.2 전환 제외 (직접 연결 유지)

| 서비스 | 사유 |
|--------|------|
| CE Advisorbot (Socket.IO) | 실시간 양방향 스트리밍, 백엔드 프록시 시 레이턴시 증가 |
| Call Audio (WebSocket) | 바이너리 오디오 스트림, 백엔드 불필요한 부하 |
| CCAAS Gateway (STOMP) | 브로드캐스트 구독, 프록시 비효율적 |
| NLP 인스턴스 | 현재 미사용 — 전환 대신 제거 |

### 3.3 병행 정리 대상

| 항목 | 조치 |
|------|------|
| `request.ts` 레거시 인스턴스 | 하드코딩 IP 제거, 참조 없으면 파일 삭제 |
| `VITE_ACCESS_TOKEN` 폴백 | 환경변수에서 제거, 코드 내 폴백 로직 삭제 |
| `envs.ts` 하드코딩 AES 키 | 환경변수로 이동 |
| `postMessage` wildcard origin | 명시적 origin으로 변경 |
| 토큰 `console.log` | `token.js` line 26 제거 |

---

## 4. 목표 아키텍처

```
┌─────────────┐
│   asst-web   │  프론트엔드
└──────┬──────┘
       │
       │  REST API (advisor 인스턴스만)
       │
┌──────▼──────┐
│ asst-service │  BFF 레이어
│              │
│  ┌─────────┐ │     ┌──────────────┐
│  │ Proxy   │─┼────▶│ User Service │
│  │ Module  │ │     ├──────────────┤
│  │         │─┼────▶│ Knowledge    │
│  │         │─┼────▶│ TA Service   │
│  │         │─┼────▶│ CE Service   │
│  │         │─┼────▶│ QA Service   │
│  │         │─┼────▶│ Auth Service │
│  └─────────┘ │     └──────────────┘
└──────────────┘

프론트엔드 직접 연결 유지:
  asst-web ──Socket.IO──▶ CE Advisorbot
  asst-web ──WebSocket──▶ Call Audio Streamer
  asst-web ──STOMP──────▶ CCAAS Gateway
```

---

## 5. 단계별 실행 계획

### Phase 0: 인프라 준비 (1주)

**목표**: BFF 프록시 공통 모듈 구축

- [ ] `asst-service/src/common/services/http-client.service.ts` 생성
  - NestJS `HttpModule`/`HttpService` 기반 공통 HTTP 클라이언트
  - 기존 raw axios 호출을 점진적으로 교체
  - 요청/응답 로깅, 타임아웃, 리트라이 정책 포함
- [ ] `asst-service/src/common/proxy/` 디렉토리 구조 생성
  - `proxy.module.ts` — 프록시 모듈
  - `base-proxy.controller.ts` — 공통 프록시 컨트롤러 베이스
- [ ] 프록시 컨트롤러 패턴 정의
  - 프론트엔드 요청 → 토큰 검증 → 백엔드 서비스 호출 → 응답 반환
  - 에러 매핑 규칙 (외부 서비스 에러 → 클라이언트 에러)
- [ ] 환경변수 정리
  - 백엔드용 `USER_HOST`, `KNOWLEDGE_HOST`, `TA_HOST` 등 추가/확인

### Phase 1: User 서비스 전환 (1~2주)

**목표**: 가장 중복이 심한 User 서비스부터 전환

- [ ] `asst-service/src/common/proxy/user-proxy.controller.ts` 생성
  ```
  GET  /api/proxy/user/get_user          → User Service
  GET  /api/proxy/user/profile/:id       → User Service
  GET  /api/proxy/user/get_managers      → User Service
  GET  /api/proxy/user/organization/*    → User Service
  POST /api/proxy/user/update_*          → User Service
  PATCH /api/proxy/user/update_*         → User Service
  ```
- [ ] 기존 `user-info.service.ts` 로직을 프록시 컨트롤러와 통합
- [ ] `asst-web/src/common/interface/user.ts` 수정
  - `VITE_NEW_USER_SERVICE_API_URL` → apiPlugin의 `advisor` 인스턴스 사용
  - 직접 axios import 제거
- [ ] apiPlugin에서 `user` 인스턴스 제거 (advisor 경유로 대체)
- [ ] `VITE_NEW_USER_SERVICE_API_URL` 환경변수 제거
- [ ] 헤더 불일치 문제 해결 (`X-auth-token` → 통일된 형식)
- [ ] 테스트: 사용자 조회, 프로필, 조직 구조, 권한 변경 E2E 검증

### Phase 2: Knowledge + TA 서비스 전환 (2주)

**목표**: 데이터 조회 중심 서비스 전환

#### Knowledge 서비스
- [ ] `knowledge-proxy.controller.ts` 생성
- [ ] 프론트엔드 Knowledge API 클래스에서 `knowledge` 인스턴스 → `advisor` 인스턴스로 변경
- [ ] apiPlugin에서 `knowledge` 인스턴스 제거
- [ ] `VITE_API_KNOWLEDGE_*` 환경변수 제거
- [ ] 테스트: 지식베이스 검색, 문서 조회 검증

#### TA 서비스
- [ ] `ta-proxy.controller.ts` 생성
- [ ] 프론트엔드 TA API 클래스에서 `ta` 인스턴스 → `advisor` 인스턴스로 변경
- [ ] apiPlugin에서 `ta` 인스턴스 제거
- [ ] `VITE_API_TA_*` 환경변수 제거
- [ ] 테스트: 텍스트 분석 결과 조회 검증

### Phase 3: CE (REST) + QA 서비스 전환 (1~2주)

**목표**: 나머지 REST API 전환

#### CE 서비스 (REST 부분만)
- [ ] `ce-proxy.controller.ts` 생성
  - 기존 `summary.service.ts`의 CE 호출을 프록시로 통합
- [ ] 프론트엔드 CE REST API 호출을 `advisor` 인스턴스로 변경
- [ ] apiPlugin에서 `ce` 인스턴스 제거
- [ ] `VITE_API_CE_*` 환경변수 제거 (단, `VITE_API_CE_ROOT_SERVER`는 Socket.IO용으로 유지)
- [ ] 테스트: CE REST API 응답 검증

#### QA 서비스
- [ ] `qa-proxy.controller.ts` 생성 (단일 엔드포인트)
  ```
  POST /api/proxy/qa/calls/end → QA Service
  ```
- [ ] `CounselingStatus.vue`에서 직접 axios 호출 → advisor API 호출로 변경
- [ ] `VITE_QA_API_URL` 환경변수 제거
- [ ] 테스트: 통화 종료 알림 검증

### Phase 4: Auth 서비스 전환 + 정리 (2주)

**목표**: 인증 흐름 개선 및 레거시 정리

#### Auth 서비스
- [ ] 인증 흐름 분석 (로그인, 토큰 갱신, 로그아웃)
- [ ] `auth-proxy.controller.ts` 생성
- [ ] 토큰 관리 일원화
  - 프론트엔드: `sessionStorage` → `httpOnly cookie` 전환 검토
  - 백엔드에서 토큰 갱신 처리
- [ ] apiPlugin에서 `auth` 인스턴스 제거

#### 레거시 정리
- [ ] `api/modules/request.ts` — 참조 확인 후 제거
- [ ] `nlp` axios 인스턴스 — 미사용 확인 후 제거
- [ ] `VITE_ACCESS_TOKEN` 폴백 로직 제거
- [ ] `envs.ts` 하드코딩 AES 키 → 환경변수 이동
- [ ] `postMessage` wildcard `"*"` → 명시적 origin
- [ ] `token.js` 디버깅 `console.log` 제거

### Phase 5: 검증 및 안정화 (1주)

- [ ] 전체 환경(dev, aws, ncp) 통합 테스트
- [ ] apiPlugin 최종 상태 확인: `advisor` 인스턴스만 남아야 함 (+ 실시간 연결용 별도 관리)
- [ ] 프론트엔드 `VITE_*` 환경변수 정리 (제거된 서비스 URL 삭제)
- [ ] 네트워크 탭에서 프론트→외부 서비스 직접 호출 없음 확인
- [ ] 성능 측정: BFF 경유로 인한 레이턴시 증가량 확인 (목표: < 50ms 추가)

---

## 6. 프록시 컨트롤러 설계 패턴

```typescript
// 예시: user-proxy.controller.ts
@Controller('api/proxy/user')
@UseGuards(JwtAuthGuard)
export class UserProxyController {
  constructor(private readonly httpClient: HttpClientService) {}

  @Get('get_user')
  async getUser(@Req() req: Request) {
    const token = req.headers['authorization'];
    return this.httpClient.get(
      `${process.env.USER_HOST}/api/user/get_user`,
      { headers: { 'X-Auth-token': token } },
    );
  }
}
```

**핵심 원칙**:
- 프록시 컨트롤러는 비즈니스 로직을 포함하지 않는다 (단순 전달)
- 인증은 `JwtAuthGuard`에서 처리
- 백엔드에서만 외부 서비스 토큰을 관리
- 에러는 적절한 HTTP 상태코드로 매핑

---

## 7. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| BFF 경유 레이턴시 증가 | 사용자 체감 속도 저하 | 응답 캐싱, 연결 풀 최적화 |
| 전환 중 프론트/백엔드 버전 불일치 | 기능 장애 | Feature flag로 신규/기존 경로 전환 가능하게 |
| 백엔드 단일 장애점 | 전체 서비스 영향 | 서킷 브레이커 패턴 적용 |
| 대용량 파일 업로드 (Knowledge) | 백엔드 메모리 부하 | 스트리밍 프록시 또는 presigned URL 방식 |

---

## 8. 성공 기준

- [ ] 프론트엔드에서 `advisor` 인스턴스 외 REST API 직접 호출 0건
- [ ] `VITE_*` 외부 서비스 URL 환경변수 제거 완료 (실시간 연결용 제외)
- [ ] 모든 환경에서 E2E 테스트 통과
- [ ] 보안 이슈 6건 모두 해소
- [ ] API 응답 레이턴시 증가 < 50ms

---

## 부록: 환경변수 변화

### 제거될 프론트엔드 환경변수
```
VITE_NEW_USER_SERVICE_API_URL
VITE_API_KNOWLEDGE_*
VITE_API_TA_*
VITE_API_CE_*  (REST용, Socket.IO용은 유지)
VITE_QA_API_URL
VITE_API_AUTH_*
VITE_ACCESS_TOKEN
```

### 추가/확인할 백엔드 환경변수
```
USER_HOST        (기존)
KNOWLEDGE_HOST   (신규)
TA_HOST          (신규)
CE_HOST          (기존)
QA_HOST          (신규)
AUTH_HOST         (신규)
```
