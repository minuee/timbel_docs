// 로그인 화면 ver2 — AM-Tray 전용 (설정 LOGIN_PAGE_VERSION=2). ver1(login.js)은 그대로 둔다.
// 흐름:
//   화면이 열리면 바로 AM-Tray 로 로그인 시도(authAPI.systemLogin({ showUi:false }) — AM 로그인 창은 띄우지 않음)
//     성공            → 메인 프로세스가 마이크 테스트 화면으로 넘긴다
//     미로그인(504011) → "AM-Tray 통합 SSO 로그인을 진행해 주세요" + [AM-Tray 로그인]
//                        → authAPI.amShowLoginUi() → (로그인은 AM-Tray 몫) → AM-Tray 가 앱에 알림 → 자동 로그인
//     설치 안 됨 / 코드별 안내 / 준비 중 → 안내 + [다시 시도]
//   앱이 이 화면에 있는 동안 AM-Tray 로그인 알림이 오면(버튼을 안 눌러도) 메인 프로세스가 자동 로그인하고
//   결과를 onAuthExchanged 로 보낸다.
// 테스트 로그인(토큰 직접 입력)은 개발 빌드(APP_ENV=dev)이고 MANUAL_LOGIN_ENABLED 일 때만 보인다.
// 약관 미동의·권한 없음 팝업은 ver1 과 같다.

const amCard = document.getElementById("amCard");
const amTitle = document.getElementById("amTitle");
const amDesc = document.getElementById("amDesc");
const amNote = document.getElementById("amNote");
const amPrimaryBtn = document.getElementById("amPrimaryBtn");
const amSecondaryBtn = document.getElementById("amSecondaryBtn");
const loginMessage = document.getElementById("loginMessage");
const manualLogin = document.getElementById("manualLogin");
const manualForm = document.getElementById("manualForm");
const manualName = document.getElementById("manualName");
const manualEmpno = document.getElementById("manualEmpno");
const manualToken = document.getElementById("manualToken");
const manualEndpoint = document.getElementById("manualEndpoint");
const manualSubmitBtn = document.getElementById("manualSubmitBtn");
const languageSelectWrap = document.getElementById("languageSelectWrap");
const termsModal = document.getElementById("termsModal");
const termsBox = termsModal.querySelector(".terms-box");
const termsBody = document.getElementById("termsBody");
const accessModal = document.getElementById("accessModal");
const accessBox = accessModal.querySelector(".terms-box");

const WINDOW_WIDTH = 380;
const WINDOW_MIN_HEIGHT = 300;
const WINDOW_BOTTOM_MARGIN = 16;
const TERMS_MODAL_TOP = 40;
const TERMS_MODAL_PADDING = 16;

// 명세 표에 문구가 있는 코드(locales amtray.code_*)
const AM_CODE_TEXTS = ["503031", "503032", "503033", "503034", "503035", "503036"];

const t = (key, params) => window.i18n.t(key, params);

