# 안내가이드 GIF 자동 촬영 — 작업 이력 & 인수인계

> **작성일** 2026-09-09 · **2차 추가** 2026-09-19 (09~17단원) · **대상 사이트** https://skhynix.timblo.io/ (A.Biz AI회의록, 개발 서버)
> **목적** 기능별 안내 가이드/매뉴얼용 GIF를 스크립트로 촬영. 화면이 바뀌면 **스크립트 재실행만으로 전체 재생성**.

이 문서 하나만 읽으면 같은 작업을 다시 하거나, 수정하거나, 새 기능으로 확장할 수 있게 쓴 것입니다.

> **문서 구성** — `1~11장` 은 **1차(01~08단원, 폴더·녹음·템플릿)**, 그 뒤 `2차 작업` 장은 **2차(09~17단원, 홈·LNB 메뉴·관리 메뉴)** 입니다.
> 1~11장 안에서 2차 때 달라진 부분은 그 자리에 **`→ 2차`** 로 표시해 뒀습니다. **어느 단원을 건드리든 두 곳을 같이 보십시오.**

---

## 1. 결론 요약 (다시 시킬 때 이것만 봐도 됨)

| 항목 | 값 |
|---|---|
| 자동화 도구 | **Playwright (Chromium, headless)** — Chrome 확장/CDP 아님 |
| 영상 → GIF | **ffmpeg** (palettegen/paletteuse) |
| 스크립트 위치 | `newDocs/_scripts/` |
| 단원 범위 | **01~08** (1차, 2026-09-09) · **09~17** (2차, 2026-09-19) |
| 산출물 위치 | **`newDocs/manual/`** — `gif` / `gif-light` / `mp4` 는 01~17, `png` / `strip` / `ppt` 는 01~08 까지<br>(1차 원본은 `newDocs/makeFolder/`, `newDocs/recording/` 에도 남아 있음) |
| 변환 | **`_scripts/build.sh`** — 단원별 crop·배속·화질을 표로 들고 있음. `./build.sh 12_calendar` 처럼 하나만도 가능 `→ 2차` |
| 뷰포트 | 단원마다 다름: **09·10·17 은 1920×1080**, 11~16 은 1440×900, 01~08 은 1440×900 `→ 2차` |
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
├── manual/                     매뉴얼 배포본 (01~17)
│   ├── gif/  gif-light/  mp4/  01~17 전부
│   ├── png/  strip/  ppt/       01~08 까지만
│   └── README.md               배포 방법 안내
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

> **주의** `.env`(비밀번호)와 `auth.json`(세션)은 **커밋 금지**.
>
> ⚠️ **2026-09-19 확인: `newDocs/` 는 `.gitignore` 에 없습니다.** (1차 문서의 기술이 틀렸음)
> `.env` 는 `.gitignore` 33행의 `.env` 규칙에 걸려 안전하지만, **`auth.json` 은 걸리지 않습니다.**
> `git add .` 하면 로그인 세션 토큰이 그대로 커밋됩니다. 아래 한 줄을 `.gitignore` 에 넣어두는 것이 안전합니다.
> ```
> newDocs/
> ```

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
| `toBox(대상)` | 로케이터 **또는** `{x,y,width,height}` 를 박스로 `→ 2차` |
| `dimRegion(page, rect, alpha)` / `undim(page)` | 영역을 반투명 흰색으로 덮음 `→ 2차` |

`highlight` · `callout` · `moveTo` 는 이제 **좌표 박스도 받습니다** (영역 단위 설명용).
`callout` 은 `side: 'right' | 'left' | 'bottom'` 이고, **화면 밖으로 나가면 자동으로 안쪽에 물리고 꼬리를 다시 잡습니다.**
`hideTooltips` 는 MUI 툴팁 + **echarts 차트 hover** 를 같이 막습니다. → 자세한 건 「2차 작업 > `lib.js` 에 추가된 것」

색상: 하이라이트/링 `#FFB020`, 말풍선 배경 `#FFF8EC` / 테두리 `#FFB020` / 글자 `#6B3E00`.

### `patch.js` — 화면 보정 (가이드용 목업)
실제 사이트와 다르게 보여줘야 할 때 **촬영 브라우저의 DOM만** 바꿉니다. 서버·실제 사이트에는 아무 영향 없음.

