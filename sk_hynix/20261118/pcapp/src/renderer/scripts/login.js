// 로그인 화면 (ver1)
// - 체크박스: "로그인 유지"(SESSION_PERSIST_ENABLED 가 true 일 때). 바꿀 때마다 메인 프로세스에 저장한다(loginPrefs.js).
// - (예전 사번 로그인·MyAccess 딥링크 로그인은 SSO 이전 방식이라 11-17 지웠다)
// - 시스템 로그인: authAPI.systemLogin → 메인 프로세스가 AM-Tray(AmHelper.exe)로 인가토큰을 받아 로그인한다.
//   미로그인이면 AM 로그인 창을 띄우고(pending), 로그인이 끝나면 결과가 onAuthExchanged 로 온다.
// - 약관 미동의(404/422): 로그인·로그인 유지 복원 뒤 확인에서 걸리면 메인 프로세스가 로그아웃시키고
//   이 화면을 다시 띄운다(auth:take-terms-notice). 안내 팝업을 띄운다.
// - AI회의록 권한 없음: 로그인 뒤 권한 확인에서 걸리면 메인 프로세스가 로그아웃시키고 이 화면을 다시 띄운다
//   (auth:take-terms-notice 의 access). 안내 팝업 [확인] → 앱 종료.

const systemLoginBtn = document.getElementById("systemLoginBtn");
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
const keepLoginLabel = document.getElementById("keepLoginLabel");
const keepLoginCheck = document.getElementById("keepLoginCheck");
const termsModal = document.getElementById("termsModal");
const termsBox = termsModal.querySelector(".terms-box");
const termsBody = document.getElementById("termsBody");
const accessModal = document.getElementById("accessModal");
const accessBox = accessModal.querySelector(".terms-box");

const WINDOW_WIDTH = 380;
const WINDOW_MIN_HEIGHT = 300;
const WINDOW_BOTTOM_MARGIN = 16;
// 약관 팝업 위치: 타이틀 바 높이(login.css .terms-modal top) + 위아래 여백
const TERMS_MODAL_TOP = 40;
const TERMS_MODAL_PADDING = 16;

