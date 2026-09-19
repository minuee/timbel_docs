# MongoDB + Express 웹페이지 10초 로딩 트러블슈팅

> 상황: Node/Express 백엔드 + MongoDB. 데이터량 적음, 사용자 소수. 그럼에도 초기 로딩 10초.

---

## 0. 결론 먼저

데이터가 적고 동시 사용자도 없는데 10초가 걸린다면 **부하 문제가 아니라 구조 문제**다.
회의에서 나온 "데이터가 많아져서", "CPU 0.5코어라서"는 이 조건에서 주범이 되기 어렵다.
단, 감으로 반박하지 말고 **숫자 3개**로 정리해서 가져갈 것.

| 지표 | 확인 위치 |
|---|---|
| TTFB (서버 응답 대기 시간) | Chrome DevTools → Network → Timing |
| 실제 쿼리 소요 시간 | 서버 로그 (`console.time`) |
| `totalDocsExamined` | `explain("executionStats")` |

이 세 값이 어긋나는 지점이 곧 원인이다.

---

## 1. 병목 위치부터 특정

가장 먼저 할 일. 쿼리 시간과 전체 응답 시간을 분리해서 잰다.

```js
console.time('query');
const result = await Model.find({ ... });
console.timeEnd('query');
```

| 결과 | 해석 |
|---|---|
| 쿼리 9초 + 나머지 1초 | DB/데이터량 문제 |
| 쿼리 0.3초 + 나머지 9초 | 백엔드 코드 또는 인프라 문제 |

쿼리가 빠른데 응답이 느리면 원인은 커넥션·직렬화·데이터 크기·이벤트 루프 쪽이다.

---

## 2. Chrome DevTools 분석

### 기본 절차
1. `F12` → **Network** 탭
2. `Disable cache` 체크
3. `Ctrl + Shift + R` 로 강제 새로고침
4. 상단 필터에서 **Fetch/XHR** 선택
5. 문제의 요청 클릭 → **Timing** 탭

### Timing 항목별 해석

| 항목이 길다면 | 의미 | 대응 |
|---|---|---|
| **Waiting for server response (TTFB)** | 서버/DB 문제 | 쿼리, 인덱스, 커넥션 재사용 점검 |
| **Content Download** | 응답 데이터가 너무 큼 | projection, 페이지네이션 |
| **Queueing / Stalled** | 동시 요청 과다 (도메인당 6개 제한) | 요청 수 줄이기, 번들링 |

### Waterfall 모양 읽기
- 막대가 **계단식**으로 밀려 있음 → 순차 호출. `await`를 연달아 쓴 것. → `Promise.all()`로 묶기
- 막대가 **겹쳐** 있음 → 병렬은 되고 있음. 개별 요청 자체가 느린 것

### API는 빠른데 화면이 늦게 뜨는 경우
**Performance** 탭 → 녹화 후 새로고침 → Main 스레드에 노란색(Scripting) 블록이 길게 깔려 있으면 렌더링 병목.
수천 개 항목을 한 번에 그리는 경우라면 가상 스크롤 또는 페이지네이션.

---

## 3. DB 측 진단 — 슬로우 쿼리 → explain

### 3-1. 슬로우 쿼리 잡기

Atlas: Performance Advisor / Profiler 탭에서 바로 확인 가능.

자체 호스팅:
```js
db.setProfilingLevel(1, { slowms: 100 })   // 100ms 초과 쿼리 기록
db.system.profile.find().sort({ millis: -1 }).limit(10)
```

확인할 필드: `millis`, `docsExamined`, `nreturned`, `planSummary`

### 3-2. explain으로 원인 확인

```js
db.컬렉션.find({ 조건 }).sort({ 필드: -1 }).explain("executionStats")
```

핵심 지표 3가지:

| 지표 | 정상 | 문제 |
|---|---|---|
| `stage` | `IXSCAN` (인덱스 사용) | `COLLSCAN` (전체 스캔 = 인덱스 없음) |
| `totalDocsExamined` vs `nReturned` | 두 값이 비슷 | 10건 뽑으려고 50만 건 훑음 |
| `SORT` 스테이지 | 없음 | 존재 시 메모리 정렬 중 (32MB 초과 시 에러) |