> `→ 2차` **`applyLnbPatch` 추가** — `내 회의록` 을 **`미완성 회의록` 으로 바꾸고 폴더 아래로 옮깁니다.**
> 제품의 의도된 순서는 `전체 회의록 / 생성한 폴더 / 미완성 회의록` 인데 2026-09-19 기준 사이트에는 `미완성 회의록` 이 없고 `내 회의록` 이 폴더 위에 있습니다.
> 사용자 폴더 행만 `⋮(더보기)` 버튼을 가지므로 그걸로 폴더를 찾아 그 아래에 끼웁니다. 18단원에서만 씁니다.

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
| `rec-home-left.js` | 09 홈 좌측 `→ 2차` |
| `rec-home-right.js` | 10 홈 우측 대시보드 `→ 2차` |
| `rec-menus.js` | 11 검색 · 12 캘린더 · 13 알림 · 14 북마크 · 15 휴지통 · 16 이용현황 `→ 2차` |
| `rec-dict.js` | 17 사전 관리 `→ 2차` |
| `rec-lnb.js` | 18 왼쪽 메뉴 하나씩 보기 `→ 2차` |
| `build.sh` | 09~17 의 gif / gif-light / mp4 생성 `→ 2차` |
| `mkgif.sh` | 영상 하나를 GIF 로 한 번 뽑아보는 보조 도구 (시행착오용). 최종본은 `build.sh` 로 만듭니다 `→ 2차` |

인자로 하나만 지정 가능: `node rec-all.js renameFolder` · `node rec-menus.js calendar` · `./build.sh 12_calendar`

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

**고정 폴더(삭제 불가):** `내 회의록`
> `→ 2차` 1차 때 있던 **`미완성 회의록` 은 2026-09-19 기준 LNB 에서 사라졌습니다.** 지금은 `내 회의록` / `AI회의록` 만 보입니다.
>
> `→ 2차` 2차에서 남긴 변경은 「2차 작업 > 사이트에 남긴 변경」 참고 (사전 `세미컨덕터 → 반도체` 1건).

---

## 10. 새 기능 GIF 추가하는 법

1. **먼저 탐색** — 로그인 후 해당 화면에 들어가 DOM을 덤프. 셀렉터·모달 구조를 모르면 촬영 스크립트를 못 씀.
   ```js
   console.log(await p.evaluate(()=>document.body.innerText.slice(0,800)));
   console.log(await p.$$eval('button', ns=>ns.map(n=>({t:n.innerText, al:n.getAttribute('aria-label')}))));
   ```
2. `rec-*.js` 하나를 복사해서 `scene` 함수만 새로 작성 (`lib.js` 헬퍼 사용)
3. 최종 스크린샷(`out/final-*.png`)으로 결과 확인
4. ffmpeg 변환 → **컨택트시트로 프레임 점검** → `newDocs/manual/gif/` 에 저장
   `→ 2차` 09번 이후로는 `build.sh` 의 `ITEMS` 표에 한 줄 추가하면 gif·gif-light·mp4 가 한 번에 나옵니다.
5. **뷰포트를 먼저 정할 것** `→ 2차` — 1440 에서 잘리는 화면이 있습니다 (홈 대시보드, 사전 관리 모달, 휴지통 표). 찍기 전에 스크린샷으로 확인하십시오.

**기능당 GIF 1개** 원칙. 한 개에 몰면 PPT 슬라이드 매핑이 어렵고, 화면이 바뀌면 전체를 다시 찍어야 합니다.

---

## 11. 남은 일 / 미확인 (1차 기준 — 2차 기준은 문서 맨 뒤)

- **PPT 제작** — 사용자가 직접 진행하기로 함 (`python-pptx` 로 자동화 가능, 미설치 상태)
  `→ 2차` 2026-09-19 기준 `python-pptx` · `Pillow` **여전히 미설치**. `ppt/` 는 01~08 까지만 들어 있음
- `recordMeeting.gif` 는 **AI요약 준비하기 모달까지만**. `[AI요약 시작]` 이후 요약 생성 화면은 미촬영
- 회의록이 1건뿐이라 `moveToFolder.gif` 는 **1건 선택**만 보여줌. 여러 건 동시 이동을 보여주려면 회의록을 더 만든 뒤 재촬영
- 사이트에 템플릿 4종이 실제 반영되면 `patch.js` 제거하고 재촬영 권장


