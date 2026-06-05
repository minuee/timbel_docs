> **문서 유형**: 아키텍처
> **종합 점수**: 70 / 100 (공용 70 × 0.6 + 전문 69 × 0.4)
> **리뷰 대상**: `docs/02-architecture/05-async-event-architecture.md`
> **페르소나**: 시니어 백엔드 개발자 — 최민재 (AI)
> **리뷰일**: 2026-04-12 15:17
> **지적사항**: P1: 2건, P2: 5건, P3: 4건
> **자동 반영 가능**: 5건 / 설계 결정 필요: 6건

---

## 리뷰 스코어카드

### 공용 루브릭 (60%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| RD-AR-01 | 관심사 분리 | 72 | 30% | 큐별 관심사 분리와 3티어 신뢰성 모델은 견고하나, `export`·`search-events` 큐의 파이프라인 상세가 parsing/embedding 대비 부족 |
| RD-AR-02 | 확장성/진화 가능성 | 70 | 25% | Worker 스케일링 가이드라인과 SystemConfig 동적 설정은 실용적이나, 이벤트 페이로드 인터페이스 미정의로 스키마 진화 기반이 부재 |
| RD-AR-03 | 보안 아키텍처 타당성 | 65 | 15% | AsyncJobContext 보안 필드와 Bull Board 접근제어는 양호하나, Redis 내 민감 페이로드 보호 및 모니터링 도구의 필드 마스킹 전략 부재 |
| RD-AR-04 | 운영 용이성 | 75 | 20% | DLQ 관리 API·Bull Board·OpenTelemetry 메트릭·Reconciliation 배치까지 운영 전반을 커버하나, Worker graceful shutdown과 Redis 메모리 모니터링 누락 |
| RD-AR-05 | 의사결정 추적성 | 60 | 10% | 개별 설계 근거(파싱 동시성, 2단계 알림 패턴)는 인라인으로 잘 기록했으나, 핵심 결정(Outbox 적용 범위, DLQ 전략 선택)에 ADR 참조가 없음 |
| | **공용 소계** | **70** | 100% | |

### 전문 루브릭 (40%)

| # | 차원 | 점수 | 가중치 | 핵심 근거 (1줄) |
|---|------|------|--------|-----------------|
| EX-AR-SR-01 | 의존성 방향 건전성 | 68 | 50% | 레이어 원칙(Domain→Infra)은 준수하나, §6.7에서 deprecated된 `re-embedding` 큐 참조 및 `search-events` 큐 발행자 불명확으로 교차 문서 정합성 결함 |
| EX-AR-SR-02 | 과잉 설계 여부 | 70 | 50% | 대부분 현실적 수준이나, 모듈러 모놀리스에서의 이벤트 버전 관리 전략과 Best-effort 티어에 Outbox 패턴 적용은 분류 체계와 모순 |
| | **전문 소계** | **69** | 100% | |

### 종합: 70 / 100 (공용 70 × 0.6 + 전문 69 × 0.4)

---

## 차원별 상세 피드백

### 공용 차원

#### RD-AR-01. 관심사 분리 — 72/100 양호

§6.1의 큐 설계는 관심사별로 깔끔하게 분리되어 있습니다. `parsing`, `embedding`, `ai-summary`, `notification`, `scheduled-publish`, `es-indexing` 각각이 명확한 책임을 갖고, 02-module-architecture.md §3.3의 3티어 신뢰성 모델(Critical/Important/Best-effort)과 정합합니다.

특히 `notification` 큐의 2단계 패턴 설명이 인상적입니다 — "EventBus(Best-effort)로 트리거하되, 모듈 내부에서는 BullMQ로 안정적 발송을 보장하는 패턴"이라는 서술은 다른 모듈이 이 큐에 직접 enqueue하지 않는다는 소유권을 명확히 합니다. `@Cron` 기반 내부 배치(`access-log-flush`, `access-count-flush`, `notice-reminder`, `notice-pin-expiry`)를 BullMQ 큐와 분리하여 별도로 기술한 것도 관심사 분리 관점에서 좋습니다.

