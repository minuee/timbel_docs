# Operations

운영 / 개발 환경 문서입니다.

| 문서 | 주제 |
|------|------|
| [env-variables.md](env-variables.md) | 백엔드/프론트엔드 환경변수 전체 + 환경별 권장 조합 |
| [local-setup.md](local-setup.md) | 로컬 개발 환경 셋업 (PG/Redis 도커, 첫 실행 체크리스트) |
| [error-logging.md](error-logging.md) | TraceLogger, OpenTelemetry, 표준 에러 매핑 (502/503/500) |
| [contacts.md](contacts.md) | 영역별 메인 담당자 + 코드 영역 ↔ 담당자 매핑 + 장애 1차 문의처 |
| [glossary.md](glossary.md) | 용어집 (STT/NLP/EOU/RAG/KMS/BFF/CCaaS/SLLM 등) |
| [incident-runbook.md](incident-runbook.md) | 장애 대응 런북 (장애별 1차 대응 + 임계치) |
| [permissions.md](permissions.md) | role(AGENT/ADMIN/VIEWER), 동적 라우터, 백엔드 권한 미완성 이슈 |
| [handover-checklist.md](handover-checklist.md) | Day-by-day 학습 체크리스트 + 디버깅 도구 + 인수인계 종료 체크 |

> 배포(Docker/K8s)·DB 마이그레이션·테스트·보안정책은 별도 문서로 두지 않습니다.
> 마이그레이션 SQL 원본은 `asst-service/migrations/`, 나머지는 인수인계 세션에서 구두 전달 + 담당자([contacts.md](contacts.md)) 연결로 다룹니다.

**신규 합류 시**: [handover-checklist.md](handover-checklist.md) → [glossary.md](glossary.md) → [contacts.md](contacts.md) 순.

**장애 발생 시**: [incident-runbook.md](incident-runbook.md) → [contacts.md](contacts.md) 순.