---

# 2차 작업 (2026-09-19) — 09~17단원 추가

01~08(폴더·녹음·템플릿)에 이어 **홈 화면·LNB 메뉴·관리 메뉴**를 9단원 추가했습니다.

## 추가된 단원

| # | 내용 | 스크립트 | 뷰포트 |
|---|---|---|---|
| 09 | 홈 좌측 — 로고 / 녹음 / 회의록 메뉴 / 관리 메뉴 | `rec-home-left.js` | 1920×1080 |
| 10 | 홈 우측 — 캘린더·최근 회의록·최근 검색어·최근 북마크·녹음량·기록된 회의 시간 | `rec-home-right.js` | 1920×1080 |
| 11 | 검색 / 상세 검색 | `rec-menus.js search` | 1440×900 |
| 12 | 캘린더 | `rec-menus.js calendar` | 1440×900 |
| 13 | 알림 메시지 | `rec-menus.js inbox` | 1440×900 |
| 14 | 북마크 | `rec-menus.js bookmark` | 1440×900 |
| 15 | 휴지통 | `rec-menus.js recycle` | 1440×900 |
| 16 | 이용 현황 | `rec-menus.js usage` | 1440×900 |
| 17 | 사전 관리 | `rec-dict.js` | 1920×1080 |
| 18 | 왼쪽 메뉴 10개를 하나씩 설명 | `rec-lnb.js` | 1920×1080 |

변환은 **`_scripts/build.sh`** 하나로 끝납니다 (crop·배속·화질을 단원별 표로 들고 있음).

```bash
node rec-menus.js calendar   # 12번만 다시 촬영
./build.sh 12_calendar       # gif / gif-light / mp4 재생성
./build.sh                   # 09~17 전부
```

## `lib.js` 에 추가된 것

| 함수 | 역할 | 왜 필요했나 |
|---|---|---|
| `toBox(대상)` | 로케이터 **또는** `{x,y,width,height}` 를 받아 박스로 | 09·10은 "이 구역은 무엇" 설명이라 요소가 아닌 **영역**을 강조해야 함 |
| `dimRegion(page, rect, alpha)` / `undim(page)` | 지정 영역을 반투명 흰색으로 덮음 | 크롭 경계에서 카드가 반쯤 잘려 들어오는 걸 가림 |
| `callout(..., side:'left')` | 말풍선을 요소 **왼쪽**에 | 우측 끝 카드는 오른쪽에 붙이면 화면 밖으로 나감 |

`callout()` 은 이제 **화면 밖으로 나가면 안쪽으로 자동으로 물리고 꼬리 위치를 다시 잡습니다.**
`hideTooltips()` 는 MUI 툴팁뿐 아니라 **echarts 차트의 pointer-events 도 끕니다** (아래 함정 13번).

## ⚠️ 2차에서 새로 밟은 함정

11. **뷰포트를 단원마다 다르게 가야 한다**
    - 홈 대시보드(09·10): 1440 에서 캘린더 우측과 히트맵이 **잘림** → 1920 필요
    - 사전 관리 모달(17): 1440 에서 `신규 등록`·`닫기` 가 **화면 밖**(x≈1469) → 1920 필요
    - 나머지(11~16): 1440 으로 충분. 기존 01~08 과 규격이 같아 오히려 잘 맞음

12. **휴지통 표의 `복구`·`영구삭제` 열이 가로로 잘려 있다**
    DOM 에는 있어서 셀렉터는 잡히지만 화면 밖이라 강조가 안 보임.
    → `.MuiDataGrid-virtualScroller` 를 `scrollLeft` 로 부드럽게 밀어서 보여주고, 말풍선에도 "표를 오른쪽으로 밀면" 이라고 적었음.

13. **echarts 차트에 커서가 올라가면 값 툴팁 + 세로 기준선이 뜬다**
    설명 말풍선을 가림. `.echarts-for-react{pointer-events:none}` 로 hover 자체를 차단 (차트는 클릭할 일이 없음).

