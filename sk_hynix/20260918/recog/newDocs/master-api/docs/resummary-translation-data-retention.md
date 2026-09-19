# 재요약·번역 시 원본 데이터 보존 분석

> 대상: `master-api` / branch `2-release` (`7acc5f5e`)
> 엔드포인트: `POST /contents/:contentId/reSummary` (`src/routes/content.router.js:77`)
> 범위: 이 저장소의 코드만. 프론트엔드·관리자 서비스는 별도 저장소이므로 포함하지 않는다.
> 작성일: 2026-08-26 · 분석 전용 문서이며 코드 수정은 하지 않았다.
> 모든 항목에 `file:line` 근거를 붙였다. ★ 표시는 DB 실측으로 확정해야 하는 항목이다.

---

## 0. 결론

| 데이터 | 저장 위치 | 재요약(언어 변경) 시 | 원본 보존 |
|---|---|---|---|
| **STT 원문** `segments` / `mergedSegments` | Mongo `transcribeResult` | 건드리지 않음 | ✅ **유지** |
| **요약문** `aiResult` | Mongo `transcribeResult` | 통째로 교체 | ❌ **소실 (복구 불가)** |
| **제목** `title` | MariaDB `Content` | 덮어씀 | ❌ 소실 |
| **키워드** `hashTag` | MariaDB `Content` | 덮어씀 | ❌ 소실 |
| **노트** `note` | Mongo `note` | **새 행 생성** | ⚠️ 남지만 조회가 불안정 (§5) |

**한 줄 요약: STT 원문은 안전하다. 없어지는 건 요약문이다. 그리고 노트는 새로 만들어지지만 화면에 반영된다는 보장이 코드에 없다.**

---

## 1. 재요약·번역을 하면 STT 원문이 통째로 다른 언어로 바뀌는가?

### 결론: 바뀌지 않는다. 단, 관리자 토글 하나가 조건이다.

#### ① 재요약의 `lang`은 "요약 출력 언어"일 뿐이다

요청 본문의 `lang`은 `auth.config.transcribeLang`에 실려 넘어간다.

```js
// src/controller/content/features/summary.controller.js:31
const { size = 'large', lang = 'ko', templateId = 'DEF-DEFAULT-BASIC' } = req.body;
// :35
auth.config.transcribeLang = lang;
```

이 값은 요약기까지 전달되어 **`output_lang`으로만 쓰인다** (`src/utils/summarizer/skaxTemplate.js:115`). 필드명이 `transcribeLang`이라 STT 언어처럼 보이지만, 재요약 경로에서는 요약 결과물의 언어를 지정하는 용도다.

#### ② 요약 완료 시 저장하는 필드에 세그먼트가 없다

```js
// src/services/engine/llm.service.js:17
manager.transUpdater({
    aiResult,
    summaryTime,
    summarySize,
    completeAt: new Date(),
    status: 'SUMMARY_DONE',
})
```

`segments` / `mergedSegments`가 들어 있지 않다. 즉 **STT 원문은 그대로 두고 요약문만 새 언어로 교체된다.**

#### ③ 예외 — `use_resummary_stt` 토글이 켜져 있으면 원문이 교체된다

```js
// src/services/content/content.service.js:396
const includeStt = await this.userModel.getWorkspaceBooleanSetting(workspaceId, 'use_resummary_stt');
if (includeStt) { ... }   // :398
```

이 분기를 타면:

1. `transcribeResultModel.upsert()`가 기존 행의 `ticket` / `status` / **`clientLanguage`를 새 lang으로 리셋**한다 (`src/services/engine/recog.service.js:103`, `src/models/transcribeResult.model.js:30`)
2. STT 완료 후 **`segments` / `mergedSegments` / `speakerInfo`를 통째로 교체**한다

```js
// src/services/engine/recog.service.js:54
await manager.transUpdater({ ...segmentInfo, status: 'STT_DONE' });
```

`transcribeResult`는 `fileId`가 unique라 **파일당 1행**이고, 이전 원문을 백업하는 필드나 컬렉션이 없다. 이 경로에서는 원문이 복구 불가로 사라진다. 메모·북마크도 함께 삭제된다 (`src/services/content/content.service.js:418`).

#### ④ 원문을 번역해서 저장하는 별도 기능은 없다

`langRefineTranslation` 프롬프트를 쓰는 곳은 문장 교정(`src/services/content/features/proofreading.service.js`)인데, 번역이 아니라 한국어 다듬기이고 **`mergedSegments`만 in-place 수정**한다. 원본 `segments`는 남아 있어 `resetSegments`로 재생성 가능하다 (`src/services/content/content.service.js:482`).

