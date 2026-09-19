# 회의록 상세 페이지 지연 분석

> 대상: `master-api` / branch `2-release` (`7acc5f5e`)
> 엔드포인트: `GET /contents/:contentId` (`src/routes/content.router.js:40`)
> 범위: 현재 브랜치 코드만. 다른 브랜치와의 비교는 포함하지 않는다.
> 모든 항목에 `file:line` 근거를 붙였다. ★ 표시는 실측(§7)으로 확정해야 하는 가설이다.

---

## 0. 결론

> ### MongoDB가 느린 게 아니라, MongoDB가 절대 최적화할 수 없는 형태로 쿼리를 짜뒀다.
>
> 이건 수사적 표현이 아니라 스키마로 증명되는 사실이다. 근거는 §2-①과 §5-5.

상세 페이지 한 번 여는 데 **DB 왕복이 25회 이상 직렬로 쌓이고**, 그중 하나는 **MongoDB 뷰가 전사 결과 컬렉션 전체를 스캔**하며, 완성된 응답은 **압축 없이** 그대로 나간다.

| # | 원인 | 성격 | 회의록이 N건일 때 | 해결 |
|---|---|---|---|---|
| **①-A** | **뷰 방향이 거꾸로** — `bookMarkedView`의 `viewOn`이 회의록(`TranscribeResult`)이다 | DB 스키마 설계 | **O(N) — 선형 증가** | 뷰 뒤집기 (DB 작업) |
| **①-B** | **회의록을 두 번 읽는다** — 상세 조회가 이미 읽어둔 걸 뷰가 또 조인해서 가져온다 | 백엔드 설계 | **O(N) — 선형 증가** | 뷰 호출 제거 (소스) |
| ② | 응답 압축 미적용 + `mergedSegments` 전문 전송 | 네트워크 | O(1) · 단 회의 **길이**에 비례 | `compression` 2줄 |
| ③ | Prisma 중첩 관계 로딩 → 왕복 25+회 | 왕복 횟수 | O(1) | 조건부 조회 분리 |
| ④ | `sharedUserProfile` MariaDB 뷰 materialization ★ | DB | **O(N) — 선형 증가** | `EXPLAIN` 후 판단 |
| ⑤ | 권한 확인이 본 조회 앞에 2단 직렬 | 왕복 횟수 | O(1) | 결과 재사용 |

**①은 독립된 두 문제가 겹친 것이다.** 뷰 자체가 잘못 만들어졌고(①-A), 애초에 그 뷰를 부를 필요가 없었다(①-B).
상세 페이지만 보면 ①-B만 고쳐도 된다 — 뷰를 안 부르면 뷰가 잘못됐든 말든 상관없기 때문이다.
대시보드처럼 회의록을 들고 있지 않은 경로에는 ①-A가 필요하다.

①은 `prisma/mongoSchema.prisma`로 **메커니즘이 확정됐다**(§2-①). 남은 건 파이프라인 원문 확인뿐이다(§7-5).
④는 아직 가설이며 `EXPLAIN` 한 번으로 판정된다.

### "데이터가 많아져서 느리다"에 대한 정확한 답

**부분적으로 맞다. ①④에 한해서 맞고, 그것도 원인 진단은 틀렸다.**

①은 진짜로 데이터량에 비례한다. 상세 페이지에서 **북마크 1건**을 읽는데:

| 회의록 건수 | `bookMarkedView`가 훑는 `TranscribeResult` 문서 수 |
|---|---|
| 100건 | 100건 |
| 1,000건 | 1,000건 |
| 10,000건 | 10,000건 |

전사 문서는 개당 수십~수백 KB다. 1,000건이면 **수십~수백 MB를 훑어서 북마크 몇 건을 골라낸다.**
그 콘텐츠에 북마크가 0건이어도 **스캔 자체는 똑같이 일어난다.** 읽을 게 없다는 걸 알아내려고 전체를 훑는다.

다만 원인은 "데이터가 많아서"가 아니라 **"필터할 필드가 스캔 대상 컬렉션에 없어서"**다. 이 구분이 전부다:

- **인덱스를 타면** N이 10배가 돼도 **로그 스케일**로만 느려진다 (1,000건 → 10,000건에 조회 시간 +30%)
- **지금은 인덱스를 탈 수 없어서** N에 **선형**으로 느려진다 (1,000건 → 10,000건에 조회 시간 **10배**)

즉 "데이터가 많아져서"는 **증상 설명**이고, "인덱스를 탈 수 없는 구조"가 **원인**이다.
데이터를 줄이는 걸로는 해결되지 않고, 시간이 지나면 반드시 다시 느려진다. 구조를 고쳐야 한다.

반대로 ②③⑤는 **회의록이 1건뿐이어도 그대로 드는 고정 비용**이다. 여기엔 데이터량 논리가 적용되지 않는다.

### "그런데 예전엔 멀쩡했는데?"

이것도 정확한 관찰이고, 설명된다. **문턱이 두 개** 있다 — 북마크 사용 시작, 그리고 WiredTiger 캐시 경계.
둘 다 **코드 변경 없이** 넘어간다. 그래서 "배포한 것도 없는데 갑자기 느려졌다"가 성립한다. 상세는 §2-①.

> ①④의 메커니즘 — 왜 인덱스를 못 타는지, NoSQL·샤딩과는 어떤 관계인지, 그래서 누구 책임인지 — 는 **§5**에서 정리했다.

---

## 1. 요청 경로 전체 지도

`tab` 파라미터 없이 상세를 여는 기본 경로(= 프론트 최초 진입)를 따라간 것이다.

```
GET /contents/:contentId
│
├─ [직렬] authenticateRequest            src/handlers/authenticate.handler.js:114
│     └ jwt.decode 만. DB 접근 없음                                    ← 왕복 0
│
├─ [직렬] authorizeMember                src/handlers/authorize.handler.js:54
│     └ memberModel.findMemberByPID      src/models/member.model.js:9
│       select: { workspace: { select: {...} } }   중첩 1단             ← MariaDB ×2
│
├─ [직렬] isMoreThanContentViewer        src/controller/content/detail.controller.js:32
│     └ findMemberContentByIdAndCreatorId  src/models/member.model.js:23
│       content + shareUsers 중첩 1단                                   ← MariaDB ×2
│
├─ [직렬] findFileByContentId            src/services/content/contentDetail.service.js:207
│     include = { highlights: true, transcribeResult: { select } }
│     select = aiResult, speakerInfo, summaryTime, mergedSegments,
│              status, clientLanguage, summarySize
│       (getFileIncludeOptions  contentDetail.service.js:157-190)       ← MongoDB ×3
│       ※ mergedSegments = 응답 본문의 대부분
│
├─ [병렬 4갈래] Promise.all              contentDetail.service.js:211-216
│   │
│   ├─ (a) contentModel.getContentDetail            content.model.js:746
│   │       ├ findContentById                       content.model.js:191
│   │       │   include: creator / editor / linkedContents
│   │       │   creator → user → profile            중첩 3단
│   │       │   linkedContents → linkedContent → editor → user → profile  중첩 5단
│   │       │   (선언부 content.model.js:9-38)                          ← MariaDB ×10 내외
│   │       └ getThumbnails([contentId])             content.model.js:625
│   │           mariaDB.sharedUserProfile — 뷰, select 없음(전 컬럼)     ← MariaDB ×1 (뷰)
│   │
│   ├─ (b) bookmarkModel.getBookmarksByContentId    bookmark.model.js:53
│   │       mongoDB.bookMarkedView — 뷰                                 ← MongoDB ×1 (뷰) ★최유력
│   │
│   ├─ (c) memoService.getMemosByContentId          memo.service.js:6
│   │       memo + creator→user→profile + comments→creator→user→profile
│   │       (memo.model.js:24-73)                                       ← MariaDB ×8 내외
│   │
│   └─ (d) getContentLifecycle                      lifecycle.model.js:50 ← MariaDB ×1
│
├─ [직렬] postProcessResponse            contentDetail.service.js:120-133
│     ├ matchProfileBySpeakerInfo        attendee.service.js:34
│     │   userModel.getUserInfosByUserIds  user.model.js:27              ← MariaDB ×1
│     ├ updateMergedSegments             contentDetail.service.js:86     ← 조건부 (§3-1 참조)
│     └ updateMeetingTime                contentDetail.service.js:76     ← 조건부 쓰기
│
└─ [직렬] 응답 직렬화 → 전송
      압축 미들웨어 없음 (src/app.js:47-92 전체에 compression 부재)
```

### 왕복 집계

| 구간 | 쿼리 수 | 직렬 깊이 |
|---|---|---|
| 미들웨어 인증/인가 | 2 | 2 |
| 콘텐츠 권한 확인 | 2 | 2 |
| MongoDB file/transcribeResult | 3 | 2~3 |
| Promise.all 4갈래 | 20 내외 | 갈래 중 최댓값 (a: 5단 / c: 3단) |
| postProcess | 1~3 | 2 |
| **합계** | **약 25~30** | **약 12~15** |

Prisma는 관계를 SQL JOIN이 아니라 **관계 단계마다 별도 쿼리**로 푼다. 같은 단계의 형제 관계(`creator` / `editor`)는 병렬화될 수 있지만, **중첩 깊이만큼은 반드시 직렬**이다.

