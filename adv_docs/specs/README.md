# Specs

기술 스펙 및 기능 정의서입니다.

## 도메인 / 외부 통합

| 문서 | 주제 |
|------|------|
| [domains-overview.md](domains-overview.md) | asst-service 17개 도메인 모듈 한눈에 보기 + 핵심 5개 상세 |
| [llm-integration.md](llm-integration.md) | LLM Orchestrator 호출 (`complete()` / `customComplete()`), 프롬프트 컨벤션 |
| [proxy-controllers.md](proxy-controllers.md) | BFF 프록시 6종 (CE/Knowledge/User/Audio/QA/TA), KMS 위임 정책 |
| [advisorbot.md](advisorbot.md) | 어드바이저봇 (CE 그래프 봇) — Assist Stream과의 차이 |
| [stt-nlp-contract.md](stt-nlp-contract.md) | 외부 STT/NLP 엔진과의 Redis 메시지 contract (필드/예시/순서) |
| [socket-events.md](socket-events.md) | 메인 Socket.IO 이벤트 전체 카탈로그 (room 컨벤션, 이벤트 매트릭스) |

## 외부 시스템 분석 (NeMo Turn EOU 관련)

| 문서 | 주제 |
|------|------|
| [turn-eou-mismatch-report.md](turn-eou-mismatch-report.md) | NeMo Turn EOU 불일치 이슈 분석 |
| [nemo-turn-eou-mismatch-server-request.md](nemo-turn-eou-mismatch-server-request.md) | 서버측 요청 분석 |
| [nemo-turn-eou-mismatch-logs-20260511.md](nemo-turn-eou-mismatch-logs-20260511.md) | 로그 분석 |
| [nemo-turn-eou-mismatch-logs-20260511-bank.md](nemo-turn-eou-mismatch-logs-20260511-bank.md) | 은행 도메인 로그 |
| [turn-eou-mismatch-raw-log.md](turn-eou-mismatch-raw-log.md) | 원본 로그 |
