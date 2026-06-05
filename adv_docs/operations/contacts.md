# 영역별 담당자

> Advisor 시스템 운영/개발 시 영역별 메인 담당자 명단입니다.
> 정확한 연락처(슬랙/이메일/전화)는 별도 사내 디렉토리 참조.

**최종 갱신**: 2026-05-15

---

## 1. 시스템 영역별 담당자

### 인프라 / 플랫폼

| 영역 | 메인 담당자 | 비고 |
|------|-----------|------|
| **콜 인프라** | 이태희 수석님, 김현철 수석님 | CTI / STT / NLP 엔진 연동, Redis 채널 |
| **DevOps** | 윤찬우 수석님, 이진형 주임님 | 배포, K8s, CI/CD, 모니터링 |
| **온프라미스** | 이태희 수석님 (임시) | 클라우드 → 온프레미스 이관 시 |

### AI / 엔진

| 영역 | 메인 담당자 | 비고 |
|------|-----------|------|
| **RAG / NLP 메인 엔진** | 손영훈 이사님 | `SEARCH_HOST` 측, assist-stream 답변 품질 |
| **대화엔진** | 도창록 책임님 | CE 서비스, 어드바이저봇 그래프 |
| **시나리오 / 프롬프트** | 이영훈 과장님, 최혜연 대리님 | LLM Orchestrator 프롬프트 (`adv-conversations-summarize` 등) |
| **SLLM (소형 LLM)** | 최문용 책임님 | 경량 모델 운영 |
| **목업 서비스** | 도창록 책임님 | mock/시뮬레이션 환경 |

### 외부 시스템 / 도메인

| 영역 | 메인 담당자 | 비고 |
|------|-----------|------|
| **KMS (지식관리)** | 김현철 수석님 (임시) → **공석** | `KNOWLEDGE_API_URL`, 문서 검색/즐겨찾기 위임 — **인계 시급** |
| **TA / QA** | **공석** | `QA_API_URL`, `TA_HOST` (현재 주석 처리) — **인계 시급** |

### 사업 / 관리

| 역할 | 담당자 |
|------|--------|
| **영업 / PM** | 이상우 이사님, 차정훈 차장님, 노희균 차장님 |

---

## 2. 코드 영역 ↔ 담당자 매핑

후임자가 코드/장애를 만났을 때 누구에게 문의할지 빠르게 찾기:

| 코드 영역 | 담당자 |
|----------|--------|
| `asst-service/src/advisor/call/` (통화 통계) | 이태희 수석님, 김현철 수석님 (콜 인프라) |
| `asst-service/src/advisor/assist-stream/` | 손영훈 이사님 (RAG/NLP) |
| `asst-service/src/advisor/summary/` (LLM 요약) | 이영훈 과장님, 최혜연 대리님 (프롬프트) + 손영훈 이사님 (엔진) |
| `asst-service/src/advisor/coaching/` | (도메인 담당) + 콜 인프라 (Redis pub/sub) |
| `asst-service/src/common/services/llm-orchestrator.service.ts` | 이영훈 과장님, 최혜연 대리님 (프롬프트) |
| `asst-service/src/common/proxy/knowledge-proxy.controller.ts` | KMS 담당 (현재 공석, 임시 김현철 수석님) |
| `asst-service/src/common/proxy/ce-proxy.controller.ts` | 도창록 책임님 (대화엔진) |
| `asst-service/src/common/gateways/` (Socket.IO) | 콜 인프라 + DevOps (sticky session) |
| `asst-service/src/common/services/dynamic-database.service.ts` | DevOps (인프라) |
| `asst-service/Dockerfile`, `docker-compose.*.yml` | 윤찬우 수석님, 이진형 주임님 (DevOps) |
| `asst-service/migrations/*.sql` | DevOps + 도메인 담당자 |
| `asst-web/src/composables/useAdvisorbot.ts` | 도창록 책임님 (대화엔진) |
| `asst-web/src/view/advisor/components/chat/` | 콜 인프라 (STT 표시) + UI 담당 |

---

## 3. 외부 시스템 ↔ 담당자

| 외부 시스템 (env) | 담당자 |
|------------------|--------|
| `USER_HOST` (사용자/테넌트) | DevOps (운영 도메인) |
| `LLM_ORCHESTRATOR_HOST` | 이영훈 과장님, 최혜연 대리님 (프롬프트) + 손영훈 이사님 |
| `SEARCH_HOST` (RAG) | 손영훈 이사님 |
| `CE_HOST` (어드바이저봇) | 도창록 책임님 |
| `KNOWLEDGE_API_URL` (KMS) | (공석) 임시 김현철 수석님 |
| `AUDIO_SERVICE_API_URL` (녹취) | 콜 인프라 |
| `QA_API_URL` | (공석) |
| Redis (Pub/Sub) | 콜 인프라 + DevOps |

---

## 4. 시급 인계 필요 영역 (공석)

후임자가 합류 전에 인수자가 확정되어야 할 영역:

1. **KMS** — `KNOWLEDGE_API_URL` 연동, 문서 검색/즐겨찾기 위임 정책. 임시로 김현철 수석님이 보고 계시지만 장기 담당자 필요.
2. **TA / QA** — `QA_API_URL`, `TA_HOST` 모두 현재 공석. `TA_HOST`는 [validation.config.ts:82](../../asst-service/src/config/validation.config.ts#L82) 에서 일시 주석 처리됨.

→ **이 영역의 코드 변경/장애 발생 시 콜 인프라(이태희 수석님) 또는 DevOps(윤찬우 수석님)에게 우선 문의**.

---

## 5. 장애 대응 시 1차 문의처

| 증상 | 1차 문의 |
|------|---------|
| STT 발화가 안 보임 | 콜 인프라 |
| 통화 요약 503 | 프롬프트팀 + RAG/NLP (LLM Orchestrator 상태) |
| assist-stream 답변 이상 | RAG/NLP (손영훈 이사님) |
| 어드바이저봇 동작 안 함 | 대화엔진 (도창록 책임님) |
| 코칭 메시지 전달 안 됨 | 콜 인프라 + DevOps (Socket.IO sticky) |
| KMS 검색 안 됨 | KMS (현재 임시 담당) |
| 배포 실패 / pod 재시작 무한 | DevOps |
| 마이그레이션 미적용 | DevOps + 도메인 담당자 |
| 게이트웨이 404 | DevOps |
| 시크릿 노출 / 보안 이슈 | DevOps (긴급) |

---

## 6. 인계 시 갱신 책임

이 문서는 다음 시점에 반드시 갱신:

- 담당자 변경
- 공석 충원
- 신규 영역 추가 (예: 새 외부 서비스 연동)
- 임시 담당이 정식 담당으로 전환

갱신 시 상단의 **최종 갱신** 날짜도 함께 수정.