그러나 **문서 내 상세도 균형이 맞지 않습니다**. `parsing`(§6.2)과 `embedding`(§6.3)은 Mermaid 흐름도까지 갖춘 반면, `export` 큐와 `search-events` 큐는 §6.1 테이블에 한 줄 기재 + §6.6 DLQ 매핑 + §6.9 Worker 스케일링 테이블에만 등장합니다. `export` 큐의 Job 생산자(ExportModule)와 처리 흐름, `search-events` 큐의 발행 모듈과 소비자 체인이 이 문서 안에서 추적되지 않습니다. 02-module-architecture.md §3.3.1 C표에서 ExportModule이 `export` 큐를 사용한다는 것은 확인되지만, 05 문서에는 해당 파이프라인 설명이 없어서 이 문서만 읽고 export 비동기 처리 흐름을 파악할 수 없습니다.

또한 §6.5 이벤트 흐름도(시퀀스 다이어그램)가 "문서 승인→배포→임베딩 완료" 단일 시나리오만 다루고 있습니다. 게시판 권한 변경(`board.events`), ACL 변경(`acl.events`), 검색 설정 변경(`search-events`)의 이벤트 흐름은 흐름도가 없어서 발행→큐→처리→후속 효과 체인을 한눈에 파악하기 어렵습니다.

#### RD-AR-02. 확장성/진화 가능성 — 70/100 양호

§6.9 Worker 스케일링 가이드라인은 실무적으로 유용합니다. 큐별 기본 concurrency와 조정 시 고려사항을 표로 정리한 것, SaaS(HPA) vs 온프렘(수동 증설/프로세스 분리) 확장 전략을 구분한 것, "Worker만 늘리고 다운스트림이 수용하지 못하면 타임아웃 실패가 증가한다"는 경고까지 — 실제 운영에서 필요한 내용이 잘 담겨 있습니다.

§6.5의 이벤트 버전 관리 규칙(필드 추가 자유, 제거·타입 변경은 새 이벤트명, 전환 기간 병행 발행)도 미래 변경에 대한 대비입니다.

SystemConfig 기반 동적 설정(DLQ 임계값, retry-all 배치 크기, Reconciliation cron 주기 등)은 코드 배포 없이 운영 파라미터를 조정할 수 있게 해주어 진화 가능성에 기여합니다.

하지만 **미비 사항으로 인지된 "전체 이벤트 카탈로그 매트릭스"와 "이벤트 페이로드 인터페이스(TypeScript)"가 부재**합니다. 이벤트 스키마가 정의되지 않은 상태에서 이벤트 버전 관리 규칙만 정의한 것은 기반 없는 정책입니다. 예를 들어 `document.published` 이벤트의 페이로드에 어떤 필드가 있는지 모르면, "필드 추가는 자유"라는 규칙의 기준선이 없습니다. `AsyncJobContext`(actorId, orgId, traceId, triggeredAt, sourceModule)만 정의되어 있고, 개별 이벤트/Job의 비즈니스 페이로드 인터페이스는 없습니다.

BullMQ Job 자체의 마이그레이션 전략도 누락되어 있습니다. 배포 시 큐에 이미 들어있는 구 스키마 Job을 신규 Worker가 어떻게 처리하는지(버전 필드 분기? 하위 호환?), Blue-Green 배포 시 두 버전의 Worker가 동시에 큐를 소비하는 상황에 대한 가이드가 없습니다.

#### RD-AR-03. 보안 아키텍처 타당성 — 65/100 양호

