# RDBMS와 NoSQL — 개념 비교부터 Timblo AI 회의록 적용까지

> 작성 목적: 데이터베이스 선택 기준을 정리하고, Timblo AI 회의록(master-api)에서
> MariaDB와 MongoDB가 실제로 어떻게 나뉘어 쓰이는지 소스 기준으로 분석한다.

---

# 1부. RDBMS vs NoSQL

## 1-1. 한 장 요약

| 구분 | RDBMS | NoSQL |
|---|---|---|
| 데이터 모델 | 행과 열의 **테이블**, 관계는 외래키(FK) | 문서·키값·컬럼·그래프 등 **모델별로 다름** |
| 스키마 | 사전 정의 필수(Schema-on-Write) | 유연·동적(Schema-on-Read) |
| 질의 언어 | SQL 표준 | 제품별 고유 API/쿼리 |
| 정합성 모델 | **ACID** (강한 일관성) | **BASE** (결과적 일관성) 중심 |
| 확장 방식 | 수직 확장(Scale-Up) 우선 | 수평 확장(Scale-Out) 전제 |
| 조인 | DB가 처리 | 앱이 처리하거나 비정규화로 회피 |
| 잘 맞는 일 | 돈·권한·재고처럼 **틀리면 안 되는 데이터** | 로그·콘텐츠·이벤트처럼 **양이 많고 형태가 변하는 데이터** |

## 1-2. 주된 사용 목적

### RDBMS를 쓰는 이유
- **정합성이 곧 요구사항일 때** — 결제, 정산, 권한, 재고
- **관계가 데이터의 본질일 때** — 사용자↔조직↔권한↔공유처럼 N:M이 얽힌 구조
- **집계·리포트가 잦을 때** — `GROUP BY`, 윈도우 함수, 뷰(View)
- **트랜잭션 경계가 여러 테이블에 걸칠 때** — 전부 성공 아니면 전부 취소

### NoSQL을 쓰는 이유
- **스키마가 계속 변할 때** — 기능 추가마다 필드가 늘어나는 영역
- **한 덩어리로 읽고 쓰는 데이터일 때** — 조인 없이 문서 하나로 응답 완결
- **쓰기량·데이터량이 큰 폭으로 늘 때** — 샤딩 기반 수평 확장
- **중첩 구조가 자연스러울 때** — 배열 안의 객체, 가변 길이 리스트

## 1-3. NoSQL 주요 모델 4종

| 모델 | 저장 형태 | 대표 제품 | 대표 용도 |
|---|---|---|---|
| **문서(Document)** | JSON/BSON 문서 | MongoDB, CouchDB | 콘텐츠, 프로필, 카탈로그 |
| **키-값(Key-Value)** | key → value | Redis, DynamoDB | 캐시, 세션, 큐, 순위표 |
| **컬럼 패밀리(Wide-Column)** | 행 키 + 동적 컬럼 | Cassandra, HBase | 시계열, 대량 로그 |
| **그래프(Graph)** | 노드 + 간선 | Neo4j, Neptune | 관계 추천, 경로 탐색, 이상거래 탐지 |

> 참고: 검색 엔진(Elasticsearch), 시계열 DB(InfluxDB), 벡터 DB(Pinecone, Milvus)도
> 넓게는 NoSQL 계열로 묶인다. 특히 벡터 DB는 AI 서비스에서 비중이 커지는 중이다.

## 1-4. 선택의 기준 — "무엇이 맞나"가 아니라 "무엇을 지킬 것인가"

```
정합성을 지켜야 한다  →  RDBMS
형태와 규모가 변한다  →  NoSQL
둘 다 필요하다        →  폴리글랏 퍼시스턴스 (둘을 나눠 쓴다)
```

현대 서비스에서는 **택일보다 분담**이 일반적이다.
Timblo AI 회의록도 이 세 번째 길을 택했다.

---

# 2부. MariaDB와 MongoDB

## 2-1. MariaDB

MySQL에서 갈라져 나온 오픈소스 RDBMS. MySQL과 높은 호환성을 유지하면서
스토리지 엔진 선택지와 라이선스 자유도를 넓힌 것이 특징이다.