---

## 2. `use_resummary_stt`가 켜진 워크스페이스 조회 쿼리

값은 MariaDB `WorkspaceSetting`에 key/value **문자열**로 저장되고, 코드는 `value === 'true'`일 때만 On으로 본다.

```js
// src/models/user.model.js:428
async getWorkspaceBooleanSetting(workspaceId, key) {
    if (!workspaceId) return false;
    const setting = await this.mariaDB.workspaceSetting.findFirst({ where: { workspaceId, key }, select: { value: true } });
    return setting?.value === 'true';   // 행 없음 → undefined === 'true' → false
}
```

### 켜진 워크스페이스만

```sql
SELECT w.id AS workspaceId, w.domain, s.value
FROM WorkspaceSetting s
JOIN Workspace w ON w.id = s.workspaceId
WHERE s.key = 'use_resummary_stt'
  AND s.value = 'true';
```

### 전체 워크스페이스의 On/Off 상태

행이 없으면 기본값 Off이므로 LEFT JOIN으로 본다.

```sql
SELECT w.id AS workspaceId, w.domain,
       COALESCE(s.value, 'false') AS useResummaryStt
FROM Workspace w
LEFT JOIN WorkspaceSetting s
       ON s.workspaceId = w.id AND s.key = 'use_resummary_stt'
ORDER BY useResummaryStt DESC, w.id;
```

> `key`는 MySQL/MariaDB 예약어다. `s.key`처럼 별칭을 붙이거나 백틱으로 감싼다.

### Prisma

```js
await prisma.workspaceSetting.findMany({
  where: { key: 'use_resummary_stt', value: 'true' },
  select: { workspaceId: true, value: true },
});
```

★ 테이블명은 이 저장소의 다른 raw 쿼리가 `ContentCapture`, `ContentWithUserProfiles`처럼 PascalCase 모델명을 그대로 쓰는 것에 근거해 `WorkspaceSetting` / `Workspace`로 잡았다. 스키마는 `@timbel-timblo-onpremise/prisma` 패키지 내부에 있고 분석 시점에 `node_modules`가 설치돼 있지 않아 `@@map` 여부는 확인하지 못했다. 안 맞으면 `SHOW TABLES LIKE '%orkspace%';`로 실제 이름을 확인한다.

---

## 3. 그 토글은 어디서 설정하는가?

### 결론: 이 저장소에는 쓰는 코드가 없다. 그리고 관리자 사이트에도 해당 기능이 없다.

- `use_resummary_stt`는 `src/services/content/content.service.js:396` **한 곳에서 읽기만** 한다
- `WorkspaceSetting`을 다루는 코드는 `src/models/user.model.js`의 조회 4개(`findFirst` / `findMany`)뿐이고 `create` / `update` / `upsert`가 **전혀 없다**
- 같은 계열 키(`email_content_summary`, `enforce_agreement`, `use_notification_setting`)도 동일하게 읽기 전용이다

즉 워크스페이스 설정을 저장하는 주체는 별도의 관리자 서비스이고, master-api는 소비자 쪽이다. **그런데 현재 관리자 사이트에 이 토글을 켜는 UI가 없다.**

### 이것이 의미하는 것

`WorkspaceSetting`에 `use_resummary_stt` 행 자체가 존재하지 않으므로 `getWorkspaceBooleanSetting`은 항상 `false`를 반환한다. 따라서:

- 실제 운영에서는 **늘 "기존 STT 결과로 요약만 재수행" 경로만 탄다**
- §1-③의 원문 교체 경로는 **코드에는 있지만 켤 수단이 없어 사실상 비활성 상태**다
- 누군가 DB에 직접 `INSERT` 하지 않는 한 발동하지 않는다

§2의 조회 쿼리 결과가 0건이면 확정이다.

---

## 4. 한국어 요약문을 영어로 재요약하면 원본 요약문이 남는가?

### 결론: 남지 않는다. 복구 불가다.

```js
// src/services/engine/llm.service.js:17
manager.transUpdater({ aiResult, summaryTime, summarySize, completeAt: new Date(), status: 'SUMMARY_DONE' })
```

`transUpdater` → `transcribeResultModel.updateStatus` → `mongoDB.transcribeResult.update`로 이어진다. `transcribeResult`는 파일당 1행이고 `aiResult` 필드를 통째로 set 하므로 **기존 한국어 요약문은 그 자리에서 사라진다.** 이전 버전을 담는 필드도, 별도 컬렉션도 없다.

### 함께 덮어써지는 것