function applyWindowSize() {
  requestAnimationFrame(() => {
    const last = languageSelectWrap && !languageSelectWrap.hidden ? languageSelectWrap : loginMessage;
    const bottom = last.getBoundingClientRect().bottom;
    let height = Math.max(WINDOW_MIN_HEIGHT, Math.ceil(bottom + WINDOW_BOTTOM_MARGIN));
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

// ---- 상태 카드 ----
// state: checking | need_login | waiting | signing_in | success | not_ready | unavailable | error
// opts: { text, code, note } — error 의 본문, 코드, 주황 안내 한 줄
let current = { state: "checking", opts: {} };
let busy = false;

function codeSuffix(code) {
  return code ? " " + t("loginV2.code", { code }) : "";
}

function setButton(btn, label, onClick) {
  btn.hidden = !label;
  btn.textContent = label || "";
  btn.onclick = label ? onClick : null;
  btn.disabled = false;
}

function render(state, opts = {}) {
  current = { state, opts };
  amCard.dataset.state = state;
  let title = "";
  let desc = "";
  let primary = null;
  let secondary = null;
  switch (state) {
    case "checking":
      title = t("loginV2.checking");
      break;
    case "need_login":
      title = t("loginV2.need_login_title");
      desc = t("loginV2.need_login_desc");
      primary = [t("loginV2.am_login_btn"), onAmLoginClick];
      break;
    case "waiting":
      title = t("loginV2.waiting_title");
      desc = t("loginV2.waiting_desc");
      primary = [t("loginV2.recheck_btn"), tryAutoLogin];
      secondary = [t("loginV2.reopen_btn"), onAmLoginClick];
      break;
    case "signing_in":
      title = t("loginV2.signing_in");
      break;
    case "success":
      title = t("loginV2.success");
      break;
    case "not_ready":
      title = t("loginV2.not_ready_title");
      desc = t("loginV2.not_ready_desc");
      primary = [t("loginV2.retry_btn"), tryAutoLogin];
      break;
    case "unavailable":
      title = t("loginV2.unavailable_title");
      desc = t("loginV2.unavailable_desc") + codeSuffix(opts.code);
      primary = [t("loginV2.retry_btn"), tryAutoLogin];
      break;
    default: // error
      title = t("loginV2.error_title");
      desc = (opts.text ? (typeof opts.text === "function" ? opts.text() : opts.text) : t("login.msg_failed")) + codeSuffix(opts.code);
      primary = [t("loginV2.retry_btn"), tryAutoLogin];
  }
  amTitle.textContent = title;
  amDesc.textContent = desc;
  amNote.hidden = !opts.note;
  amNote.textContent = opts.note ? t(opts.note) : "";
  setButton(amPrimaryBtn, primary && primary[0], primary && primary[1]);
  setButton(amSecondaryBtn, secondary && secondary[0], secondary && secondary[1]);
  applyWindowSize();
}

function setBusy(on) {
  busy = on;
  amPrimaryBtn.disabled = on;
  amSecondaryBtn.disabled = on;
  manualSubmitBtn.disabled = on;
}

// 메인 프로세스 결과 → 화면 상태
function handleResult(result) {
  const r = result || {};
  if (r.success) return render("success");
  switch (r.error) {
    case "terms_not_agreed":
      render("error", { text: () => t("terms.title") });
      showTermsNotice();
      return;
    case "amtray_login_ui_shown":
      return render("waiting");
    case "amtray_login_message_received":
    case "amtray_busy":
      return render("signing_in");
    case "amtray_login_timeout":
      return render("waiting", { note: "loginV2.waiting_timeout" });
    case "amtray_not_logged_in":
      return render("need_login");
    case "system_login_not_ready":
    case "system_login_disabled":
      return render("not_ready");
    case "amtray_unavailable":
      // 509090 / 공백 = AM-Tray 없음·꺼짐. 500001·500003 = 연동 모듈(DLL) 문제
      if (!r.code || r.code === "509090") return render("unavailable", { code: r.code });
      return render("error", { text: () => t("loginV2.module_error"), code: r.code });
    case "amtray_error":
      if (AM_CODE_TEXTS.includes(r.code)) return render("error", { text: () => t("amtray.code_" + r.code), code: r.code });
      return render("error", { text: r.message || (() => t("login.msg_amtray_error", { code: r.code })), code: r.message ? r.code : "" });
    case "amtray_sso_server_down":
      return render("error", { text: () => t("loginV2.sso_down") });
    case "amtray_helper_error":
      return render("error", { text: () => t("loginV2.module_error") });
    case "amtray_server_not_ready":
      return render("error", { text: () => t("loginV2.server_not_ready") });
    case "network_error":
      return render("error", { text: () => t("login.msg_network_error") });
    case "login_rejected":
      return render("error", { text: r.message || (() => t("login.msg_rejected", { code: r.httpCode })) });
    default:
      return render("error", { text: () => t("login.msg_failed_with_error", { error: r.error || "unknown" }) });
  }
}

// 화면이 열릴 때 / [다시 시도] / [다시 확인] — AM 로그인 창은 띄우지 않고 토큰만 시도
async function tryAutoLogin() {
  if (busy) return;
  setBusy(true);
  render("checking");
  try {
    handleResult(await window.authAPI.systemLogin({ showUi: false }));
  } catch (err) {
    handleResult({ error: err && err.message });
  } finally {
    setBusy(false);
  }
}

// [AM-Tray 로그인] → AM-Tray 로그인 호출(ShowSSOLoginUI). 로그인 방식은 AM-Tray 몫이라 화면에 적지 않는다
async function onAmLoginClick() {
  if (busy) return;
  setBusy(true);
  try {
    handleResult(await window.authAPI.amShowLoginUi());
  } catch (err) {
    handleResult({ error: err && err.message });
  } finally {
    setBusy(false);
  }
}

// AM-Tray 로그인 알림으로 메인 프로세스가 자동 로그인한 결과(또는 진행 중 알림)
window.electronAPI.onAuthExchanged((payload) => handleResult(payload));

// ---- 테스트 로그인 (개발 빌드만) ----
let lastMessage = null;
function showMessage(text, isError) {
  lastMessage = { text, isError };
  loginMessage.textContent = (typeof text === "function" ? text() : text) || "";
  loginMessage.classList.toggle("error", !!isError);
  applyWindowSize();
}

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
    const msg = result && result.error === "access_token_required" ? t("login.msg_access_token_required")
      : result && result.error === "invalid_endpoint" ? t("login.msg_invalid_endpoint")
      : t("login.msg_failed_with_error", { error: (result && result.error) || "unknown" });
    showMessage(msg, true);
  } catch (err) {
    showMessage(() => t("login.msg_failed_with_error", { error: (err && err.message) || "unknown" }), true);
  } finally {
    setBusy(false);
  }
});
manualLogin.addEventListener("toggle", applyWindowSize);