14. **이용 현황 차트는 `<canvas>` 이고 `window.echarts` 도 없다**
    → **DOM 패치로 수치를 목업할 수 없음.** 텍스트 숫자만 바꾸면 "12회"인데 그래프는 0이라 앞뒤가 안 맞음.
    사용자 결정: **0인 실제 화면 그대로 찍고 "무엇이 표시되는지"만 설명.**

15. **`li:has-text("사전 관리")` 는 두 개가 잡힌다**
    개인 환경 설정 팝업이 사이드바 메뉴 `li` **안에** 렌더링됨 → `.first()` 는 바깥 메뉴(=팝업 토글)라 모달이 안 열림. **`.last()` 를 써야 함.**

16. **같은 글자가 화면 두 곳에 있으면 x 좌표로 걸러야 한다**
    `'사전 관리'` 는 좌측 팝업 메뉴에도, 모달 제목에도 있음. 텍스트로만 찾으면 팝업 쪽이 잡혀 강조가 엉뚱한 데로 감 → `minX` 로 걸렀음.

17. **카드 제목만 잡히는 문제**
    텍스트에서 부모로 올라갈 때 **폭 조건만** 두면 제목 줄(높이 50px)에서 멈춤. **높이 조건(`minH`)도 같이** 봐야 카드 전체가 잡힘.

18. **`waitToast` 가 5초를 통째로 버리고 있었다**
    토스트가 안 뜨는 페이지에서도 `waitFor({state:'visible'})` 가 타임아웃까지 기다림 → 2.5초로 줄여 각 GIF 가 2~3초씩 짧아짐.

19. **`du -h` 로 GIF 용량을 보면 안 된다**
    macOS `du` 는 디스크 블록 단위라 1.4MB 파일이 2.3M 으로 찍힘. `stat -f%z` 로 실제 바이트를 봐야 함.

20. **zsh 에서 `$C[p]` 는 배열 첨자로 해석된다**
    `palettegen=max_colors=$C[p]` 가 빈 값으로 전달됨 → `${C}` 로 감쌀 것.

## GIF 변환 레시피 (09~17)

디더링은 화면마다 유불리가 갈립니다 — **차트가 많으면 `none`, 단색 UI 는 `bayer` 가 작습니다.**
`build.sh` 는 둘 다 만들어 **작은 쪽만 남깁니다.**

| GIF | crop | 배속 | 폭/fps/색 | 결과 |
|---|---|---|---|---|
| 09 home-left | `700:1080:0:0` | — | 660 / 11 / 96 | 1.42MB · 18.5초 |
| 10 home-right | `1680:910:240:0` | — | 1060 / 10 / 80 | 1.50MB · 21.8초 |
| 11 search | `880:600:560:0` | — | 880 / 11 / 88 | 0.95MB · 16.4초 |
| 12 calendar | 없음 | — | 1100 / 10 / 88 | 1.53MB · 21.6초 |
| 13 inbox | 없음 | — | 1100 / 10 / 88 | 0.86MB · 18.2초 |
| 14 bookmark | 없음 | — | 1100 / 10 / 88 | 0.61MB · 15.1초 |
| 15 recycle | 없음 | — | 1100 / 10 / 88 | 1.02MB · 23.5초 |
| 16 usage | 없음 | — | 1040 / 8 / 72 | 2.02MB · 28.0초 |
| 17 dictionary | `1640:910:0:150` | **1.3배** | 1150 / 10 / 88 | 2.06MB · 27.1초 |
| 18 lnb-menus | `700:1080:0:0` | — | 660 / 9 / 80 | 2.01MB · 30.3초 |

## 사이트에 남긴 변경 (2차)

| 항목 | 상태 |
|---|---|
| 사전 `세미컨덕터 → 반도체` | **등록됨, 남겨둠** (사용자 지시). 17번 재촬영 시 **먼저 지워야 중복 등록이 안 됨** |
| 그 외 | 없음 — 11~16 은 읽기 전용 화면만 |

## 2차에서 확인한 셀렉터 추가분

