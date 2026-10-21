// 로그인 화면
// - 사번 로그인: authAPI.loginWithEmpno → 성공하면 메인 프로세스가 index.html 로 넘긴다.
// - 체크박스: "사번 저장"(사번 폼이 보일 때), "로그인 유지"(SESSION_PERSIST_ENABLED 가 true 일 때).
//   바꿀 때마다 메인 프로세스에 저장한다(loginPrefs.js) — SSO 는 딥링크로 돌아오므로 미리 있어야 한다.
// - MyAccess 로그인: 브라우저를 열고 기다린다. 웹이 딥링크를 호출하면 메인 프로세스가
//   토큰을 교환하고 index.html 로 넘긴다. 실패하면 auth-exchanged 로 사유가 온다.
// - 약관 미동의(HMP 404/422): 사번 로그인은 응답 error 'terms_not_agreed', MyAccess·로그인 유지 복원은
//   메인 프로세스가 로그아웃시키고 이 화면을 다시 띄운다(auth:take-terms-notice). 둘 다 안내 팝업을 띄운다.

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
const loginOptions = document.getElementById("loginOptions");
const rememberEmpnoLabel = document.getElementById("rememberEmpnoLabel");
const rememberEmpnoCheck = document.getElementById("rememberEmpnoCheck");
const keepLoginLabel = document.getElementById("keepLoginLabel");
const keepLoginCheck = document.getElementById("keepLoginCheck");
const termsModal = document.getElementById("termsModal");
const termsBox = termsModal.querySelector(".terms-box");
const termsBody = document.getElementById("termsBody");

const WINDOW_WIDTH = 380;
const WINDOW_MIN_HEIGHT = 300;
const WINDOW_BOTTOM_MARGIN = 16;
// 약관 팝업 위치: 타이틀 바 높이(login.css .terms-modal top) + 위아래 여백
const TERMS_MODAL_TOP = 40;
const TERMS_MODAL_PADDING = 16;

// 보이는 항목(사번 폼, 테스트 로그인 펼침 여부)에 따라 높이가 달라져서 마지막 요소 위치로 창을 맞춘다.
function applyWindowSize() {
  requestAnimationFrame(() => {
    // 맨 아래 요소: 언어 선택(MULTI_LANG_ENABLED 일 때만 보임) 또는 안내 문구
    const last = languageSelectWrap && !languageSelectWrap.hidden ? languageSelectWrap : loginMessage;
    const bottom = last.getBoundingClientRect().bottom;
    let height = Math.max(WINDOW_MIN_HEIGHT, Math.ceil(bottom + WINDOW_BOTTOM_MARGIN));
    // 약관 팝업이 떠 있으면 팝업이 잘리지 않을 만큼은 높인다
    if (!termsModal.hidden) {
      height = Math.max(height, Math.ceil(TERMS_MODAL_TOP + TERMS_MODAL_PADDING * 2 + termsBox.offsetHeight));
    }
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
      // 약관 미동의(404/422)는 terms_not_agreed 로 따로 와서 팝업으로 보여준다. 그 밖의 거절은 서버 메시지 그대로.
      return result.message || t("login.msg_rejected", { code: result.httpCode });
    case "invalid_parameters":
    case "invalid_host":
      return t("login.msg_invalid_response");
    default:
      return t("login.msg_failed_with_error", { error: result.error || "unknown" });
  }
}

// 약관 안내 팝업. 본문 문구의 {url} 자리에 링크를 넣는다(누르면 기본 브라우저).
let termsAgreeUrl = "https://aimeeting.skhynix.com/";
function renderTermsBody() {
  const parts = t("terms.body").split("{url}");
  termsBody.textContent = "";
  parts.forEach((part, index) => {
    if (index > 0) {
      const link = document.createElement("a");
      link.className = "terms-link";
      link.href = "#";
      link.textContent = termsAgreeUrl;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        window.authAPI.openTermsPage().catch(() => {});
      });
      termsBody.appendChild(link);
    }
    termsBody.appendChild(document.createTextNode(part));
  });
}

function showTermsNotice() {
  renderTermsBody();
  showMessage("");
  termsModal.hidden = false;
  applyWindowSize();
  document.getElementById("termsLogoutBtn").focus();
}

// 이미 로그아웃된 상태라 팝업만 닫고 로그인 화면에 남는다.
document.getElementById("termsLogoutBtn").addEventListener("click", () => {
  termsModal.hidden = true;
  applyWindowSize();
});
document.getElementById("termsQuitBtn").addEventListener("click", () => {
  window.windowAPI.appQuit();
});

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
  await saveLoginOptions();
  try {
    const result = await window.authAPI.loginWithEmpno(empno, passwordInput.value);
    if (result && result.success) {
      // 화면 전환은 메인 프로세스가 한다.
      showMessage(() => t("login.msg_success"));
      return;
    }
    if (result && result.error === "terms_not_agreed") {
      showTermsNotice();
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

function saveLoginOptions() {
  return window.authAPI
    .setLoginOptions({
      rememberEmpno: !rememberEmpnoLabel.hidden && rememberEmpnoCheck.checked,
      keepLogin: !keepLoginLabel.hidden && keepLoginCheck.checked,
    })
    .catch(() => {});
}
rememberEmpnoCheck.addEventListener("change", saveLoginOptions);
keepLoginCheck.addEventListener("change", saveLoginOptions);

ssoBtn.addEventListener("click", async () => {
  await saveLoginOptions();
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
  // "로그인 유지" 체크는 테스트 로그인에도 적용된다
  await saveLoginOptions();
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
  if (!termsModal.hidden) renderTermsBody();
  applyWindowSize();
});

// 체크박스 표시와 마지막 값. 저장해 둔 사번이 있으면 채워 둔다.
function renderLoginOptions(status) {
  const prefs = (status && status.loginPrefs) || {};
  rememberEmpnoLabel.hidden = empnoForm.hidden;
  keepLoginLabel.hidden = !(status && status.keepLoginEnabled);
  loginOptions.hidden = rememberEmpnoLabel.hidden && keepLoginLabel.hidden;
  rememberEmpnoCheck.checked = !!prefs.rememberEmpno;
  keepLoginCheck.checked = !!prefs.keepLogin;
  if (!empnoForm.hidden && prefs.rememberEmpno && prefs.empno) empnoInput.value = prefs.empno;
  // 사번 폼이 숨겨져 있으면 "로그인 유지" 줄을 MyAccess 버튼 위로 옮긴다
  if (empnoForm.hidden && !loginOptions.hidden) ssoBtn.before(loginOptions);
}

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
  if (status && status.termsAgreeUrl) termsAgreeUrl = status.termsAgreeUrl;
  if (status && status.defaultEndpoint) {
    defaultEndpoint = status.defaultEndpoint;
    renderEndpointPlaceholder();
  }
  renderLoginOptions(status);
  if (!empnoForm.hidden) (empnoInput.value ? passwordInput : empnoInput).focus();
  // 메인 화면에서 돌아온 경우 창 크기 제약이 남아 있을 수 있어 다시 맞춘다.
  applyWindowSize();
  // MyAccess·로그인 유지 복원 뒤 약관 미동의로 로그아웃돼 이 화면으로 왔으면 안내 팝업
  const notice = await window.authAPI.takeTermsNotice().catch(() => null);
  if (notice && notice.show) showTermsNotice();
}

init();
