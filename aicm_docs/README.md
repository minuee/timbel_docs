# AICM 제품 설계 문서

| 항목 | 값 |
|------|---|
| 제품 | AICM (AI Content Management — 지식 관리 시스템) |
| 문서 수 | 151개 (.md) |
| 최종 갱신 | 2026-03-27 |

---

## 폴더 구조

| 폴더 | 역할 |
|------|------|
| `01-requirements/usecases/` | 유즈케이스 문서 — 사용자 관점 시나리오 |
| `01-requirements/features/` | 기능정의서 — 시스템 관점 규칙/제약 |
| `01-requirements/flows/` | 프로세스 흐름도 — Mermaid 상태/시퀀스/플로우차트 |
| `02-architecture/` | 시스템 개요, 모듈 아키텍처, 인증, 이벤트, 횡단관심사, 권한 체계 |
| `02-architecture/data/` | 데이터 아키텍처 — 서비스별 인프라(RDB, ES, Redis, Milvus, MinIO) |
| `03-module-design/` | 모듈별 상세 설계 (README/api/rules/events/data 5파일 구조) |
| `adr/` | 아키텍처 결정 기록 (ADR). `{번호}-영문-kebab.md` 형식 |
| `reviews/` | 아키텍처/스펙 리뷰 결과 |
| `qna/` | Q&A 기록 |

---

## 문서 작성 순서

```
유즈케이스 → 기능정의서 → 프로세스 흐름도 → 모듈 설계
(01-requirements)                           (03-module-design)
```

- 유즈케이스에서 사용자 시나리오를 먼저 정의하고
- 기능정의서에서 시스템 규칙을 구체화하고
- 프로세스 흐름도에서 복잡한 흐름을 시각화하고
- 모듈 설계에서 구현 가능한 수준으로 상세화한다

---

## 네이밍 컨벤션

| 문서 유형 | 패턴 | 예시 |
|-----------|------|------|
| 유즈케이스 | `UC-{도메인}-한글명.md` | `UC-DOC-문서관리.md` |
| 기능정의서 | `FD-{약자}-한글명.md` | `FD-APR-승인워크플로.md` |
| 아키텍처 | `{번호}-영문명.md` | `01-system-overview.md` |
| ADR | `{번호}-영문-kebab.md` | `001-resource-classification-and-system-role.md` |
| 모듈 설계 | `{역할}.md` | `README.md`, `api.md`, `rules.md`, `events.md`, `data.md` |

---

## 주요 진입점

| 문서 | 설명 |
|------|------|
| [아키텍처 README](02-architecture/README.md) | 시스템 설계 문서 인덱스 |
| [유즈케이스 인덱스](01-requirements/usecases/README.md) | 역할 정의, UC 매트릭스, 도메인별 상세 링크 |
| [기능정의서 인덱스](01-requirements/features/README.md) | FD 목록, 도메인 교차 참조 |
| [모듈 설계 README](03-module-design/README.md) | 모듈 목록, 작성 상태, 의존성 |

---

## 관련 도구

| 도구 | 위치 | 용도 |
|------|------|------|
| 모듈 레지스트리 | `.claude/commands/_shared/module-registry.md` | 커맨드 공유 데이터 (모듈 매핑, 체크리스트) |
| 스펙 파이프라인 | `.claude/commands/module-spec-pipeline.md` | 모듈 스펙 작성→검수→상태 업데이트 |
| 문서 작성 스킬 | `.claude/skills/document-writer/` | UC/FD/흐름도 작성 가이드 |
| 레지스트리 동기화 | `.claude/skills/registry-sync/` | 원천 문서 변경 시 레지스트리 자동 갱신 |