- 같은 리전(왕복 2ms) → 직렬 깊이 15 × 2ms ≈ **30ms** (문제 없음)
- 리전 불일치(왕복 200ms) → 15 × 200ms ≈ **3초** (쿼리 자체는 0ms여도)

> §7-4의 `ping` 측정이 이 구간의 배수를 결정한다. 먼저 재야 한다.

---

## 2. 지연 원인 — 심각도 순

### ① `bookMarkedView` — MongoDB 뷰 $lookup 전량 스캔 ★최유력

> **이 항목은 독립된 두 문제가 겹쳐 있다.**
>
> **①-A 뷰 방향이 거꾸로다** — `viewOn`이 회의록(`TranscribeResult`)이라 회의록 전체를 훑고 맨 끝에 1건을 고른다.
> **①-B 애초에 그 뷰를 부를 필요가 없다** — 상세 조회는 회의록을 이미 메모리에 읽어뒀는데(`:207`), 4줄 뒤에 뷰를 시켜 **같은 회의록을 다시 읽게** 한다(`:213`).
>
> A는 DB 작업(뷰 재생성), B는 소스 수정이다. **상세 페이지는 B만 고쳐도 해결된다.**

`src/models/bookmark.model.js:53`

```js
async getBookmarksByContentId(contentId) {
    return await this.mongoDB.bookMarkedView.findMany({
        where: { contentId },
        select: { id: true, key: true, time: true, isAll: true, data: true },
    });
}
```

상세 조회의 `Promise.all` 4갈래 중 (b)에 해당한다(`contentDetail.service.js:213`).

**문제의 구조 — 스키마로 확인됨**

`prisma/mongoSchema.prisma` (패키지 이관 전 마지막 버전, `git show 03e1ff9d~1:prisma/mongoSchema.prisma`):

```prisma
view BookMarkedView {
    id        String   @id @map("_id") @db.ObjectId
    contentId String              // ← 뷰는 contentId를 노출한다
    key       BookmarksKeys
    time      DateTime
    data      Json[]              // ← 전사 본문에서 뽑아낸 payload
}

model TranscribeResult {
    id       String   @id @map("_id")
    fileId   String?  @unique     // ← contentId 필드가 없다. fileId만 있다.
    segments        Segment[]
    mergedSegments  Segment[]
    speakerInfo     SpeakerInfo[]
    aiResult        Json?
    summaryTime     SummaryTime[]

    @@index([updateAt])
    @@index([segments])           // ← contentId 인덱스 없음 (필드 자체가 없으므로)
}

model Bookmarks {
    contentId String              // 인덱스 선언 없음
    fileId    String              // 인덱스 선언 없음
    key       BookmarksKeys
    itemIds   String[]
}
```

여기서 결정적인 사실이 나온다.

> **`TranscribeResult`에는 `contentId` 필드가 아예 없다.**
> 뷰가 노출하는 `contentId`는 조인된 `Bookmarks` 쪽에서 온 값이다.

따라서 `where: { contentId }`는 **push down이 "안 되는" 게 아니라 "원리적으로 불가능"하다.**
스캔 대상 컬렉션에 필터할 필드가 존재하지 않기 때문이다. 옵티마이저가 아무리 똑똑해도 방법이 없다.

실행 순서는 이렇게 고정된다:

1. `TranscribeResult` **전체**를 훑는다 ← contentId로 못 줄인다
2. 각 문서마다 `Bookmarks`를 `$lookup` ← **`Bookmarks`에 인덱스가 없어 여기도 전량 스캔**
3. `itemIds`로 `data`를 조립
4. **그제서야** `contentId`로 1건을 골라낸다

북마크 1건을 읽으려고 전사 결과 컬렉션 전체를 스캔하는 셈이다.
`Bookmarks`에도 인덱스가 없으므로 2번이 `O(N × M)`이 된다(§5-1).

> `@@index([segments])`도 별건으로 의심스럽다. 세그먼트 **배열 전체**에 걸린 multikey 인덱스라 크기가 크고 쓰기를 느리게 한다. 조회에 쓰이는지 확인 필요(§7-5).

**오해 방지 — 이건 크로스 DB 조인이 아니다**

"MariaDB에 있는 북마크를 MongoDB 뷰로 조인하는 거냐"는 질문이 나올 수 있다. **아니다.**

```
MongoDB (mongoSchema.prisma)
├─ model Bookmarks          ← 북마크 원본. MariaDB 아님
├─ model TranscribeResult   ← 전사 결과
└─ view  BookMarkedView     ← 위 둘을 $lookup 으로 조인 (전부 MongoDB 내부)
```

- `bookmark.model.js`는 9곳 전부 `this.mongoDB.*` 를 쓴다. 코드 전체에 `mariaDB.bookmark` 는 **0건**
- MariaDB 스키마에도 북마크 테이블·뷰가 **없다**
- 애초에 DB 뷰로 크로스 DB 조인은 **불가능**하다. Prisma도 `mariaDB` / `mongoDB` 별도 클라이언트다

**DB 경계는 `contentId` 문자열이다.** `Content` 테이블은 MariaDB, MongoDB의 `contentId`는 복사된 문자열이며 FK도 제약도 없다. 두 DB를 잇는 건 애플리케이션이고 **그건 정상이다.**
문제는 경계 처리가 아니라 **MongoDB 안에서 굳이 뷰로 조인한 것**이다.

**그리고 이게 "RDBMS처럼 썼다"의 실물 증거다**

MariaDB 스키마의 뷰 목록(`git show 03e1ff9d~1:prisma/mariaSchema.prisma`):

```
UserView, ContentWithUserProfiles, SharedUserProfile, InboxContent,
MonthlyWorkspaceStats, HourlyMemberStats, DailyMemberStats,
WeeklyMemberStats, MonthlyMemberStats                          → 9개
```

**MariaDB에서 뷰를 적극 쓰던 관행을 MongoDB에 그대로 옮겼다.** `BookMarkedView` 라는 이름부터 MariaDB 뷰 네이밍과 같다.

RDBMS 뷰는 옵티마이저가 `WHERE`를 뷰 안으로 밀어넣어 주는 경우가 많아 대체로 잘 동작한다.
**MongoDB 뷰는 그 보장이 없고**, 이 케이스는 `TranscribeResult`에 `contentId` 필드가 아예 없어 **원리적으로 불가능**하다.

> 같은 습관인데 한쪽에서만 사고가 났다. 그래서 **"MongoDB를 RDBMS처럼 썼다"**가 정확한 표현이다.
> (다만 §2-④에서 보듯 MariaDB 뷰 쪽도 안전하지는 않다 — `EXPLAIN` 검증 대상이다)

**왜 이게 상세 페이지에서 특히 나쁜가**

- **한 건 보는 화면인데 비용이 전체 건수에 비례한다.** 상세 페이지는 `contentId` 하나를 여는 화면이다. 그런데 뷰를 거치는 순간 비용이 "그 콘텐츠의 북마크 수"가 아니라 **"워크스페이스 전체 회의록 수"**에 묶인다.
- **북마크가 0건이어도 스캔은 그대로 일어난다.** 읽을 게 없다는 걸 알아내기 위해 전체를 훑는다. (다만 그 뒤 단계는 비어서 체감은 작다 — 아래 "문턱 1")
- `Promise.all`로 병렬화되어 있어도 **전체 응답 시간이 이 갈래에 묶인다.** 나머지 3갈래가 20ms에 끝나도 이 하나가 1초면 1초다. 병렬화는 이 문제를 **감추지 못한다.**
- 전사 문서는 개당 수십~수백 KB다. 스캔 1건당 단가가 높다. 같은 1,000건 스캔이라도 작은 문서를 훑는 것과 비용이 다르다.

**시간이 갈수록 나빠진다**

이건 지금 느린 것보다 더 큰 문제다. 사용량이 늘면:

| 시점 | 회의록 | 스캔 문서 | 예상 소요 (선형 가정) |
|---|---|---|---|
| 지금 | 1,000건 | 1,000건 | 1초 |
| 6개월 후 | 3,000건 | 3,000건 | 3초 |
| 1년 후 | 10,000건 | 10,000건 | **10초** |

인덱스를 타는 구조로 바꾸면 같은 구간에서 1초 → 1.1초 수준이다. **CPU를 늘리거나 데이터를 정리하는 걸로는 이 기울기를 바꿀 수 없다.**

**왜 예전에는 멀쩡했나 — 두 개의 문턱**

"데이터가 적을 땐 문제가 없었다"는 관찰은 정확하다. 두 가지 문턱이 겹친다.

**문턱 1 — 북마크가 0건이면 파이프라인이 사실상 비어 있다**

`$unwind`는 기본적으로 빈 배열 문서를 **떨어뜨린다**(`preserveNullAndEmptyArrays` 미지정 시). 그래서:

| 워크스페이스 전체 북마크 | 파이프라인 동작 |
|---|---|
| **0건** | `$lookup`이 매번 빈 결과 → `$unwind`가 전부 제거 → `data` 조립(3단계)이 **한 번도 실행되지 않음** |
| **1건 이상** | 살아남은 문서가 전사 본문을 실은 채 3단계로 진입 → `itemIds`로 `segments`/`mergedSegments` 배열에서 payload 추출 시작 |

스캔(1단계)은 어느 쪽이든 일어나지만, **북마크가 없으면 그 뒤가 전부 공짜**다.
즉 북마크·메모 기능이 실제로 쓰이기 시작한 시점부터 비용이 발현된다. 코드는 그대로인데 증상만 나타난다.