§6.5의 이벤트 페이로드 보안 컨텍스트(`AsyncJobContext`)는 잘 설계되어 있습니다. `actorId`와 `orgId`로 "누가, 어느 테넌트에서" 작업을 트리거했는지 추적하고, `traceId`로 end-to-end 분산 추적이 가능합니다. "DLQ로 이동 시에도 원본 페이로드의 보안 컨텍스트가 보존되어 감사 추적이 가능하다"는 서술은 금융권 감사 요건을 의식한 설계입니다.

Bull Board 접근 제어(§6.6)도 3중 방어입니다 — ADMIN 인증 미들웨어, AdminPermission 인가, 프로덕션 환경 노출 제한. "모든 Bull Board 접근은 감사 로그에 기록된다"까지 포함하여 금융권 컴플라이언스를 충족합니다.

그러나 **Redis에 저장되는 BullMQ Job 페이로드의 보안이 논의되지 않았습니다**. Job 데이터에는 `actorId`, `orgId`, `documentId` 등 민감 정보가 포함되는데, Redis 내 데이터 암호화(at-rest encryption)나 접근 제어에 대한 언급이 없습니다. 01-system-overview.md §2.2에서도 Redis는 "캐시, BullMQ 큐 백엔드, 세션" 역할로 기술되어 있지만 데이터 보호 수준은 논의되지 않았습니다.

Bull Board가 Job 페이로드를 UI에 노출한다고 인지하면서도, 접근 제어 이외의 보호(필드 마스킹, 민감 데이터 리덕션)는 고려되지 않았습니다. ADMIN 권한자라도 모든 페이로드의 모든 필드를 볼 필요는 없을 수 있습니다.

또한 `AsyncJobContext`의 `actorId`/`orgId` 값이 Job 생성 시 인증된 세션 컨텍스트에서 주입되는지, 아니면 호출자가 임의로 설정할 수 있는지에 대한 검증 절차가 명시되지 않았습니다.

#### RD-AR-04. 운영 용이성 — 75/100 양호

이 차원이 이 문서에서 가장 잘 작성된 영역입니다.

§6.6 DLQ 전략은 운영자 관점에서 필요한 것을 빠짐없이 다루고 있습니다:
- 큐별 DLQ 매핑 테이블
- BullMQ 실패 처리 정책 코드 예시 (지수 백오프 3회 → DLQ 이동)
- DLQ Job 스키마 (originalQueue, failedAt, lastError 등)
- 관리자 API 4종 (조회, 단건 재시도, 일괄 재시도, 영구 삭제)
- retry-all 부하 제어 (배치 크기, 딜레이, 큐 대기열 확인)
- DLQ 처리 흐름도 (Mermaid)

§6.8의 OpenTelemetry 메트릭도 구체적입니다. `bullmq.job.duration`, `bullmq.job.waiting_count`, `bullmq.dlq.size` 등 실제 대시보드 구성에 바로 사용할 수 있는 수준입니다. 알림 임계값(DLQ 적체, 큐 대기, Job 처리 시간)까지 정의되어 있습니다.

§6.7 Reconciliation 배치도 "기존 한계 → 개선 방안 → 점검 대상 → 중복 방지 → 실행 로그"까지 체계적입니다.

그러나 **Worker graceful shutdown 전략이 누락**되어 있습니다. Kubernetes 환경에서 Pod 종료 시(rolling update, scale-down) 진행 중인 Job을 어떻게 처리하는지 — BullMQ의 `gracefulShutdown` 옵션, SIGTERM 핸들링, Job 타임아웃과 Pod terminationGracePeriodSeconds의 관계 — 이 부분이 정의되지 않으면 배포 시 Job 유실이 발생할 수 있습니다.

**Redis 메모리 모니터링도 빠져 있습니다**. 01-system-overview.md §2.2에서 "Redis 단일 장애점(SPOF)"을 인식하고 있는데, BullMQ 큐 백엔드로서의 Redis 메모리 사용량 모니터링과 `maxmemory-policy` 설정이 §6.8 메트릭에 포함되어 있지 않습니다. Redis OOM 발생 시 모든 큐가 동시에 실패합니다.

