# 회의록 상세 진입 지연 — API 2건 확인

프론트엔드팀 문의(2026-08-20)에 대한 확인 결과. 대상은 아래 두 API 다.

| | API | 성격 |
|---|---|---|
| ① | `GET /api/contents/{contentId}` | 상세 화면 전체를 그리는 단일 응답 |
| ② | `POST /api/contents/{contentId}/stream-grant` | 재생·다운로드용 콘텐츠별 인증 쿠키 발급 |

조사는 `release` 브랜치 코드 기준이다.
**응답 시간은 실측하지 않았다.** 서버에 구간별 계측이 없어 평균·최악값이 존재하지 않는다.
아래 내용 중 시간에 관한 서술은 전부 구조 분석이며, 측정치가 아니다.

---

## 결론

1. 두 API 는 무게가 완전히 다르다. **①은 세그먼트 수에 비례해 무겁고, ②는 DB 1회 + 서명 1회**다.
   10초 지연의 원인은 ②가 아니다.
2. ①에는 **외부 스토리지(MinIO/S3) 호출도, 타 서비스 HTTP 호출도 없다.** 전부 DB 다.
3. 병목 후보는 두 곳 — **전사 결과 문서 전체 읽기**, 그리고 **북마크·메모 view**(미확인).
4. 프론트는 서버 배포를 기다리지 않고 **`tab` 파라미터**로 전사 전문을 분리해 받을 수 있다.

---

## 1. ① `GET /api/contents/{contentId}`

### 1-1. 요청 1건의 처리 순서

라우터 `src/routes/content.router.js:38` → 컨트롤러 `src/controller/content.controller.js:308` →
서비스 `src/services/contentDetail.service.js:170`

```
① 인증 미들웨어                                      Redis 1 + MariaDB 1   [직렬]
   authorize.handler.js:42   redis.get(accessTokens:<token>)
   authorize.handler.js:60   memberModel.findMemberByPID

② 콘텐츠 접근 권한 확인 (뷰어 이상)                  MariaDB 1             [직렬]
   content.controller.js:330 → auth.handler.js:36
   member.model.js:23        findMemberContentByIdAndCreatorId

③ 전사 결과 문서 로드                                MongoDB 1             [직렬]  ★세그먼트 비례
   contentDetail.service.js:175 → content.model.js:93
   file.findFirst({ include: { highlights, transcribeResult: { select } } })

④ 아래 5건 동시 실행                                 MariaDB 3 + MongoDB 2 [병렬]
   contentDetail.service.js:179  Promise.all
     · content.model.js:137   findContentById (작성자·편집자 프로필 포함)   MariaDB
     · content.model.js:525   getThumbnails → sharedUserProfile           MariaDB
     · bookmark.model.js:52   bookMarkedView.findMany                     MongoDB view  ★의심
     · memo.model.js:34       memoView.findMany                           MongoDB view  ★의심
     · lifecycle.model.js:47  lifecycleTask.findMany                      MariaDB

⑤ 화자 프로필 매칭                                   MariaDB 1             [직렬]
   contentDetail.service.js:94 → attendee.service.js:34 → user.model.js:27

⑥ JSON 직렬화 + 이미지 URL 정규화                    CPU                   [직렬]  ★세그먼트 비례
   app.js:29  json replacer → urlResolver.js:60 (응답 전 키 순회)
```

DB 왕복 9회, 직렬 단계 4개. **외부 스토리지 호출 0, 타 서비스 HTTP 0.**

### 1-2. 세그먼트 수에 비례하는가 — 비례한다, 3곳

**(1) 전사 결과 문서 읽기 — 지배적**

Mongo `TranscribeResult` 한 문서 안에 `segments`(원본)와 `mergedSegments`(30초 병합)가
**둘 다 임베드**돼 있다 (사내 prisma 패키지 `mongoDB/schema.prisma`).
`getFileIncludeOptions` 가 `mergedSegments` 만 select 해도, MongoDB 는 문서 전체를
디스크→메모리로 읽는다. 이 비용은 select 와 무관하게 발생한다.
1시간 회의면 문서 하나가 수 MB 규모다(BSON 16MB 한계에 근접 가능).

**(2) 응답 직렬화** — `mergedSegments` 전량이 JSON 으로 나간다.

**(3) json replacer** — `urlResolver.js:60` 이 응답의 모든 키를 순회한다. O(전체 노드 수).

