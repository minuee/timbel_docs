# 작업 10 — 로그인 화면 동작 (login.js)

**손대는 파일**: `src/renderer/scripts/login.js` — **신규** (이미 있으면 통째로 덮어쓰기)
**다른 파일은 건드리지 않는다.**
**선행 작업**: 작업 8(preload), 작업 9(login.html)

## 하는 일
- 사번 폼 제출 → `authAPI.loginWithEmpno()`. 성공하면 메인 프로세스가 화면을 넘긴다. 실패하면 사유를 빨간 글씨로 보여준다.
- MyAccess 로그인 버튼 → `authAPI.openSso()` 로 브라우저를 연다. 딥링크 교환이 실패하면 `onAuthExchanged` 로 사유가 온다.
- 화면이 뜨는 사이에 딥링크 교환이 먼저 끝났으면 바로 메인 화면으로 간다.
- 비밀번호 칸은 시도할 때마다 비운다.

## 할 일
아래 내용 그대로 `src/renderer/scripts/login.js` 파일을 만든다.

```js
// 로그인 화면
// - 사번 로그인: authAPI.loginWithEmpno → 성공하면 메인 프로세스가 index.html 로 넘긴다.
// - MyAccess 로그인: 브라우저를 열고 기다린다. 웹이 딥링크를 호출하면 메인 프로세스가
//   토큰을 교환하고 index.html 로 넘긴다. 실패하면 auth-exchanged 로 사유가 온다.

const empnoForm = document.getElementById("empnoForm");
const empnoInput = document.getElementById("empnoInput");
const passwordInput = document.getElementById("passwordInput");
const empnoSubmitBtn = document.getElementById("empnoSubmitBtn");
const ssoBtn = document.getElementById("ssoBtn");
const loginMessage = document.getElementById("loginMessage");

const WINDOW_WIDTH = 380;
const WINDOW_HEIGHT = 436;

function showMessage(text, isError) {
  loginMessage.textContent = text || "";
  loginMessage.classList.toggle("error", !!isError);
}

function setBusy(busy) {
  empnoSubmitBtn.disabled = busy;
  ssoBtn.disabled = busy;
}

// 서버/메인 프로세스 오류 코드를 사용자 문구로 바꾼다.
function toUserMessage(result) {
  if (!result) return "로그인에 실패했습니다.";
  switch (result.error) {
    case "empno_required":
      return "사번을 입력해 주세요.";
    case "network_error":
      return "서버에 연결할 수 없습니다.\n사내망 연결 상태를 확인해 주세요.";
    case "login_rejected":
      // 모바일 기준 404/422 는 약관 미동의. 서버 메시지가 있으면 그대로 보여준다.
      return result.message || `로그인이 거절되었습니다. (code ${result.httpCode})`;
    case "invalid_parameters":
    case "invalid_host":
      return "로그인 응답이 올바르지 않습니다.\n다시 시도해 주세요.";
    default:
      return `로그인에 실패했습니다.\n(${result.error || "unknown"})`;
  }
}

document.getElementById("minimizeBtn").addEventListener("click", () => {
  window.windowAPI.minimizeWindow();
});
document.getElementById("closeBtn").addEventListener("click", () => {
  window.windowAPI.closeWindow();
});

empnoForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const empno = empnoInput.value.trim();
  if (!empno) {
    showMessage("사번을 입력해 주세요.", true);
    empnoInput.focus();
    return;
  }

  setBusy(true);
  showMessage("로그인 중입니다...");
  try {
    const result = await window.authAPI.loginWithEmpno(empno, passwordInput.value);
    if (result && result.success) {
      // 화면 전환은 메인 프로세스가 한다.
      showMessage("로그인되었습니다.");
      return;
    }
    showMessage(toUserMessage(result), true);
  } catch (err) {
    showMessage(toUserMessage({ error: err && err.message }), true);
  } finally {
    passwordInput.value = "";
    setBusy(false);
  }
});

ssoBtn.addEventListener("click", async () => {
  const result = await window.authAPI.openSso();
  if (result && result.success) {
    showMessage("브라우저에서 MyAccess 로그인을 완료해 주세요.\n완료되면 자동으로 넘어갑니다.");
  } else {
    showMessage(toUserMessage(result), true);
  }
});

// 딥링크 토큰 교환 결과. 성공 시 화면 전환은 메인 프로세스가 하므로 실패만 다룬다.
window.electronAPI.onAuthExchanged((payload) => {
  if (payload && payload.success) {
    showMessage("로그인되었습니다.");
    return;
  }
  showMessage(toUserMessage(payload), true);
});

async function init() {
  // 메인 화면에서 돌아온 경우 창 크기 제약이 남아 있을 수 있어 다시 맞춘다.
  window.electronAPI.setWindowConstraints({
    resizable: false,
    minWidth: WINDOW_WIDTH,
    maxWidth: WINDOW_WIDTH,
    minHeight: WINDOW_HEIGHT,
    maxHeight: WINDOW_HEIGHT,
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
  });

  const status = await window.authAPI.getStatus();
  // 화면이 뜨는 사이 딥링크 교환이 먼저 끝났을 수 있다.
  if (status && status.authenticated) {
    window.electronAPI.loadIndex();
    return;
  }
  empnoForm.hidden = !(status && status.empnoLoginEnabled);
  if (!empnoForm.hidden) empnoInput.focus();
}

init();
```

## 확인 방법
```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/renderer/scripts/login.js','utf8')); console.log('문법OK')"
```
문법OK 가 나오면 성공. 이어서 INDEX 문서 "7. 완료 확인"을 사람이 직접 진행한다.