```js
// src/utils/transcribe.util.js:120
async contentUpdater({ keywords = [] }, title = '') {
    const targetData = { hashTag: keywords, title, transcribeStatus: 'DONE' };
    await contentModel.updateContent({ contentId: this.contentId }, targetData);
}
```

제목과 키워드도 MariaDB `Content`에서 새 언어 값으로 교체된다 (`src/services/engine/llm.service.js:16`에서 호출).

### 이력에도 본문은 없다

`reSummaryHistory` 테이블은 `contentId`, `requesterId`, `summarySize`, `requestedAt`만 기록한다 (`src/models/reSummaryHistory.model.js:7`). **"언제 누가 어떤 크기로 재요약했다"는 남지만 이전 요약문 텍스트는 남지 않는다.**

원문 대조가 필요하면 재요약 전에 `aiResult`를 스냅샷으로 남기는 처리가 별도로 필요하다.

---

## 5. 노트는 업데이트인가, 새 행 생성인가? 화면에는 무엇이 노출되는가?

### 결론: 새 행 생성이 맞다. 그리고 화면에는 기존 노트가 계속 노출될 개연성이 높다.

#### ① 저장은 `create`다

재요약 완료 시 `createNote(contentId, note)`를 무조건 호출한다 (`src/services/engine/llm.service.js:15`). 그 끝은 이렇다.

```js
// src/models/note.model.js:67
const newNote = await tx.note.create({ data: { contentId, noteName: `${fileName}_note`, content } });
const file = await tx.file.update({ where: { id: fileId }, data: { linkNoteId: newNote.id } });
```

`update`가 아니라 `create`이므로 **같은 `contentId`에 노트 행이 하나 더 쌓인다.** 링크(`linkNoteId`)는 새 노트를 가리키게 바뀐다.

#### ② 그런데 `linkNoteId`를 읽는 코드가 없다 — 이게 핵심이다

`linkNoteId`를 전수 검색하면 **쓰는 곳 2군데뿐이고 읽는 코드가 0개**다. 나머지 1건은 Swagger 스키마 문서(`src/docs/schemas/dataSchemas.js:2352`)다.

| 위치 | 동작 |
|---|---|
| `src/models/note.model.js:83` | 쓰기 (재요약·최초 노트 생성) |
| `src/models/note.model.js:127` | 쓰기 (나만의 노트 생성) |
| `src/docs/schemas/dataSchemas.js:2352` | 문서 정의 |
| — | **읽는 코드 없음** |

정작 조회는 이렇게 한다.

```js
// src/models/note.model.js:12
return await this.mongoDB.note.findFirst({ where: { contentId }, ... });   // orderBy 없음
```

`contentId`로만 찾고 **정렬 지정이 없다.** 노트가 2건 이상이면 MongoDB natural order로 먼저 저장된 행, 즉 **기존(한국어) 노트가 반환될 가능성이 높다.** 엄밀히는 정렬 미지정이라 비결정적이며, 어느 쪽이든 "새 노트를 보여준다"는 보장이 코드에 없다.

호출 경로: `GET /contents/:contentId/note` (`src/routes/content.router.js:53`) → `noteService.getNoteContent` (`src/services/content/features/note.service.js:18`) → 위 `findFirst`.

#### ③ 예상되는 두 가지 증상

1. **재요약해도 노트가 안 바뀐 것처럼 보인다** — 새 노트는 생성됐는데 조회가 옛 행을 집는다
2. **고아 노트가 누적된다** — 재요약할 때마다 `note` 행이 하나씩 늘어난다

★ 확인 방법: 문제가 보고된 `contentId`로 `db.note.find({ contentId: "..." })`를 세어 본다. 2건 이상이면 확정이다.

#### ④ 수정 방향 (미적용 — 참고용)

| 안 | 내용 | 장점 | 확인 필요 |
|---|---|---|---|
| **A (권장)** | 재요약 경로에서 `create` 대신 기존 노트 `content`를 update | 노트 1:1 유지, 고아 미발생 | 사용자가 손으로 편집한 노트를 재요약이 덮어쓰는 정책이 맞는지 |
| B | 조회를 `linkNoteId` 기준으로 변경 | 노트 이력 보존 | 기존 데이터 중 `linkNoteId`가 비어 있는 건의 폴백 |

---

## 6. 확인용 쿼리 — MariaDB / MongoDB

이 서비스는 **두 DB를 나눠 쓴다.** 확인도 두 단계로 갈린다.