#### RD-AR-05. 의사결정 추적성 — 60/100 양호

인라인 설계 근거가 일부 항목에서 잘 작성되어 있습니다:
- "왜 `parsing` 큐의 동시 처리 수가 2인가" — 메모리 부하, OOM 위험, SaaS 스케일아웃 가능성까지 설명
- "notification 큐와 EventBus의 2단계 패턴" — 소유권과 패턴 선택 근거
- "@Cron 기반이므로 다음 주기에 자동 재실행되어 별도 DLQ를 두지 않는다" — DLQ 불필요 근거
- `re-embedding` → `embedding` priority=3 통합 결정

그러나 **핵심 아키텍처 결정에 대한 ADR 참조가 전무합니다**. 01-system-overview.md §4에서 "ADR이 필요한 결정 사항" 목록에 비동기 처리 관련 항목이 없는 것 자체가 문제이지만, 이 문서에서도 다음 결정들의 근거가 부족합니다:

1. **Outbox 패턴 적용 범위**: `system_config.changed` 이벤트에만 Outbox를 적용하고 다른 EventBus 이벤트(`document.published`, `approval.approved` 등)에는 적용하지 않는 이유가 명시되지 않았습니다. `system_config.changed`는 "설정 캐시 무효화와 감사 로그 기록이 이벤트에 의존"이라고 했는데, `document.published`도 알림과 집계 캐시가 이벤트에 의존합니다. 왜 한쪽은 Outbox이고 다른 쪽은 아닌가에 대한 판단 근거가 필요합니다.

2. **DLQ 전략 선택**: 큐별 개별 DLQ vs 통합 DLQ, BullMQ 네이티브 실패 보존 vs 별도 DLQ 큐 이동 — 이 선택의 트레이드오프가 논의되지 않았습니다.

3. **이벤트 신뢰성 티어 경계**: 왜 ES 인덱싱은 Important(BullMQ)이고 감사 로그 기록은 Best-effort(EventBus)인가? 01-system-overview.md SP-4에서 "모든 변경 행위는 불변 감사 로그로 기록"이 핵심 원칙인데, 감사 로그 트리거가 Best-effort인 것은 긴장 관계가 있습니다.

---

### 전문 차원

#### EX-AR-SR-01. 의존성 방향 건전성 — 68/100 양호

이 문서의 의존성 방향은 대체로 레이어 원칙을 따릅니다. 도메인 모듈(DocumentModule, ApprovalModule, ParsingModule 등)이 인프라(BullMQ 큐)에 Job을 등록하고, Worker가 외부 서비스를 호출하는 구조는 깔끔합니다. EventBus도 도메인→인프라→소비 도메인 방향으로 흐릅니다.

02-module-architecture.md §3.3의 규칙 2("읽기 의존은 단방향 허용, 쓰기는 이벤트 디커플링")를 BullMQ 큐로 잘 구현하고 있습니다. 특히 Critical 티어(ApprovalModule → DocumentModule 직접 트랜잭션)와 Important 티어(BullMQ enqueue)의 분리가 §6.5 시퀀스 다이어그램에서 명확히 드러납니다.

그러나 **두 가지 교차 문서 정합성 문제**가 있습니다.

**첫째, §6.7 Reconciliation에서 deprecated된 `re-embedding` 큐를 참조합니다.** "벡터 수 불일치 → `re-embedding` 큐에 재등록"이라고 기술되어 있는데, §6.1에서 `re-embedding` 큐는 취소선 처리되어 "`embedding` 큐 priority=3으로 통합"이라고 명시되어 있습니다. 이 상태로 구현하면 Reconciliation 배치가 존재하지 않는 큐에 Job을 등록하려 시도하여 런타임 에러가 발생합니다. `embedding` 큐에 priority=3으로 등록하도록 수정해야 합니다.

