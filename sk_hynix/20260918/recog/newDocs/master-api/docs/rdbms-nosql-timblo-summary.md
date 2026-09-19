# RDBMS와 NoSQL, 그리고 Timblo AI 회의록

> 발표용 요약 (상세 내용은 별첨 문서 참조)

---

## 1. RDBMS vs NoSQL

| | RDBMS | NoSQL |
|---|---|---|
| **주된 목적** | 정합성이 곧 요구사항인 데이터 | 형태와 규모가 계속 변하는 데이터 |
| 데이터 모델 | 테이블 + 외래키 관계 | 문서 / 키-값 / 컬럼 / 그래프 |
| 스키마 | 사전 정의 필수 | 유연 (필드 추가 자유) |
| 정합성 | ACID (강한 일관성) | BASE (결과적 일관성) |
| 확장 | 수직 확장(Scale-Up) | 수평 확장(Scale-Out) |
| 대표 용도 | 결제·권한·재고·집계 | 콘텐츠·로그·캐시·이벤트 |

**NoSQL 주요 모델 4종**

| 모델 | 대표 제품 | 용도 |
|---|---|---|
| 문서(Document) | **MongoDB** | 콘텐츠, 프로필 |
| 키-값(Key-Value) | Redis, DynamoDB | 캐시, 세션, 큐 |
| 컬럼(Wide-Column) | Cassandra, HBase | 시계열, 대량 로그 |
| 그래프(Graph) | Neo4j | 관계 추천, 경로 탐색 |

> **결론: 택일이 아니라 분담.** 현대 서비스는 둘을 나눠 쓰는 폴리글랏 퍼시스턴스가 일반적.

---

## 2. MariaDB와 MongoDB

| | **MariaDB** | **MongoDB** |
|---|---|---|
| 계열 | MySQL 포크, 오픈소스 RDBMS | 문서 지향 NoSQL 표준 |
| 저장 단위 | Row (테이블) | Document (BSON) |
| 관계 표현 | 외래키 조인 | 임베딩(중첩) |
| 배열 저장 | 별도 테이블 또는 JSON 컬럼 | 네이티브 배열 |
| 스키마 변경 | `ALTER TABLE` (비용 발생) | 필드 추가만 하면 끝 |
| 트랜잭션 | 기본 제공 | 4.0+ 지원 (레플리카셋 전제) |
| 집계 | SQL `GROUP BY` | Aggregation Pipeline |
| **강점** | 참조 무결성, 트랜잭션, 뷰(View) | 중첩 구조, 대용량 문서, 샤딩 |
| **적합 영역** | 회원·권한·공유·통계 | 전사 결과·AI 요약·노트 |

---

## 3. Timblo AI 회의록 적용 현황

**구조** — Prisma 하나로 두 DB를 동시 사용. 호출 비중 **MariaDB 226 : MongoDB 52**

```
Service → Model(BaseDatabase) → this.mariaDB  /  this.mongoDB
                                      └── 공용 키: contentId ──┘
```

### 데이터 분담

| **MariaDB — 관계와 권한** | **MongoDB — 가변 구조 본문** |
|---|---|
| `content` 회의록 메타데이터 | `transcribeResult` STT 전사 + AI 요약 |
| `contentShareUser` 공유 대상 | `file` 미디어 정보 |
| `member`/`workspace` 조직·권한 | `note`/`noteRevision` 노트와 버전 |
| `memo`/`contact`/`folder` | `highlight`/`bookmarks` |
| 통계·로그·STT 사전 | `template` 요약 템플릿 |

### 적용된 주요 기능

| MariaDB | MongoDB |
|---|---|
| 트랜잭션 `$transaction` — 다중 테이블 원자성 | 임베딩 배열 검색 `some` — 전사 본문 내 키워드 |
| 중첩 `select` — 조인을 필요 컬럼만 | Projection — 탭별 필요 필드만 조회 |
| **DB 뷰** `ContentWithUserProfiles` | **Mongo 뷰** `bookMarkedView` |
| Raw SQL — 조건부 집계(이용 통계, 공유 현황) | Upsert — STT 재실행 대응 |
| JSON 컬럼 `array_contains` — 해시태그 | 다중 문서 트랜잭션 — 노트 생성 |
| count + findMany 병렬 페이징 | 스키마리스 — 가변 깊이 템플릿 |

### 두 DB를 잇는 지점 ★

1. **공용 키** — `contentId`로 연결 (FK 아닌 앱이 보증)
2. **동시 생성** — 회의록 1건 = MariaDB `content` + MongoDB `file`
3. **병렬 조회** — `Promise.all`로 두 DB 동시 조회 후 앱에서 조합
4. **응답 조립** — 본문은 MongoDB, `meta`는 MariaDB
5. **2단계 검색** — 내용 검색은 MongoDB → 권한·페이징은 MariaDB

### 보조 저장소

**Redis** (캐시 · Bull 작업 큐) 포함 → 실제로는 **3계층 저장소**

---

## 정리

| 얻은 것 | 감수한 비용 |
|---|---|
| 권한·과금 정합성 보장 | 교차 DB 트랜잭션 불가 |
| AI 필드 추가 시 마이그레이션 불필요 | 참조 무결성을 코드가 책임 |
| 큰 전사 문서를 조인 없이 1회 읽기 | 이중 백업·모니터링 |
| 전사 데이터 증가를 샤딩으로 흡수 | 두 DB 조건 동시 쿼리 불가 |

> **"틀리면 안 되는 데이터는 MariaDB, 형태가 변하는 큰 데이터는 MongoDB"**
> — 이 원칙을 코드 레벨에서 일관되게 지키고 있음