### 3-3. 인덱스 설계 주의점
- `find` 조건과 `sort`를 **합쳐서** 복합 인덱스로 생성
- 필드 순서 정석: **등호 조건 → 정렬 → 범위 조건**
- explain이 빨라도 안심 금지. 쿼리 50ms인데 응답 10초면 원인은 다른 곳

---

## 4. 백엔드(Express) 측 원인 — 발생 빈도순

### 4-1. 반복문 안의 await (N+1) — 압도적 1위
```js
// 나쁜 예: 500명이면 쿼리 500번
for (const u of users) {
  u.posts = await Post.find({ userId: u._id });
}
```
각 쿼리가 20ms여도 500번이면 10초.

**대응:** `Promise.all`로 묶기 / `$in`으로 한 번에 가져와 메모리에서 매핑 / `$lookup`

> 이 경우 CPU를 늘려도 해결되지 않는다.

### 4-2. 커넥션 풀 고갈 / 재수립
- 요청마다 `mongoose.connect()` 또는 `new MongoClient()` 호출 → 매번 핸드셰이크 발생
- 연결은 **앱 부팅 시 딱 한 번만**
- 서버리스(Vercel, Lambda, Next.js API routes)라면 전역 캐싱 필수
- Mongoose 기본 `maxPoolSize`는 100

### 4-3. 이벤트 루프 블로킹
Node는 싱글 스레드 → 동기 작업 하나가 전체를 멈춤.
- 수만 건 데이터를 `JSON.stringify`, `sort()`, `map()`으로 후처리
- `JSON.parse/stringify`로 깊은 복사하는 코드는 특히 의심

### 4-4. Mongoose 하이드레이션 비용
문서 수천 건 조회 시 전부 Document 객체로 변환하는 비용이 큼.
읽기 전용이면 `.lean()` 하나로 몇 배 개선되는 경우 많음.

### 4-5. 진단용 미들웨어
```js
app.use((req, res, next) => {
  const t = Date.now();
  res.on('finish', () => console.log(req.path, Date.now() - t, 'ms'));
  next();
});
```
핸들러 안에서는 `console.time`을 **쿼리 전후 / 가공 전후**로 나눠 찍으면 어디서 시간이 새는지 즉시 파악 가능.

이벤트 루프 지연 자체 측정:
```bash
npx clinic doctor -- node app.js
```

---

## 5. 데이터 조회량 줄이기

- `.limit()` + **커서 기반 페이지네이션** (`_id > lastId` 방식이 `skip`보다 훨씬 빠름)
- `.select('필요한 필드만')` — projection
- Mongoose면 `.lean()`

---

## 6. 인프라 / 환경 요인

### Atlas 무료 티어(M0)
공유 인스턴스라 기본적으로 느림.

### 리전 거리
DB 리전과 서버 리전이 다르면 왕복 지연만으로 수 초 발생.
서버는 한국인데 Atlas가 미국 리전 → 왕복 1회 200ms → 50회면 10초.

**측정 방법:**
```js
db.adminCommand({ ping: 1 })
```
데이터 조회가 아닌 순수 왕복 지연만 측정. 200~300ms 나오면 리전 문제 확정.

### CPU 0.5코어
- Node는 싱글 스레드라 CPU 바운드 구간에서 그대로 2배 느려짐
- 스로틀링 걸리면 응답 시간이 튀는 패턴 발생
- **다만 주범인지 증폭기인지는 별개 문제**

**검증 방법:** 요청 중 컨테이너 CPU 사용률이 100%(0.5코어 기준)에 붙는지, throttled 지표가 오르는지 확인.
k8s라면 `container_cpu_cfs_throttled_seconds_total`
→ CPU가 20%에서 놀고 있는데 10초 걸린다면 그 자리에서 반박 가능.

### HCP (아키텍처 다이어그램상 요소)
일반 용어가 아니라 **브랜드명**. 가장 흔한 건 **HashiCorp Cloud Platform**.