| DB | 담당 데이터 | 이 문서에서 확인할 것 |
|---|---|---|
| **MariaDB** | 워크스페이스 설정, 콘텐츠 메타(제목·키워드), 재요약 이력 | 토글 상태, 재요약된 콘텐츠 목록 |
| **MongoDB** | STT 원문, 요약문(`aiResult`), 노트 | 원문 보존 여부, 요약 언어, 노트 중복 |

**확인 순서: MariaDB에서 대상 `contentId`를 뽑고 → 그 값으로 MongoDB를 본다.** `transcribeResult`에는 `contentId`가 없고 `fileId`만 있으므로, Mongo 안에서도 `File` → `TranscribeResult` 순으로 타고 들어가야 한다 (`src/models/content.model.js:240`).

---

### 6-A. MariaDB

```bash
mysql -h <HOST> -u <USER> -p <DB_NAME>
```

#### A-1. 실제 테이블명 확인 (★1)

Prisma `@@map`이 걸려 있으면 아래 쿼리의 테이블명이 다를 수 있다. **가장 먼저 이것부터 확인한다.**

```sql
SHOW TABLES LIKE '%orkspace%';
SHOW TABLES LIKE '%eSummary%';
DESC WorkspaceSetting;
```

#### A-2. `use_resummary_stt` 토글 상태 (★2) — 가장 중요

```sql
-- 켜진 워크스페이스만
SELECT w.id AS workspaceId, w.domain, s.value
FROM WorkspaceSetting s
JOIN Workspace w ON w.id = s.workspaceId
WHERE s.key = 'use_resummary_stt'
  AND s.value = 'true';
```

**결과가 0건이면 §3의 결론이 확정된다** — 원문 교체 경로는 발동한 적이 없다.

행 자체가 아예 없는지도 같이 본다. `value`가 `'false'`인 행이 있다면 과거에 UI나 스크립트로 건드린 이력이 있다는 뜻이다.

```sql
SELECT workspaceId, s.value, COUNT(*) AS cnt
FROM WorkspaceSetting s
WHERE s.key = 'use_resummary_stt'
GROUP BY workspaceId, s.value;
```

#### A-3. 워크스페이스별 전체 설정 현황

토글 UI가 없는 다른 키들도 같이 보면 어떤 키가 실제로 세팅되고 있는지 파악된다.

```sql
SELECT s.key AS settingKey, s.value, COUNT(*) AS workspaceCount
FROM WorkspaceSetting s
GROUP BY s.key, s.value
ORDER BY settingKey;
```

#### A-4. 재요약된 콘텐츠 목록 뽑기 → MongoDB 조사 대상

노트 중복(§5)을 확인하려면 **재요약을 실제로 겪은 `contentId`**가 필요하다. 여기서 뽑는다.

```sql
SELECT h.contentId,
       COUNT(*)          AS reSummaryCount,
       MIN(h.requestedAt) AS firstAt,
       MAX(h.requestedAt) AS lastAt
FROM ReSummaryHistory h
GROUP BY h.contentId
HAVING reSummaryCount >= 1
ORDER BY reSummaryCount DESC, lastAt DESC
LIMIT 20;
```

`reSummaryCount`가 큰 `contentId`일수록 노트가 많이 쌓여 있어야 정상이다. 이 목록을 6-B에서 그대로 쓴다.

#### A-5. 제목·키워드가 어떤 언어로 남아 있는지

재요약으로 제목이 덮어써졌는지(§4) 눈으로 확인한다.

```sql
SELECT c.contentId, c.title, c.hashTag, c.transcribeStatus, c.updateAt
FROM Content c
JOIN ReSummaryHistory h ON h.contentId = c.contentId
GROUP BY c.contentId
ORDER BY c.updateAt DESC
LIMIT 20;
```

한국어 회의인데 `title`이 영어라면 영어로 재요약된 건이다.

---

### 6-B. MongoDB

```bash
mongosh "mongodb://<USER>:<PASS>@<HOST>:27017/<DB_NAME>"
```

#### B-1. 실제 컬렉션명 확인 (★1)

```js
show collections
```

★ Prisma 모델명이 그대로 컬렉션명이 되므로 `File`, `TranscribeResult`, `Note`로 잡았다. 다를 경우 아래 쿼리의 컬렉션명을 바꿔서 쓴다.

#### B-2. contentId → fileId 확보 (모든 조회의 출발점)

```js
const CID = "여기에_contentId";

db.File.findOne(
  { contentId: CID },
  { _id: 1, contentId: 1, fileName: 1, linkNoteId: 1 }
)
```

여기서 나온 `_id`가 `fileId`이고, `linkNoteId`가 **재요약이 마지막으로 연결한 노트**다.

#### B-3. STT 원문이 보존됐는지 (§1 검증)