**문턱 2 — WiredTiger 캐시 경계**

스캔 대상이 캐시에 들어가느냐가 성능을 계단식으로 바꾼다.

| 회의록 | 스캔 크기(개당 40KB 가정) | 동작 | 체감 |
|---|---|---|---|
| 100건 | 4MB | 캐시 히트 — 메모리 스캔 | ~50ms · **아무도 못 느낌** |
| 1,000건 | 40MB | 캐시 경계 | 0.5~1초 · 느리다는 말 나옴 |
| 3,000건 | 120MB | **캐시 미스 — 디스크 I/O** | 수 초 · **"갑자기 느려졌다"** |

WiredTiger 캐시 기본값은 `(RAM - 1GB) × 50%`다. 컨테이너 메모리가 작으면 이 경계가 금방 온다.
선형이던 그래프가 캐시를 넘는 순간 **꺾인다.** "어느 날 갑자기"로 느껴지는 이유가 이것이다.

> 결론: 문턱 1이 **증상의 시작**을, 문턱 2가 **급격한 악화**를 설명한다.
> 둘 다 코드 변경 없이 일어난다. 그래서 "배포한 것도 없는데 느려졌다"가 성립한다.

**①-B — 회의록을 두 번 읽는다**

같은 요청 안에서 회의록(전사 결과)을 **두 번** 읽는다. 그런데 비용이 전혀 다르다.

| | 위치 | 무엇을 | 어떻게 | 비용 |
|---|---|---|---|---|
| 1번째 | `contentDetail.service.js:207` | **그 회의록 1건** | `fileId` 인덱스 (`@unique`) | 싸다 |
| 2번째 | `contentDetail.service.js:213` (뷰) | **회의록 전체 N건** | 전량 스캔 | **비싸다** |

```js
// :207 — 회의록 본문을 읽는다. mergedSegments, speakerInfo, summaryTime, aiResult 전부 여기 있다.
let { transcribeResult, ... } = await contentModel.findFileByContentId(contentId, ...);

// :213 — 방금 읽은 그 회의록을, 뷰를 시켜 다시 조인해서 가져온다
bookmarkModel.getBookmarksByContentId(contentId)   // → bookMarkedView
```

**중복이라서 나쁜 게 아니라, 두 번째가 잘못된 방식이라서 나쁘다.**
첫 번째는 필요한 1건만 인덱스로 집어오고, 두 번째는 전부 훑은 뒤 1건을 고른다.

북마크가 필요로 하는 데이터(`BookmarksKeys`: `mergedSegments`, `speakerInfo`, `summaryTime`, 그리고 `aiResult` 안의 `topics`/`keywords`/`summary`/`tasks`/`issues`)는 **전부 1번째에서 이미 로드된다.**
즉 뷰가 하는 조인은 **이미 메모리에 있는 데이터를 다시 가져오는 일**이다.

> 그래서 상세 페이지는 ①-A(뷰 뒤집기) 없이 **①-B만 고쳐도 해결된다.** 뷰를 안 부르면 뷰가 잘못됐든 상관없다.

**CPU를 태우는 건 MongoDB 쪽이다**

전량 스캔이 소모하는 건 **MongoDB 서버의 CPU와 디스크 I/O**다. 백엔드(Node)는 그동안 `await`로 기다릴 뿐이다.

이것이 "MongoDB VM에 0.5코어" 이슈와 맞물리는 지점이다:

- 스캔이 MongoDB CPU를 태우는데 그 MongoDB가 0.5코어다 → **더 오래 걸린다**
- 하지만 코어를 늘려도 **훑어야 할 양은 그대로다** → 근본 해결이 아니다

즉 0.5코어는 **증폭기**이지 원인이 아니다(§4). 코어를 늘리면 일시적으로 나아지지만 회의록이 늘면 원위치한다.

**대응**

뷰를 경유하지 말고 원본을 읽어 앱에서 조립한다.

```js
async getBookmarksByContentId(contentId) {
    return await this.mongoDB.bookmarks.findMany({
        where: { contentId },
        select: { id: true, key: true, itemIds: true, time: true, isAll: true, fileId: true },
    });
}
```

**단, 인덱스가 먼저다.** `Bookmarks`에는 인덱스 선언이 없어서 이대로 두면 원본 조회도 `COLLSCAN`이다.

```js
db.Bookmarks.createIndex({ contentId: 1 })
db.Bookmarks.createIndex({ fileId: 1 })     // $lookup / 파일 단위 조회용
```

`data`는 `itemIds`를 전사 본문에 매핑해 만든 값인데, **상세 조회는 이미 같은 요청에서 그 본문을 읽어 놓았다**(`contentDetail.service.js:207`). 추가 조회 없이 메모리에서 조립하면 된다 — 자세한 건 §5-5.

**이 뷰를 부르는 곳은 세 군데다.** 상세만 고치면 나머지 둘이 남는다.

| # | 경로 | 호출 지점 | 회의록이 메모리에 있나 |
|---|---|---|---|
| 1 | 회의록 상세 | `bookmark.model.js:53` ← `contentDetail.service.js:213` | ✅ 있음 (`:207`) |
| 2 | 대시보드 | `bookmark.model.js:49` ← `dashboard.service.js:78`, `:168` | ❌ 없음 |
| 3 | 북마크 목록 API (`GET /bookmark`) | `bookmark.model.js:49` ← `bookmark.service.js:55` | ❌ 없음 |

2·3은 회의록을 들고 있지 않으므로 `TranscribeResult`를 한 번 더 조회해 조립한다. **왕복 2회지만 둘 다 인덱스 조회**라 전량 스캔이 사라진다. 구체적인 코드는 §8 처리 방법 3단계.

---

### ② 응답 압축 없음 + `mergedSegments` 전문 전송

`src/app.js` 전체에 **compression 미들웨어가 없다.**

`tab` 파라미터가 없으면 `getFileIncludeOptions`(`contentDetail.service.js:157-190`)가 모든 tabAction을 실행해서:

```js
select.aiResult      = true
select.speakerInfo   = true
select.summaryTime   = true
select.mergedSegments = true      // ← 회의 전체 발화 텍스트
```

1시간짜리 회의면 `mergedSegments`만으로 수백 KB다. 여기에 `highlights`, `bookmarks`, `memos`가 더 붙는다.

전사 텍스트 JSON은 압축률이 매우 좋다(보통 8~10:1). **gzip 하나로 500KB → 60KB가 된다.**

**대응**

```js
import compression from 'compression';
app.use(compression());   // src/app.js, express.json() 위쪽
```

체감상 가장 저렴한 개선이다. 코드 2줄이고 위험도 없다.

**추가로 확인할 것**: 프론트가 `tab` 파라미터를 쓰고 있는지. `tabList`에 `segments / speakerInfo / aiResult / summaryTime / bookmarks / file / memos`가 정의돼 있는데(`detail.controller.js:21`), 최초 진입에서 파라미터 없이 호출한다면 **화면에 당장 안 쓰는 것까지 전부 실어 보내는 중**이다.

---

### ③ Prisma 중첩 관계 로딩 — 왕복 25+회

**(a) `findContentById` — `src/models/content.model.js:191`**

```js
include: {
    creator: this.userProfileNickNameSelectOption,   // creator → user → profile  (3단)
    editor:  this.userProfileNickNameSelectOption,   // editor  → user → profile  (3단)
    linkedContents: this.linkedContentSelectOption,  // → linkedContent → editor → user → profile (5단)
}
```

선언부는 `content.model.js:9-38`. 닉네임 하나 얻자고 `member → user → userProfile` 3단을 타고, `linkedContents`는 5단이다.

**(c) `getMemosByContentId` — `src/models/memo.model.js:24`**

```js
creator: userProfileNickNameSelectOption,       // 3단
comments: {
    select: { creator: userProfileNickNameSelectOption }   // comments(1) + 3단
}
```

메모 목록 하나에 관계 쿼리 8개 내외.

**대응 (효과 순)**

1. `linkedContents`를 기본 조회에서 분리 — `MERGED_CONTENT` 타입일 때만 필요한데(`contentDetail.service.js:121`) **모든 상세 조회가 조인 비용을 낸다.** `mariaDBContent.type`을 먼저 확인하고 필요할 때만 2차 조회.
2. 닉네임/PID는 `contentWithUserProfiles` 뷰가 이미 평탄화해서 갖고 있다. 3단 중첩 대신 뷰의 컬럼을 쓰면 왕복이 사라진다. (단 ④ 검증 후)
3. Prisma의 `relationLoadStrategy: 'join'` 검토 — 관계를 실제 SQL JOIN으로 푼다. 지원 버전인지 확인 필요.

---

### ④ `sharedUserProfile` MariaDB 뷰 ★검증 필요

`src/models/content.model.js:625`

```js
async getThumbnails(contentIds) {
    return await this.mariaDB.sharedUserProfile.findMany({
        where: { contentId: { in: contentIds } },
        // select 없음 → 뷰의 모든 컬럼
    });
}
```

상세 조회마다 호출된다(`content.model.js:748`).

MariaDB 뷰가 `UNION` / `GROUP BY` / `DISTINCT` / 집계함수를 포함하면 옵티마이저가 **TEMPTABLE 알고리즘**을 택하고, 그 순간 바깥 `WHERE`가 뷰 안으로 push down 되지 않는다. → **조회할 때마다 뷰 전체를 임시 테이블로 만든다.**