| 구성요소 | 역할 |
|---|---|
| HCP Vault | MongoDB 접속 URI·비밀번호 등 시크릿 관리 |
| HCP Consul | 서비스 디스커버리, 네트워크 연결 관리 |

**성능 연관성:** 요청마다 Vault에서 시크릿을 새로 조회하면 그 자체가 왕복 지연이 됨.
→ 시크릿은 앱 시작 시 한 번만 받아서 캐싱.

> 문맥에 따라 SAP HANA Cloud Platform(구 명칭), Huawei Cloud Platform, 사내 자체 약어(Hybrid Cloud Platform 등)일 가능성도 있음.

---

## 7. 오해 정리 — "NoSQL이 RDBMS보다 조회가 빠르다"

**사실이 아니다.** NoSQL이라서 빠른 게 아니라, 특정 접근 패턴에서만 빠르다.

### MongoDB가 유리한 경우
- 한 문서에 관련 데이터를 임베딩해서 JOIN 없이 한 번에 읽을 때
- 단순 키 조회, 스키마가 자주 바뀌는 데이터
- 수평 확장(샤딩)이 필요한 대규모 트래픽

### RDBMS가 유리하거나 대등한 경우
- 정규화된 데이터의 복잡한 조인·집계 (PostgreSQL/MySQL 옵티마이저가 `$lookup`보다 우수)
- 트랜잭션이 잦은 업무
- **인덱스만 제대로 걸려 있으면 단건 조회 속도는 둘 다 비슷** (둘 다 B-tree 인덱스 사용)

### 핵심
> 조회 속도를 결정하는 건 DB 종류가 아니라 **인덱스 유무, 데이터 모델링, 네트워크 거리**다.
> 인덱스 없는 MongoDB는 인덱스 있는 MySQL보다 100배 느리다.

---

## 8. 5분 안에 원인 좁히는 테스트

### 테스트 A — 연속 새로고침 3회

| 결과 | 원인 |
|---|---|
| 첫 번째만 10초, 이후 빠름 | 콜드 스타트 또는 커넥션 초기화 → **데이터·CPU 문제 아님 확정** |
| 매번 10초 | 요청마다 반복되는 비용 → N+1 또는 커넥션 재수립 |

### 테스트 B — ping 왕복 지연 측정
```js
db.adminCommand({ ping: 1 })
```
200~300ms 이상이면 리전 문제 확정.

---

## 9. 체크리스트

- [ ] DevTools Network → TTFB / Content Download / Queueing 중 어디가 긴지 확인
- [ ] Waterfall이 계단식인지 확인 (순차 await 여부)
- [ ] 서버 로그로 쿼리 시간 vs 전체 응답 시간 분리 측정
- [ ] `explain("executionStats")` → `COLLSCAN` 여부, `totalDocsExamined` 확인
- [ ] 라우트 핸들러에 반복문 안 `await` 있는지 확인
- [ ] `mongoose.connect()`가 요청마다 호출되지 않는지 확인
- [ ] 읽기 전용 쿼리에 `.lean()` 적용 여부
- [ ] `db.adminCommand({ping:1})` 왕복 지연 측정
- [ ] 연속 새로고침 3회 테스트
- [ ] 컨테이너 CPU 사용률 / throttling 지표 확인
- [ ] 시크릿 조회(Vault 등)가 요청마다 발생하는지 확인

---

## 10. 데이터가 적은데도 10초인 경우 — 유력 원인 요약

1. **매 요청마다 새 커넥션 수립** — 데이터량과 무관한 고정 비용. 데이터가 적어도 느린 게 오히려 이쪽 증거
2. **N+1 반복 쿼리** — 데이터가 적어도 왕복 횟수가 많으면 느림
3. **DB와 서버의 물리적 거리** — 리전 불일치
4. **콜드 스타트** — 사용자가 적다 = 요청이 뜸하다 → 인스턴스가 잠들었다 깨어나는 시간

> "데이터가 많아져서 느리다"는 진단이 아니라 증상 설명에 가깝다.
> 인덱스가 제대로 걸려 있으면 데이터가 늘어도 로그 스케일로만 느려지지, 선형으로 늘지 않는다.