| 항목 | 내용 |
|---|---|
| 계열 | MySQL 포크, 완전 오픈소스(GPL) |
| 기본 엔진 | InnoDB (행 단위 잠금, 외래키, 크래시 복구) |
| 강점 | ACID 트랜잭션, 외래키 제약, 뷰(View), 성숙한 SQL 생태계 |
| 확장 | 복제(Replication), Galera Cluster(동기 다중 마스터), MaxScale |
| 부가 기능 | JSON 컬럼 타입, 가상 컬럼, 시스템 버전 테이블 |
| 적합 영역 | 회원·권한·공유·과금·집계 |

**핵심 개념**
- **정규화** — 중복을 제거해 갱신 이상(Anomaly)을 막는다
- **외래키 + CASCADE** — 부모가 지워지면 자식도 정리, 참조 무결성을 DB가 보증
- **트랜잭션** — 여러 테이블 변경을 하나의 단위로 묶는다
- **뷰(View)** — 반복되는 조인을 미리 정의해 조회를 단순화

## 2-2. MongoDB

문서 지향 NoSQL의 사실상 표준. BSON 문서를 컬렉션에 저장하며,
중첩 배열과 객체를 그대로 담을 수 있다.

| 항목 | 내용 |
|---|---|
| 데이터 단위 | Document(BSON) → Collection → Database |
| 스키마 | 유연. 문서마다 필드가 달라도 됨 (스키마 검증은 선택) |
| 강점 | 중첩 구조 저장, 대용량 문서 처리, 수평 확장(샤딩) |
| 질의 | 필드 조건, 배열 요소 조건(`$elemMatch`), Aggregation Pipeline |
| 트랜잭션 | 4.0부터 다중 문서 트랜잭션 지원 (**레플리카셋 구성 필요**) |
| 부가 기능 | 인덱스(복합·텍스트·부분), View, Change Stream, TTL 인덱스 |
| 적합 영역 | 전사 결과, AI 요약, 노트, 템플릿 등 가변 구조 본문 |

**핵심 개념**
- **임베딩 vs 참조** — 같이 읽으면 임베딩, 따로 크면 참조
- **비정규화** — 조인 대신 중복을 허용해 읽기 1회로 끝낸다
- **Aggregation Pipeline** — `$match → $group → $project` 단계형 집계
- **16MB 문서 제한** — 무한히 키우면 안 되는 실질적 설계 제약

## 2-3. 나란히 비교

| 기준 | MariaDB | MongoDB |
|---|---|---|
| 한 건의 단위 | Row | Document |
| 관계 표현 | 외래키 조인 | 임베딩 또는 앱 조인 |
| 스키마 변경 | `ALTER TABLE` (비용 있음) | 필드 추가만 하면 끝 |
| 배열 저장 | 별도 테이블 또는 JSON 컬럼 | 네이티브 배열 |
| 트랜잭션 | 기본 제공 | 레플리카셋 전제 |
| 집계 | SQL `GROUP BY` | Aggregation Pipeline |
| 확장 | 수직 + 복제 | 수평 샤딩 |

---

# 3부. Timblo AI 회의록 소스 분석

> 분석 대상: `master-api` (Node.js + Express)
> ORM: **Prisma** (`@timbel-timblo-onpremise/prisma`) — 하나의 BaseDatabase 클래스가
> `this.mariaDB`와 `this.mongoDB` 두 클라이언트를 함께 노출한다.

## 3-1. 전체 아키텍처

```
                  ┌──────────────────────────┐
                  │   Service Layer          │
                  │   (비즈니스 로직 / 조합)  │
                  └────────────┬─────────────┘
                               │
                  ┌────────────▼─────────────┐
                  │   Model Layer            │
                  │   extends BaseDatabase   │
                  └──────┬────────────┬──────┘
                         │            │
              this.mariaDB          this.mongoDB
                         │            │
              ┌──────────▼───┐   ┌────▼──────────┐
              │   MariaDB    │   │   MongoDB     │
              │  관계·권한·  │   │  전사·요약·   │
              │  메타데이터  │   │  노트·본문    │
              └──────────────┘   └───────────────┘
                         │            │
                    공용 키: contentId
```

