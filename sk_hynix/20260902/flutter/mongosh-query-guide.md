# 몽고 쉘 야전교범

> 웹 버전(모바일에서 보기 좋음): https://claude.ai/code/artifact/2ae0b1d3-e337-4375-9871-1f0c67c2e184

망분리 환경에서 **손으로 직접 타이핑**해야 하는 상황을 전제로 만든 조회 전용 쿼리 모음.
이 서비스가 실제로 쓰는 8개 컬렉션 기준으로 정리했다.

- 대상: mongosh 1.x / 2.x
- ORM: Prisma (MongoDB)
- 원칙: **읽기만**

---

## 목차

| # | 장 | 내용 |
|---|---|---|
| 00 | [앉자마자 30초](#00-앉자마자-30초) | 접속 · DB 선택 · 컬렉션 확인 |
| 01 | [이 시스템의 몽고 지도](#01-이-시스템의-몽고-지도) | 컬렉션 8개와 탐색 경로 |
| 02 | [Prisma가 파놓은 함정 4개](#02-prisma가-파놓은-함정-4개) | id/ObjectId/날짜 |
| 03 | [타이핑 절약 세팅](#03-타이핑-절약-세팅) | **가장 중요** |
| 04 | [문서 구조 훑기](#04-문서-구조-훑기) | 안전하게 스키마 파악 |
| — | [find 기본기](#find-기본기) | 조건 · 프로젝션 · 정렬 |
| — | [실전 쿼리 — 컬렉션별](#실전-쿼리--컬렉션별) | 바로 쓰는 것들 |
| — | [배열과 임베디드 문서](#배열과-임베디드-문서) | $elemMatch · $unwind |
| — | [집계 파이프라인](#집계-파이프라인) | $match → $group → $sort |
| — | [날짜 다루기](#날짜-다루기) | UTC/KST 9시간 |
| — | [인덱스와 성능 확인](#인덱스와-성능-확인) | explain |
| — | [결과를 보기 좋게](#결과를-보기-좋게) | 출력 제어 |
| — | [안전수칙과 막혔을 때](#안전수칙과-막혔을-때) | 금지 명령 · 증상별 대처 |
| — | [빠른 참조](#빠른-참조) | 막혔을 때 여기만 |

---

## 00. 앉자마자 30초

순서대로 네 줄. 여기서 나온 컬렉션 이름이 이 문서 전체의 기준이 된다.

**접속.** URI를 모르면 서버의 `.env` 안 `MONGO_URL` / `DATABASE_URL`을 본다.

```bash
mongosh "mongodb://아이디:비번@호스트:27017/DB이름"

# 인증 DB가 따로면
mongosh "mongodb://...:27017/DB이름?authSource=admin"

# 레플리카셋이면 (Prisma 트랜잭션 쓰므로 대개 레플리카셋)
mongosh "mongodb://h1:27017,h2:27017/DB이름?replicaSet=rs0"
```

**DB 목록 → DB 선택 → 컬렉션 확인.** 세 번째 줄이 제일 중요하다.

```js
show dbs
use 디비이름
db.getCollectionNames()
```

**각 컬렉션 문서 수를 한 번에** (빠른 추정치)

```js
db.getCollectionNames().forEach(c => print(c, db[c].estimatedDocumentCount()))
```

> ⚠️ **먼저 확인할 것**
> Prisma는 스키마에 `@@map`이 없으면 **모델명 그대로** 컬렉션을 만든다.
> 그래서 실제 이름이 `transcribeResult`일 수도, `TranscribeResult`일 수도 있다.
> `db.getCollectionNames()` 결과를 보고 **03장의 별칭 한 줄만 고치면** 이 문서의 나머지 쿼리는 전부 그대로 동작한다.

---

## 01. 이 시스템의 몽고 지도

MariaDB가 관계·권한·페이징을 맡고, MongoDB는 **가변 구조 본문**을 맡는다.
두 DB를 잇는 유일한 열쇠는 `contentId` 하나다.

| 컬렉션 | 담는 것 | 핵심 키 |
|---|---|---|
| `transcribeResult` | STT 결과 전체 — 세그먼트·화자·AI요약. 가장 크고 가장 많이 쓰임 | `fileId` (유니크) |
| `file` | 미디어 파일 정보. **MariaDB와 연결되는 지점** | `contentId`, `_id` |
| `note` | 나만의 노트 본문 | `contentId`, `pid` |
| `noteRevision` | 노트 버전 이력 | `noteId`, `version` |
| `highlight` | 사용자 하이라이트 (문단 좌표 기반) | `fileId`, `category` |
| `bookmarks` | 구간 북마크 | `fileId`, `contentId`, `key` |
| `template` | 회의록 요약 템플릿 (중첩 모듈 배열) | `workspaceId`, `version` |
| `bookMarkedView` | **뷰(View)** — 북마크 조회 전용. 읽기만 가능 | `contentId` |

### 탐색 경로 — 이것만 외우면 된다

```
MariaDB.content.contentId   ← 화면/로그에서 보이는 그 ID
        │  (같은 값)
        ▼
  file.contentId  →  file._id
                        │
                        ▼
        transcribeResult.fileId      (STT 본문·요약)
        highlight.fileId             (하이라이트)
        bookmarks.fileId             (북마크)
        file.linkNoteId  →  note._id  →  noteRevision.noteId
```

### transcribeResult 문서 생김새

```js
{
  _id, fileId, ticket, status, engine, clientLanguage, summarySize,
  segments:       [ { segmentId, speakerId, text, startTime, endTime, duration } ],  // 수천 개
  mergedSegments: [ { segmentId, speakerId, text, startTime, endTime, duration } ],  // 화자 병합본
  speakerInfo:    [ { speakerId, name, displayName, pid } ],
  aiResult:       { title, topics, keywords, summary, issues, tasks,
                    templateSummary, manualTag },
  summaryTime:    [ { index, time, topic, summary, issues, tasks } ]
}
```

> 📌 **크기 주의**
> 1시간 회의면 `segments`가 수천 개다. `transcribeResult`를 아무 옵션 없이 `find()` 하면 터미널이 수만 줄로 도배된다.
> **반드시 큰 배열을 빼고 조회한다** — 03장의 `SLIM` 변수가 그 용도다.

---

## 02. Prisma가 파놓은 함정 4개

코드에서 보던 필드명과 몽고 안의 실제 필드명이 다르다.
이걸 모르면 "분명 있는데 안 나오는" 상황에 빠진다.

| 코드에서는 | 몽고 안에서는 | 쉘에서 쓸 때 |
|---|---|---|
| `id` | `_id` | `{_id: ObjectId("...")}` |
| `fileId` | `fileId` (ObjectId 타입) | `{fileId: ObjectId("...")}` — 따옴표만 쓰면 **0건** |
| `contentId` | `contentId` (문자열 UUID) | `{contentId: "abc-123"}` — 그냥 문자열 |
| `createAt` / `updateAt` | Date (UTC 저장) | `ISODate("2026-08-01")`, 한국시간 아님 |

> ⚠️ **가장 흔한 실수**
> `db.transcribeResult.findOne({fileId: "68a1..."})` → **null**
> `fileId`는 ObjectId라 문자열과 절대 매칭되지 않는다. 항상 `ObjectId("68a1...")`로 감싼다.

**타입이 헷갈릴 때** — 이 필드가 문자열인지 ObjectId인지 바로 확인

```js
db.file.findOne({}, {contentId:1, _id:1})
// _id: ObjectId("...")   ← 감싸야 함
// contentId: "b3f2-..."  ← 그냥 문자열
```

---

## 03. 타이핑 절약 세팅

붙여넣기가 안 되는 환경에서 **제일 중요한 장**.
접속하자마자 이 블록부터 친다. 여기 5줄에 시간을 쓰면 이후 모든 쿼리가 한 줄로 줄어든다.

**1단계 · 컬렉션 별칭.** 00장에서 확인한 실제 이름으로 오른쪽만 고친다.

```js
var F=db.file, T=db.transcribeResult, N=db.note, R=db.noteRevision
var H=db.highlight, B=db.bookmarks, P=db.template, V=db.bookMarkedView
```

**2단계 · 큰 배열 잘라내는 프로젝션.** transcribeResult 조회할 땐 늘 두 번째 인자로 넣는다.

```js
var SLIM={segments:0, mergedSegments:0, summaryTime:0}
```

**3단계 · 헬퍼 함수.** ObjectId 감싸기와 contentId 추적을 자동화한다.

```js
var oid = s => ObjectId(s)
var fc  = id => F.findOne({contentId:id})                      // contentId → file
var tr  = id => { var f=fc(id); return f && T.findOne({fileId:f._id}, SLIM) }
var seg = id => { var f=fc(id); return T.findOne({fileId:f._id},
                  {mergedSegments:1,_id:0}).mergedSegments }
```

이제 이 세 줄이면 콘텐츠 하나를 통째로 들여다볼 수 있다.

```js
fc("콘텐츠ID")              // 파일 정보
tr("콘텐츠ID")              // STT 상태 + AI 요약 (본문 제외)
seg("콘텐츠ID").length      // 세그먼트 개수
```

**4단계 · 출력 줄 수 제한.** 기본 20건씩 쏟아지는 걸 5건으로 줄인다.

```js
config.set("displayBatchSize", 5)     // mongosh 2.x
DBQuery.shellBatchSize = 5            // 구버전 mongo 쉘
```

> 💡 **알아두면 편한 것**
> - **↑ 방향키**로 직전 명령 불러와서 일부만 수정 — 손타이핑 환경의 생명줄
> - **Tab** 자동완성: `db.tra` + Tab → 컬렉션명 완성
> - 결과가 더 있으면 `it` 한 글자로 다음 페이지
> - 변수는 접속 세션 동안만 유지. 재접속하면 03장을 다시 친다

---

## 04. 문서 구조 훑기

"이 컬렉션에 어떤 필드가 있지?"를 안전하게 확인하는 방법. 전부 본문을 쏟아내지 않는 쿼리들이다.

```js
// 필드 이름만 나열 — 본문은 안 찍힌다. 구조 파악의 첫 수
Object.keys(T.findOne())
Object.keys(F.findOne())

// 중첩 객체 안까지. aiResult에 어떤 필드가 생겼는지 볼 때
Object.keys(T.findOne({"aiResult":{$exists:true}}).aiResult)

// 문서 한 건 전체 보기 — 큰 배열은 빼고
T.findOne({}, SLIM)

// 배열은 앞 2개만 잘라서 샘플 확인. 구조만 보면 되니까
T.findOne({}, {mergedSegments:{$slice:2}, segments:0, aiResult:0, summaryTime:0})

// 어떤 값들이 들어있는지 — enum 성격 필드에 특히 유용
T.distinct("status")
T.distinct("engine")
F.distinct("sttStatus")
F.distinct("mimeType")
```

**문서 크기 순위** — 어떤 회의록이 비정상적으로 큰지. 성능 이슈 추적의 출발점.

```js
T.aggregate([
  {$project:{fileId:1, mb:{$divide:[{$bsonSize:"$$ROOT"},1048576]},
             segN:{$size:{$ifNull:["$segments",[]]}}}},
  {$sort:{mb:-1}}, {$limit:5}
])
```

---

## find 기본기

문법 한 판. `find(조건, 보여줄필드)` 두 인자 구조만 잡으면 나머지는 조합이다.

### 조건 연산자

| 쓰임 | 쿼리 |
|---|---|
| 같음 | `{status:"DONE"}` |
| 같지 않음 | `{status:{$ne:"DONE"}}` |
| 여러 값 중 하나 | `{status:{$in:["ERROR","WAITING"]}}` |
| 제외 | `{status:{$nin:["DONE"]}}` |
| 크다/작다 | `{duration:{$gt:3600000}}` · `$gte $lt $lte` |
| 범위 | `{duration:{$gte:1000, $lte:9000}}` |
| 필드 있음/없음 | `{aiResult:{$exists:true}}` |
| null 이거나 없음 | `{linkNoteId:null}` |
| 부분 문자열 | `{fileName:/회의/}` |
| 대소문자 무시 | `{fileName:/report/i}` |
| ~로 시작 | `{fileName:/^A.Biz/}` |
| OR | `{$or:[{status:"ERROR"},{status:"CANCEL"}]}` |
| AND (같은 필드 조건 겹칠 때) | `{$and:[{a:{$gt:1}},{a:{$lt:9}}]}` |
| NOT | `{status:{$not:/DONE/}}` |
| 타입 확인 | `{fileId:{$type:"objectId"}}` |

### 보여줄 필드 고르기 (프로젝션)

`1`은 포함, `0`은 제외. **둘을 섞을 수 없다** — 단 `_id:0`은 예외.

```js
F.find({}, {fileName:1, sttStatus:1, _id:0})     // 포함 방식
T.find({}, {segments:0, mergedSegments:0})       // 제외 방식
```

### 정렬 · 개수 · 자르기

```js
F.find().sort({createAt:-1}).limit(5)      // 최신 5건 (-1=내림차순)
F.find().sort({createAt:1}).limit(5)       // 가장 오래된 5건
F.find().skip(10).limit(10)                // 11~20번째
F.countDocuments({sttStatus:"ERROR"})      // 정확한 개수
F.estimatedDocumentCount()                 // 전체 개수 (즉시, 추정)
F.findOne({contentId:"..."})               // 딱 한 건
```

> 💡 **화면 관리**
> `.limit(5)`를 **습관처럼** 붙인다. 한 줄로 압축해 보려면 `.toArray()`, 예쁘게 보려면 `.pretty()`.
> 개수만 궁금하면 구버전 `count()` 대신 `countDocuments()`를 쓴다.

---

## 실전 쿼리 — 컬렉션별

03장 별칭이 세팅되어 있다고 가정한다.

### file — 파일과 STT 상태

```js
// 콘텐츠 ID로 파일 찾기 (모든 추적의 시작점)
F.findOne({contentId:"콘텐츠ID"})

// STT 상태별 건수
F.aggregate([{$group:{_id:"$sttStatus", n:{$sum:1}}}, {$sort:{n:-1}}])

// 실패한 파일 최근 10건
F.find({sttStatus:"ERROR"}, {fileName:1, contentId:1, createAt:1})
 .sort({createAt:-1}).limit(10)

// 아직 처리 안 끝난 것들
F.find({sttStatus:{$in:["WAITING","PROGRESS"]}}, {fileName:1, createAt:1})

// 파일명으로 찾기
F.find({fileName:/2026/}, {fileName:1, contentId:1, sttStatus:1}).limit(10)

// 1시간 넘는 긴 녹취 (duration은 밀리초)
F.find({duration:{$gt:3600000}}, {fileName:1, duration:1}).sort({duration:-1}).limit(10)

// 노트가 연결 안 된 파일
F.countDocuments({linkNoteId:null})
```

### transcribeResult — STT 결과와 AI 요약

```js
// 콘텐츠 하나의 STT 상태·요약 (헬퍼 사용)
tr("콘텐츠ID")

// 헬퍼 없이 2단계로
var f = F.findOne({contentId:"콘텐츠ID"})
T.findOne({fileId: f._id}, SLIM)

// 상태별 분포
T.aggregate([{$group:{_id:"$status", n:{$sum:1}}}, {$sort:{n:-1}}])

// 엔진별 분포
T.aggregate([{$group:{_id:"$engine", n:{$sum:1}}}])

// 실패 건 최근 10개
T.find({status:"ERROR"}, {fileId:1, ticket:1, engine:1, updateAt:1})
 .sort({updateAt:-1}).limit(10)

// 티켓 번호로 추적
T.findOne({ticket:"티켓ID"}, SLIM)

// AI 요약이 비어있는 건 (요약 실패 의심)
T.countDocuments({$or:[{aiResult:null}, {"aiResult.summary":{$size:0}}]})

// 템플릿 요약이 실제로 생성됐는지
T.countDocuments({"aiResult.templateSummary":{$exists:true, $ne:""}})

// 요약 본문만 꺼내 읽기
T.findOne({fileId: f._id}, {"aiResult.templateSummary":1, _id:0}).aiResult.templateSummary

// 키워드만
T.findOne({fileId: f._id}, {"aiResult.keywords":1, _id:0})
```

### 전사 본문 검색 — 몽고가 제일 잘하는 일

```js
// 특정 단어가 나온 회의 찾기
T.find({"mergedSegments.text":/계약/}, {fileId:1}).limit(10)

// 파일 정보까지 붙여서 보기
T.find({"mergedSegments.text":/계약/}, {fileId:1,_id:0}).limit(10)
 .toArray().map(x => F.findOne({_id:x.fileId},{fileName:1,contentId:1,_id:0}))

// 매칭된 문장만 뽑아 보기
T.aggregate([
  {$match:{"mergedSegments.text":/계약/}},
  {$project:{hits:{$filter:{input:"$mergedSegments", as:"s",
             cond:{$regexMatch:{input:"$$s.text", regex:/계약/}}}}}},
  {$project:{texts:"$hits.text"}}, {$limit:3}
])

// 참석자 이름으로 회의 찾기
T.find({"speakerInfo.name":/홍길동/}, {fileId:1}).limit(10)

// 세그먼트 ID로 역추적
T.findOne({"mergedSegments.segmentId":"세그먼트UUID"}, {speakerInfo:1})
```

### note · noteRevision — 노트와 버전

```js
// 콘텐츠의 노트
N.find({contentId:"콘텐츠ID"}, {noteName:1, pid:1, updateAt:1})

// 특정 사용자의 나만의 노트
N.findOne({contentId:"콘텐츠ID", pid:"사용자PID"})

// 노트의 버전 이력 (최신순)
var nt = N.findOne({contentId:"콘텐츠ID"})
R.find({noteId: nt._id}, {version:1, lastUpdateUser:1, createAt:1}).sort({version:-1})

// 버전이 비정상적으로 많은 노트 상위 5개
R.aggregate([{$group:{_id:"$noteId", n:{$sum:1}}}, {$sort:{n:-1}}, {$limit:5}])

// 본문 길이만 확인 (본문 자체는 안 찍힘)
N.aggregate([{$project:{noteName:1, len:{$strLenCP:{$ifNull:["$content",""]}}}},
             {$sort:{len:-1}}, {$limit:5}])
```

### highlight · bookmarks

```js
// 파일의 하이라이트
H.find({fileId: f._id}, {text:1, category:1, start:1, end:1}).limit(10)

// 전사 영역 하이라이트만
H.find({"category.key":"mergedSegments"}, {text:1}).limit(10)

// 영역별 하이라이트 수
H.aggregate([{$group:{_id:"$category.key", n:{$sum:1}}}, {$sort:{n:-1}}])

// 콘텐츠의 북마크
B.find({contentId:"콘텐츠ID"}, {key:1, itemIds:1, isAll:1, time:1})

// 뷰로 조회 (읽기 전용)
V.find({contentId:"콘텐츠ID"}).limit(5)

// 고아 북마크 — 파일이 사라진 북마크 찾기
B.find({}, {fileId:1,_id:0}).limit(50).toArray()
 .filter(b => !F.findOne({_id:b.fileId}))
```

### template — 회의록 템플릿

```js
// 기본(global) 템플릿
P.findOne({workspaceId:"global", isUsed:"Y", isDeleted:"N"})

// 워크스페이스별 템플릿 목록
P.find({isDeleted:"N"}, {workspaceId:1, title:1, version:1, isUsed:1})
 .sort({workspaceId:1, version:-1})

// 어떤 모듈들로 구성돼 있는지
P.findOne({workspaceId:"global"}).template.map(m => m.moduleKey)

// 특정 모듈을 쓰는 템플릿
P.find({"template.moduleKey":"summaryTime"}, {workspaceId:1, title:1})

// 워크스페이스별 템플릿 개수
P.aggregate([{$match:{isDeleted:"N"}},
             {$group:{_id:"$workspaceId", n:{$sum:1}}}, {$sort:{n:-1}}])
```

---

## 배열과 임베디드 문서

이 스키마는 거의 전부 배열이다. 여기가 몽고 쿼리의 진짜 관문.

### 점 표기법 — 배열 안 필드 바로 찌르기

```js
T.find({"speakerInfo.name":"참석자 1"})       // 배열 원소 중 하나라도 맞으면 매칭
T.find({"aiResult.keywords":"반도체"})        // 문자열 배열도 동일
T.find({"mergedSegments.0.text":/안녕/})      // 첫 번째 원소만 지정
```

### $elemMatch — 두 조건이 **같은 원소**에서 만나야 할 때

이 차이가 오답의 단골 원인이다.

```js
// ✗ 서로 다른 원소에서 각각 만족해도 매칭됨
T.find({"mergedSegments.speakerId":1, "mergedSegments.text":/계약/})

// ✓ 같은 문장 안에서 둘 다 만족
T.find({mergedSegments:{$elemMatch:{speakerId:1, text:/계약/}}})
```

### 배열 크기

```js
T.find({"speakerInfo":{$size:0}})              // 화자가 하나도 없는 것
T.find({"aiResult.keywords":{$size:3}})        // 정확히 3개 ($gt 등은 불가)

// 개수 비교는 집계로
T.aggregate([{$project:{fileId:1, n:{$size:{$ifNull:["$speakerInfo",[]]}}}},
             {$match:{n:{$gte:5}}}, {$limit:5}])
```

### 배열 일부만 꺼내기

```js
T.findOne({fileId:f._id}, {mergedSegments:{$slice:3}, segments:0})     // 앞 3개
T.findOne({fileId:f._id}, {mergedSegments:{$slice:-3}, segments:0})    // 뒤 3개
T.findOne({fileId:f._id}, {mergedSegments:{$slice:[10,5]}, segments:0}) // 11번째부터 5개
```

### 배열 펼치기 · 뽑기 · 거르기 (집계 단계)

```js
// 화자별 발화 문장 수
T.aggregate([
  {$match:{fileId:f._id}},
  {$unwind:"$mergedSegments"},
  {$group:{_id:"$mergedSegments.speakerId", n:{$sum:1}}},
  {$sort:{n:-1}}
])

// 화자별 총 발화 시간(초)
T.aggregate([
  {$match:{fileId:f._id}},
  {$unwind:"$mergedSegments"},
  {$group:{_id:"$mergedSegments.speakerId",
           sec:{$sum:{$divide:["$mergedSegments.duration",1000]}}}},
  {$sort:{sec:-1}}
])

// 필드 하나만 배열로 뽑기
T.aggregate([{$match:{fileId:f._id}},
             {$project:{names:"$speakerInfo.name", _id:0}}])
```

> ⚠️ **주의**
> `$unwind`는 세그먼트 수천 개짜리 문서를 수천 행으로 펼친다.
> **반드시 `$match`로 먼저 좁힌 뒤** 쓴다. 전체 컬렉션에 `$unwind`를 거는 건 운영 DB에 부하를 준다.

---

## 집계 파이프라인

단계를 순서대로 통과시키는 구조. 순서만 지키면 어렵지 않다 —
**좁히고(match) → 묶고(group) → 정렬(sort) → 자른다(limit)**.

| 단계 | 하는 일 | 비고 |
|---|---|---|
| `$match` | 조건으로 거름 (find와 같은 문법) | **항상 맨 앞에** |
| `$project` | 필드 고르기·계산 필드 만들기 | |
| `$group` | `_id` 기준으로 묶고 집계 | `_id:null` = 전체 하나로 |
| `$sort` | 정렬 | `$group` 뒤에 |
| `$limit` / `$skip` | 개수 제한 | 습관적으로 |
| `$unwind` | 배열을 행으로 펼침 | `$match` 뒤에만 |
| `$lookup` | 다른 컬렉션 조인 | 느림, 소량에만 |
| `$count` | 결과 개수 | 맨 끝 |

### 집계 함수

| 함수 | 예시 |
|---|---|
| 건수 | `{$sum: 1}` |
| 합계 | `{$sum: "$duration"}` |
| 평균 | `{$avg: "$duration"}` |
| 최대·최소 | `{$max: "$duration"}` · `{$min: ...}` |
| 값 모으기 | `{$push: "$fileId"}` |
| 중복 없이 모으기 | `{$addToSet: "$engine"}` |
| 첫/마지막 | `{$first: "$status"}` · `{$last: ...}` |

### 바로 쓰는 집계

```js
// 일자별 업로드 건수 (한국시간)
F.aggregate([
  {$group:{_id:{$dateToString:{format:"%Y-%m-%d", date:"$createAt",
                               timezone:"Asia/Seoul"}}, n:{$sum:1}}},
  {$sort:{_id:-1}}, {$limit:14}
])

// 상태 × 엔진 교차 집계
T.aggregate([
  {$group:{_id:{s:"$status", e:"$engine"}, n:{$sum:1}}},
  {$sort:{n:-1}}
])

// 총 녹취 시간 (시간 단위)
F.aggregate([{$group:{_id:null, hours:{$sum:{$divide:["$duration",3600000]}},
                      n:{$sum:1}}}])

// STT 소요 시간 통계 (생성→수정 간격, 분)
T.aggregate([
  {$match:{status:"DONE"}},
  {$project:{min:{$divide:[{$subtract:["$updateAt","$createAt"]},60000]}}},
  {$group:{_id:null, avg:{$avg:"$min"}, max:{$max:"$min"}, n:{$sum:1}}}
])

// 컬렉션 간 조인 — 실패한 STT의 파일명 붙이기
T.aggregate([
  {$match:{status:"ERROR"}},
  {$limit:10},
  {$lookup:{from:"file", localField:"fileId", foreignField:"_id", as:"f"}},
  {$project:{ticket:1, engine:1, name:{$first:"$f.fileName"},
             cid:{$first:"$f.contentId"}}}
])
```

> 💡 **순서가 성능이다**
> `$match`와 `$limit`을 최대한 **앞**으로 밀어라.
> `$lookup`이나 `$unwind` 앞에 `$limit` 하나만 넣어도 체감이 완전히 달라진다.

---

## 날짜 다루기

몽고는 UTC로 저장한다. 한국시간과 **9시간** 차이 — 날짜 경계에서 결과가 틀리는 원인 1위.

```js
// 특정 날짜 이후
F.find({createAt:{$gte:ISODate("2026-08-01")}}).limit(5)

// 기간 (끝은 다음 날 00시로 잡는 게 안전)
F.find({createAt:{$gte:ISODate("2026-08-01"), $lt:ISODate("2026-09-01")}})

// 한국시간 기준 하루 (UTC로 환산해서 넣기)
F.find({createAt:{$gte:ISODate("2026-08-30T15:00:00Z"),
                  $lt: ISODate("2026-08-31T15:00:00Z")}})

// 최근 N시간 / N일 — 계산식으로
var HOUR=3600000, DAY=86400000
F.countDocuments({createAt:{$gte:new Date(Date.now()-24*HOUR)}})
F.countDocuments({createAt:{$gte:new Date(Date.now()-7*DAY)}})

// 오늘(한국시간) 업로드 건수
var kst = new Date(new Date().toISOString().slice(0,10)+"T00:00:00+09:00")
F.countDocuments({createAt:{$gte:kst}})

// 출력할 때 한국시간으로 보기
F.find({}, {fileName:1,createAt:1,_id:0}).sort({createAt:-1}).limit(5)
 .toArray().forEach(d => print(d.createAt.toLocaleString("ko-KR"), d.fileName))

// 시간대별 분포 (한국시간)
F.aggregate([
  {$group:{_id:{$hour:{date:"$createAt", timezone:"Asia/Seoul"}}, n:{$sum:1}}},
  {$sort:{_id:1}}
])
```

> 📌 **암산용**
> 한국시간 **00시 = UTC 전날 15시**. 한국시간 **09시 = UTC 00시**.
> 하루 = `86400000`ms, 1시간 = `3600000`ms.
> 이 스키마의 `duration`·`startTime`·`endTime`은 전부 **밀리초**다.

---

## 인덱스와 성능 확인

"왜 이렇게 느리지?"에 답하는 도구들. 전부 읽기 전용이라 마음 놓고 써도 된다.

```js
// 이 컬렉션에 걸린 인덱스
F.getIndexes()
T.getIndexes()

// 인덱스 이름만 간단히
F.getIndexes().map(i => i.name)

// 이 쿼리가 인덱스를 타는가
F.find({contentId:"..."}).explain("executionStats").executionStats

// 핵심 지표만 보기
var e = F.find({sttStatus:"ERROR"}).explain("executionStats").executionStats
print("반환:", e.nReturned, "검사:", e.totalDocsExamined, "ms:", e.executionTimeMillis)

// 컬렉션 용량·인덱스 크기 (MB)
F.stats().size/1048576
F.totalIndexSize()/1048576
db.stats(1048576)

// 지금 돌고 있는 느린 작업
db.currentOp({"secs_running":{$gt:3}})

// 접속 상태
db.serverStatus().connections
db.version()
```

> 💡 **읽는 법**
> - `stage: "COLLSCAN"` → 인덱스 못 탐. 전체 스캔 중
> - `stage: "IXSCAN"` → 인덱스 사용 중. 정상
> - `totalDocsExamined`가 `nReturned`보다 **훨씬 크면** 인덱스가 비효율적이라는 뜻

운영 DB에 부담 주기 싫을 때 — 세컨더리로 읽기를 돌린다.

```js
db.getMongo().setReadPref("secondaryPreferred")
```

---

## 결과를 보기 좋게

화면이 도배되는 걸 막는 법. 손으로 옮겨 적어야 하는 상황이면 특히 중요하다.

```js
// 한 줄씩 필요한 값만 뽑아 출력 — 옮겨 적기 제일 편한 형태
F.find({sttStatus:"ERROR"}).limit(10).forEach(d =>
  print(d.contentId, "|", d.sttStatus, "|", d.fileName))

// 표처럼 정렬해서
F.find({}, {fileName:1,sttStatus:1,_id:0}).limit(10).forEach(d =>
  print((d.sttStatus||"").padEnd(10), d.fileName))

// 개수만
F.countDocuments({sttStatus:"ERROR"})

// 값 하나만 딱
F.findOne({contentId:"..."}).sttStatus

// 예쁘게 / 압축해서
F.findOne().pretty()
JSON.stringify(F.findOne())

// 배열로 받아 JS로 가공
var arr = F.find({}, {duration:1,_id:0}).limit(100).toArray()
arr.reduce((a,b) => a+b.duration, 0) / 3600000     // 총 시간

// 페이지 넘기기
it

// 화면 정리
cls
```

> 💡 **기록 남기기**
> 쉘 결과를 파일로 남겨야 하면 접속할 때 `--eval`과 리다이렉션을 쓴다:
> ```bash
> mongosh "URI" --quiet --eval 'db.file.countDocuments({})' > out.txt
> ```
> 쉘 안에서는 `.forEach(print)`로 뽑고 터미널 로그를 그대로 저장하는 편이 빠르다.

---

## 안전수칙과 막혔을 때

> 🚫 **절대 치지 말 것**
> - `deleteMany({})` · `remove({})` · `drop()` — 조건 없는 삭제는 전멸
> - `updateMany`에서 `$set` 빼먹기 → 문서 통째로 교체됨
> - `db.dropDatabase()`
> - 운영 DB에서 `createIndex` — 락이 걸릴 수 있다
> - 전체 컬렉션에 `$unwind` 걸기
>
> **안전한 습관:** 뭔가 바꿔야 하면 먼저 같은 조건으로 `countDocuments()`를 돌려
> **몇 건이 걸리는지 확인**하고, 그 다음에 손댄다.

### 증상별 대처

| 증상 | 원인과 해결 |
|---|---|
| `null`만 나온다 | ObjectId를 문자열로 넣었다. `ObjectId("...")`로 감싼다 |
| `TypeError: ... not a function` | 컬렉션 이름 오타 또는 대소문자. `db.getCollectionNames()` 재확인 |
| 결과가 끝없이 쏟아진다 | `Ctrl+C`로 중단. `.limit(5)`와 `SLIM` 붙여 재실행 |
| 날짜 결과가 하루 어긋난다 | UTC/KST 9시간 차. 날짜 장 참고 |
| `not authorized` | 읽기 권한 없음. `db.runCommand({connectionStatus:1})`로 확인 |
| 뷰에 쓰기 시도 실패 | `bookMarkedView`는 뷰다. 읽기만 된다 |
| 쿼리가 안 끝난다 | `Ctrl+C`. `.explain()`으로 COLLSCAN인지 확인 |
| 한글이 깨진다 | 터미널 인코딩 UTF-8 확인 |

### 내 권한 확인

```js
db.runCommand({connectionStatus:1}).authInfo
db.getUsers()          // 권한 있으면
```

---

## 빠른 참조

### 접속 직후 세팅 (통째로)

```js
use 디비이름
var F=db.file, T=db.transcribeResult, N=db.note, R=db.noteRevision
var H=db.highlight, B=db.bookmarks, P=db.template, V=db.bookMarkedView
var SLIM={segments:0, mergedSegments:0, summaryTime:0}
var fc = id => F.findOne({contentId:id})
var tr = id => { var f=fc(id); return f && T.findOne({fileId:f._id}, SLIM) }
config.set("displayBatchSize", 5)
```

### 제일 자주 쓸 다섯 줄

```js
db.getCollectionNames()
fc("콘텐츠ID")
tr("콘텐츠ID")
F.aggregate([{$group:{_id:"$sttStatus", n:{$sum:1}}}])
T.find({status:"ERROR"}, {fileId:1,ticket:1}).sort({updateAt:-1}).limit(5)
```

### 필드 빠른 색인

| 찾는 것 | 어디에 |
|---|---|
| STT 상태 | `file.sttStatus` · `transcribeResult.status` |
| 회의 본문 | `transcribeResult.mergedSegments[].text` |
| 참석자 | `transcribeResult.speakerInfo[].name` |
| AI 요약 | `transcribeResult.aiResult.summary` |
| 템플릿 요약(마크다운) | `transcribeResult.aiResult.templateSummary` |
| 키워드 | `transcribeResult.aiResult.keywords` |
| 주제별 요약 | `transcribeResult.summaryTime[]` |
| STT 엔진 | `transcribeResult.engine` |
| 작업 티켓 | `transcribeResult.ticket` |
| 파일명 / 길이 | `file.fileName` · `file.duration` (ms) |
| 노트 본문 | `note.content` |
| 템플릿 모듈 | `template.template[].moduleKey` |

### 자주 보는 상태값

| 필드 | 값 |
|---|---|
| `sttStatus` / `status` | WAITING · PROGRESS · RUNNING · STT_DONE · SUMMARY_DONE · DONE · ERROR · CANCEL · TEXT_SPLIT_DONE · NORMALIZE_WAITING · NORMALIZE_DONE · RE_SUMMARY_RUNNING |
| 콘텐츠 타입 (MariaDB) | AUDIO · VIDEO · RECORD · MERGED_CONTENT |
| `template.moduleKey` | title · topics · speakerInfo · keywords · summary · issues · tasks · summaryTime |
| `highlight.category.key` | mergedSegments · summary · topics · 그 외 화면 영역 |

---

이 문서의 컬렉션·필드 이름은 `src/models`의 `mongoDB.*` 호출과
`src/docs/schemas/dataSchemas.js`에서 뽑았다.
실제 컬렉션 표기(대소문자)는 접속 후 `db.getCollectionNames()`로 확정할 것.