---

## 11. master-api 실사 결과

> **최초 분석:** 2026-08-19 / branch `release`, 39eab3af
> **재검증:** 2026-08-22 / branch `2-release`, 7acc5f5e — 전 항목을 현재 코드에 다시 대조했다.
> 위 1~10장의 체크리스트를 실제 코드에 대조한 결과. 모든 항목에 `file:line` 근거를 붙였다.
> ★코드 정황 근거이며, 실측(TTFB·explain)으로 확정하기 전까지는 "가설"이다. 확정 절차는 11-5 참조.

### 11-0. 재검증 변경 요약

최초 분석 이후 코드가 상당히 움직였다. **서비스 파일이 대부분 하위 폴더로 이동했고**
(`services/user/`, `services/system/`, `services/feature/`, `services/content/features/`),
일부 항목은 해소, 일부는 판정이 뒤집혔다.

| 판정 | 항목 | 내용 |
|---|---|---|
| ⚠️ **뒤집힘** | ④ MongoDB 뷰 | "최근 제거됐다"는 서술은 **사실이 아니다.** `BookMarkedView`는 지금도 쓰인다 |
| ✅ 해소 | ③ `count()` → `findMany()` 순차 | `Promise.all`로 수정됨 (`search.model.js:255`) |
| ✅ 해소 | ③ 공유자·화자 조회 순차 | `Promise.all`로 수정됨 (`calendar.service.js:28`) |
| ✅ 해소 | ① 썸네일 O(N×M) 순회 | 썸네일 조회 자체가 사라지고 공유자는 해시 색인화됨 |
| ✅ 해소 | `app.js` json replacer | 코드에서 제거됨 |
| 🔻 축소 | ⑤ PrismaClient × PM2 3인스턴스 | 실제 설정은 `instances: 1`, `fork` 모드 |
| ❗ 근거 소실 | ② 전사 문서 크기 실측치 | 근거였던 주석이 삭제됨 → 재측정 필요 |
| ✔️ 유효 | ① 대시보드 전량 조회 | 그대로 유효 |
| ✔️ 유효 | ② 정규식 전문 검색 | 그대로 유효 |

### 11-0-1. 결론

데이터량 문제가 아니라 아래 세 가지 **구조 문제**다.

1. **limit 없는 전량 조회** — 5건 보여주려고 전체를 읽는다 (11-2 ①)
2. **인덱스를 탈 수 없는 정규식 전문 검색** — 검색 기본값이 전사 전량 스캔 (11-2 ②)
3. **DB 뷰 materialization** — MongoDB·MariaDB **양쪽 모두** 남아 있음 (11-2 ④)

CPU 0.5코어는 이 셋을 **증폭**시키는 요소지 원인이 아니다(§6 참조).

### 11-1. 배제된 항목 — 회의 반박용

체크리스트 중 이 서버에서는 원인이 될 수 없는 것들. 근거와 함께 정리한다.

| 의심 항목 | 실제 코드 | 판정 |
|---|---|---|
| 요청마다 커넥션 재수립 (§4-2, §10-1) | 모델 28개 전부 `export default new XxxModel()` 모듈 싱글턴 (`src/models/*.model.js`) | ❌ 아님 |
| 요청마다 시크릿 조회 (§6 HCP/Vault) | `src/utils/fetchEnv.js` — Consul KV를 **컨테이너 기동 시 1회**만 읽어 `.env`로 기록 | ❌ 아님 |
| Redis 연결 재수립 | `src/utils/redis/client.util.js:64` 싱글턴 + `connectWithRetry`(`:26,29`) | ❌ 아님 |
| Mongoose 하이드레이션 / `.lean()` (§4-4) | Mongoose 미사용. Prisma(`@timbel-timblo-onpremise/prisma`) | ❌ 해당 없음 |

> §10의 "매 요청마다 새 커넥션 수립"과 §6의 Vault 왕복은 이 서버에서 배제해도 된다.
> 인증 미들웨어(`src/handlers/authorize.handler.js:33`)가 요청당 추가하는 것은 Redis GET 1회 + MariaDB 조회 1회뿐이다.