let defaultEndpoint = "";
function renderEndpointPlaceholder() {
  manualEndpoint.placeholder = defaultEndpoint
    ? t("login.manual_endpoint_default", { url: defaultEndpoint })
    : t("login.manual_endpoint");
}

// ---- 약관·권한 팝업 (ver1 과 같음) ----
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
  termsModal.hidden = false;
  applyWindowSize();
  document.getElementById("termsLogoutBtn").focus();
}
document.getElementById("termsLogoutBtn").addEventListener("click", () => {
  termsModal.hidden = true;
  applyWindowSize();
});
document.getElementById("termsQuitBtn").addEventListener("click", () => {
  window.windowAPI.appQuit();
});
function showAccessNotice() {
  termsModal.hidden = true;
  accessModal.hidden = false;
  applyWindowSize();
  document.getElementById("accessOkBtn").focus();
}
document.getElementById("accessOkBtn").addEventListener("click", () => {
  try { window.developerAPI.logAction("access_denied_quit", {}); } catch (_) {}
  window.windowAPI.appQuit();
});

document.getElementById("minimizeBtn").addEventListener("click", () => window.windowAPI.minimizeWindow());
document.getElementById("closeBtn").addEventListener("click", () => window.windowAPI.closeWindow());

// 언어가 바뀌면 스크립트가 그린 글자를 다시 그린다
window.i18n.onChange(() => {
  renderEndpointPlaceholder();
  render(current.state, current.opts);
  if (lastMessage) showMessage(lastMessage.text, lastMessage.isError);
  if (!termsModal.hidden) renderTermsBody();
});

async function init() {
  render("checking");
  renderEndpointPlaceholder();
  const status = await window.authAPI.getStatus();
  if (status && status.authenticated) {
    window.electronAPI.loadIndex();
    return;
  }
  manualLogin.hidden = !(status && status.manualLoginEnabled && status.appEnv === "dev");
  if (status && status.termsAgreeUrl) termsAgreeUrl = status.termsAgreeUrl;
  if (status && status.defaultEndpoint) {
    defaultEndpoint = status.defaultEndpoint;
    renderEndpointPlaceholder();
  }
  applyWindowSize();
  // 약관 미동의·권한 없음으로 로그아웃돼 이 화면으로 왔으면 팝업부터. 이때는 자동 시도를 하지 않는다(같은 결과가 반복되므로).
  const notice = await window.authAPI.takeTermsNotice().catch(() => null);
  if (notice && notice.access) {
    showAccessNotice();
    render("error", { text: () => t("access.title") });
    return;
  }
  if (notice && notice.show) {
    showTermsNotice();
    render("error", { text: () => t("terms.title") });
    return;
  }
  tryAutoLogin();
}

init();