모든 모델 클래스(`src/models/*.model.js`, 28개)가 동일한 `BaseDatabase`를 상속받아
두 DB를 한 객체에서 다룬다. 호출 비중은 **MariaDB 226회 : MongoDB 52회**.

## 3-2. 데이터 분담표

### MariaDB — "관계와 권한"
| 엔티티 | 역할 |
|---|---|
| `content` | 회의록 메타데이터(제목, 시간, 상태, 소유자) — **최다 사용(40회)** |
| `contentShareUser` | 회의록 공유 대상자 (N:M) |
| `member`, `user`, `userProfile`, `workspace` | 조직·계정·프로필 |
| `folder`, `inbox`, `inboxContent` | 폴더 트리, 수신함 |
| `memo`, `memoComment` | 메모와 댓글 (대댓글 관계) |
| `contact`, `contactLabel`, `labelOnContact` | 주소록과 라벨 (N:M) |
| `calendar`, `calendarIntegrate`, `calendarIntegrateSync` | 외부 캘린더 연동 |
| `contentCapture`, `downloadHistory`, `usage` | 활동 로그·통계 |
| `lifecycleTask`, `lifecyclePolicyExecutionLog` | 보존정책 자동 실행 |
| `corpus`, `keywordBoosting`, `correction`, `transcribeEngine` | STT 정확도 향상 사전 |
| `chatbot`, `chatMessage`, `chatCitation` | AI 챗봇 대화 이력 |
| `contentWithUserProfiles` | **DB 뷰** — content + 프로필 조인 결과 |

### MongoDB — "가변 구조 본문"
| 컬렉션 | 역할 |
|---|---|
| `transcribeResult` | STT 결과 전체 — **최다 사용(15회)** |
| `file` | 미디어 파일 정보, `contentId`로 MariaDB와 연결 |
| `highlight` | 사용자 하이라이트(문단 좌표 기반) |
| `bookmarks` | 구간 북마크 |
| `note`, `noteRevision` | 나만의 노트와 버전 이력 |
| `template` | 회의록 요약 템플릿(중첩 모듈 구조) |
| `bookMarkedView` | **Mongo View** — 북마크 조회 전용 |

### 왜 이렇게 나눴는가 — `transcribeResult` 문서 구조가 답이다

```js
transcribeResult {
  status, clientLanguage, engine, ticket, summarySize,
  segments:       [ { segmentId, text, start, end, speaker, ... } ],  // 수천 건
  mergedSegments: [ { index, text, ... } ],                           // 화자 병합본
  speakerInfo:    [ { name, displayName, ... } ],                     // 참석자
  aiResult:       { title, topics, keywords, summary, issues, tasks },// AI 요약
  summaryTime:    [ { index, topic, summary, issues, tasks } ]        // 주제별 요약
}
```

1시간 회의면 세그먼트가 수천 개다. RDBMS라면 별도 테이블에 수천 행 + 조인이지만,
MongoDB에서는 **문서 하나를 읽으면 화면 하나가 완성된다**.
게다가 AI 기능이 추가될 때마다 `aiResult` 하위 필드가 늘어나는데,
스키마 마이그레이션 없이 대응할 수 있다.

## 3-3. 적용된 주요 기능 — MariaDB

### ① 트랜잭션 (`$transaction`)
`src/models/contact.model.js`, `user.model.js`, `calendar.model.js`에서 사용.
주소록 등록처럼 **여러 테이블을 동시에 바꿔야 하는 작업**을 원자적으로 처리한다.

```js
return await this.mariaDB.$transaction(async tx => {
    // 연락처 생성 + 라벨 연결을 하나의 단위로
});
```

### ② 관계형 조회 — 중첩 `select`로 조인 대체
```js
// src/models/memo.model.js — 메모 → 작성자 → 사용자 → 프로필 3단 조인
select: {
  creator: { select: { user: { select: { profile: {
      select: { pid: true, name: true, nickName: true }
  }}}}},
  comments: { select: { ... } }   // 댓글까지 한 번에
}
```
Prisma의 중첩 select가 SQL JOIN으로 번역된다. 필요한 컬럼만 골라 오버페칭을 막는다.