### 11-2. 확인된 문제 — 심각도 순

#### ① 대시보드가 전체 콘텐츠를 읽고 5건만 잘라낸다 ★최유력

`src/services/user/dashboard.service.js:48,162,178`

```js
contentService.getAllContents(pid, email, { contentFilter: Enums.ContentFilter.ALL })  // take 미전달 = 무제한
...
contents: filteredContents.slice(0, 5),   // 실제로 쓰는 건 5건
```

`contentModel.getContents()`는 `take > 0`일 때만 `options.take`를 붙인다(`src/models/content.model.js:468`).
대시보드는 `take`를 넘기지 않으므로 **사용자의 전체 콘텐츠를 다 읽는다.**
호출이 **2곳**(`:48`, `:162`)이라는 점도 같이 봐야 한다.

그 전체 목록이 `getContentsResponseWithIds`(`src/services/feature/calendar.service.js:25`)로 넘어간다.

**재검증 — 절반은 개선됐다**

| 최초 지적 | 현재 |
|---|---|
| MariaDB에서 전체 썸네일 조회 | ✅ **해당 조회 자체가 사라짐** |
| `thumbnails.filter()` 중첩 순회 | ✅ 코드 없음 |
| 공유자 조회 순차 | ✅ `Promise.all`로 병렬화 (`:28-32`) |
| `sharedUsers` 매핑 | ✅ `reduce`로 **해시 색인화 완료** (`:38-46`) |
| `files.find()` / `folders.find()` | ⚠️ **남아 있음** (`:58`, `:66`) |
| `shareUsers.findIndex()` / `.find()` | ⚠️ **남아 있음** (`:51`, `:69`) |

즉 O(N×M) 순회는 일부만 걷혔다. `contents.map()`(`:49`) 안에서 `files`·`folders`·`shareUsers`를
매번 선형 탐색하는 구조는 그대로다.

> 이것이 "데이터가 많아져서 느리다"는 회의 주장이 **부분적으로 맞게 되는 유일한 경로**다.
> 단 원인은 데이터량이 아니라 limit 미적용이다 — 데이터가 늘수록 **선형으로** 느려진다(§10 마지막 문단의 반례).

**대응**
- `getAllContents`에 `take` 전달 (대시보드는 5, 여유를 둬도 20) — **최우선, 수정 작음**
- 남은 `files.find()` / `folders.find()`를 `sharedUsersHash`와 같은 방식으로 `Map` 색인화

#### ② 검색: MongoDB 전문 정규식 스캔이 기본 동작

`src/models/search.model.js:274-286`

```js
where: {
  contentId: { in: contentIds },
  transcribeResult: { mergedSegments: { some: { text: { contains: keyword } } } },
}
```

Prisma의 `contains` → MongoDB `$regex` **비앵커** 매칭. 인덱스를 탈 수 없다.
배열 임베디드 문서(`mergedSegments[].text`)를 문서마다 전부 훑는다.

게다가 `src/controller/system/search.controller.js:16`에서

```js
if (!filter || filter === '') filter = 'all';
```

이고, `filter: 'all'`이면 이 쿼리가 **항상** 실행된다(`src/services/system/search.service.js:60-64`).

`searchContentByAttendee`(`search.model.js:290`)도 같은 구조다 — `speakerInfo[]` 배열에
`contains` 매칭을 걸며, `attendee` 파라미터가 있을 때 실행된다(`search.service.js:67-72`).

§3-2의 `COLLSCAN` + `totalDocsExamined` 폭증 전형이다.

> ❗ **근거 소실 주의** — 최초 분석이 인용한 "전사 문서 평균 39.5KB · 최대 570KB" 실측치는
> `bookmark.model.js:20` 주석에 있었으나 **현재 코드에서 삭제됐다.**
> 수치를 회의에 들고 가려면 `db.TranscribeResult.stats()` 또는
> `db.TranscribeResult.aggregate([{$project:{sz:{$bsonSize:"$$ROOT"}}},{$group:{_id:null,avg:{$avg:"$sz"},max:{$max:"$sz"}}}])`로 **재측정할 것.**