**둘째, `search-events` 큐의 발행 모듈이 불명확합니다.** §6.1에 "검색 설정 변경·인덱스 재구성 이벤트 발행"으로 기술되어 있고, §6.6 DLQ 매핑, §6.9 Worker 스케일링에도 등장하지만, **어느 모듈이 이 큐에 Job을 넣는지** 이 문서에서 명시되지 않았습니다. 02-module-architecture.md §3.3.1 "C. 모듈별 인프라 의존 요약"에서도 SearchModule의 Redis/BullMQ 열이 비어 있어, SearchModule이 `search-events` 큐를 사용한다는 기록이 없습니다. 발행 모듈이 SearchModule인지 SystemConfigModule인지, 혹은 다른 모듈인지 확인이 필요합니다.

또한 §6.5 시퀀스 다이어그램에서 `AS->>DV: DocumentVersion 생성 (status=submitted)`, `AS->>BS: BlockSnapshot 생성`으로 ApprovalService가 직접 DocumentVersion과 BlockSnapshot을 생성하는 것처럼 표현되어 있는데, 02-module-architecture.md 기준으로 ApprovalModule은 `DocumentModule.transitionToPublished()`를 호출하는 것이지 DocumentVersion/BlockSnapshot 엔티티를 직접 조작하는 것이 아닙니다. 다이어그램의 정확도를 개선하면 의존 방향이 더 명확해질 것입니다.

#### EX-AR-SR-02. 과잉 설계 여부 — 70/100 양호

전반적으로 현재 요구사항 대비 적절한 복잡도를 유지하고 있습니다. BullMQ 큐를 관심사별로 분리한 것, 3티어 신뢰성 모델, DLQ + 관리자 API, Reconciliation 배치 — 이것들은 프로덕션 운영에 실제로 필요한 것들입니다. `re-embedding` → `embedding` priority=3 통합 결정은 불필요한 큐를 줄인 좋은 판단입니다.

그러나 **몇 가지 설계가 현재 컨텍스트(모듈러 모놀리스)와 맞지 않거나, 분류 체계와 모순**됩니다.

**이벤트 버전 관리 전략(§6.5)이 모듈러 모놀리스에서 필요한가**: "document.published.v2" 같은 버전 접미사, 신·구 이벤트 병행 발행, 전환 기간 — 이것은 마이크로서비스 환경에서 서비스별 독립 배포가 가능할 때 필요한 전략입니다. 01-system-overview.md SP-2에서 "NestJS 단일 애플리케이션"이라고 명시했고, 모든 발행자와 소비자가 동일 배포 단위에 있습니다. 스키마 변경 시 발행자와 소비자를 동시에 수정하고 한 번에 배포하면 됩니다. "추후 마이크로서비스 분리가 필요해질 때"를 대비한다면, 그때 도입해도 충분합니다.

**Outbox 패턴과 티어 분류의 모순**: `system_config.changed`는 Best-effort 티어(EventBus)로 분류되어 있으면서 동시에 Outbox 패턴을 적용합니다. Outbox 패턴의 목적은 "DB 트랜잭션과 이벤트 발행의 원자성 보장"입니다. 이것은 유실이 허용되지 않는다는 의미인데, Best-effort 티어의 정의는 "유실 시 무결성 무관"입니다. `system_config.changed`가 Outbox까지 필요할 정도라면 Important 티어로 승격하거나, Best-effort에서 Outbox를 사용하는 것의 의미를 재정의해야 합니다.