```js
const FID = "위에서_나온_id";

db.TranscribeResult.findOne(
  { fileId: FID },
  {
    clientLanguage: 1,          // STT 당시 언어
    engine: 1,
    status: 1,
    completeAt: 1,
    segmentCount:      { $size: { $ifNull: ["$segments", []] } },
    mergedSegmentCount:{ $size: { $ifNull: ["$mergedSegments", []] } },
    firstSegment:      { $slice: ["$mergedSegments", 1] }   // 원문 언어 육안 확인
  }
)
```

**`firstSegment`의 `text`가 한국어면 원문이 그대로 살아 있는 것이다.** `clientLanguage`가 `ko`인지도 같이 본다. 재요약을 여러 번 한 콘텐츠에서도 한국어면 §1 결론이 확정된다.

#### B-4. 요약문이 어떤 언어로 덮어써졌는지 (§4 검증)

```js
db.TranscribeResult.findOne(
  { fileId: FID },
  { "aiResult": 1, summaryTime: 1, summarySize: 1, completeAt: 1 }
)
```

`aiResult` 안에 **이전 한국어 요약을 담은 키가 없다는 것**을 눈으로 확인한다. 키가 하나뿐이면 통째로 교체된 것이 맞다.

#### B-5. 노트가 몇 개 쌓였는지 (★3) — §5의 핵심

```js
db.Note.find(
  { contentId: CID },
  { _id: 1, noteName: 1, content: { $substrCP: ["$content", 0, 80] } }
).toArray()
```

**2건 이상이면 §5의 "새 행 생성" 구조가 실증된다.** 재요약 횟수(6-A-4의 `reSummaryCount`)+1 만큼 있어야 계산이 맞는다.

#### B-6. 화면에 어떤 노트가 나오는지 (★4) — 결정적 확인

백엔드 조회는 정렬 없는 `findFirst`다 (`src/models/note.model.js:12`). **같은 조건을 그대로 재현해서 `linkNoteId`와 비교한다.**

```js
// 백엔드가 실제로 집어오는 행 (orderBy 없음 = natural order)
const shown = db.Note.findOne({ contentId: CID }, { _id: 1, noteName: 1 });

// 재요약이 마지막으로 연결한 행
const linked = db.File.findOne({ contentId: CID }, { linkNoteId: 1 });

print("화면 노출:", shown._id, " / 최신 연결:", linked.linkNoteId);
```

**두 값이 다르면 버그가 확정된다** — 새 노트가 만들어졌는데 화면에는 옛 노트가 나오고 있다는 뜻이다.

#### B-7. 전체 범위에서 고아 노트 스캔

개별 확인이 끝나면 얼마나 퍼져 있는지 본다.

```js
db.Note.aggregate([
  { $group: { _id: "$contentId", noteCount: { $sum: 1 } } },
  { $match: { noteCount: { $gt: 1 } } },
  { $sort:  { noteCount: -1 } },
  { $limit: 20 }
])
```

여기 걸리는 `contentId` 수가 **영향받은 회의록 규모**다.

#### B-8. 원문이 교체된 흔적이 있는지 (§1-③ 역추적)

토글이 실제로 켜진 적이 있었다면 `clientLanguage`가 `ko`가 아닌 행이 남아 있을 수 있다.

```js
db.TranscribeResult.aggregate([
  { $group: { _id: { lang: "$clientLanguage", engine: "$engine" }, cnt: { $sum: 1 } } },
  { $sort:  { cnt: -1 } }
])
```

`ko` 외 언어가 있다면 업로드 시 지정된 것인지, 재요약으로 리셋된 것인지 해당 건의 `File.createAt`과 `ReSummaryHistory`를 대조해서 구분한다.

---

## 7. 미확인 항목 체크리스트

| # | 항목 | 확인 위치 | 판정 기준 |
|---|---|---|---|
| ★1 | 실제 물리 테이블/컬렉션명 (`@@map` 여부) | 6-A-1 / 6-B-1 | 이름이 다르면 이하 쿼리 수정 |
| ★2 | `use_resummary_stt` 행이 실제로 0건인지 | 6-A-2 | **0건 → 원문 교체 경로 미발동 확정** |
| ★3 | 재요약된 콘텐츠의 `Note` 행이 2건 이상인지 | 6-B-5 | **2건 이상 → 새 행 생성 구조 실증** |
| ★4 | `findFirst`가 실제로 어느 노트를 반환하는지 | 6-B-6 | **`linkNoteId`와 불일치 → 버그 확정** |
| ★5 | STT 원문이 한국어로 남아 있는지 | 6-B-3 | 한국어 → §1 결론 확정 |