**대응**
- MongoDB **text index** 또는 Atlas Search 도입
- 최소한 `filter=all`에서 detail 검색을 분리 — 사용자가 명시적으로 요청할 때만 실행

#### ③ 독립 쿼리가 순차 await — ✅ 대부분 해소됨

| 위치 | 최초 지적 | 현재 |
|---|---|---|
| `src/services/feature/calendar.service.js:28-32` | 화자정보/공유자 조회 순차 | ✅ **`Promise.all` 3개로 병렬화됨** |
| `src/models/search.model.js:255-268` | 같은 where로 `count()` → `findMany()` 순차 | ✅ **`Promise.all`로 묶임** |
| `src/services/system/search.service.js:60,67,74` | detail → attendee → 본 검색 순차 | ⚠️ **남아 있음** (의존관계상 불가피) |

남은 것은 검색 파이프라인의 3단 순차 왕복뿐이다. 뒤 단계가 앞 단계의 `contentIds`를
입력으로 받으므로 병렬화 불가. DB 왕복이 200ms면(§6 리전 항목) 그만큼 누적된다.

> 이 항목은 우선순위에서 내려도 된다. 실질 개선 여지가 거의 없다.

#### ④ DB 뷰 materialization — ⚠️ MongoDB·MariaDB **양쪽 모두** 살아 있음

**최초 분석의 "MongoDB 뷰 의존은 최근 제거됐다"는 서술은 현재 코드 기준으로 사실이 아니다.**
근거로 인용했던 `bookmark.model.js:107-110` 실측 주석도 코드에서 사라졌다.

**MongoDB 뷰 — 현재도 사용 중**

| 위치 | 호출 |
|---|---|
| `src/models/bookmark.model.js:49` | `getBookmarks()` — `bookMarkedView.findMany(options)` |
| `src/models/bookmark.model.js:53` | `getBookmarksByContentId()` — `bookMarkedView.findMany({ where: { contentId } })` |

문제 구조는 최초 분석 그대로다:

> `BookMarkedView`는 `viewOn: TranscribeResult` + `$lookup` 구조라 `where: { contentId }`가
> 파이프라인 앞으로 push down 되지 않아 조회마다 TranscribeResult 전량 스캔이 일어난다.

`TranscribeResult`에 `contentId` 필드가 없어, push down이 "안 되는" 게 아니라 **원리적으로 불가능**하다.
스캔 대상 컬렉션에 필터할 필드가 존재하지 않기 때문이다(§5 참조).

**대응:** 뷰 대신 `Bookmarks` 컬렉션을 직접 읽는다. `Bookmarks`에는 `contentId`가 있으므로
(`bookmark.model.js:68,83,111` 참조) 필터가 정상 동작한다. `getBookmarksByItem()` 등
다른 메서드는 이미 그렇게 하고 있어 **패턴은 이미 코드 안에 있다.**

**MariaDB 뷰 — 동일 구조가 그대로**

| 뷰 | 사용처 (10곳 / 4곳) |
|---|---|
| `contentWithUserProfiles` | `content.model.js:86,166,484,597,702,715,751` / `search.model.js:257,260` / `calendar.model.js:102` |
| `sharedUserProfile` | `content.model.js:328,626` / `share.model.js:10,88` |

MariaDB 뷰가 `UNION`·`GROUP BY`·`DISTINCT`를 포함하면 옵티마이저가 **TEMPTABLE 알고리즘**을 택하고,
그 순간 `WHERE`가 뷰 안으로 push down 되지 않는다 → 조회할 때마다 뷰 전체를 임시 테이블로 만든다.
MongoDB 뷰와 **정확히 같은 실패 모드**다.

**검증**
```sql
SHOW CREATE VIEW contentWithUserProfiles\G
EXPLAIN SELECT * FROM contentWithUserProfiles WHERE creatorPID = '...';
```
`DERIVED` / `Using temporary`가 뜨고 rows가 전체 건수면 확정.