// 보이는 항목(테스트 로그인 펼침 여부 등)에 따라 높이가 달라져서 마지막 요소 위치로 창을 맞춘다.
function applyWindowSize() {
  requestAnimationFrame(() => {
    // 맨 아래 요소: 언어 선택(MULTI_LANG_ENABLED 일 때만 보임) 또는 안내 문구
    const last = languageSelectWrap && !languageSelectWrap.hidden ? languageSelectWrap : loginMessage;
    const bottom = last.getBoundingClientRect().bottom;
    let height = Math.max(WINDOW_MIN_HEIGHT, Math.ceil(bottom + WINDOW_BOTTOM_MARGIN));
    // 약관·권한 팝업이 떠 있으면 팝업이 잘리지 않을 만큼은 높인다
    if (!termsModal.hidden) {
      height = Math.max(height, Math.ceil(TERMS_MODAL_TOP + TERMS_MODAL_PADDING * 2 + termsBox.offsetHeight));
    }
    if (!accessModal.hidden) {
      height = Math.max(height, Math.ceil(TERMS_MODAL_TOP + TERMS_MODAL_PADDING * 2 + accessBox.offsetHeight));
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
  systemLoginBtn.disabled = busy;
  manualSubmitBtn.disabled = busy;
}

const t = (key, params) => window.i18n.t(key, params);

// 서버/메인 프로세스 오류 코드를 사용자 문구로 바꾼다.
function toUserMessage(result) {
  if (!result) return t("login.msg_failed");
  switch (result.error) {
    case "access_token_required":
      return t("login.msg_access_token_required");
    case "invalid_endpoint":
      return t("login.msg_invalid_endpoint");
    case "network_error":
      return t("login.msg_network_error");
    case "system_login_not_ready":
      return t("login.msg_system_not_ready");
    // 시스템 로그인(AM-Tray)
    case "amtray_login_ui_shown":
      return t("login.msg_amtray_ui_shown");
    case "amtray_login_message_received":
      return t("login.msg_amtray_message_received");
    case "amtray_busy":
      return t("login.msg_amtray_busy");
    case "amtray_login_timeout":
      return t("login.msg_amtray_timeout");
    case "amtray_not_logged_in":
      return t("login.msg_amtray_not_logged_in");
    case "amtray_sso_server_down":
      return t("login.msg_amtray_sso_down");
    case "amtray_unavailable":
      return t("login.msg_amtray_unavailable", { code: result.code });
    case "amtray_install_required":
      return t("loginV2.unavailable_title") + " " + t("loginV2.code", { code: result.code || "-" });
    case "amtray_sso_page_failed":
      return t("amtray.sso_page_failed") + " " + t("loginV2.code", { code: result.code || "-" });
    case "amtray_sso_blocked":
      return t("amtray.sso_blocked");
    case "amtray_denied":
    case "amtray_error":
      // AM 이 준 안내 문구(GetReturnMessage)가 있으면 그대로, 없으면 코드만
      return result.message ? `${result.message} (${result.code})` : t("login.msg_amtray_error", { code: result.code });
    case "amtray_helper_error":
      return t("login.msg_amtray_helper_error");
    case "amtray_server_not_ready":
      return t("login.msg_amtray_server_not_ready");
    case "amtray_token_rejected":
      return t("loginV2.token_rejected") + " " + t("loginV2.code", { code: result.code || "-" });
    case "login_rejected":
      // 약관 미동의(404/422)는 terms_not_agreed 로 따로 와서 팝업으로 보여준다. 그 밖의 거절은 서버 메시지 그대로.
      return result.message || t("login.msg_rejected", { code: result.httpCode });
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

// AI회의록 권한 없음 안내. 닫기 없이 [확인] → 앱 종료.
function showAccessNotice() {
  showMessage("");
  termsModal.hidden = true;
  accessModal.hidden = false;
  applyWindowSize();
  document.getElementById("accessOkBtn").focus();
}
document.getElementById("accessOkBtn").addEventListener("click", () => {
  try { window.developerAPI.logAction("access_denied_quit", {}); } catch (_) {}
  window.windowAPI.appQuit();
});

document.getElementById("minimizeBtn").addEventListener("click", () => {
  window.windowAPI.minimizeWindow();
});
document.getElementById("closeBtn").addEventListener("click", () => {
  window.windowAPI.closeWindow();
});

function saveLoginOptions() {
  return window.authAPI
    .setLoginOptions({
      keepLogin: !keepLoginLabel.hidden && keepLoginCheck.checked,
    })
    .catch(() => {});
}
keepLoginCheck.addEventListener("change", saveLoginOptions);

systemLoginBtn.addEventListener("click", async () => {
  setBusy(true);
  showMessage(() => t("login.msg_in_progress"));
  await saveLoginOptions();
  try {
    const result = await window.authAPI.systemLogin();
    if (result && result.success) {
      // 화면 전환은 메인 프로세스가 한다.
      showMessage(() => t("login.msg_success"));
      return;
    }
    if (result && result.pending) {
      // AM 로그인 창이 떴다 — 로그인이 끝나면 결과가 onAuthExchanged 로 온다. 오류 색 없이 안내만.
      showMessage(() => toUserMessage(result));
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
    setBusy(false);
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

// 시스템 로그인(AM 로그인 창·AM-Tray 알림) 뒤 결과. 성공 시 화면 전환은 메인 프로세스가 하므로 실패만 다룬다.
window.electronAPI.onAuthExchanged((payload) => {
  if (payload && payload.success) {
    showMessage(() => t("login.msg_success"));
    return;
  }
  if (payload && payload.error === "terms_not_agreed") {
    showTermsNotice();
    return;
  }
  // AM-Tray 로그인 알림을 받아 자동 로그인 중(언제든 받는다, 2026-11-14) — 오류 색 없이 안내만
  if (payload && payload.pending) {
    showMessage(() => toUserMessage(payload));
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

// 체크박스 표시와 마지막 값.
function renderLoginOptions(status) {
  const prefs = (status && status.loginPrefs) || {};
  keepLoginLabel.hidden = !(status && status.keepLoginEnabled);
  loginOptions.hidden = keepLoginLabel.hidden;
  keepLoginCheck.checked = !!prefs.keepLogin;
}

async function init() {
  renderEndpointPlaceholder();
  const status = await window.authAPI.getStatus();
  // 화면이 뜨는 사이 로그인(AM-Tray 알림 자동 로그인 등)이 먼저 끝났을 수 있다.
  if (status && status.authenticated) {
    window.electronAPI.loadIndex();
    return;
  }
  manualLogin.hidden = !(status && status.manualLoginEnabled);
  systemLoginBtn.hidden = !(status && status.systemLoginEnabled);
  if (status && status.termsAgreeUrl) termsAgreeUrl = status.termsAgreeUrl;
  if (status && status.defaultEndpoint) {
    defaultEndpoint = status.defaultEndpoint;
    renderEndpointPlaceholder();
  }
  renderLoginOptions(status);
  // 메인 화면에서 돌아온 경우 창 크기 제약이 남아 있을 수 있어 다시 맞춘다.
  applyWindowSize();
  // 로그인·로그인 유지 복원 뒤 약관 미동의로 로그아웃돼 이 화면으로 왔으면 안내 팝업
  // 권한 없음이면 그쪽을 먼저(확인 = 앱 종료라 약관 안내는 의미가 없다)
  const notice = await window.authAPI.takeTermsNotice().catch(() => null);
  if (notice && notice.access) showAccessNotice();
  else if (notice && notice.show) showTermsNotice();
}

init();