### ③ 데이터베이스 뷰 — `ContentWithUserProfiles`
회의록 목록/검색은 항상 "콘텐츠 + 작성자 프로필"이 함께 필요하다.
매번 조인하는 대신 **뷰로 고정**해 조회 코드를 단순화했다.
검색·통계 양쪽에서 이 뷰를 재사용한다.

### ④ Raw SQL — 복잡한 집계
Prisma 문법으로 표현하기 어려운 조건부 집계는 `$queryRaw`로 내려간다.

```sql
-- src/models/content.model.js : 사용자 이용 통계
SELECT COUNT(*) as total,
       COUNT(CASE WHEN isRecord = 1 THEN 1 END) as record,
       COALESCE(SUM(CASE WHEN isRecord = 1 THEN duration ELSE 0 END), 0) as recordDuration,
       DATE(createAt) as date
FROM ContentWithUserProfiles
WHERE creatorPID = ? AND transcribeStatus = 'DONE'
GROUP BY DATE(createAt), isRecord
```
```sql
-- src/models/contentCapture.model.js : 공유 in/out 동시 집계 (쿼리 1회로 처리)
SELECT COUNT(CASE WHEN shareEmail = ? THEN 1 END) as incomingCount,
       COUNT(CASE WHEN creatorId  = ? THEN 1 END) as outgoingCount
FROM ContentCapture WHERE captureType = 'SHARE' ...
```

### ⑤ JSON 컬럼 활용 — `array_contains`
해시태그는 관계 테이블 대신 **MariaDB의 JSON 컬럼**에 배열로 저장한다.
RDBMS 안에서 NoSQL식 유연성을 부분적으로 빌려온 사례.

```js
// src/models/search.model.js
hashTag: { OR: [ { hashTag:   { array_contains: keyword } },
                 { manualTag: { array_contains: keyword } } ] }
```

### ⑥ 페이지네이션 + 카운트 병렬화
```js
const [_count, pagedContents] = await Promise.all([
    this.mariaDB.contentWithUserProfiles.count({ where }),
    this.mariaDB.contentWithUserProfiles.findMany({ where, take, skip, orderBy })
]);
```
총 개수와 현재 페이지를 **동시에** 조회해 응답 지연을 줄인다.

## 3-4. 적용된 주요 기능 — MongoDB

### ① 임베딩 문서 + 배열 요소 검색 (`some`)
배열 안 객체를 조건으로 거는, 문서 DB의 대표 기능.

```js
// 전사 본문에서 키워드 검색 — src/models/search.model.js
where: { transcribeResult: { mergedSegments: { some: { text: { contains: keyword } } } } }

// 참석자 이름으로 검색 (displayName 우선, 없으면 name)
where: { transcribeResult: { speakerInfo: { some: {
    OR: [ { AND: [{ displayName: { not: null } }, { displayName: { contains: attendee } }] },
          { AND: [{ displayName: null },          { name:        { contains: attendee } }] } ]
}}}}
```
RDBMS였다면 세그먼트 테이블을 조인해 LIKE 스캔해야 할 일을,
문서 안에서 바로 해결한다.

### ② 부분 조회(Projection)로 응답 최적화
전사 결과 문서는 매우 크다. 그래서 **탭 단위로 필요한 필드만** 골라 읽는다.

```js
// src/models/content.model.js : getTranscribeResult(fileId, tabs)
const select = { status: true, clientLanguage: true, summarySize: true };
tabs.forEach(tab => {
    switch (tab) {
        case 'aiResult':    select.aiResult = true; select.speakerInfo = true; break;
        case 'summaryTime': select.summaryTime = true; break;
        case 'segments':    select.mergedSegments = true; select.segments = true; break;
    }
});
```
요약 탭만 보는 사용자에게 수천 개 세그먼트를 내려보내지 않는다.

### ③ Upsert — STT 재실행 대응
`fileId`가 unique라 재실행 시 create가 충돌한다. 있으면 갱신, 없으면 생성.