```js
// 사이드바 네 구역
'.sidebar .MuiPaper-root > div'      // children: [0]로고+녹음 [1]회의록메뉴 [2]hr [3]프로필 [4]관리메뉴
'img[src*="sk_logo"]'                // 로고 (클릭 → /home 이동 확인함)

// 홈 대시보드 카드 6개
'.home-container > div'              // children[0]=상단 3장, children[1]=하단 3장
                                     // 상단: 캘린더 / 최근 회의록 / 최근 검색어
                                     // 하단: 최근 북마크 / 녹음량(제목 없음) / 기록된 회의 시간

// 상세 검색
'.detail-search-container'           // 팝업 전체 (검색어·조회 기간·저장 폴더·참석자·공유·유형 + 초기화/검색)

// 캘린더 페이지 (/calendar)
'.calendar'                          // 월 격자
'.component'                         // 날짜 셀 컨테이너 (날짜 클릭은 여기서 getByText)
'.day-contents'                      // 우측 패널 — 날짜 클릭 시 그날 회의록. 카드 클릭 → /content/<id>

// 알림 (/inbox) · 휴지통 (/recycle)
'.MuiTabs-root'                      // 전체 / 회의록 / 오류
'button[name="전체 확인"]'
'.MuiDataGrid-virtualScroller'       // 휴지통 표 (가로 스크롤)

// 이용 현황 (/usage)
'.echarts-for-react'                 // 3개: [0]히트맵 [1]기록된 회의 시간 [2]사전 도넛 — 전부 canvas

// 사전 관리
'[aria-label="개인 환경 설정"]'        // → 팝업
"li:has-text('사전 관리') .last()"    // 팝업 안 항목 (.first() 는 바깥 메뉴)
'input[placeholder="단어를 입력하세요.(필수)"]'
'input[placeholder="변경할 단어를 입력하세요.(필수)"]'
```

## 2차 기준 남은 일

> **미결 — 다음에 이어받을 때 먼저 볼 것 (2026-09-19)**
>
> 1. **`내 회의록` 이 제거될 예정** 인데 09번 GIF 와 PPT 5쪽 본문에는 아직 이 문구가 남아 있습니다.
>    > 현재: "회의록을 찾아보는 메뉴 — 전체 회의록 · **내 회의록** · 폴더 · 캘린더 · 알림 메시지 · 북마크 · 휴지통"
>    > 바꾼다면: "전체 회의록 · 폴더 · **미완성 회의록** · 캘린더 · 알림 메시지 · 북마크 · 휴지통"
>
>    09번을 다시 찍을 거면 `rec-home-left.js` 에 18번과 같은 `applyLnbPatch` 를 태우면 화면의 메뉴 이름·순서까지 같이 맞춰집니다.
>    **사용자가 "이번엔 그냥 두라"고 해서 보류 중입니다.**
>
> 2. **18번의 `미완성 회의록` 설명 문구가 미검증입니다.**
>    > "녹음이나 AI 요약이 끝나지 않은 회의록이 여기에 남습니다."
>
>    실제 제품 정의를 확인하지 못해 추정으로 쓴 문장입니다. 확정되면 `rec-lnb.js` 의 `ITEMS` 배열에서 한 줄만 고치고 재촬영하면 됩니다.


- ~~`png/` · `strip/` · `ppt/` 는 01~08 까지만~~ → **해결됨.** 2026-09-19 10:55 사용자가 직접 01~18 전부 생성함
  (`AI회의록_전체가이드.pptx` 51장 + 경량본 + PDF). 이 환경에는 여전히 `python-pptx`·`Pillow` 가 없으므로, 다시 만들 일이 생기면 설치부터 해야 함
- `mp4/` 만 19개 — 16·17 의 분할본(`16a`·`16b`·`17a`·`17b`)에 대응하는 mp4 가 없음
- LNB 고정 폴더가 바뀌었음: 1차 때 있던 `미완성 회의록` 이 없어지고 `내 회의록` / `AI회의록` 만 있음
- `manual/gif/` 의 `16a` · `16b` · `17a` · `17b` 는 **사용자가 PPT 제작 중 직접 나눈 파일** (2026-09-19 09:56). 촬영 스크립트에 대응물이 없으니 `build.sh` 로는 재생성되지 않습니다. **덮어쓰지 말 것.**
- PPT 본체는 사용자가 만들었습니다: `newDocs/AI회의록_전체가이드_경량.pptx` (51장, 단원마다 설명 슬라이드 + GIF 슬라이드 한 쌍)
- 홈의 녹음량 히트맵 카드는 **제목이 아예 없음** (다른 카드는 다 있음) — 가이드에서는 "날짜별 녹음량을 색 농도로" 라고 풀어서 설명함