①의 MongoDB 뷰와 정확히 같은 실패 모드다.

**검증**

```sql
SHOW CREATE VIEW sharedUserProfile\G
EXPLAIN SELECT * FROM sharedUserProfile WHERE contentId = '...';
```

`DERIVED` / `Using temporary`가 뜨고 `rows`가 전체 건수면 확정.

같은 뷰를 쓰는 다른 지점: `content.model.js:328`(`getSharedContentIds`), `share.model.js:10, 88`.
자매 뷰 `contentWithUserProfiles`도 동일 점검 대상 — `content.model.js:86, 166, 484, 597, 702, 715, 751` / `search.model.js:257, 260` / `calendar.model.js:102`.

---

### ⑤ 권한 확인이 본 조회 앞에 2단 직렬

본 데이터를 한 건도 읽기 전에 **직렬 왕복 4회**가 먼저 소모된다.

| 순서 | 위치 | 쿼리 |
|---|---|---|
| 1 | `authorize.handler.js:54` | `findMemberByPID` — member + workspace |
| 2 | `auth.handler.js:30` | `findMemberContentByIdAndCreatorId` — content + shareUsers |

2번(`member.model.js:23`)은 `contentId`로 `content` 행을 읽는다. 그런데 그 직후 `findContentById`(`content.model.js:191`)가 **같은 행을 다시 읽는다.**

**대응**

- 2번을 `Promise.all`로 3번(`findFileByContentId`)과 병렬화 — 권한 실패 시 MongoDB 조회가 낭비되지만, 정상 경로에서 왕복 1단이 줄어든다. 트레이드오프 판단 필요.
- 또는 2번의 결과를 `req`에 실어 `findContentById`가 재사용하도록 — 중복 조회 1회 제거.

---

## 3. 부수 발견 — 성능 외

### 3-1. `updateMergedSegments` — 실행되면 500 에러 (잠재 버그)

`src/services/content/contentDetail.service.js:86`

```js
const updateMergedSegments = (mongoDBcontent, file) => {
    if (mongoDBcontent?.mergedSegments?.length === 0) {
        mongoDBcontent.mergedSegments = convert.createMergedSegments({ segments: mongoDBcontent.segments });
        ...
    }
};
```

그런데 `getFileIncludeOptions`(`contentDetail.service.js:171-174`)에서 `segments` select가 **주석 처리**돼 있다:

```js
segments: () => {
    select.mergedSegments = true;
    // select.segments = true;      ← 주석
},
```

따라서 `mongoDBcontent.segments`는 항상 `undefined`이고,
`processSegments`(`src/utils/convert/segment.util.js:9`)의 `segments.forEach(...)`에서 **TypeError**가 난다.

`mergedSegments`가 빈 배열인 콘텐츠를 열면 상세 페이지가 500으로 죽는다. 평소엔 채워져 있어 드러나지 않는 지뢰다.

### 3-2. `updateMeetingTime` — 읽기 요청에서 쓰기 발생

`src/services/content/contentDetail.service.js:76`

`meetingStartTime` / `meetingEndTime`이 비어 있으면 상세 **조회** 중에 MariaDB **UPDATE**가 실행된다(`:79`).
또 함수 안에서 파라미터를 재대입할 뿐(`mariaDBContent = await ...`) 호출자 객체는 갱신되지 않아, **그 요청의 응답에는 갱신 전 값(null)이 나간다**(`createResponseData` → `pick`, `:145`).

DB는 갱신되므로 다음 요청부터는 정상이지만, 첫 조회 1회는 쓰기 왕복 + 잘못된 응답이다.

### 3-3. `transcribeResult: true` 과다 조회 (상세 페이지 외)

상세 조회 본 경로는 `select`로 좁혀져 있어 해당 없다. 다만 인접 API가 **전사 결과 문서를 통째로** 가져온다:

- `attendee.service.js:61`, `:145` — `file.transcribeResult?.clientLanguage` **한 필드**만 쓴다(`:68`, `:168`)
- `content.service.js:356, 391, 470, 557` — 동일 패턴

`select: { clientLanguage: true }`로 좁히면 된다. 상세 페이지에서 참석자 탭·이름 변경을 연달아 호출한다면 체감에 영향을 준다.

### 3-4. `transformLinkedContents` — 연결 콘텐츠당 3쿼리

`contentDetail.service.js:93-118` — `MERGED_CONTENT`일 때 연결 콘텐츠 N건 × 쿼리 3개.
`Promise.all`로 병렬화돼 있어 지연은 최댓값이지만, N이 크면 커넥션 풀을 한 번에 소모한다.
`:100`의 `await contentModel.findFileByContentId(...)` — `Promise.all` 배열 안의 불필요한 `await`(동작엔 영향 없음).

---

## 4. 배제된 항목

의심되지만 **이 서버에서는 원인이 아닌** 것들. 회의에서 되돌아올 때 쓸 근거다.

| 의심 | 실제 코드 | 판정 |
|---|---|---|
| 요청마다 커넥션 재수립 | 모델 27개 전부 `export default new XxxModel()` 모듈 싱글턴 (`src/models/*.model.js`) | ❌ 아님 |
| 요청마다 시크릿 조회 (Vault/Consul) | `src/utils/fetchEnv.js` — 컨테이너 기동 시 1회만 | ❌ 아님 |
| Redis 연결 재수립 | `src/utils/redis/client.util.js` 싱글턴 | ❌ 아님 |
| Mongoose 하이드레이션 / `.lean()` | Mongoose 미사용. Prisma(`@timbel-timblo-onpremise/prisma`) | ❌ 해당 없음 |
| 전역 `json replacer` 오버헤드 | `src/app.js`에 미장착 | ❌ 아님 |
| 인증 미들웨어의 외부 HTTP 호출 | `authenticate.handler.js:114` — 일반 경로는 `jwt.decode`만. HTTP는 외부 API 인증 경로 전용 | ❌ 아님 |
| 상세 조회의 반복문 안 `await` | 본 경로에 없음 (`Promise.all` 사용) | ❌ 아님 |

**CPU 0.5코어**는 원인이 아니라 증폭기다. Node는 싱글 스레드라 JSON 직렬화 같은 CPU 바운드 구간이 그대로 2배 느려지고, 스로틀링이 걸리면 응답 시간이 튄다. 다만 **요청 중 CPU가 20%에서 놀고 있는데 느리다면 CPU는 원인이 아니다**(§7-6).

---

## 5. 왜 `$lookup`이 느린가 — NoSQL·조인·샤딩 정리

①④의 근본 메커니즘이다. 회의에서 "MongoDB는 대용량에 강한데 왜 느리냐"는 질문이 나올 지점이라 따로 정리한다.

### 5-1. MongoDB에는 조인 알고리즘이 하나뿐이다

RDBMS 옵티마이저는 상황에 따라 세 가지 중에서 고른다.

| 알고리즘 | 비용 | 쓰이는 상황 |
|---|---|---|
| Nested Loop Join | O(N × log M) — inner에 인덱스 필요 | outer가 작을 때 |
| **Hash Join** | O(N + M) | outer가 클 때 |
| **Merge Join** | O(N + M) — 정렬돼 있을 때 | 양쪽이 정렬된 인덱스일 때 |

**MongoDB의 `$lookup`은 Nested Loop Join 하나뿐이다.** Hash Join도 Merge Join도 없다.
즉 outer 문서 하나당 inner 컬렉션 조회를 1회씩, N번 반복한다.

여기서 갈린다:

- inner의 `foreignField`에 **인덱스가 있으면** → `O(N × log M)`. N이 작으면 견딜 만하다.
- inner에 **인덱스가 없으면** → `O(N × M)`. outer 하나당 inner **전량 스캔**. 재앙이다.

**어느 쪽이든 N을 줄이는 게 유일한 방어책이다.** MongoDB는 N이 커지면 대안 알고리즘으로 갈아탈 수단이 없기 때문이다. 그래서 `$lookup` 앞에 `$match`를 두어 outer를 먼저 줄이는 게 정석이고, 이걸 못 하면 방법이 없다.

### 5-2. 그런데 이 뷰는 `$match`를 앞으로 보내는 게 "불가능"하다

일반적으로 뷰가 느린 이유는 **옵티마이저가 push down을 포기해서**다. `$lookup` 뒤에 `$unwind` / `$group` / 계산 필드 `$project`가 끼면 의미가 달라질 수 있어 `$match`를 앞으로 못 민다.

**그런데 `bookMarkedView`는 그보다 한 단계 더 나쁘다.**

```
뷰 정의:       viewOn: TranscribeResult
               [ $lookup(Bookmarks), $unwind, $project ]
앱이 보낸 쿼리:  where: { contentId: "abc" }

실제 실행:     [ TranscribeResult 전량 ] → [ $lookup ] → [ $unwind ] → [ $project ] → [ $match contentId ]
                        ↑ 여기서 이미 끝났다                                    ↑ 조건은 맨 뒤

"앞으로 밀면?"  [ $match contentId ] → [ TranscribeResult ... ]
                        ↑ 밀 수가 없다. TranscribeResult에 contentId 필드가 존재하지 않는다.
```