```js
// src/models/transcribeResult.model.js
await this.mongoDB.transcribeResult.upsert({
    where:  { fileId },
    update: data,
    create: { file: { connect: { id: fileId } }, ...data }
});
```

### ④ 다중 문서 트랜잭션 — 노트 생성
노트 생성과 파일의 노트 링크 갱신을 하나로 묶는다.
MongoDB 4.0+ 레플리카셋 구성이 전제되어야 동작하는 기능.

```js
// src/models/note.model.js
return await this.mongoDB.$transaction(async tx => {
    const newNote = await tx.note.create({ data: { contentId, noteName, content } });
    await tx.file.update({ where: { id: fileId }, data: { linkNoteId: newNote.id } });
    return newNote;
});
```

### ⑤ 문서 버전 관리 — 노트 리비전
`note`에 `revisions` 배열을 두고 `version desc` + `take: 1`로 최신본만 가져온다.
버전 이력을 관계 테이블 없이 문서 구조로 처리한 사례.

### ⑥ 중첩 객체 정확 매칭 — 하이라이트 좌표
하이라이트는 `{ key, idx, sub }` 복합 좌표로 위치를 특정한다.

```js
// src/models/highlight.model.js
category: { equals: { key, idx: Number(idx), sub } },   // 객체 전체 일치
category: { is:    { key: 'mergedSegments', idx: { in: indexes } } },  // 부분 조건
category: { isNot: { key: 'mergedSegments' } }          // 부정 조건
```
`equals` / `is` / `isNot` — 임베디드 문서 전용 연산자를 모두 활용한다.

### ⑦ MongoDB View — `bookMarkedView`
북마크와 원본 데이터를 결합한 조회 전용 뷰.
읽기 경로를 단순화하는 목적은 MariaDB의 `ContentWithUserProfiles`와 동일하다.

### ⑧ 템플릿 — 스키마리스의 진가
회의록 템플릿은 `[{ index, moduleKey, items: [{ index, type, value }] }]` 형태의
**가변 깊이 중첩 배열**이다. 모듈 개수와 종류가 워크스페이스마다 다르다.
RDBMS로 정규화하면 테이블 3개가 필요하지만, 문서 하나면 끝난다.

## 3-5. 두 DB를 잇는 지점 — 여기가 이 아키텍처의 핵심

### ① 공용 키 `contentId`
MariaDB의 `content.contentId`와 MongoDB의 `file.contentId`가 같은 값을 갖는다.
FK 제약이 아니라 **애플리케이션이 보증하는 논리적 키**다.

### ② 동시 생성 — 회의록 1건 = 2 DB 기록
```js
// src/models/content.model.js
const content = await this.mariaDB.content.create({ data: { title, type, creator, workspace, ... } });
const file    = await this.mongoDB.file.create({ data: { contentId: content.contentId, fileKey, ... } });
return { content, file };
```

### ③ 병렬 조회 후 앱 레벨 조인
```js
// src/services/content/content.service.js
let [mongoDBcontent, mariaDBContent, bookmarks] = await Promise.all([
    this.contentModel.getTranscribeResultByContentId(contentId, selectFields, includeFields), // Mongo
    this.contentModel.findContentById(contentId),                                             // Maria
    this.bookmarkModel.getBookmarksByContentId(contentId)                                      // Mongo View
]);
```
순차 호출이 아닌 **병렬**이라, 응답 시간은 둘 중 느린 쪽 하나로 수렴한다.

### ④ 응답 조립 규칙
```js
// src/services/content/contentDetail.service.js
const createResponseDataForSegments = (mongoDBcontent, mariaDBContent) => {
    const { clientLanguage, ...restMongoDBContent } = mongoDBcontent;
    const metaFromMaria = pick(mariaDBContent, allowedKeys);   // 허용 필드만 화이트리스트 통과
    const meta = { clientLanguage, ...metaFromMaria };
    return { ...restMongoDBContent, meta };                    // 본문은 Mongo, meta는 Maria
};
```
**본문은 MongoDB, `meta`는 MariaDB** — 응답 구조에 두 DB의 역할 분담이 그대로 드러난다.

