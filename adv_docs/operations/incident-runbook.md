# 장애 대응 런북 (Incident Runbook)

> 운영 중 자주 발생하는 장애 + 대응 매뉴얼. 새벽 호출 시에도 따라 할 수 있도록 단계별 정리.
> 1차 문의처는 [contacts.md](contacts.md#5-장애-대응-시-1차-문의처) 참조.

---

## 0. 장애 대응 기본 흐름

```
1. 영향도 파악 (사용자 수, 기능 범위)
2. trace ID / call_id / tenant_id 확보
3. 본 런북에서 해당 시나리오 찾기
4. 1차 대응 (재시작 / 토글 / fallback)
5. 1차 담당자에게 통보 (contacts.md)
6. 사후 분석 + 런북 업데이트
```

**의사결정 원칙**:
- **서비스 가용성 > 데이터 일관성**: 일부 기능 제한해서라도 메인 통화 흐름은 유지
- **재시작 전에 로그 수집**: pod 재시작 시 메모리 상태 손실됨
- **혼자 결정하지 않기**: 운영 변경 (env, 시크릿, 마이그레이션) 은 반드시 2인 검증

---

## 1. STT 발화가 화면에 안 보임

### 증상
- 통화는 시작됐는데 채팅 영역에 발화 버블이 안 뜸
- 또는 일부 발화만 보임

### 1차 진단

| 확인 사항 | 명령 / 위치 |
|-----------|------|
| 브라우저 콘솔에 `[stt-diag] agent_id mismatch drop` 경고 있나? | DevTools Console |
| `socket.on('redis-message', ...)` 호출 횟수 | DevTools Console |
| Redis 구독 상태 | `GET /api/asst/v1/redis-monitor/status` |
| Socket.IO room 상태 | `GET /api/asst/v1/redis-monitor/debug/rooms` |

### 원인 후보 → 대응

| 원인 | 확인 | 대응 |
|------|------|------|
| **`agent_id` 불일치** | 브라우저 콘솔 warn 로그 | 사용자 프로필의 `cc_cti_id` 확인. STT 엔진과 매핑 검증 (콜 인프라). |
| **Redis 채널 prefix 불일치** | 환경별 `VITE_USER_NODE_ENV` 값 | 빌드 환경 확인. `dev`/`prod` prefix 일치 여부. |
| **K8s sticky session 끊김** | LB 설정 | ALB stickiness.enabled=true 확인. **DevOps 즉시 문의**. |
| **Redis 구독 미등록** | `/redis-monitor/channels` 호출 | 프론트가 `POST /redis-monitor/subscribe/...` 호출했는지 |
| **외부 STT 엔진 다운** | STT 엔진 측 로그 | **콜 인프라 (이태희/김현철 수석님) 호출** |

### 임시 우회
- 브라우저 새로고침 (소켓 재연결)
- 다른 pod로 라우팅 시도 (LB 캐시 클리어)

---

## 2. 통화 요약 / 자동 todo 실패 (LLM 측 오류)

### 증상
- `POST /api/asst/v1/summary` 가 502/503 반환
- 통화 종료 후 자동 todo 안 생성됨

### 1차 진단

| 상태 코드 | 의미 |
|-----------|------|
| **502 Bad Gateway** | LLM Orchestrator가 응답했지만 오류 |
| **503 Service Unavailable** | LLM Orchestrator 연결 불가 |
| **404** | `callstats_id` 잘못 (orchestrator:persisted 미수신) |
| **400** | `tenantId` 누락 (인증/토큰 문제) |

### 원인 후보 → 대응

| 원인 | 확인 | 대응 |
|------|------|------|
| **LLM Orchestrator 다운** | `LLM_ORCHESTRATOR_HOST` 헬스 체크 | 1차 담당: 손영훈 이사님 + 프롬프트팀 |
| **프롬프트 변경 후 응답 형식 불일치** | Orchestrator 측 trace ID로 로그 | 프롬프트팀 (이영훈 과장/최혜연 대리님) |
| **타임아웃 (30초 초과)** | LLM 응답 시간 | 프롬프트팀 + 모델 변경 검토 |
| **`X-Tenant-Id` 누락** | asst-service 로그 | 토큰에서 추출 안 됨 → USER_HOST 응답 확인 |
| **`SEARCH_HOST` 없는데 assist-stream 호출** | env 확인 | 503 응답. env 보완 또는 기능 비활성 |

### 임시 우회
- 사용자에게 "잠시 후 다시 시도" 안내
- `LLM_HOST` (fallback) 활성화 검토

---

## 3. assist-stream 답변이 이상함 / 안 옴

### 증상
- 고객 발화 후 추천 답변이 안 뜸
- 답변이 다른 테넌트의 내용 같음
- SSE 연결이 즉시 끊김

### 1차 진단

| 확인 사항 | 명령 / 위치 |
|-----------|------|
| `SEARCH_HOST` 설정 | env 확인 |
| `X-Tenant-Id` 값 | [assist-stream.service.ts:82-83](../../asst-service/src/advisor/assist-stream/services/assist-stream.service.ts#L82-L83) |
| 인증 미들웨어 우회 확인 | [app.module.ts:37](../../asst-service/src/app.module.ts#L37) |

### 알려진 함정

⚠️ **`X-Tenant-Id` 하드코딩 TODO** — 현재 `00000000-0000-0000-0000-000000000000` 으로 박혀 있음. 멀티테넌트 환경에서 **다른 테넌트 데이터로 검색될 위험** 있음.

### 대응

| 원인 | 대응 |
|------|------|
| `SEARCH_HOST` 다운 | 1차: 손영훈 이사님 |
| SSE 연결 즉시 끊김 | 게이트웨이 / Nginx `X-Accel-Buffering: no` 설정 확인 (DevOps) |
| 답변 내용 이상 | 프롬프트팀 + RAG 엔진팀 |
| 모든 테넌트 동일 답변 | 위 하드코딩 TODO 처리 필요 |

---

## 4. 코칭 메시지가 상담원에게 안 감

### 증상
- 관리자가 코칭 메시지 발송했는데 상담원 화면에 안 뜸

### 1차 진단

| 확인 사항 | 위치 |
|-----------|------|
| `CoachingSocketHandler` 구독 상태 | asst-service 로그 (`Redis 코칭 채널 구독 완료`) |
| 상담원의 Socket.IO room 가입 여부 | `/redis-monitor/debug/rooms` |
| 같은 pod 라우팅 여부 | K8s sticky session |

### 원인 후보

| 원인 | 대응 |
|------|------|
| **K8s sticky session 끊김** | DevOps 즉시 문의 |
| **`CoachingRedisService` publish 실패** | asst-service 로그 |
| **상담원이 사이트 비활성** (페이지 백그라운드) | 알림 푸시 검토 |
| **자동 마이그레이션 컬럼 누락** | `coaching_request_id`, `sender_name`, `customer_name` 컬럼 확인 |

---

## 5. DB 연결 오류 / 풀 고갈

### 증상
- `connectionTimeoutMillis` 초과 에러
- `DB 연결 생성 실패` 로그
- 응답이 느려지거나 타임아웃

### 1차 진단

| 확인 | 명령 |
|------|------|
| 활성 연결 수 | `getActiveConnectionCount()` (코드상) |
| PG 측 연결 수 | `SELECT count(*) FROM pg_stat_activity` |
| 테넌트별 캐시 | `getConnectionDetails()` (코드상) |

### 원인 후보

| 원인 | 대응 |
|------|------|
| **테넌트 DataSource 누적** | pod 재시작 (임시) + LRU 도입 검토 |
| **PG 측 max_connections 초과** | DBA + PG 설정 |
| **`USER_HOST` 응답 지연** | TenantConfigService 30초 timeout 영향 |
| **장기 트랜잭션 hang** | `pg_stat_activity` 에서 active 쿼리 확인 |

### 임시 우회
- pod 재시작 → 모든 DataSource 해제 (`OnModuleDestroy`)
- USER_HOST 응답 캐싱 (현재 없음, 검토 필요)

---

## 6. 게이트웨이 404 / 라우팅 오류

### 증상
- 프론트 → asst-service 호출이 404
- Socket.IO 핸드셰이크 실패

### 1차 진단

| 확인 | 방법 |
|------|------|
| 게이트웨이 라우팅 규칙 | 게이트웨이 측 설정 (DevOps) |
| asst-service `setGlobalPrefix` | `/api/asst/v1` 일치 확인 |
| 클라이언트 path | `/aicc/asst-service/socket.io` |

### 매핑

```
브라우저 path: /aicc/asst-service/socket.io
   ↓ 게이트웨이 (StripPrefix=2 + PrefixPath=/api/asst/v1)
asst-service: /api/asst/v1/socket.io
```

### 대응
- 1차: DevOps (윤찬우 수석님)
- prefix 변경 시 양쪽 동시 배포 필요

---

## 7. 시크릿 노출 / 보안 인시던트

### 증상
- 깃 로그에 평문 비밀번호 발견
- 외부 시스템 접속 로그에 비정상 패턴

### 즉시 대응
- 노출된 자격증명 즉시 로테이션 (PG / Redis 등) — DBA + DevOps
- 영향 범위 파악 (접속 로그)
- DevOps + 보안팀 통보
- `.env` 파일이 git에 추적되고 있지 않은지 확인 (`.gitignore`)
- 필요 시 git history 정리는 협의 후 진행

> 구체적인 노출 항목/대응 우선순위는 문서에 남기지 않고 담당자에게 직접 인계합니다 ([contacts.md](contacts.md)).

---

## 8. 마이그레이션 미적용 / 컬럼 누락

### 증상
- `column "xxx" does not exist` 에러
- 특정 테넌트만 동작 안 함

### 1차 진단

| 확인 | 방법 |
|------|------|
| 자동 마이그레이션 컬럼 적용 여부 | asst-service 로그 `컬럼 추가 완료` 검색 |
| 다른 테넌트 적용 누락 | 모든 테넌트 DB에 `\d advisor.<table>` |

### 원인 후보

| 원인 | 대응 |
|------|------|
| **DBA가 일부 테넌트 누락** | 누락 테넌트 식별 → SQL 재적용 |
| **자동 마이그레이션 실패** | `스키마 마이그레이션 중 경고` 로그 검색 |
| **엔티티 추가 후 dynamic-database.service.ts 누락** | entities 배열 양쪽 확인 |

---

## 9. 어드바이저봇 동작 안 함

### 증상
- 봇 위젯이 응답 없음 / 알림만 표시 후 결과 없음

### 1차 진단

| 확인 | 위치 |
|------|------|
| CE 소켓 연결 상태 | Vue DevTools → `advisorbotStore.isConnected` |
| 세션 초기화 | `isSessionInitialized` |
| 마지막 결과 | `lastExecutionResult` |
| CE 서비스 상태 | `CE_HOST` 헬스 |

### 대응
- 1차: 도창록 책임님 (대화엔진)
- 또는: DevOps (CE 서비스 인프라)

---

## 10. 통화 종료 후 채팅이 멈춤 / 스트리밍 잔존

### 증상
- 통화 종료됐는데 발화 버블이 계속 "스트리밍 중" 상태
- 새 통화 시작해도 이전 발화 잔존

### 원인

[useChatMessageParser.ts](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts) 의 `call:events end` 핸들러가 정상 실행 안 됨.

### 대응

- 페이지 새로고침 (임시)
- `call:events` 채널 구독 확인 (`/redis-monitor/status`)
- `streamingBySpeaker` 와 `pendingMergeBySpeker` 상태 디버깅 (브라우저 콘솔)

---

## 11. 일반 인시던트 대응 템플릿

장애 발생 시 슬랙 채널에 다음 형식으로 보고:

```
🚨 [장애] STT 발화 미표시
영향: tenantA 의 ~20명 상담원
시작: 2026-05-15 14:30 KST
증상: 통화 시작은 되는데 발화 안 보임
trace_id: abc-123-def
1차 진단: K8s sticky session 끊김으로 추정
대응: DevOps 윤찬우 수석님 호출 중
다음 업데이트: 15분 내
```

---

## 12. 사후 분석 (Postmortem)

장애 해결 후 다음 정보를 별도 문서로 정리 (예: `incidents/2026-05-15-stt-outage.md`):

- **타임라인** (감지 → 1차 대응 → 해결)
- **근본 원인**
- **영향 범위** (사용자 수, 통화 수, 시간)
- **잘 한 점**
- **개선할 점**
- **재발 방지 조치** (코드 변경 / 모니터링 추가 / 런북 업데이트)

→ 본 런북도 이 결과로 갱신.

---

## 13. 모니터링 권장 메트릭

운영 시 다음 지표 모니터링 (Grafana 등):

| 메트릭 | 임계치 | 의미 |
|--------|--------|------|
| asst-service p95 응답시간 | < 500ms | API 성능 |
| Socket.IO 연결 수 | (테넌트별) | 활성 사용자 |
| Redis subscribe 채널 수 | 100~500 | 누수 감지 |
| DB 활성 연결 수 | < 80% of max | 풀 고갈 임박 |
| LLM Orchestrator 호출 성공률 | > 99% | LLM 의존성 |
| `[stt-diag]` warn 로그 빈도 | 낮을수록 좋음 | agent_id 매핑 이슈 |
| Tracer 에러율 | < 0.1% | 전체 안정성 |

(현재 메트릭 수집/대시보드 인프라 구축 여부는 DevOps 확인 필요)