`TranscribeResult` 스키마에는 `contentId`가 **아예 없다**(§2-①). `fileId`만 있다.
뷰가 노출하는 `contentId`는 조인된 `Bookmarks` 쪽 값이다.

> **즉 옵티마이저가 "포기"한 게 아니라, 밀어넣을 대상 자체가 없다.**
> 필터 조건이 스캔 대상 컬렉션에 존재하지 않는 필드를 가리킨다. 어떤 데이터베이스도 이걸 최적화할 수 없다.

그 결과가 §2-①이다. `where: { contentId }`를 분명히 넘겼는데도 전량 스캔이 된다.

> **핵심**: 느린 건 "MongoDB라서"도 "조인이라서"도 아니다. **필터 기준이 되는 필드를, 필터가 적용돼야 할 컬렉션이 갖고 있지 않기 때문**이다.
> 같은 `$lookup`이라도 outer에 필터 가능한 필드가 있으면 빠르다. 그래서 §2-①의 대응은 "뷰를 쓰지 말고 `Bookmarks`(= `contentId`를 가진 컬렉션)를 직접 읽으라"다.

### 5-3. 샤딩에 대한 정정

> "NoSQL은 대용량에 적합하고 샤딩 효과로 단일 조회는 빠르다"

절반만 맞다. 두 가지를 정정해야 한다.

**(1) 샤딩은 조회 가속 기술이 아니라 저장·쓰기 확장 기술이다.**

단일 문서 조회가 빠른 이유는 샤딩이 아니라 **인덱스** 때문이다. 샤드가 1개든 100개든, 인덱스가 있으면 B-tree 탐색으로 빠르고 없으면 느리다. 이건 MySQL도 똑같다(둘 다 B-tree를 쓴다).

샤딩이 조회에 주는 영향은 오히려 조건부다:

| 쿼리 유형 | 동작 | 결과 |
|---|---|---|
| 샤드 키를 조건에 포함 | targeted query — 해당 샤드만 조회 | 빠름 |
| 샤드 키 없이 조회 | **scatter-gather** — 전 샤드에 브로드캐스트 후 병합 | **샤드가 늘수록 느려짐** |

**(2) 이 서버는 샤딩 클러스터가 아닐 가능성이 높다.**

데이터량이 적고 사용자도 소수인 온프레미스 구성이다. 단일 레플리카셋이면 샤딩 논의 자체가 성립하지 않는다.

확인:
```js
sh.status()          // "not a shard cluster" 면 샤딩 없음
db.serverStatus().process   // mongos 면 샤딩, mongod 면 단일/레플리카셋
```

**(3) 샤딩이 있다면 `$lookup`은 오히려 더 나쁘다.**

샤딩 환경에서 `$lookup`의 inner 컬렉션 조회는 샤드 경계를 넘나든다. 즉 **조인 한 번에 네트워크 왕복이 추가로 붙는다.** 샤딩은 `$lookup`을 구제하지 않고 악화시킨다.

### 5-4. 그래서 결론

| 흔한 오해 | 실제 |
|---|---|
| "NoSQL이라 조회가 빠르다" | 조회 속도를 정하는 건 DB 종류가 아니라 **인덱스 유무·데이터 모델링·네트워크 거리**다 |
| "MongoDB는 대용량에 강하니 괜찮다" | 대용량에 강한 건 **샤딩 기반 쓰기/저장 확장**이지, 조인 성능이 아니다 |
| "샤딩이 있으니 조회는 문제없다" | 샤드 키를 안 쓰는 쿼리는 전 샤드 브로드캐스트다. 게다가 이 서버는 샤딩이 아닐 것이다 |
| "조인이 원래 느리다" | `$match`가 앞에 걸린 `$lookup`은 빠르다. **뷰가 그걸 막고 있는 게 문제**다 |

> 인덱스 없는 MongoDB는 인덱스 있는 MySQL보다 느리다. 지금 `bookMarkedView`가 정확히 그 상태다.
> **MongoDB를 버릴 필요는 없다. 뷰를 거치지 않고 원본을 인덱스로 읽으면 된다** (§2-① 대응).

### 5-5. 그래서 백엔드 문제인가, MongoDB 문제인가

**백엔드 문제다.** 근거 셋과, 30초짜리 증명 하나가 있다.

#### 근거 1 — 필터가 불가능하도록 설계돼 있다

`TranscribeResult`에 `contentId`가 없는데 뷰는 `contentId`로 조회하게 만들어 놨다(§2-①, §5-2).
**MongoDB의 최적화 실패가 아니라, 최적화할 여지를 남기지 않은 설계다.**

#### 근거 2 — `Bookmarks`에 인덱스가 하나도 없다

```prisma
model Bookmarks {
    contentId String     // 인덱스 선언 없음
    fileId    String     // 인덱스 선언 없음
}
```

`$lookup`의 `foreignField`에 인덱스가 없으면 outer 문서 하나당 `Bookmarks` 전량 스캔이다(§5-1).
이건 MongoDB의 기능 문제가 아니라 **인덱스를 안 건** 문제다. `File`에는 `@@index([contentId])`가 제대로 걸려 있다 — 할 줄 몰라서가 아니라 여기만 빠졌다.

#### 근거 3 — 조인해서 가져오는 데이터를 이미 메모리에 들고 있다 ★결정타

`BookmarksKeys` enum이 가리키는 대상:

```prisma
enum BookmarksKeys {
    segments  mergedSegments  speakerInfo  summaryTime
    topics  keywords  summary  tasks  issues     // ← aiResult(Json) 내부
}
```

그런데 상세 조회는 **`contentDetail.service.js:207`에서 이미 그걸 전부 읽어 놓는다**:

```js
// :207 — 여기서 mergedSegments, speakerInfo, summaryTime, aiResult 를 모두 로드
let { transcribeResult, highlights = [], ...file } =
    await contentModel.findFileByContentId(contentId, getFileIncludeOptions(tabs));

// ... 4줄 뒤 ...

// :211 — 방금 읽은 그 데이터를 가져오겠다고 DB에 조인을 시킨다
let [..., bookmarks, ...] = await Promise.all([
    ...
    bookmarkModel.getBookmarksByContentId(contentId),   // ← bookMarkedView
    ...
]);
```

`BookmarksKeys` 중 `segments`를 뺀 전부가 **이미 로컬 변수 `transcribeResult` 안에 들어 있다.**
(`segments`는 `getFileIncludeOptions`에서 select가 주석 처리돼 있어 애초에 안 쓴다 — §3-1)

> **조인의 목적이 "이미 갖고 있는 데이터를 가져오는 것"이다.**
> 어느 데이터베이스를 쓰든 이건 애플리케이션 설계 문제다.

올바른 형태는 조인이 아니라 이렇다:

```js
// 1) contentId 인덱스로 북마크 원본만 읽는다 (itemIds 목록)
const bookmarks = await this.mongoDB.bookmarks.findMany({
    where: { contentId },
    select: { id: true, key: true, itemIds: true, isAll: true, time: true },
});

// 2) 이미 로드된 transcribeResult 에서 메모리로 조립 — DB 왕복 0회
const resolved = bookmarks.map(b => ({
    ...b,
    data: pickByItemIds(transcribeResult[b.key] ?? transcribeResult.aiResult?.[b.key], b.itemIds),
}));
```

**DB 왕복 1회, 인덱스 조회 1회.** `$lookup` 없음, 뷰 없음, 전량 스캔 없음.

#### 30초 증명 — 회의에서 이걸로 끝난다

말싸움 대신 **같은 DB · 같은 데이터 · 같은 인스턴스**에서 A/B 하나면 된다.

```js
// A — 현재 코드 경로 (뷰 경유)
db.BookMarkedView.find({ contentId: "..." }).explain("executionStats")

// B — 원본 직접
db.Bookmarks.find({ contentId: "..." }).explain("executionStats")
```

`totalDocsExamined` 와 `executionTimeMillis` 를 비교한다.

> **A가 수천 건인데 B가 몇 건이면, 두 쿼리 사이에 MongoDB는 아무것도 바뀌지 않았다.**
> **바뀐 건 쿼리를 짠 방식뿐이다.**

뷰 정의 원문을 띄우면 더 명확하다:

```js
db.getCollectionInfos({ name: "BookMarkedView" })   // viewOn + pipeline
```

`viewOn: "TranscribeResult"` 가 찍히는 순간, **"북마크를 읽는데 왜 전사 결과를 스캔하죠?"** 한 문장으로 정리된다.

#### 공정하게 — MongoDB 쪽 한계도 인정하고 가자

MongoDB에 **한계**는 분명히 있다. `$lookup`이 Nested Loop Join 하나뿐이라 Hash/Merge Join으로 갈아탈 수 없고(§5-1), 뷰 파이프라인의 push down도 제약이 많다.

하지만 그건 **문서화된 알려진 동작**이지 결함이 아니다. RDBMS 뷰처럼 생각하고 MongoDB 뷰를 설계한 게 원인이다.

그리고 이게 좋은 소식이다 — **원인이 우리 쪽에 있으면 우리가 고칠 수 있다.**
DB를 교체할 필요도, 서버를 키울 필요도, 데이터를 지울 필요도 없다.

> ### 한 줄
> **MongoDB가 느린 게 아니라, MongoDB가 절대 최적화할 수 없는 형태로 쿼리를 짜뒀다.**

### 5-6. "조인을 앱으로 옮기면 오히려 느려지지 않나?"