> **원본 `segments` 는 응답에 포함되지 않는다.**
> `contentDetail.service.js:139` 에서 `select.segments` 가 주석 처리돼 있다.
> 프론트가 받는 전사 전문은 `mergedSegments` 하나뿐이다 — 두 벌이 나가는 게 아니다.

### 1-3. 지연 구간 — 1순위 의심은 북마크·메모 view (미확인)

`BookMarkedView` / `MemoView` 는 Prisma `view` = **MongoDB view** 다.
원본 `Bookmarks` / `Memo` 컬렉션에 없는 `data Json[]` 필드를 갖고 있다 →
view 파이프라인이 다른 컬렉션을 `$lookup` 으로 조인해 채운다는 뜻이다.
**조인 대상이 `transcribeResult` 라면 북마크·메모 조회에도 세그먼트 비례 비용이 붙는다.**

추가로 원본 `Bookmarks` / `Memo` 컬렉션에는 `contentId` 인덱스가 **없다**.

파이프라인 정의가 DB 안에 있어 코드로는 확인 불가. 운영 Mongo 에서 확인해야 한다.

```js
db.getCollectionInfos({ name: 'BookMarkedView' })
db.getCollectionInfos({ name: 'MemoView' })
```

### 1-4. 스키마 부수 사항 — `@@index([segments])`

`TranscribeResult` 에 세그먼트 배열 전체를 대상으로 하는 multikey 인덱스가 걸려 있다.
세그먼트 1개당 인덱스 엔트리 1개(본문 텍스트 포함)가 생긴다.
읽기에 직접 영향은 작지만 인덱스 크기와 쓰기 비용을 크게 부풀린다.
STT 완료 시점 쓰기와 WiredTiger 캐시 압박을 통해 간접 영향 가능. **미검증.**

### 1-5. 프론트가 지금 쓸 수 있는 것 — `tab` 파라미터

`content.controller.js:319` 에 이미 부분 조회가 있다.
지정 가능: `segments` `speakerInfo` `aiResult` `summaryTime` `bookmarks` `file` `memos` (콤마 연결)

```
# 1차 — 화면 골격 + 요약/북마크/메모 (전사 전문 제외)
GET /api/contents/{id}?tab=aiResult,speakerInfo,summaryTime,bookmarks,memos,file

# 2차 — 우측 음성기록 패널
GET /api/contents/{id}?tab=segments,aiResult
```

주의 두 가지:

- **`tab=segments` 단독은 500.** `postProcessResponse` 가 `aiResult.manualTag` 에 접근하는데
  `aiResult` 를 select 하지 않아 TypeError (`contentDetail.service.js:99`).
  수정 전까지는 `aiResult` 를 반드시 함께 지정해야 한다.
- **DB 왕복 수는 줄지 않는다.** `tab` 을 지정해도 ④ 병렬 5건은 그대로 실행된다
  (early return 은 `:177` `file` 단독, `:195` `bookmarks` 단독, `:199` `memos` 단독뿐).
  줄어드는 것은 응답 크기와 직렬화 비용이다.

### 1-6. 500 유발 케이스 2건

| 위치 | 조건 | 증상 |
|---|---|---|
| `contentDetail.service.js:99` | `tab=segments` 단독 | `aiResult` 미select → TypeError |
| `contentDetail.service.js:88` | `mergedSegments` 가 빈 콘텐츠 | `segments` 미select 인데 `segments.forEach` → TypeError |

두 번째가 특히 문제다. 프론트가 "무한 로딩"으로 보고 있는 것 중 일부가 이 500 일 수 있다.
재현 `contentId` 확보 필요.

부수적으로 확인된 것들 (별건, 우선순위 낮음):

- `contentDetail.service.js:170-176` — `if (!file)` 가드가 도달 불가.
  rest 객체라 falsy 가 될 수 없고, `findFileByContentId` 가 null 이면 구조분해에서 먼저 터진다.
- `contentDetail.service.js:89`, `:203` — await 되지 않는 promise
  (Mongo 쓰기 / MariaDB 4쿼리 체인). 응답 이후로 새는 unhandled rejection.

---

## 2. ② `POST /api/contents/{contentId}/stream-grant`

배경과 설계 의도는 `ARCHITECTURE.md` 4-3 "스트리밍 신원 격리" 참고.

### 2-1. 하는 일

`content.controller.js:193-227`

1. **MariaDB 1회** — `checkStreamAuth(range:true)` → 뷰어 이상 권한 확인
   (`auth.handler.js:74` → `isMoreThanContentViewer`)
