# 안내가이드 GIF 자동 촬영 — 작업 이력 & 인수인계

> **작성일** 2026-09-09 · **대상 사이트** https://skhynix.timblo.io/ (A.Biz AI회의록, 개발 서버)
> **목적** 기능별 안내 가이드/매뉴얼용 GIF를 스크립트로 촬영. 화면이 바뀌면 **스크립트 재실행만으로 전체 재생성**.

이 문서 하나만 읽으면 같은 작업을 다시 하거나, 수정하거나, 새 기능으로 확장할 수 있게 쓴 것입니다.

---

## 1. 결론 요약 (다시 시킬 때 이것만 봐도 됨)

| 항목 | 값 |
|---|---|
| 자동화 도구 | **Playwright (Chromium, headless)** — Chrome 확장/CDP 아님 |
| 영상 → GIF | **ffmpeg** (palettegen/paletteuse) |
| 스크립트 위치 | `newDocs/_scripts/` |
| 산출물 위치 | `newDocs/makeFolder/`, `newDocs/recording/` (챕터별 폴더) |
| 로그인 | `.env` → `login.js` 로 `auth.json`(세션) 생성 후 재사용 |
| 연출 | 가짜 커서 + 클릭 링 + 요소 하이라이트 + 말풍선 (`lib.js`) |
| 화면 보정 | 실제와 다르게 보여줘야 할 때 DOM 패치 (`patch.js`) — **서버 무관** |

**왜 Chrome 확장이 아니라 Playwright인가:** 확장은 영상 녹화가 안 되고 매번 수동 반복이 필요합니다. Playwright는 스크립트라 재실행 한 번으로 전체 GIF를 다시 만들 수 있습니다. 가이드는 화면이 바뀌면 전부 다시 찍어야 하므로 이게 결정적입니다.

---

## 2. 산출물 목록

```
newDocs/
├── makeFolder/                 폴더 관리 챕터
│   ├── makeFolder.gif          폴더 생성 (LNB 확대, 권장)
│   ├── makeFolder-full.gif     폴더 생성 (전체화면)
│   ├── folderMenu.gif          폴더 ⋮ 메뉴 3종 소개 (말풍선 설명)
│   ├── renameFolder.gif        폴더명 변경
│   ├── deleteFolder.gif        폴더 삭제
│   └── moveToFolder.gif        회의록 폴더 이동
├── recording/                  녹음 챕터
│   ├── recordMeeting.gif       녹음 전체 흐름 (1.3배속, 2.0MB, 권장)
│   └── recordMeeting-slow.gif  녹음 전체 흐름 (실제 속도, 3.2MB)
├── _scripts/                   ← 촬영 스크립트 (아래 4장)
└── GUIDE_GIF_HANDOFF.md        ← 이 문서
```

> 폴더 구성은 사용자가 챕터 단위로 정리함. 새 GIF를 만들면 해당 챕터 폴더에 넣을 것.

---

## 3. 환경 준비 (새 세션에서 처음 시작할 때)

```bash
cd newDocs/_scripts
npm install                      # playwright
npx playwright install chromium  # 브라우저 (~95MB)

cp .env.example .env
$EDITOR .env                     # TIMBLO_PW 채우기
chmod 600 .env

node login.js                    # → auth.json 생성 (로그인 세션 저장)
```

`ffmpeg` 필요 (`brew install ffmpeg`). 작업 당시 7.1.1 사용.

> **주의** `.env`(비밀번호)와 `auth.json`(세션)은 **커밋 금지**. `newDocs/` 는 이미 `.gitignore` 에 포함되어 있음.

---

## 4. 스크립트 구조

### `lib.js` — 연출 라이브러리
| 함수 | 역할 |
|---|---|
| `installCursor(page, x, y)` | 가짜 마우스 커서 주입 (headless 는 커서가 안 찍힘) |
| `moveTo(page, locator, ms)` | 커서를 요소로 부드럽게 이동 (실제 마우스도 같이 → hover 발생) |
| `highlight(page, locator, on, pad)` | 요소에 주황 테두리 강조 |
| `clickAt(page, locator, opts)` | 커서 이동 → 클릭 링 이펙트 → 실제 클릭 |
| `typeText(page, locator, text, delay)` | 한 글자씩 타이핑 |
| `callout(page, locator, text, opts)` | **말풍선** (꼬리 포함, `side: 'right' \| 'bottom'`) |
| `hideCallout(page)` / `hideTooltips(page)` | 말풍선 숨김 / 사이트 기본 툴팁 숨김 |
| `folderRow(page, name)` / `menuItem(page, label)` / `menuPaper(page)` | LNB 폴더·⋮메뉴 헬퍼 |