정당한 반문이다. **보통은 맞다.** 앱 조인은 대표적인 안티패턴(N+1)이기도 하다.
하지만 이 케이스에서는 빨라진다. 이유가 분명하다.

#### 핵심 — 왕복 횟수가 늘지 않는다

앱 조인이 느려지는 건 **왕복이 1회에서 N+1회로 늘 때**다. 여기선 그런 일이 없다.

| | 현재 (뷰 경유) | 변경 후 (개별 조회 + 앱 매핑) |
|---|---|---|
| DB 왕복 | **1회** | **1회** ← 늘지 않음 |
| 스캔 문서 수 | `TranscribeResult` **전량 (N건)** | `Bookmarks` **인덱스 조회 (수 건)** |
| `$lookup` | N × M (인덱스 없음) | **없음** |
| 전송 데이터 | 조립된 `data` payload | `itemIds` 목록 (수십 바이트) |
| 복잡도 | **O(N × M)** | **O(log N)** |

왕복은 그대로인데 스캔량만 사라진다. **트레이드오프가 없는 개선**이다.

#### 왜 왕복이 안 느는가 — 조인 상대가 이미 메모리에 있다

일반적인 앱 조인은 "A 조회 → B 조회 → 매핑"으로 왕복이 2회다.
그런데 여기서 B(`transcribeResult`)는 **이미 4줄 위에서 읽어 놨다**(`contentDetail.service.js:207`, §5-5 근거 3).

```
현재:   [207] transcribeResult 로드  →  [211] 뷰로 transcribeResult를 다시 조인 ❌
변경:   [207] transcribeResult 로드  →  [211] Bookmarks(itemIds)만 조회 → 메모리 매핑 ✅
```

즉 **조인을 앱으로 "옮기는" 게 아니라, 중복으로 하고 있던 조인을 "없애는" 것**이다.

#### 조인을 없애는 게 아니라 "조인 대상을 1건으로 줄이는" 것

|  | 지금 | 변경 후 |
|---|---|---|
| 순서 | N건 스캔 → 조인 → **마지막에** 1건 고르기 | **먼저** 인덱스로 1건 찾기 → 끝 |

MongoDB의 `$lookup`은 조인 대상 N을 줄이는 것 외에 방어책이 없다(§5-1).
앱에서 짜면 `where`(= `$match`)가 **반드시 먼저** 걸리므로, 그 N이 구조적으로 1이 된다.

#### 제대로 하려면 — 지켜야 할 4가지

이 패턴은 잘못 쓰면 정말로 느려진다. 규칙이 있다.

1. **반드시 `$in` / `IN` 으로 한 번에 조회한다.** 루프 안에서 건별 조회하면 그게 N+1이다
   ```js
   // ✅ 왕복 1회
   await model.findMany({ where: { contentId: { in: ids } } })
   // ❌ 왕복 N회 — 이러면 정말 느려진다
   for (const id of ids) await model.findFirst({ where: { contentId: id } })
   ```
2. **매핑은 `Map`으로 색인한다.** `find`/`filter` 중첩은 O(N×M)이다
   ```js
   const byId = new Map(files.map(f => [f.contentId, f]));   // ✅ O(N+M)
   contents.map(c => byId.get(c.contentId))
   ```
3. **인덱스가 전제조건이다.** 원본을 직접 읽어도 인덱스가 없으면 `COLLSCAN`이다(§5-5 근거 2)
4. **왕복 수가 늘지 않는지 확인한다.** 늘어난다면 그 케이스에선 이 패턴이 답이 아니다

#### 이 패턴이 안 맞는 경우 (공정하게)

- **조인 결과로 대량 필터링·집계**를 해야 할 때 → DB에서 걸러야 전송량이 준다
- **조인 결과 기준으로 페이지네이션**할 때 → 앱에서 자르면 전량을 받아야 한다
- **조인 상대가 매우 클 때** → 앱 메모리로 끌어오면 이벤트 루프가 막힌다

지금 케이스는 셋 다 해당하지 않는다. 단건 조회 · 페이지네이션 없음 · 조인 상대는 이미 메모리.

#### 참고 — 이 저장소에 이미 같은 패턴이 있다

`getContentsResponseWithIds`(`src/services/feature/calendar.service.js:29`)가 정확히 이 구조다.

```js
const [files, sharedUsers, folders] = await Promise.all([   // 조인 대신 개별 조회 3개
    transcribeResultModel.findSpeakerInfosByContentIds(contentIds),
    shareModel.getSharedUsers(contentIds),
    userModel.getFolders(pid),
]);
// → 이후 앱에서 매핑
```

`sharedUsers`는 `reduce`로 해시 색인까지 해 놨다(`:39`). **방식은 이미 팀 안에 있다.**
다만 `files.find(...)`(`:52`)가 `contents.map()` 안에 있어 O(N×M)이다 — 위 규칙 2번 위반. 함께 `Map`으로 바꾸면 된다.

---

## 6. 개선 우선순위

### 즉시 (배포 없이 / 코드 2줄)

| 순위 | 항목 | 위치 | 효과 | 비용 | 위험 |
|---|---|---|---|---|---|
| 0 | **`Bookmarks` 인덱스 생성** — 배포 불필요, 뷰를 그대로 둬도 `$lookup`이 빨라진다 | `db.Bookmarks.createIndex({contentId:1})` / `({fileId:1})` | **큼** | **1줄** | 없음 |
| 1 | **`compression` 미들웨어 추가** | `src/app.js` | 큼 | **2줄** | 없음 |

> 0번은 **오늘 바로** 할 수 있고 롤백도 `dropIndex` 한 줄이다. 2번 수정의 전제조건이기도 하다.

### 구조 수정

| 순위 | 항목 | 위치 | 효과 | 비용 | 위험 |
|---|---|---|---|---|---|
| 2 | `bookMarkedView` → `Bookmarks` 원본 + 메모리 조립 | `bookmark.model.js:49,53` (§5-5) | **큼** | 작음 | 낮음 |
| 3 | `linkedContents`를 조건부 조회로 분리 | `content.model.js:191` / `contentDetail.service.js:121` | 중 | 작음 | 낮음 |
| 4 | `sharedUserProfile` / `contentWithUserProfiles` `EXPLAIN` 후 판단 | `content.model.js:625` 외 | 큼 | **조사** | — |
| 5 | 프론트 `tab` 파라미터 활용 (초기 진입 payload 축소) | `detail.controller.js:21` | 큼 | 프론트 협의 | 중 |
| 6 | `getThumbnails`에 `select` 추가 | `content.model.js:625` | 중 | 작음 | 낮음 |
| 7 | 권한 확인 결과 재사용 (중복 content 조회 제거) | `auth.handler.js:30` ↔ `content.model.js:191` | 중 | 중 | 중 |
| 8 | `transcribeResult: true` → `select` 좁히기 | `attendee.service.js:61,145` 외 | 중 | 작음 | 낮음 |

### 버그 (성능과 별개로 고쳐야 함)

| 순위 | 항목 | 위치 | 성격 |
|---|---|---|---|
| 9 | `updateMergedSegments` 크래시 | `contentDetail.service.js:86` | 500 에러 유발 |
| 10 | `updateMeetingTime` 읽기 중 쓰기 + 응답 불일치 | `contentDetail.service.js:76` | 정합성 |
| 11 | `@@index([segments])` 적정성 검토 | `mongoSchema.prisma` | 쓰기 성능 |

**0·1·2번만 해도 체감이 크게 바뀔 가능성이 높다.** 셋 다 수정 범위가 작고 되돌리기 쉽다.

---

## 7. 검증 절차

가설을 숫자로 확정하는 순서다. **위에서부터 순서대로** 하면 한 단계마다 원인 후보가 줄어든다.

### 7-1. 어디가 긴지부터 분리

DevTools → Network → `Disable cache` → `Ctrl+Shift+R` → Fetch/XHR → `contents/{id}` 요청 → **Timing** 탭

| 긴 항목 | 의미 | 다음 단계 |
|---|---|---|
| **Waiting for server response (TTFB)** | 서버/DB 문제 | §7-2로 |
| **Content Download** | 응답이 너무 큼 | **②번(압축) 확정** — 즉시 조치 |
| **Queueing / Stalled** | 동시 요청 과다 | 프론트 요청 수 점검 |

Response 탭에서 **응답 크기**를 함께 확인한다. 수백 KB인데 `Content-Encoding: gzip`이 없으면 ② 확정이다.

### 7-2. 서버 내부 구간 분리

`contentDetail.service.js`에 임시로 넣는다.

```js
console.time('1_findFile');
let { transcribeResult, highlights = [], ...file } = await contentModel.findFileByContentId(...);
console.timeEnd('1_findFile');

console.time('2_parallel4');
let [[mariaDBContent, shareUsers], bookmarks, memos, contentLifecycleActions] = await Promise.all([...]);
console.timeEnd('2_parallel4');

console.time('3_postProcess');
await postProcessResponse(transcribeResult, mariaDBContent, file);
console.timeEnd('3_postProcess');
```

`2_parallel4`가 지배적이면, 4갈래를 각각 감싸서 어느 갈래인지 특정한다. **(b) 북마크가 튀면 ①번 확정.**

### 7-3. Prisma 쿼리 실측

```bash
DEBUG=prisma:query node ./src/app.js
```

