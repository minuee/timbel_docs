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
const manualLogin = document.getElementById("manualLogin");
const manualForm = document.getElementById("manualForm");
const manualName = document.getElementById("manualName");
const manualEmpno = document.getElementById("manualEmpno");
const manualToken = document.getElementById("manualToken");
const manualEndpoint = document.getElementById("manualEndpoint");
const manualSubmitBtn = document.getElementById("manualSubmitBtn");
const languageSelectWrap = document.getElementById("languageSelectWrap");

const WINDOW_WIDTH = 380;
const WINDOW_MIN_HEIGHT = 300;
const WINDOW_BOTTOM_MARGIN = 16;

// 보이는 항목(사번 폼, 테스트 로그인 펼침 여부)에 따라 높이가 달라져서 마지막 요소 위치로 창을 맞춘다.
function applyWindowSize() {
  requestAnimationFrame(() => {
    // 맨 아래 요소: 언어 선택(MULTI_LANG_ENABLED 일 때만 보임) 또는 안내 문구
    const last = languageSelectWrap && !languageSelectWrap.hidden ? languageSelectWrap : loginMessage;
    const bottom = last.getBoundingClientRect().bottom;
    const height = Math.max(WINDOW_MIN_HEIGHT, Math.ceil(bottom + WINDOW_BOTTOM_MARGIN));
    window.electronAPI.setWindowConstraints({
      resizable: false,
      minWidth: WINDOW_WIDTH,
      maxWidth: WINDOW_WIDTH,
      minHeight: height,
      maxHeight: height,
      width: WINDOW_WIDTH,
      height: height,
    });
  });
}

// text 는 문구를 만드는 함수로 받는다 — 언어가 바뀌면 같은 안내를 새 언어로 다시 그린다
let lastMessage = null;
function showMessage(text, isError) {
  lastMessage = { text, isError };
  loginMessage.textContent = (typeof text === "function" ? text() : text) || "";
  loginMessage.classList.toggle("error", !!isError);
  applyWindowSize();
}

function setBusy(busy) {
  empnoSubmitBtn.disabled = busy;
  ssoBtn.disabled = busy;
  manualSubmitBtn.disabled = busy;
}

const t = (key, params) => window.i18n.t(key, params);

// 서버/메인 프로세스 오류 코드를 사용자 문구로 바꾼다.
function toUserMessage(result) {
  if (!result) return t("login.msg_failed");
  switch (result.error) {
    case "empno_required":
      return t("login.msg_empno_required");
    case "access_token_required":
      return t("login.msg_access_token_required");
    case "invalid_endpoint":
      return t("login.msg_invalid_endpoint");
    case "network_error":
      return t("login.msg_network_error");
    case "login_rejected":
      // 모바일 기준 404/422 는 약관 미동의. 서버 메시지가 있으면 그대로 보여준다.
      return result.message || t("login.msg_rejected", { code: result.httpCode });
    case "invalid_parameters":
    case "invalid_host":
      return t("login.msg_invalid_response");
    default:
      return t("login.msg_failed_with_error", { error: result.error || "unknown" });
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
    showMessage(() => t("login.msg_empno_required"), true);
    empnoInput.focus();
    return;
  }

  setBusy(true);
  showMessage(() => t("login.msg_in_progress"));
  try {
    const result = await window.authAPI.loginWithEmpno(empno, passwordInput.value);
    if (result && result.success) {
      // 화면 전환은 메인 프로세스가 한다.
      showMessage(() => t("login.msg_success"));
      return;
    }
    showMessage(() => toUserMessage(result), true);
  } catch (err) {
    showMessage(() => toUserMessage({ error: err && err.message }), true);
  } finally {
    passwordInput.value = "";
    setBusy(false);
  }
});

ssoBtn.addEventListener("click", async () => {
  const result = await window.authAPI.openSso();
  if (result && result.success) {
    showMessage(() => t("login.msg_sso_waiting"));
  } else {
    showMessage(() => toUserMessage(result), true);
  }
});

manualForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(true);
  showMessage(() => t("login.msg_in_progress"));
  try {
    const result = await window.authAPI.loginManual({
      name: manualName.value,
      empno: manualEmpno.value,
      accessToken: manualToken.value,
      endpoint: manualEndpoint.value,
    });
    if (result && result.success) {
      showMessage(() => t("login.msg_success"));
      return;
    }
    showMessage(() => toUserMessage(result), true);
  } catch (err) {
    showMessage(() => toUserMessage({ error: err && err.message }), true);
  } finally {
    setBusy(false);
  }
});

manualLogin.addEventListener("toggle", applyWindowSize);

// 딥링크 토큰 교환 결과. 성공 시 화면 전환은 메인 프로세스가 하므로 실패만 다룬다.
window.electronAPI.onAuthExchanged((payload) => {
  if (payload && payload.success) {
    showMessage(() => t("login.msg_success"));
    return;
  }
  showMessage(() => toUserMessage(payload), true);
});

let defaultEndpoint = "";
function renderEndpointPlaceholder() {
  manualEndpoint.placeholder = defaultEndpoint
    ? t("login.manual_endpoint_default", { url: defaultEndpoint })
    : t("login.manual_endpoint");
}

// 언어 선택 상자(languageSelect.js)로 바뀌면 스크립트가 그린 글자를 다시 그린다(나머지는 preload 가 바꿈)
window.i18n.onChange(() => {
  renderEndpointPlaceholder();
  if (lastMessage) showMessage(lastMessage.text, lastMessage.isError);
  applyWindowSize();
});

async function init() {
  renderEndpointPlaceholder();
  const status = await window.authAPI.getStatus();
  // 화면이 뜨는 사이 딥링크 교환이 먼저 끝났을 수 있다.
  if (status && status.authenticated) {
    window.electronAPI.loadIndex();
    return;
  }
  empnoForm.hidden = !(status && status.empnoLoginEnabled);
  manualLogin.hidden = !(status && status.manualLoginEnabled);
  if (status && status.defaultEndpoint) {
    defaultEndpoint = status.defaultEndpoint;
    renderEndpointPlaceholder();
  }
  if (!empnoForm.hidden) empnoInput.focus();
  // 메인 화면에서 돌아온 경우 창 크기 제약이 남아 있을 수 있어 다시 맞춘다.
  applyWindowSize();
}

init();
