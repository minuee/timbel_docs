# 작업 6 — 로그인 대기 화면 만들기

**손대는 파일**
- `src/renderer/pages/login.html` — **신규 생성**
- `src/renderer/scripts/login.js` — **신규 생성**

**다른 파일은 건드리지 않는다.**

---

## 왜 필요한가

로그인은 브라우저에서 이뤄지므로, 앱 쪽에는 "브라우저에서 로그인 중"이라는
대기 화면이 필요하다. 아무 화면도 없으면 사용자는 앱이 멈춘 줄 안다.

화면이 할 일은 3가지뿐이다.
1. 화면이 뜨면 브라우저를 자동으로 1회 연다
2. 브라우저를 놓친 사용자를 위해 "다시 열기" 버튼을 준다
3. 로그인 성공 통지(`auth-exchanged`)를 받으면 메인 화면으로 넘어간다

> 메인 화면 이동은 **이미 있는 IPC** `electronAPI.loadIndex()` 를 쓴다
> (`main.js` 의 `load-index` 핸들러). 새로 만들지 않는다.

---

## 참고 — 창 크기와 프레임

메인 창은 `380 x 436`, `frame: false`(제목표시줄 없음)다.
그래서 이 화면도 **닫기/최소화 버튼을 직접 그려야 한다.**
버튼 동작은 이미 있는 `windowAPI.minimizeWindow()` / `windowAPI.closeWindow()` 를 쓴다.

아이콘 경로는 메인 화면(`src/renderer/index.html`)과 동일하다.
단, 이 파일은 `pages/` 안에 있으므로 경로 앞에 `../` 가 붙는다.

---

## 할 일 1 — `src/renderer/pages/login.html` 생성

```html
<!DOCTYPE html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI 회의록 녹음기 - 로그인</title>
    <link
      rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@100;300;400;500;700;900&display=swap"
    />
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }

      body {
        font-family: "Noto Sans KR", sans-serif;
        height: 100vh;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        background: #ffffff;
      }

      /* 프레임 없는 창이라 제목 영역을 직접 그린다. -webkit-app-region 으로 드래그 이동을 준다. */
      .title-area {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 16px;
        -webkit-app-region: drag;
      }
      .title-text { font-size: 18px; font-weight: 600; }
      .title-right { display: flex; gap: 8px; -webkit-app-region: no-drag; }
      .title-right button {
        background: none; border: none; cursor: pointer; padding: 0;
      }

      .login-body {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 16px;
        padding: 0 24px 32px;
        text-align: center;
      }

      .login-title { font-size: 16px; font-weight: 600; }
      .login-desc { font-size: 13px; line-height: 1.6; color: #666; }

      #retryBtn {
        margin-top: 8px;
        padding: 10px 20px;
        font-family: inherit;
        font-size: 14px;
        border: 1px solid #d0d0d0;
        border-radius: 6px;
        background: #fff;
        cursor: pointer;
      }
      #retryBtn:hover { background: #f5f5f5; }

      /* 로그인 실패 시에만 보인다. */
      #errorText { font-size: 12px; color: #d33; min-height: 18px; }
    </style>
  </head>

  <body>
    <div class="title-area">
      <div class="title-text">AI 회의록 녹음기</div>
      <div class="title-right">
        <button id="minimizeBtn">
          <img src="../assets/icons/minalizeBtn.svg" alt="최소화" />
        </button>
        <button id="closeBtn">
          <img src="../assets/icons/closeBtn.svg" alt="닫기" />
        </button>
      </div>
    </div>

    <div class="login-body">
      <div class="login-title">로그인이 필요합니다</div>
      <div class="login-desc">
        브라우저에서 로그인을 완료해주세요.<br />
        완료되면 이 화면이 자동으로 넘어갑니다.
      </div>
      <div id="errorText"></div>
      <button id="retryBtn">브라우저에서 다시 로그인</button>
    </div>

    <script src="../scripts/login.js"></script>
  </body>
</html>
```

---

## 할 일 2 — `src/renderer/scripts/login.js` 생성

```js
// 로그인 대기 화면
// - 실제 로그인은 브라우저에서 이뤄진다. 이 화면은 대기와 안내만 담당한다.
// - 로그인 완료는 딥링크 → 토큰 교환 → main 이 보내는 auth-exchanged 로 알게 된다.

const retryBtn = document.getElementById("retryBtn");
const errorText = document.getElementById("errorText");
const minimizeBtn = document.getElementById("minimizeBtn");
const closeBtn = document.getElementById("closeBtn");

// 브라우저를 여러 번 여는 것을 막는다(사용자가 버튼을 연타하는 경우).
let opening = false;

async function openLogin() {
  if (opening) return;
  opening = true;
  errorText.textContent = "";
  try {
    const res = await window.authAPI.openLogin();
    if (!res || !res.success) {
      errorText.textContent = "브라우저를 열지 못했습니다. 다시 시도해주세요.";
    }
  } catch (_) {
    errorText.textContent = "브라우저를 열지 못했습니다. 다시 시도해주세요.";
  } finally {
    opening = false;
  }
}

// 로그인 실패 사유를 사용자 문구로 바꾼다.
// main 이 보내는 error 값은 main.js 의 processDeepLink() 참고.
function toErrorMessage(error) {
  if (error === "invalid_parameters") return "로그인 정보가 올바르지 않습니다. 다시 시도해주세요.";
  if (error === "invalid_host") return "서버 주소가 올바르지 않습니다. 관리자에게 문의해주세요.";
  if (error === "network_error") return "서버에 연결하지 못했습니다. 네트워크를 확인해주세요.";
  return "로그인에 실패했습니다. 다시 시도해주세요.";
}

// 토큰 교환 결과 수신
window.electronAPI.onAuthExchanged((payload) => {
  if (payload && payload.success) {
    // 메인 화면으로 이동. 기존 load-index IPC 를 그대로 쓴다.
    window.electronAPI.loadIndex();
    return;
  }
  errorText.textContent = toErrorMessage(payload && payload.error);
});

retryBtn.addEventListener("click", openLogin);
minimizeBtn.addEventListener("click", () => window.windowAPI.minimizeWindow());
closeBtn.addEventListener("click", () => window.windowAPI.closeWindow());

// 화면이 뜨면 브라우저를 자동으로 1회 연다.
openLogin();
```

---

## 확인 방법

```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/renderer/scripts/login.js','utf8')); console.log('문법 OK')"
ls -l src/renderer/pages/login.html src/renderer/scripts/login.js
```

두 파일이 존재하고 `문법 OK` 가 나오면 성공.
**화면 확인은 작업 7 이후에 한다** (아직 앱이 이 화면을 띄우지 않는다).