**DLQ 큐 개수(10+)의 타당성**: 12개 메인 큐 × DLQ = 22+ 큐를 Redis에서 관리합니다. BullMQ는 실패한 Job을 원본 큐 내에서 `failed` 상태로 보존하는 네이티브 기능이 있습니다. 별도 DLQ 큐로 이동시키는 패턴은 "원본 큐의 메트릭을 깨끗하게 유지"하는 이점이 있지만, 큐 수가 두 배로 늘어나는 운영 비용이 있습니다. 단일 `dead-letter` 큐에 `originalQueue` 필드로 출처를 태깅하는 방식도 검토해볼 만합니다 — DLQ 관리 API가 이미 `originalQueue` 필드를 사용하고 있으므로 전환 비용도 낮습니다.

---

## 핵심 지적사항 요약

| 우선순위 | 차원 | 이슈 | 대상 파일 | 변경 유형 | 영향/사유 | 조치 제안 |
|----------|------|------|-----------|-----------|-----------|-----------|
| P1 | EX-AR-SR-01 | §6.7 Reconciliation에서 deprecated된 `re-embedding` 큐를 참조 — 구현 시 런타임 에러 발생 | 05-async-event-architecture.md §6.7 점검 대상 테이블 | fix | 존재하지 않는 큐에 Job 등록 시도 → Reconciliation 배치 전체 실패 | "벡터 수 불일치" 행의 조치를 `embedding` 큐 priority=3으로 수정 |
| P1 | RD-AR-01 | `search-events` 큐의 발행 모듈이 05 문서에서 미명시, 02 문서에서도 SearchModule의 BullMQ 의존 미기재 | 05-async-event-architecture.md §6.1, 02-module-architecture.md §3.3.1 C표 | add | 구현자가 누가 이 큐에 Job을 넣는지 판단 불가 → 큐가 비어있거나 잘못된 모듈이 발행 | `search-events` 큐의 발행 모듈·트리거 시점·소비 처리를 05 문서에 추가하고, 02 문서 인프라 의존 테이블에 반영 |
| P2 | RD-AR-01 | `export` 큐의 파이프라인 흐름도 부재 — parsing/embedding 수준의 상세 없음 | 05-async-event-architecture.md | add | export 비동기 처리 흐름(Job 생산→변환→파일 저장→상태 갱신)이 추적 불가 | §6.2~6.3과 동일 수준의 export 파이프라인 흐름도 추가 |
| P2 | RD-AR-05, EX-AR-SR-02 | Outbox 패턴이 `system_config.changed`에만 적용되는 판단 근거 미기재 — Best-effort 티어 정의와 모순 | 05-async-event-architecture.md §6.5 Outbox 패턴 적용 대상 | decision | 티어 분류 체계의 신뢰성 저하 — "Best-effort인데 Outbox?"라는 의문에 답이 없음 | (a) `system_config.changed`를 Important 티어로 승격하거나, (b) Best-effort 내 Outbox 적용 기준을 명시하고 다른 이벤트에도 동일 기준 적용 여부 판단 |
| P2 | RD-AR-04 | Worker graceful shutdown 전략 미정의 — 배포 시 in-flight Job 처리 방안 부재 | 05-async-event-architecture.md §6.9 | add | Rolling update 시 진행 중 Job이 중단되면 BullMQ가 `stalled` 처리 → 재시도 or DLQ. terminationGracePeriodSeconds와 Job 타임아웃 불일치 시 데이터 손상 가능 | §6.9에 graceful shutdown 정책 추가: SIGTERM 수신 시 Worker.close() 호출, BullMQ `lockDuration` 설정, Pod terminationGracePeriodSeconds 권장값 |
| P2 | RD-AR-04 | Redis 메모리 모니터링 및 OOM 대응 전략 미정의 | 05-async-event-architecture.md §6.8 | add | Redis OOM 시 모든 BullMQ 큐 동시 실패 — 01-system-overview.md §2.2에서 SPOF로 인식했으나 메트릭에 미반영 | §6.8 메트릭에 `redis.memory.used_bytes`, `redis.memory.max_bytes` 추가. `maxmemory-policy` 설정 권장값(noeviction) 명시 |
| P2 | RD-AR-02 | 이벤트 페이로드 TypeScript 인터페이스 미정의 — 미비 사항에 인지되어 있으나 진화 기반 부재 | 05-async-event-architecture.md 미비 사항 | add | 스키마 진화 규칙(§6.5 이벤트 버전 관리)의 기준선이 없어 규칙 적용 불가 | 미비 사항의 "이벤트 페이로드 인터페이스" 항목을 우선 해소하여 각 이벤트/Job의 페이로드 인터페이스 정의 |
| P3 | EX-AR-SR-02 | 모듈러 모놀리스에서 이벤트 버전 관리(v2 접미사, 병행 발행) 전략이 조기 도입 — 동일 배포 단위에서는 불필요 | 05-async-event-architecture.md §6.5 이벤트 버전 관리 | decision | 구현 비용(버전 분기 로직, 병행 발행) 대비 현재 이익 없음. MSA 전환 시 도입해도 무방 | 현재는 "단일 배포 단위이므로 스키마 변경은 배포 단위로 조율"로 간소화하고, MSA 분리(SP-2) 시 이벤트 버전 관리를 ADR로 재결정하는 것을 권장 |
| P3 | EX-AR-SR-02 | DLQ별 개별 큐(10+)가 운영 복잡도 증가 — 단일 DLQ + origin 태그 방식 검토 가치 | 05-async-event-architecture.md §6.6 큐별 DLQ 매핑 | decision | 22+ 큐 관리. 현재 DLQ Job 스키마에 이미 `originalQueue` 필드가 있어 단일 DLQ 전환 시 API 호환 가능 | 단일 `dead-letter` 큐 + `originalQueue` 필드 기반 필터링 방식과 현재 방식의 트레이드오프를 비교하여 ADR로 결정 |
| P3 | RD-AR-03 | Bull Board에서 Job 페이로드 노출 시 민감 필드 마스킹 전략 부재 | 05-async-event-architecture.md §6.6 Bull Board 접근 제어 | add | ADMIN 권한 내에서도 최소 권한 원칙 미적용. 페이로드에 포함될 수 있는 사용자 ID, 문서 내용 등이 무차별 노출 | Bull Board 커스텀 어댑터에서 민감 필드(`actorId`, `orgId` 등) 마스킹 옵션 추가 검토 |
| P3 | EX-AR-SR-01 | §6.5 시퀀스 다이어그램에서 ApprovalService가 DocumentVersion/BlockSnapshot을 직접 조작하는 것처럼 표현 — 02 문서 기준 DocumentModule에 위임하는 구조 | 05-async-event-architecture.md §6.5 시퀀스 다이어그램 | fix | 다이어그램이 모듈 경계를 정확히 반영하지 않아 구현자가 혼동 가능 | 시퀀스 다이어그램에서 ApprovalService → DocumentModule.transitionToPublished() 호출로 수정하고, DocumentModule 내부에서 DocumentVersion/BlockSnapshot을 처리하도록 표현 |

---

## 설계 질문

| ID | 질문 | 블로킹 항목 |
|----|------|-------------|
| DQ-1 | `search-events` 큐의 발행 모듈은 무엇인가? SearchModule이 직접 발행하는가, SystemConfigModule에서 설정 변경 시 트리거하는가, 아니면 다른 모듈인가? | P1 #2 |
| DQ-2 | `system_config.changed` 이벤트에 Outbox 패턴을 적용하면서 Best-effort 티어로 분류한 의도는 무엇인가? 다른 EventBus 이벤트(`document.published` 등)에는 Outbox가 불필요한 판단 근거는? | P2 #2 |
| DQ-3 | 감사 로그 기록(`approval.approved` → LogEventModule)이 Best-effort 티어인데, SP-4("모든 변경 행위는 불변 감사 로그로 기록")와의 긴장 관계를 어떻게 해소하는가? EventBus 유실 시 감사 로그 누락이 허용되는 것인가? | — |