색상: 하이라이트/링 `#FFB020`, 말풍선 배경 `#FFF8EC` / 테두리 `#FFB020` / 글자 `#6B3E00`.

### `patch.js` — 화면 보정 (가이드용 목업)
실제 사이트와 다르게 보여줘야 할 때 **촬영 브라우저의 DOM만** 바꿉니다. 서버·실제 사이트에는 아무 영향 없음.

현재 적용 내용:
- 템플릿 목록 `일반 회의록 / 전화 대화 요약 / 인터뷰 요약` → **`기본형 / 운영형 / 의사결정형 / 보고형`**
- 템플릿 설명 → **유형별로 다르게** (항목을 클릭하면 오른쪽 패널이 바뀜)

| 템플릿 | 설명 내용 |
|---|---|
| 기본형 | `*** 제목 ***` · `** 키워드 **` · `** 회의기본정보 **` (공통 3줄) |
| 운영형 | 공통 3줄 + `** 주제별 요약 **` · `** 액션 아이템 **` |
| 의사결정형 | 공통 3줄 + `** 안건 및 논의사항 **` · `** 결정사항 **` |
| 보고형 | 공통 3줄 + `** 진행 경과 **` · `** 보고 요약 **` |

문구를 바꾸려면 `patch.js` 상단 `PATCH_ARGS.templates` 의 `lines` 배열만 수정.

> 처음에는 4개 모두 같은 설명이었으나, GIF 에서 템플릿을 눌러도 오른쪽이 안 바뀌어 **고장난 것처럼 보이는 문제**가 있어 유형별로 분리함.

`MutationObserver` 로 동작하므로 **모달이 뜨기 전에 미리 설치**해두면 모달이 뜨는 순간 자동 적용됩니다(원본이 한 프레임도 안 보임). React 리렌더로 되돌아가도 다시 적용됩니다.

> 사이트에 템플릿 4종이 실제 반영되면 `rec-record.js` 에서 `applyPatch` 호출 두 줄만 지우고 재실행하면 진짜 화면으로 재생성됩니다.

### 촬영 스크립트
| 파일 | 만드는 GIF |
|---|---|
| `rec-makeFolder.js` | `makeFolder.gif` |
| `rec-all.js` | `folderMenu.gif`, `renameFolder.gif`, `deleteFolder.gif` (3개 연속) |
| `rec-record.js` | `recordMeeting.gif` |
| `rec-move.js` | `moveToFolder.gif` |

`rec-all.js` 는 인자로 하나만 지정 가능: `node rec-all.js renameFolder`

---

## 5. 사이트 셀렉터 사전 (조사해서 알아낸 것)

MUI 기반 React SPA. `aria-label` 이 잘 붙어 있어 대체로 안정적입니다.

### 로그인
```js
input[placeholder="아이디(이메일)"]
input[placeholder="비밀번호"]
button:has-text("로그인")
// 로그인 페이지: /sign/?f=true&s=false  ·  제목: "A.Biz AI회의록"
```

### LNB (좌측 메뉴)
```js
div[role="button"][aria-label="전체 회의록"]
button[aria-label="폴더 추가"]     // '+'  (전체 회의록 우측)
button[aria-label="접기"]          // '^'  토글
div[role="button"]:has-text("폴더명")            // 폴더 행
div[role="button"]:has-text("폴더명") button     // hover 시 나타나는 ⋮
```

### 폴더 생성 / 이름변경 (인라인 입력)
```js
// 생성:   placeholder="새 폴더(8글자)"
// 이름변경: placeholder="폴더명(8글자)"  (기존 이름이 value 로 채워져 있음)
div.MuiInputBase-root:has(input[placeholder*="새 폴더"])
  .locator('button').first()   // ✓ 확인  (입력 전에는 disabled)
  .locator('button').nth(1)    // ✕ 취소
```
**폴더명은 8글자 제한.**

### ⋮ 메뉴
```js
.MuiPopover-paper                                  // 메뉴 컨테이너
  .locator('.MuiStack-root').first()               // '녹음' (아이콘+텍스트 묶음)
  .getByText('폴더명 변경', {exact:true})           // <li> 아님, <p> 태그!
  .getByText('폴더 삭제', {exact:true})
```