```js
// MongoDB 쪽 뷰 정의 확인
db.getCollectionInfos({ name: "BookMarkedView" })
```

> **오해 방지 — 이건 크로스 DB 조인이 아니다.**
> `Bookmarks`·`TranscribeResult`·`BookMarkedView` 모두 MongoDB 안에 있다.
> `bookmark.model.js`는 전부 `this.mongoDB.*`이며 `mariaDB.bookmark`는 코드 전체에 0건이다.
> 두 DB의 경계는 `contentId` 문자열이고, 그 연결은 애플리케이션이 담당한다 — 그건 정상이다.
> 문제는 경계 처리가 아니라 **MongoDB 안에서 굳이 뷰로 조인한 것**이다.

#### ⑤ PrismaClient 다중 인스턴스 — 🔻 영향 범위 축소

**최초 분석의 "PM2 인스턴스 3개 × 28 = 컨테이너당 84개"는 현재 설정과 다르다.**

`ecosystem.config.cjs` (저장소 루트, `src/` 아님):

```js
instances: 1,
exec_mode: 'fork',
max_memory_restart: '3G',
```

cluster 모드도 아니고 인스턴스도 1개다. 따라서 **프로세스당 PrismaClient 28개**까지만 유효하다.

> 근거로 인용했던 `inbox.model.js:107` 주석("BaseDatabase 는 모델 인스턴스마다 별개 PrismaClient 를 만든다")도
> 현재 코드에서 삭제됐다. `prisma` 서브모듈이 체크아웃되지 않아(`git submodule status` 무응답)
> `BaseDatabase` 구현을 이 저장소에서는 확인할 수 없다. **확인하려면 서브모듈을 받아야 한다.**

남은 영향:
- **콜드 스타트** — §8 테스트 A에서 "첫 요청만 10초" 패턴이 나오면 여전히 이쪽이 후보
- CPU 0.5코어에서 부팅 시 풀 초기화 비용이 첫 요청에 얹힌다
- §4-2의 "연결은 앱 부팅 시 딱 한 번만"은 지켰지만 "한 개만"은 아닌 상태

### 11-3. 부수 발견 — 10초와 직접 관련은 낮음

#### 커넥션 누수 — `/queue` 관리 API

`src/services/system/queue.service.js:53,66,78` — `pauseQueue` / `resumeQueue` / `getJob`이
호출마다 `new Queue()`를 만들고 **한 번도 `close()`하지 않는다.** (재검증 결과 그대로 유효)
Bull `Queue` 하나당 Redis 연결 3개(client / subscriber / bclient)가 생기고 누적된다.

#### `forEach(async ...)` — await되지 않는 fire-and-forget

- `src/services/content/features/share.service.js:132` — 공유 알림 발송·캡처 생성이 응답 이후로 밀리고, 에러는 unhandled rejection
- `src/services/system/recycle.service.js:51` — 즉시삭제 태스크 등록도 동일
- `src/utils/contact/recycle.util.js:47` — **재검증에서 새로 발견.** 연락처 삭제도 동일 패턴

성능이 아니라 **정합성** 이슈다(1~10장에 없는 항목).

#### 반복문 안 await — 진짜 N+1 (§4-1)

- `src/services/user/user.service.js:899-909` — 약관 동의서를 건별 INSERT 루프(`createTermsAgreement`).
  약관 수가 3~5개라 영향은 작지만 `createMany` 대상 (위치만 이동, 구조 동일)
- `src/services/system/queue.service.js:11-46` — 큐 수 × 상태 4개 중첩 순차 루프.
  안쪽 `jobIds.map`은 `Promise.all`이지만 바깥 2중 루프는 순차다

#### 과다 조회

`src/services/content/features/attendee.service.js:61,145` — `clientLanguage` 한 필드를 읽으려고
`findFileByContentId(contentId, { transcribeResult: true })`로 **전사 결과 전문**을 가져온다.
(같은 파일 `:20,115,227,270`은 옵션 없이 호출하므로 해당 없음)

#### 응답 캐싱 없음