상세 요청 1회에 찍히는 **쿼리 개수**를 센다. §1의 "25~30회" 추정과 대조한다. 예상보다 많으면 ③번이 주범 쪽으로 기운다.

### 7-4. 리전 지연 배제

```js
db.adminCommand({ ping: 1 })
```

데이터 조회가 아닌 **순수 왕복 지연**만 측정한다.
- 1~5ms → 리전 문제 아님. ③의 왕복 20회는 60ms 수준으로 무해
- 200~300ms → **리전 불일치 확정.** ③⑤가 곧바로 주범이 된다 (20회 × 200ms = 4초)

MariaDB도 같이 잰다: `SELECT 1;` 왕복 시간.

### 7-5. 뷰 검증 — 여기서 논쟁이 끝난다

**(1) 뷰 정의 원문 확인** — 30초, 가장 먼저 할 것

```js
db.getCollectionInfos({ name: "BookMarkedView" })
```

`options.viewOn` 과 `options.pipeline` 이 나온다.
`viewOn: "TranscribeResult"` 면 §2-①·§5-2·§5-5가 **전부 확정**된다.

**(2) A/B 비교** — "MongoDB 탓이냐 코드 탓이냐"를 가르는 결정적 실험

같은 DB · 같은 데이터 · 같은 인스턴스에서 두 번 조회한다.

```js
// A — 현재 코드 경로 (뷰 경유)
db.BookMarkedView.find({ contentId: "..." }).explain("executionStats")

// B — 원본 직접
db.Bookmarks.find({ contentId: "..." }).explain("executionStats")
```

| 지표 | A (뷰) | B (원본) | 해석 |
|---|---|---|---|
| `totalDocsExamined` | 수천~수만 | 수 건 | **A만 전량 스캔** |
| `executionTimeMillis` | 수백~수천 ms | 수 ms | 같은 DB인데 차이가 이만큼 |
| `stage` | `COLLSCAN` | `IXSCAN` (인덱스 생성 후) | 인덱스 사용 여부 |

> **MongoDB는 두 쿼리 사이에 아무것도 바뀌지 않았다. 바뀐 건 쿼리를 짠 방식뿐이다.**

주의: **B를 재기 전에 인덱스를 먼저 만들어야 한다.** `Bookmarks`에는 인덱스 선언이 없어서(§5-5 근거 2) 그냥 재면 B도 `COLLSCAN`이 나온다.

```js
db.Bookmarks.createIndex({ contentId: 1 })
```

**(3) 인덱스 현황 확인**

```js
db.Bookmarks.getIndexes()          // _id 만 있으면 §5-5 근거 2 확정
db.TranscribeResult.getIndexes()   // @@index([segments]) 실물 크기도 함께 확인
db.TranscribeResult.stats().indexSizes
```

**(4) MariaDB 뷰 (④번)**

```sql
SHOW CREATE VIEW sharedUserProfile\G
EXPLAIN SELECT * FROM sharedUserProfile WHERE contentId = '...';
```

`DERIVED` / `Using temporary` + `rows` = 전체 건수 → ④번 확정.

**(5) 샤딩 여부 (§5-3 전제 확인)**

```js
sh.status()                  // "not a shard cluster" 면 샤딩 논의 자체가 무효
db.serverStatus().process    // mongos = 샤딩 / mongod = 단일·레플리카셋
```

### 7-6. CPU 배제

요청이 도는 동안 컨테이너 CPU 사용률과 throttling 지표를 본다.
k8s: `container_cpu_cfs_throttled_seconds_total`

→ **CPU가 20%에서 놀고 있는데 느리다면 CPU는 원인이 아니다.** 그 자리에서 반박 가능하다.

### 7-7. 연속 새로고침 3회

| 결과 | 해석 |
|---|---|
| 첫 번째만 느림 | 콜드 스타트 / 커넥션 풀 초기화. **데이터·CPU 문제 아님 확정** |
| 매번 느림 | 요청마다 반복되는 비용 — ①②③④ 쪽 |

`morganMiddleware`(`src/app.module.js:6`)가 이미 응답 시간을 기록한다. **서버 로그 응답시간 vs DevTools TTFB**를 대조하면 게이트웨이/네트워크 구간 지연도 분리된다.

---

## 8. 최종 정리 (회의용)

### 한 줄

> **MongoDB를 RDBMS처럼 쓴 백엔드 설계 문제다.**
> MongoDB가 느린 게 아니라, MongoDB가 절대 최적화할 수 없는 형태로 쿼리를 짜뒀다.

### 무슨 일이 일어난 건가 (한 문단)

사용자가 회의록 상세를 연다. 백엔드는 **그 회의록 1건**을 인덱스로 정확히 읽어 메모리에 올린다. 여기까진 정상이다.
그런데 곧바로 북마크를 가져오려고 `bookMarkedView`를 부른다. 이 뷰는 **회의록 컬렉션 전체를 펼쳐놓고** 각각에 북마크를 붙여본 다음, **맨 마지막에** 해당 콘텐츠 1건을 골라낸다.
회의록이 1,000건이면 999건은 만들자마자 버려진다. 그 과정에서 MongoDB의 CPU와 메모리가 소진되고, 스캔량이 캐시를 넘어가면 디스크 I/O로 떨어지면서 **10~20초**가 된다.

**그리고 그 뷰가 찾으러 간 데이터는, 이미 메모리에 올라와 있던 바로 그 회의록이었다.**

### 원인 — 두 개가 겹쳐 있다

#### 원인 1 — 뷰가 거꾸로 만들어졌다 (①-A)

- 뷰가 `viewOn: TranscribeResult` + `$lookup(Bookmarks)` 구조다. **큰 컬렉션이 바깥 루프**에 있다
- `$lookup`은 Nested Loop Join(이중 for문)이라 **바깥 루프를 줄이는 게 유일한 방어책**인데(§5-1),
- **`TranscribeResult`에는 `contentId` 필드가 아예 없다.** 뷰가 노출하는 `contentId`는 조인된 `Bookmarks` 쪽 값이다
- 그래서 `where: { contentId }`로 바깥 루프를 줄이는 게 **원리적으로 불가능**하다. 옵티마이저가 포기한 게 아니라 밀어넣을 대상이 없다
- 게다가 `Bookmarks`에 **인덱스 선언이 하나도 없어** 안쪽 조회도 전량 스캔이다 → `O(N × M)`

**해결: 뷰 뒤집기** — `viewOn`을 `Bookmarks`로. 그러면 `contentId` 인덱스로 몇 건만 남기고 회의록은 1건만 조회한다.
단 이건 **DB 작업**이다(`db.createView` 재생성). Prisma의 `view` 블록은 타입 선언일 뿐 뷰를 만들지 않는다.

#### 원인 2 — 애초에 그 뷰를 부를 필요가 없다 (①-B)

- 상세 조회는 `contentDetail.service.js:207`에서 **회의록 본문을 이미 읽어 메모리에 갖고 있다**
- 북마크가 필요로 하는 데이터(`mergedSegments`, `speakerInfo`, `summaryTime`, `aiResult` 내부 항목)가 **전부 거기 들어 있다**
- 그런데 4줄 뒤 `:213`에서 뷰를 시켜 **같은 회의록을 다시 읽게** 한다
- 같은 "회의록 읽기"인데 1번째는 인덱스로 1건, 2번째는 전량 스캔이다. **비용이 1 : 1000**

**해결: 뷰 호출 제거** — `Bookmarks`에서 `itemIds`만 읽고, 메모리에 있는 회의록에서 꺼내 조립한다. **소스 수정만으로 된다.**

> **상세 페이지는 원인 2만 고쳐도 해결된다.** 뷰를 안 부르면 뷰가 잘못됐든 상관없기 때문이다.
> 원인 1(뷰 뒤집기)은 대시보드처럼 **회의록을 들고 있지 않은 경로**를 위해 필요하다.

#### 왜 하필 지금 터졌나

**북마크가 0건이던 시절엔 증상이 없었다.** `$unwind`가 빈 결과를 전부 떨어뜨려 뒤 단계가 공짜였기 때문이다.
사용자가 북마크를 **1건이라도** 쓰기 시작하는 순간, 살아남은 문서가 회의록 본문을 실은 채 조립 단계로 진입한다.
여기에 스캔량이 WiredTiger 캐시를 넘으면 메모리 스캔이 디스크 I/O로 떨어진다.

**둘 다 코드 변경 없이 넘어간다.** 그래서 "배포한 것도 없는데 갑자기 CPU가 100% 쳤다"가 성립한다. (§2-①)

### 동반 원인

| | 항목 | 데이터량 영향 |
|---|---|---|
| ② | 응답 압축(gzip) 미적용 — 수백 KB를 그대로 전송 | 없음 (고정) |
| ③ | Prisma 중첩 관계 로딩으로 왕복 25회 이상 | 없음 (고정) |
| ④ | MariaDB 뷰(`sharedUserProfile`) materialization ★미검증 | 선형 |
| ⑤ | 권한 확인이 본 조회 앞에 2단 직렬 + 중복 조회 | 없음 (고정) |

> **메모는 이 브랜치에서 해당 없다.** `memo.model.js`는 MariaDB(`mariaDB.memo`)로 이관돼 MongoDB 뷰를 쓰지 않는다.
> 다만 메모 조회도 Prisma 중첩 관계로 **왕복 8회**를 쓴다(§2-③). 성격이 다른 별개 문제다.