### ⑤ 2단계 통합 검색 — 두 DB를 순차로 거치는 흐름
```
1) MongoDB: 전사 본문/참석자에서 키워드 매칭 → contentId 목록 확보
       searchContentDetail() / searchContentByAttendee()
                    ↓
2) contentIds 병합 (Set으로 중복 제거)
                    ↓
3) MariaDB: 해당 contentId들에 권한·기간·정렬·페이징 적용
       contentWithUserProfiles 뷰로 count + findMany 병렬 조회
```
**"내용 검색은 MongoDB, 권한과 페이징은 MariaDB"** — 각자 잘하는 일만 맡긴 구조다.
(`src/services/system/search.service.js:62~74`)

## 3-6. 보조 저장소 — Redis

캐시·큐 계층으로 Redis도 함께 쓴다. (`src/utils/redis/`)
- `redis` 클라이언트 — 일반 캐시
- `ioredis`의 `Redis.Cluster` — 클러스터 구성
- `bull` / `bullmq` — STT·요약 등 **비동기 작업 큐**

즉 이 서비스는 실제로는 **3계층 저장소**다.

| 저장소 | 성격 | 담당 |
|---|---|---|
| MariaDB | RDBMS | 관계·권한·정합성 |
| MongoDB | 문서 NoSQL | 전사·요약·노트 본문 |
| Redis | 키-값 NoSQL | 캐시·작업 큐 |

---

# 4부. 정리

## 4-1. 이 아키텍처가 주는 것

| 항목 | 효과 |
|---|---|
| 정합성 | 권한·공유·과금은 MariaDB 트랜잭션과 FK가 보증 |
| 유연성 | AI 요약 필드가 늘어도 MongoDB는 마이그레이션 불필요 |
| 성능 | 큰 전사 문서를 조인 없이 1회 읽기로 처리, projection으로 전송량 절감 |
| 확장성 | 전사 데이터 증가는 MongoDB 샤딩으로 흡수, 관계 데이터는 영향 없음 |
| 개발 편의 | Prisma 단일 인터페이스로 두 DB를 같은 문법으로 다룸 |

## 4-2. 감수한 비용

| 항목 | 내용 |
|---|---|
| 교차 DB 트랜잭션 부재 | MariaDB `content` 생성 성공 + MongoDB `file` 생성 실패 시 정합성 깨짐 → 앱 레벨 보정 필요 |
| 참조 무결성 | `contentId` 연결은 DB가 아니라 코드가 지킨다 |
| 운영 부담 | 이중 백업·이중 모니터링·이중 장애 대응 |
| 조인 불가 | "MariaDB 조건 + MongoDB 조건"을 한 쿼리로 못 푼다 → 2단계 검색으로 우회 |

## 4-3. 결론

> RDBMS와 NoSQL은 대체재가 아니라 **역할이 다른 도구**다.
> Timblo AI 회의록은 **"틀리면 안 되는 데이터는 MariaDB, 형태가 변하는 큰 데이터는 MongoDB"**
> 라는 원칙을 코드 레벨에서 일관되게 지키고 있으며,
> 그 접합부를 `contentId`와 `Promise.all` 병렬 조회로 설계했다.

---

## 부록. 소스 참조 위치

| 주제 | 파일 |
|---|---|
| 두 DB 동시 생성 | `src/models/content.model.js` |
| 병렬 조회 후 조합 | `src/services/content/content.service.js` |
| 응답 조립 규칙 | `src/services/content/contentDetail.service.js` |
| 2단계 통합 검색 | `src/services/system/search.service.js`, `src/models/search.model.js` |
| MongoDB 트랜잭션 | `src/models/note.model.js` |
| MariaDB 트랜잭션 | `src/models/contact.model.js`, `user.model.js` |
| Raw SQL 집계 | `src/models/contentCapture.model.js`, `content.model.js` |
| Upsert / 전사 결과 | `src/models/transcribeResult.model.js` |
| 임베디드 문서 연산 | `src/models/highlight.model.js` |
| 스키마리스 템플릿 | `src/models/template.model.js` |
| Redis · 큐 | `src/utils/redis/` |