Redis는 있으나 읽기 경로 캐시는 `driveHeadCache` / `accessTokens` / 엔진 토큰뿐이다.
대시보드·목록은 매 요청 DB 직행.

#### ~~`json replacer` 전역 장착~~ — ✅ 해소

최초 분석이 지적한 `src/app.js:29`의 `imageUrlJsonReplacer`는 **현재 코드에 없다.** 항목 종료.

### 11-4. 우선순위 (재검증 반영)

| 순위 | 항목 | 근거 위치 | 예상 효과 |
|---|---|---|---|
| 1 | 대시보드 `take` 전달 | `dashboard.service.js:48,162` | 큼 · 수정 작음 |
| 2 | `filter=all`에서 detail 검색 분리 | `search.controller.js:16` | 큼 · 수정 작음 |
| 3 | **`bookMarkedView` → `Bookmarks` 직접 조회로 교체** | `bookmark.model.js:49,53` | 큼 · 수정 작음 |
| 4 | MariaDB 뷰 `EXPLAIN` 후 판단 | 11-2 ④ 표 | 큼 · 조사 필요 |
| 5 | `calendar.service.js` 잔여 `find()` Map 색인화 | `calendar.service.js:58,66` | 중 · 수정 작음 |
| 6 | MongoDB text index 도입 | `search.model.js:274` | 큼 · 수정 큼 |
| 7 | `queue.service.js` Queue 재사용/close | `queue.service.js:53,66,78` | 누수 제거 |
| 8 | PrismaClient 공유 | `BaseDatabase` (서브모듈 측) | 콜드 스타트 개선 |

> 최초 분석의 4위였던 "독립 쿼리 `Promise.all` 묶기"는 **이미 반영되어 목록에서 제외**했다.
> 대신 3위에 MongoDB 뷰 교체가 새로 들어왔다 — 제거된 줄 알았으나 남아 있었고, 수정 비용도 작다.

### 11-5. 이 저장소에 맞춘 측정 순서

§8을 그대로 쓰되 대상만 특정했다.

1. **`GET /home` 하나만** DevTools Timing으로 TTFB 측정 → 10초에 가까우면 11-2 ① 확정
2. 같은 요청에서 `getAllContents`가 반환한 **건수**를 로그로 출력
   → 5건 보여주는 데 몇 건을 읽는지가 그대로 증거가 된다
3. `contentWithUserProfiles`에 `EXPLAIN` → `DERIVED` / `Using temporary` 확인 (11-2 ④ 검증)
4. `db.getCollectionInfos({name:"BookMarkedView"})`로 뷰 정의 확인 후
   `db.BookMarkedView.find({contentId:"..."}).explain("executionStats")` → `totalDocsExamined` 확인
5. 전사 문서 크기 재측정 (11-2 ②의 근거 소실 항목)
6. `db.adminCommand({ping:1})` → 리전 지연 배제 (§8 테스트 B)
7. `morganMiddleware`(`src/app.module.js:6`)가 이미 응답시간을 기록하므로,
   **서버 로그 응답시간 vs DevTools TTFB**를 대조하면 네트워크/게이트웨이 구간 지연도 분리된다
8. 연속 새로고침 3회 (§8 테스트 A) → "첫 번째만 느림"이면 11-2 ⑤(콜드 스타트) 쪽

### 11-6. 회의용 한 줄 요약

> 데이터량 문제가 아니라 **limit 없는 전량 조회** + **인덱스 불가능한 정규식 전문 검색** + **DB 뷰 materialization** 구조 문제다.
> CPU 0.5코어는 이 셋을 증폭시키는 요소지 원인이 아니다.
> 근거: 요청당 커넥션 재수립 없음(모델 싱글턴), 시크릿 조회 없음(부팅 시 1회), 리전 지연은 ping으로 측정 가능.
>
> **2026-08-22 재검증 추가:** 순차 await 항목은 이미 개선됐고, MongoDB 뷰는 제거된 줄 알았으나
> 아직 사용 중이다(`bookmark.model.js:49,53`). 수정 비용이 작아 우선순위 3위로 올렸다.
