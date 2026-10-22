# Postman 으로 머지 → STT → LLM 테스트

`merge_stt_test.postman_collection.json` 을 Postman 에 가져와(Import) 순서대로 실행한다.

```
1-2 머지 요청 → 1-3 상태 조회 → 1-4 결과 다운로드
      → 2-1 master-api 업로드 (STT·LLM 자동 실행) → 2-2 결과 조회
```

실제 서비스에서 master-api 가 머지 결과를 STT 로 넘기는 경로(`createContent` →
`recogService.addTask`)와 **2-1 이 타는 경로가 같다.** STT 가 끝나면 LLM 요약은
master-api 가 자동으로 이어서 실행한다 (별도 호출 불필요).

---

## 0. 준비 — 변수 3개 채우기

Postman 에서 컬렉션 선택 → **Variables** 탭.

| 변수 | 값 | 구하는 법 |
|---|---|---|
| `recogUrl` | `http://<recog서버>:<포트>` | Swagger 띄우는 그 주소 (`/docs` 빼고) |
| `masterApiUrl` | 예: `http://<웹주소>/api` | 아래 "브라우저에서 복사" |
| `token` | JWT 문자열 | 아래 "브라우저에서 복사" |

`jobId`, `contentId` 는 비워 둔다. 요청을 보내면 자동으로 채워진다.

### 브라우저에서 주소·토큰 복사

1. 크롬에서 Timblo 웹에 로그인
2. `F12` → **Network** 탭 → 회의록 목록 아무거나 클릭
3. 요청 목록에서 `contents` 가 들어간 요청 클릭 → **Headers**
4. **Request URL** 에서 `/contents` 앞부분까지 → `masterApiUrl`
   (예: `https://timblo.사내.com/api/contents/list` → `https://timblo.사내.com/api`)
5. **Request Headers** 의 `x-timblo-token` 값 → `token`
   (`x-timblo-token` 이 없고 `Authorization: Bearer xxx` 만 있으면 `xxx` 부분을 넣고,
   2-x 요청의 헤더 이름을 `Authorization`, 값을 `Bearer {{token}}` 으로 바꾼다)

---

## 1. recog — 머지

### 1-2 머지 요청

**Body** 탭에서 `files` 세 줄에 각각 파일을 고른다 (**A → B → C 순서**).

| key | 파일 |
|---|---|
| files | `phone_A.flac` |
| files | `phone_B.flac` |
| files | `phone_C.flac` |

Send → 응답의 `jobId` 가 변수에 자동 저장된다.

### 1-3 상태 조회

`status` 가 `DONE` 이 될 때까지 몇 초 간격으로 Send. 보통 몇 초면 끝난다.
Postman 하단 **Console** 에 요약이 찍힌다.

```
status: DONE
mode: beep | trimmedMs: 5062
f1 offsetMs: 0
f2 offsetMs: 546
f3 offsetMs: 1296
```

`mode: none` 이 나오면 비프를 못 찾은 것이다 (`no_beep/` 샘플이면 정상).

### 1-4 결과 다운로드

**Send 버튼 옆 ▼ → Send and Download** → `merged.flac` 로 저장.

---

## 2. master-api — STT · LLM

### 2-1 업로드

**Body** 탭의 `file` 에 1-4 에서 받은 `merged.flac` 를 고른다. Send.

- 응답의 `contentId` 가 변수에 자동 저장된다 (Console 에 표시).
- `attendeeNum=3` 은 화자 수 힌트다. 샘플은 3명이다.
- **"duration is 0" 에러**가 나면 파일 형식을 못 읽은 것이다. Body 의 `file` 줄
  오른쪽 `...` → Content-Type 을 `audio/flac` 로 지정한다.
- 이 업로드로 Timblo 웹 목록에도 회의록이 하나 생긴다. 화면으로 봐도 된다.

### 2-2 결과 조회 (반복)

처리 단계에 따라 응답이 다르다. 결과는 응답의 `data` 안에 들어 있다.

| 응답 | 의미 |
|---|---|
| 에러 `1114` + `status` | 아직 STT 처리 중. 잠시 후 다시 Send |
| `data.status: STT_DONE` + `data.segments` | **STT 완료.** LLM 요약은 진행 중 |
| 정상 응답 + `data.aiResult` | STT·LLM 모두 완료 |
| 에러 `1119` | STT 실패 (ERROR/CANCEL) |

**STT_DONE 만 나와도 정렬 검증은 할 수 있다.** `data.segments` 의 각 항목에서
`startTime`(**밀리초**)·화자·텍스트를 `../README.md` 5절 정답지와 비교한다.

```
정답지  0:10.56  박 책임  먼저 수율부터 말씀드리겠습니다...
STT     startTime ≈ 10560 근처, 화자 B, 같은 문장
```

**발언 순서가 같고 시각이 ±0.3초(±300) 안이면 정렬 성공.**

### 2-3 (선택) LLM 요약 다시 실행

요약만 다시 돌리고 싶을 때. 워크스페이스 설정(`use_resummary_stt`)이 켜져 있으면
STT 부터 다시 돈다.

---

## 참고

- 2-x 는 사용자 토큰으로 호출하므로 **그 계정의 회의록**으로 등록된다.
  테스트 후 웹에서 삭제하면 된다.
- 토큰이 만료되면 2-x 가 인증 에러를 낸다. 브라우저에서 다시 복사한다.
- master-api 에 있는 `POST /contents/merge` 는 회의록을 **이어붙이는** 기존 기능이다.
  우리 머지(동시 녹음 겹치기)와 다르니 쓰지 않는다.