### 원인이 아닌 것 — MongoDB VM의 0.5코어

**증폭기이지 원인이 아니다.**

전량 스캔이 태우는 건 **MongoDB 서버의 CPU와 디스크 I/O**다(백엔드 Node는 그동안 `await`로 기다릴 뿐이다).
그 MongoDB가 0.5코어이니 **같은 스캔이 더 오래 걸리는 건 맞다.**

하지만 코어를 늘려도 **훑어야 할 양은 그대로다.** 일시적으로 나아졌다가 회의록이 늘면 원위치한다.

> 스캔량을 줄이는 게 해결이고, 코어를 늘리는 건 지연이다.

검증: 요청이 도는 동안 백엔드 CPU가 20%에서 놀고 있는데 느리다면 백엔드 CPU는 원인이 아니다(§7-6).

그 외 배제 항목: 요청당 커넥션 재수립 없음(모델 싱글턴), 시크릿 조회 없음(부팅 시 1회), 인증 경로에 외부 HTTP 없음, 상세 조회 본 경로에 반복문 `await` 없음. 상세는 §4.

### 처리 방법

리스크가 낮고 효과가 큰 순서다. **1단계는 오늘 가능하고, 2~3단계면 근본 해결된다.**

#### 1단계 — 인덱스 추가 (DB 작업 · 배포 불필요 · 오늘 가능)

```js
db.Bookmarks.createIndex({ contentId: 1 })
db.Bookmarks.createIndex({ fileId: 1 })
```

- **인덱스는 뷰에 걸 수 없다.** MongoDB 뷰는 저장된 파이프라인일 뿐 데이터가 없다. **원본 컬렉션**에 건다
- 지금 구조(뷰 그대로)에서 실제로 먹는 건 **`$lookup`이 조인 키로 쓰는 필드**다 → `O(N × M)` → `O(N × log M)`
- 뒤집거나 원본 직접 조회로 갈 때 필요한 건 `contentId` 쪽이다
- `Bookmarks`에 둘 다 있으므로 **둘 다 만든다.** 비용이 거의 없고 어느 경로로 가든 하나는 쓰인다
- `TranscribeResult.fileId`는 `@unique`라 이미 인덱스가 있다 — 추가 불필요
- 롤백은 `dropIndex` 한 줄

> 조인 키가 `fileId`인지 `contentId`인지는 `db.getCollectionInfos({name:"BookMarkedView"})`로 확정된다.

#### 2단계 — 응답 압축 (소스 2줄)

```js
import compression from 'compression';
app.use(compression());     // src/app.js
```

수백 KB 응답이 8~10:1로 압축된다. 위험 없음.

#### 3단계 — 원인 2 해결: 뷰 호출 제거 (소스 수정) ★근본 해결

**`bookMarkedView`를 부르는 곳은 세 군데다.** 세 군데 다 원본 `Bookmarks`를 직접 읽으면 된다.

| # | 경로 | 호출 지점 | 회의록이 메모리에 있나 | 필요한 왕복 |
|---|---|---|---|---|
| 1 | **회의록 상세** | `bookmark.model.js:53` ← `contentDetail.service.js:213` | ✅ **있음** (`:207`) | **1회** — 조립만 |
| 2 | **대시보드** | `bookmark.model.js:49` ← `dashboard.service.js:78`, `:168` | ❌ 없음 | **2회** |
| 3 | **북마크 목록 API** (`GET /bookmark`) | `bookmark.model.js:49` ← `bookmark.service.js:55` | ❌ 없음 | **2회** |

```
경로 1 (상세):        Bookmarks 조회 1회  →  메모리의 transcribeResult 에서 조립
경로 2·3 (목록):      Bookmarks 조회 1회  →  TranscribeResult 조회 1회  →  조립
```

경로 2·3은 회의록을 들고 있지 않아 `itemIds`를 실제 내용으로 채우려면 한 번 더 조회해야 한다.
**하지만 둘 다 인덱스 조회다.** 왕복이 2회여도 전량 스캔이 사라지므로 지금보다 압도적으로 빠르다.

```js
// 공통 — 원본에서 itemIds 만 읽는다 (contentId 인덱스)
const bookmarks = await this.mongoDB.bookmarks.findMany({
    where: { contentId: { in: contentIds } },
    select: { id: true, contentId: true, key: true, itemIds: true, isAll: true, time: true, fileId: true },
});

// 경로 2·3 — 회의록을 한 번에 가져와 Map 색인 (§5-6 규칙 1·2)
const trs = await this.mongoDB.transcribeResult.findMany({
    where: { fileId: { in: [...new Set(bookmarks.map(b => b.fileId))] } },
});
const byFileId = new Map(trs.map(t => [t.fileId, t]));

// itemIds → data 조립
bookmarks.map(b => ({ ...b, data: pickByItemIds(byFileId.get(b.fileId), b.key, b.itemIds) }));
```

→ **`$lookup` 없음, 전량 스캔 없음, 뷰 의존 없음.**
→ 뷰를 안 부르므로 **뷰가 잘못돼 있든 상관없다.** 4단계가 불필요해진다.

#### 4단계 — 원인 1 해결: 뷰 뒤집기 (DB 작업) · **선택지**

**3단계를 전부 적용하면 이 단계는 필요 없다.** 뷰를 계속 쓰고 싶을 때의 대안이다.

```js
db.BookMarkedView.drop()
db.createView("BookMarkedView", "Bookmarks", [ /* $lookup → TranscribeResult */ ])
```

- **소스 수정이 아니라 DB 작업이다.** Prisma의 `view` 블록은 타입 선언일 뿐 뷰를 만들지 않는다
- 작업 전 뷰를 참조하는 다른 지점이 없는지 확인할 것
- 장점: 세 경로의 코드를 안 건드려도 된다
- 단점: DB 마이그레이션 절차가 필요하고, 조립 로직이 계속 DB에 남는다

> **권장은 3단계다.** 소스만 고치면 되고, 배포 파이프라인만 타면 되며, 뷰라는 의존 자체가 사라진다.

#### 5단계 — 조사 후 판단

- MariaDB 뷰 `EXPLAIN` (④번 확정, §7-5)
- `linkedContents` 조건부 조회로 분리 (§2-③)
- 프론트 `tab` 파라미터 적용해 초기 payload 축소 (§2-②)

#### 별건 — 버그 수정

- `updateMergedSegments` 크래시 (§3-1) — 조건 충족 시 500
- `updateMeetingTime` 읽기 중 쓰기 + 응답 불일치 (§3-2)

### 증명 절차 (반박이 나오면)

**같은 DB · 같은 데이터 · 같은 인스턴스**에서 두 번 조회한다. 30초면 끝난다.

```js
db.getCollectionInfos({ name: "BookMarkedView" })          // viewOn: TranscribeResult 확인
db.BookMarkedView.find({contentId:"..."}).explain("executionStats")   // A
db.Bookmarks.find({contentId:"..."}).explain("executionStats")        // B
```

A의 `totalDocsExamined`가 수천인데 B가 몇 건이면 — **MongoDB는 두 쿼리 사이에 아무것도 바뀌지 않았다.**

### 예상 질문 대응

**Q. "데이터가 많아져서 느린 거 아니냐"**
→ 증상은 맞고 진단은 틀렸다. 원인은 데이터량이 아니라 **인덱스를 탈 수 없는 구조**다. 인덱스를 타면 데이터가 10배가 돼도 +30%(로그 스케일)인데, 지금은 **10배(선형)**다. 데이터를 정리해도 반드시 재발한다. (§0, §2-①)

**Q. "예전엔 멀쩡했는데 배포한 것도 없이 왜 갑자기?"**
→ 문턱이 둘이다. ①북마크가 0건이면 `$unwind`가 파이프라인을 비워서 뒤 단계가 공짜였다 → 기능이 쓰이기 시작하며 비용 발현. ②스캔 크기가 WiredTiger 캐시를 넘는 순간 메모리 스캔이 디스크 I/O로 떨어진다. **둘 다 코드 변경 없이 넘어간다.** (§2-①)

**Q. "MongoDB는 대용량에 강한데 왜 느리냐"**
→ 대용량에 강한 건 샤딩 기반 **저장·쓰기 확장**이지 조인 성능이 아니다. `$lookup`은 Nested Loop Join 하나뿐이고 Hash/Merge Join이 없어서, 조인 대상을 줄이는 것 외에 방어책이 없다. (§5-1)

**Q. "샤딩하면 되지 않냐"**
→ 샤딩은 조회 가속 기술이 아니다. 샤드 키를 안 쓰는 쿼리는 전 샤드 브로드캐스트다. 샤딩 환경에서 `$lookup`은 샤드 경계를 넘어 **더 느려진다.** 이 서버가 샤딩인지부터 확인해야 한다(`sh.status()`). (§5-3)

**Q. "CPU/코어를 늘리면?"**
→ 전량 스캔의 스캔량은 코어 수와 무관하다. 증폭기지 원인이 아니다. (§7-6)

**Q. "그럼 MySQL로 옮겨야 하나"**
→ 아니다. 조회 속도를 정하는 건 DB 종류가 아니라 인덱스·모델링·네트워크 거리다. **뷰를 거치지 않고 원본을 인덱스로 읽으면 MongoDB 그대로 해결된다.** (§5-5)