### 폴더 삭제 확인 다이얼로그
```
"폴더를 삭제할까요? / 폴더를 삭제하면 폴더 안에 있는 회의록은 모두 휴지통으로 이동됩니다."
[취소] [확인]  →  dlg.getByRole('button', {name:'확인'})
```

### 녹음
```js
p.locator('text=녹음').first()              // 좌상단 마이크 버튼
p.locator('text=위 내용을 확인했습니다')      // 동의 체크박스(라벨 클릭)
p.locator('.record button.circle-icon-box') // 빨간 원형 = 녹음 시작
p.locator('text=녹음 종료').first()          // 녹음 중 패널의 종료 (취소 / ⏸ / 녹음 종료)
p.waitForSelector('text=AI요약 준비하기')     // 종료 후 모달
```
모달 구성: `요약 언어 선택`(한국어/영어) · `발화자수 선택`(1~2/3~6/7~10/11명 이상) · `템플릿 선택` · `템플릿 설명` · `[닫기] [AI요약 시작]`

### 폴더 이동
```js
input[type=checkbox] nth(0)=헤더 전체선택, nth(1)=첫 행
button:has-text("폴더 이동")   // 상단 우측
// 팝오버: "이동할 폴더를 선택해 주세요" + 라디오 목록
p.getByRole('radio',  {name:'AI회의록'})
p.getByRole('button', {name:'이동', exact:true})
```

---

## 6. ⚠️ 함정 모음 (여기서 시간 다 씀 — 꼭 읽을 것)

1. **`waitUntil:'networkidle'` 쓰지 말 것**
   로그인 후 socket.io 폴링이 계속 돌아 영원히 안 걸림 → 30초 타임아웃.
   → `waitUntil:'domcontentloaded'` + `waitForSelector('text=전체 회의록')`

2. **로딩 토스트 "데이터를 불러오는 중이에요"**
   페이지 이동 직후 화면 중앙에 검은 박스로 뜸. GIF에 잡히면 지저분함.
   → **"뜨는 것"을 먼저 기다린 뒤 "사라지는 것"을 기다려야 함.** 바로 `state:'hidden'` 을 기다리면 아직 안 뜬 상태라 즉시 통과해버림.
   ```js
   await toast.waitFor({state:'visible', timeout:6000}).catch(()=>{});
   await toast.waitFor({state:'hidden',  timeout:20000}).catch(()=>{});
   ```

3. **하이라이트 잔상**
   클릭으로 대상이 사라지면(메뉴 닫힘 등) 빈 주황 테두리만 남음.
   → `clickAt()` 이 클릭 직후 자동으로 하이라이트를 끄도록 이미 수정해둠.

4. **⋮ 메뉴는 `<li>` / `role=menuitem` 이 아님**
   `.MuiPopover-paper` 안의 `<p>` 태그. `.MuiMenu-list` 도 없음.

5. **템플릿 리스트 부모 한 단계 주의**
   `일반 회의록` 텍스트 노드는 `<p>` → 부모가 **항목** div → 그 부모가 **목록** 컨테이너.

6. **`page.evaluate` 인자는 1개만**
   여러 개 넘기려면 객체 하나로 묶을 것. (`Too many arguments` 에러)

7. **마이크**
   headless 에 마이크가 없음 → Chromium 실행 인자 필요:
   ```js
   args: ['--use-fake-device-for-media-capture','--use-fake-ui-for-media-stream']
   permissions: ['microphone']
   ```
   가짜 장치가 사인파를 내보내서 **레벨 미터도 실제로 움직임**. 마이크 테스트 화면 정상 통과.

8. **모든 장면은 `전체 회의록` 페이지에서 시작**
   홈(`/`)에서 시작하면 우측에 캘린더가 잘려 나와 지저분함. `/contents` 는 비어 있어 깔끔.

9. **`MutationObserver` 스로틀 필수**
   녹음 타이머가 매초 DOM을 건드림. 패치 함수가 `querySelectorAll('*')` 를 돌므로 200ms 스로틀 걸어둠.

10. **툴팁 가림**
    폴더에 hover 하면 검은 툴팁이 아래 항목을 가림 → `hideTooltips()` 로 `.MuiTooltip-popper` 숨김.

---

## 7. GIF 변환 레시피

기본 형태:
```bash
ffmpeg -y -ss <OFFSET> -i <video.webm> \
  -vf "crop=<W:H:X:Y>,fps=<FPS>,scale=<SCALE>:-1:flags=lanczos,split[s0][s1];\
[s0]palettegen=max_colors=<N>[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
  -loop 0 out.gif
```