2. **JWT HS256 서명 1회** — payload `{ pid, email, contentId, purpose:'stream' }`, `expiresIn: '10m'`
   (`streamGrant.util.js:25`)
3. **쿠키 설정** — `streamGrant_<contentId>`, httpOnly · secure · sameSite=lax ·
   path `/api/contents/download` · maxAge 10분

**외부 스토리지 호출 없음. 타 서비스 HTTP 없음. Redis 접근 없음**
(공통 미들웨어의 Redis 1회는 전 API 공통이라 이 API 고유 비용이 아니다).

성능 목적이 아니라 **신원 정확성** 장치다. `<audio src>` 는 커스텀 헤더를 못 실어
게이트웨이가 주입한 전역 세션 토큰으로 인증되는데, 한 브라우저에서 SSO 로그인과
일반 로그인을 병행하면 그 세션 신원이 "그 탭의 계정"이 아닐 수 있다.

### 2-2. 응답 시간

**미측정.** 구조상 ①과 비교 대상이 아닐 만큼 가볍다 — DB 1회 + 서명 1회.
체감될 정도로 느리다면 원인은 grant 로직이 아니라 공통 인증 미들웨어나 게이트웨이다.

### 2-3. 호출 시점 — 재생 클릭 시점이 맞다

JWT 만료 10분(`streamGrant.util.js:18`), 쿠키 maxAge 10분(`content.controller.js:224`).
**둘 다 10분**이라, 상세 진입 시 발급받고 10분 넘게 보다가 재생하면 이미 만료다.
진입 시점 발급은 이득 없이 만료 위험만 만든다.

- 재생 버튼 클릭 시점에 발급
- 긴 회의 재생 대비 약 8분 주기 재발급(또는 다음 재생·탐색 직전 갱신)
- 호출 시 `withCredentials: true` 필요 (서버는 `app.js:53` `cors({ credentials: true })`)

### 2-4. 발급 실패 시 폴백 — 있다

`streamGrant.handler.js` 는 best-effort 다. 쿠키가 없거나 · 서명 불일치 · 만료면
아무것도 하지 않고 `next()` → 게이트웨이가 주입한 세션 토큰으로 기존대로 인증된다.
**grant 발급이 실패해도 재생은 동작한다.**

영향받는 경우는 이 기능이 해결하려던 상황 하나뿐이다 —
한 브라우저에서 SSO 로그인과 일반 로그인 병행 중일 때 401·403 가능.

→ **프론트는 ②의 실패로 상세 화면이나 재생을 막을 필요가 없다.**
실패는 넘기고 재생을 시도한 뒤, 재생이 실제로 401·403 이면 그때 안내하는 편이 낫다.

### 2-5. 참고 — 재생과 다운로드의 권한 기준이 다르다

`content.controller.js:179` 가 `headers` 를 그대로 넘겨 `{ range }` 를 읽는다.

- `Range` 헤더 있음(오디오 재생) → **뷰어 이상**
- `Range` 헤더 없음(전체 다운로드) → **다운로더 이상** (`auth.handler.js:75`)

---

## 3. 프론트 자체 조치 예정 항목에 대한 코멘트

세 가지 모두 맞는 방향이다.

| 항목 | 코멘트 |
|---|---|
| ① 3회 중복 호출 → 1회 | 효과가 가장 확실하다. 1건이 DB 9회 + 수 MB 문서 읽기라 3회면 그대로 3배 |
| ②를 로딩 완료 조건에서 분리 | 필수. 나아가 재생 클릭 시점으로 미루면 만료 위험까지 함께 해소 (2-3) |
| axios 타임아웃 + 에러 화면 | 필요. 값은 실측 회신 전까지 넉넉히. 상태 코드를 구분 표시해 주면 500 케이스 식별이 빨라진다 (1-6) |

---

## 4. 백엔드 후속 작업

| | 작업 | 목적 |
|---|---|---|
| 1 | ①에 구간별 `durationMs` 계측 추가 | 회의 길이 구간별 평균·최악값 측정 → 미답변 해소 |
| 2 | `BookMarkedView` / `MemoView` 파이프라인 확인 | 지연 1순위 의심 구간 검증 (1-3) |
| 3 | 500 유발 케이스 2건 수정 | `tab=segments` 단독 / `mergedSegments` 빈 콘텐츠 (1-6) |
| 4 | `TranscribeResult` 문서 구조 개선 검토 | 원본·병합 세그먼트 동거로 읽기 비용이 항상 최대치 (1-2) |