`OFFSET` = 촬영 스크립트가 `video/meta*.json` 에 남기는 값. 영상은 페이지 생성 시점부터 녹화되므로 **로그인/준비 구간을 잘라내는 용도**입니다.

| GIF | crop | scale | fps | 비고 |
|---|---|---|---|---|
| makeFolder | `520:500:0:175` | 780 | 14 | LNB 확대 |
| makeFolder-full | 없음 | 1152 | 14 | 전체화면 |
| folderMenu | `740:460:0:180` | 1036 | 14 | 말풍선이 우측으로 나가서 폭 필요 |
| renameFolder | `560:520:0:170` | 840 | 14 | |
| deleteFolder | `940:530:0:175` | 1000 | 14 | 다이얼로그가 화면 중앙(x546~894) |
| recordMeeting | `1230:730:0:85` | 880 | 10 | `setpts=PTS/1.3` 로 1.3배속, 96색 |
| moveToFolder | `1210:520:0:0` | 1050 | 13 | |

**용량 조절 손잡이:** `fps` ↓ · `scale` ↓ · `max_colors` ↓ · `setpts=PTS/n` 배속. 녹음 GIF는 49초라 그대로면 3.3MB → 1.3배속+축소로 2.0MB.

**프레임 점검법** (GIF를 눈으로 확인할 때):
```bash
ffmpeg -i out.gif -vf "select='not(mod(n\,16))',scale=420:-1,tile=3x3" -frames:v 1 sheet.png
```

---

## 8. GIF 연출 규칙 (톤 유지용)

- 도입 1초 정지 → 조작 → 마지막 2초 정지 후 반복
- 클릭 전: 커서 이동(0.65초) → 주황 하이라이트(0.7초) → 클릭 링 → 클릭
- 타이핑 0.18초/글자
- 뷰포트 1440×900 고정, `locale: 'ko-KR'`
- 말풍선은 **꼭 필요한 설명에만** (현재는 `folderMenu.gif` 3개, `renameFolder.gif` 1개)

---

## 9. 사이트에 실제로 남긴 변경 (되돌리려면)

| 항목 | 상태 |
|---|---|
| `AI회의록` 폴더 | **생성됨, 남겨둠** (사용자 지시) |
| `주간회의` → `팀회의록` | 데모용 생성 → 이름변경 → `deleteFolder.gif` 촬영 중 삭제됨 (흔적 없음) |
| `테스트폴더`, `AICC` | 작업 중 사용자가 직접 삭제 |
| 테스트 녹음 (16초짜리) | 회의록 1건 생성 → **`AI회의록` 폴더로 이동됨, 남겨둠** (사용자 지시) |

**고정 폴더(삭제 불가):** `미완성 회의록`, `내 회의록`

---

## 10. 새 기능 GIF 추가하는 법

1. **먼저 탐색** — 로그인 후 해당 화면에 들어가 DOM을 덤프. 셀렉터·모달 구조를 모르면 촬영 스크립트를 못 씀.
   ```js
   console.log(await p.evaluate(()=>document.body.innerText.slice(0,800)));
   console.log(await p.$$eval('button', ns=>ns.map(n=>({t:n.innerText, al:n.getAttribute('aria-label')}))));
   ```
2. `rec-*.js` 하나를 복사해서 `scene` 함수만 새로 작성 (`lib.js` 헬퍼 사용)
3. 최종 스크린샷(`out/final-*.png`)으로 결과 확인
4. ffmpeg 변환 → **컨택트시트로 프레임 점검** → `newDocs/<기능>/` 에 저장

**기능당 GIF 1개** 원칙. 한 개에 몰면 PPT 슬라이드 매핑이 어렵고, 화면이 바뀌면 전체를 다시 찍어야 합니다.

---

## 11. 남은 일 / 미확인

- **PPT 제작** — 사용자가 직접 진행하기로 함 (`python-pptx` 로 자동화 가능, 미설치 상태)
- `recordMeeting.gif` 는 **AI요약 준비하기 모달까지만**. `[AI요약 시작]` 이후 요약 생성 화면은 미촬영
- 회의록이 1건뿐이라 `moveToFolder.gif` 는 **1건 선택**만 보여줌. 여러 건 동시 이동을 보여주려면 회의록을 더 만든 뒤 재촬영
- 사이트에 템플릿 4종이 실제 반영되면 `patch.js` 제거하고 재촬영 권장
