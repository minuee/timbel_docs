const { app, BrowserWindow, ipcMain, Tray, nativeImage, Menu, Notification } = require("electron");
const path = require("path");
const FormData = require("form-data");
const { spawn } = require("child_process");
const { v4: uuidv4 } = require("uuid");
const logger = require('./logger');
const fs = require('fs');
require('dotenv').config();

// 전역 에러/리젝션 로깅
process.on('uncaughtException', (err) => {
  try { logger.logError('uncaught_exception', { message: err && err.message, stack: err && err.stack }); } catch (_) {}
});
process.on('unhandledRejection', (reason) => {
  try {
    const msg = reason && reason.message ? reason.message : String(reason);
    const stack = reason && reason.stack ? reason.stack : undefined;
    logger.logError('unhandled_rejection', { message: msg, stack });
  } catch (_) {}
});

const {
  createUploadListWindow,
  closeUploadListWindow,
  toggleUploadListWindow,
  isUploadListWindowOpen,
  jobsUpdated,
} = require("./windows/uploadList");
const { 
  createPopupWindow, 
  closePopupWindow, 
  sendUploadProgressToPopup,
  sendUploadFailedToPopup,
  sendUploadSucceededToPopup } = require("./windows/popup");
const { createSummarizeWindow } = require("./windows/summarize");
const { StringDecoder } = require("string_decoder");
const { AudioHelperManager } = require("./audioHelperManager");

const recRepo = require("./db/recordings");
const memoRepo = require("./db/memos");
const tagRepo = require("./db/tags");
const jobRepo = require("./db/jobs");
const summaryRepo = require("./db/summaries");

const { scanAndAutoQueue } = require("./services/recoveryService");
const authService = require("./services/authService");
const { client: apiClient } = require("./services/apiService");
const { registerAuthIpc, loadHome, onAuthenticated } = require("./ipc/handleAuth");
const authConfig = require("./services/authConfig");
const apiEndpoints = require("./services/apiEndpoints");
const userService = require("./services/userService");
const logShipper = require("./services/logShipper");
const updateService = require("./services/updateService");
const templateService = require("./services/templateService");
const { t, registerI18nIpc } = require("./i18n");
const { getRecordingBase, isSafeRecordingTarget } = require("./recordingDir");

// 업로드 에러 분류 유틸리티
function classifyUploadError(err) {
  try {
    const hasResponse = !!(err && err.response);
    const hasRequest = !!(err && err.request);
    const status = hasResponse ? Number(err.response.status) : undefined;
    const code = err && (err.code || err.errno || err.name);
    const message = (err && err.message) ? String(err.message) : 'upload_failed';

    // 서버 오류: 응답이 있고 5xx 또는 429
    if (hasResponse && (status >= 500 || status === 429)) {
      return { kind: 'server', status, code, message };
    }

    // 네트워크 오류: 응답 없음 + 요청은 존재하거나, 네트워크 관련 에러 코드
    const networkCodes = new Set(['ECONNABORTED','ENOTFOUND','ECONNREFUSED','EAI_AGAIN','ETIMEDOUT','ENETUNREACH','ERR_NETWORK']);
    if (!hasResponse && (hasRequest || networkCodes.has(String(code || '').toUpperCase()))) {
      return { kind: 'network', status: undefined, code, message };
    }

    // 그 외는 알 수 없는 오류
    return { kind: 'unknown', status, code, message };
  } catch (_) {
    return { kind: 'unknown', status: undefined, code: undefined, message: 'upload_failed' };
  }
}

// =====================================
// 재업로드 알림 큐 관리 (하이브리드 방식)
// =====================================
let notificationQueue = [];
let notificationTimer = null;
const NOTIFICATION_DEBOUNCE_MS = 4000; // 4초 디바운스

// 알림 큐 처리 함수
function flushNotificationQueue() {
  if (notificationQueue.length === 0) return;
  
  const succeeded = notificationQueue.filter(n => n.success);
  const failed = notificationQueue.filter(n => !n.success);
  
  if (notificationQueue.length === 1) {
    // 개별 알림
    const item = notificationQueue[0];
    const message = item.success
      ? t('notify.upload_success_one', { name: item.fileName })
      : t('notify.upload_failed_one', { name: item.fileName });
    createSystemNotification({
      title: item.success ? t('notify.upload_done_title') : t('notify.upload_failed_title'),
      subtitle: message,  // macOS용
      body: message,      // Windows용
    });
  } else {
    // 요약 알림
    const total = notificationQueue.length;
    const successCount = succeeded.length;
    const failCount = failed.length;
    
    let message = '';
    if (failCount === 0) {
      message = t('notify.upload_all_success', { total });
      createSystemNotification({
        title: t('notify.upload_done_title'),
        subtitle: message,  // macOS용
        body: message,      // Windows용
      });
    } else if (successCount === 0) {
      message = t('notify.upload_all_failed', { total });
      createSystemNotification({
        title: t('notify.upload_failed_title'),
        subtitle: message,  // macOS용
        body: message,      // Windows용
      });
    } else {
      message = t('notify.upload_mixed', { success: successCount, fail: failCount });
      createSystemNotification({
        title: t('notify.upload_done_title'),
        subtitle: message,  // macOS용
        body: message,      // Windows용
      });
    }
  }
  
  notificationQueue = [];
  notificationTimer = null;
}

// 알림 추가 함수
function queueUploadNotification(fileName, success) {
  notificationQueue.push({ fileName, success });
  
  // 기존 타이머 취소 후 새로 시작
  if (notificationTimer) {
    clearTimeout(notificationTimer);
  }
  
  notificationTimer = setTimeout(() => {
    flushNotificationQueue();
  }, NOTIFICATION_DEBOUNCE_MS);
}

let mainWindow;
// 업로드 리스트 창 상태는 windows/uploadList 모듈에서 관리
let audioHelper;
// 인증 세션(accessToken, endpoint, deviceId)은 services/authService 가 보관한다.
// 온프레미스 환경일 경우 고정 엔드포인트 사용 (예: 'https://dev.timblo.io')
let tray = null;
let currentOutputDirectory = null; // set_output_dir로 설정된 베이스 출력 경로
let requestedOutputDirectory = null; // 마지막으로 헬퍼에 보낸 set_output_dir 경로(절대경로)
let initialFileName;
// 온프레미스 대응
const hostName  = require('./config').get('HOST_NAME', 'dev.timblo.io');

// 헬퍼 이벤트의 경로를 렌더러가 그대로 쓸 수 있게 정리한다.
// - output_dir_set 에 directory 가 비어 오면(회사 PC 에서 undefined 로 옴) 보낸 경로로 채운다.
//   비어 있으면 렌더러의 업로드 경로가 "undefined/{uuid}" 가 되어 업로드가 실패했다.
// - segment_ready 의 path 가 상대경로면 헬퍼 작업 폴더 기준 절대경로로 바꾸고,
//   그 폴더를 dir 로 붙인다. 렌더러는 이 dir(실제 파일 위치)을 업로드 경로로 쓴다.
function normalizeHelperEventPaths(payload) {
  if (!payload || typeof payload !== 'object') return;
  try {
    if (payload.ev === 'output_dir_set' && !payload.directory && requestedOutputDirectory) {
      try { logger.logError('output_dir_not_applied', { requested: requestedOutputDirectory, received: payload.directory === undefined ? 'undefined' : payload.directory }); } catch (_) {}
      payload.directory = requestedOutputDirectory;
    }
    if (payload.ev === 'segment_ready' && typeof payload.path === 'string' && payload.path) {
      let filePath = payload.path;
      if (!path.isAbsolute(filePath)) {
        const cwd = audioHelper && audioHelper.helperCwd;
        if (cwd) filePath = path.resolve(cwd, filePath);
      }
      payload.path = filePath.replace(/\\/g, '/');
      payload.dir = path.dirname(filePath).replace(/\\/g, '/');
    }
  } catch (_) {}
}

// Helper 이벤트 ACK 대기 관리
const helperEventWaiters = new Set();
function waitForHelperEvent(match, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const waiter = {
      match,
      resolve,
      reject,
      timeoutId: setTimeout(() => {
        try { helperEventWaiters.delete(waiter); } catch (_) {}
        reject(new Error('helper_event_timeout'));
      }, timeoutMs)
    };
    helperEventWaiters.add(waiter);
  });
}

// Windows 알림(토스트)에 보이는 앱 이름·아이콘.
// 지정하지 않으면 Electron 기본값(electron.app.timbloRecApp)이 쓰여 알림에 "timbloRecApp" 이 보인다.
// 설치 프로그램이 시작 메뉴 바로가기(SKHynixRecApp)에 package.json build.appId 를 붙여 두므로,
// 같은 ID 를 쓰면 알림에 바로가기 이름(SKHynixRecApp)이 나온다.
// 개발 모드는 바로가기가 없어 알림이 안 뜰 수 있으므로 설치본에서만 지정한다.
const WINDOWS_APP_USER_MODEL_ID = "net.timbel.timblo.recapp"; // = package.json build.appId
if (process.platform === "win32" && app.isPackaged) {
  try { app.setAppUserModelId(WINDOWS_APP_USER_MODEL_ID); } catch (_) {}
}

// 딥링크 처리 설정
const PROTOCOL_SCHEME = "timbloRecApp";
let deepLinkQueue = [];
// 이미 교환을 시도한 code. 창 로딩 중에 들어온 딥링크는 sendDeepLinkToRenderer 와
// flushDeepLinks 양쪽에서 processDeepLink 를 타는데, code 는 1회용이라 두 번째 교환이
// 실패하면서 "로그인 성공 직후 실패 통지"가 날아가던 문제를 막는다.
const handledDeepLinkCodes = new Set();

function sendDeepLinkToRenderer(url) {
  try {
    if (!url) return;
    if (!mainWindow) {
      deepLinkQueue.push(url);
      return;
    }
    if (mainWindow.webContents.isLoading()) {
      deepLinkQueue.push(url);
    } else {
      mainWindow.webContents.send("deep-link", url);
    }
  } catch (_) {}

  // 비동기로 딥링크 처리 (connect 교환 등)
  processDeepLink(url).catch(() => {});
}

function flushDeepLinks() {
  if (!mainWindow) return;
  if (deepLinkQueue.length === 0) return;
  for (const url of deepLinkQueue) {
    mainWindow.webContents.send("deep-link", url);
    processDeepLink(url).catch(() => {});
  }
  deepLinkQueue = [];
}

// 녹음 이름: {접두어}YYYYMMDD_HHmmss (한국 시각, 녹음 시작 시각) 예) A.Biz_p_rec_20261014_205510
// - 업로드 때 서버로 보내는 fileName, 업로드 리스트 제목(기본값)에 같이 쓴다.
// - 녹음 시작 때 한 번 정해 DB(recordings.upload_name)에 저장 → 재업로드해도 같은 이름.
// - 접두어는 src/config/app.config.json 의 RECORDING_FILE_PREFIX.
// (예전: aimm_w_rec_YYMMDD_HHmmss 를 업로드 시각으로 매번 새로 만들었고, 날짜는 PC 시각·시간은 KST 로 섞여 있었다)
function buildRecordingFileName(date = new Date()) {
  const prefix = require('./config').get('RECORDING_FILE_PREFIX', 'A.Biz_p_rec_');
  const kst = new Date(date.getTime() + 9 * 60 * 60 * 1000); // UTC+9 — 날짜·시간 모두 KST 로
  const pad = (n) => String(n).padStart(2, '0');
  const ymd = `${kst.getUTCFullYear()}${pad(kst.getUTCMonth() + 1)}${pad(kst.getUTCDate())}`;
  const his = `${pad(kst.getUTCHours())}${pad(kst.getUTCMinutes())}${pad(kst.getUTCSeconds())}`;
  return `${prefix}${ymd}_${his}`;
}


// 딥링크 비즈니스 로직
async function processDeepLink(url) {
  try {
    const u = new URL(url);
    if (
      u.protocol.replace(":", "").toLowerCase() !==
      PROTOCOL_SCHEME.toLowerCase()
    )
      return;

    // timbloRecApp://connect?code=...&host=...
    const route = (u.hostname || "").toLowerCase();
    if (route !== "connect") return;

    const code = u.searchParams.get("code") || "";
    const hostB64 = u.searchParams.get("host") || "";
    let endpoint = "";

    try { logger.logInfo('deeplink_received', { route, code_present: !!code, host_present: !!hostB64 }); } catch (_) {}
    if (code && handledDeepLinkCodes.has(code)) return;
    if (code) handledDeepLinkCodes.add(code);
    if (!code || !hostB64) {
      broadcastAuthExchanged({ success: false, error: "invalid_parameters" });
      return;
    }

		
		try {
			endpoint = Buffer.from(hostB64, 'base64').toString('utf8').trim();
			const test = new URL(endpoint);
			if (!/^https?:$/i.test(test.protocol)) throw new Error('invalid_protocol');
		} catch (_) {
			broadcastAuthExchanged({ success: false, error: 'invalid_host' });
			return;
		}
    try { logger.logInfo('deeplink_exchange_begin', { endpoint_present: !!endpoint }); } catch (_) {}
    const exchangeResult = await authService.exchangeToken(endpoint, code);
    if (!exchangeResult.success) {
      broadcastAuthExchanged({
        success: false,
        error: exchangeResult.error || "exchange_failed",
      });
      return;
    }

    authService.setSession({
      accessToken: exchangeResult.result,
      refreshToken: exchangeResult.refreshToken,
      endpoint,
    });
    try { logger.logInfo('deeplink_exchange_success'); } catch (_) {}

    broadcastAuthExchanged({ success: true, endpoint });
    // 로그인 화면에서 기다리던 중이면 메인 화면으로 넘긴다.
    onAuthenticated();
  } catch (err) {
    try { logger.logError('deeplink_unexpected_error', { message: err && err.message }); } catch (_) {}
    broadcastAuthExchanged({ success: false, error: "unexpected_error" });
  }
}

// MyAccess(SSO) 로그인 결과는 모두 여기를 지난다.
function broadcastAuthExchanged(payload) {
  try {
    if (payload && payload.success) logger.logUserAction('login_success', { method: 'sso' });
    else logger.logUserAction('login_failed', { method: 'sso', reason: payload && payload.error });
  } catch (_) {}
  try {
    if (!mainWindow) return;
    mainWindow.webContents.send("auth-exchanged", payload);
  } catch (_) {}
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 380,
    height: 436,
    frame: false,
    movable: true,
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
    },
    skipTaskbar: false,
    autoHideMenuBar: false,
    icon: path.join(__dirname, "../renderer/assets/icons/logo_big.png"), // 아이콘이 있다면
  });

  // 로그인 상태면 마이크 테스트, 아니면 로그인 화면(loadHome 이 판단).
  // 로그인 유지(SESSION_PERSIST_ENABLED)가 켜져 있으면 whenReady 에서 미리 복원해 둔다.
  loadHome();
  try { logger.logInfo('window_created', { windowId: mainWindow.id }); } catch (_) {}

  // 렌더러 로드 완료 후 누적된 딥링크 전달
  mainWindow.webContents.on("did-finish-load", () => {
    try { logger.logInfo('window_loaded', { windowId: mainWindow.id }); } catch (_) {}
    flushDeepLinks();
  });

  // 렌더러 콘솔 메시지 중앙 수집 (개발 단계 품질 향상용)
  try {
    mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
      try {
        // Chromium 레벨: 0=verbose 1=info 2=warning 3=error
        // (예전 매핑이 2→error, 1→warn, 3→info 로 어긋나 console.error 가 info 로 찍히고 있었다)
        level = level === 3 ? 'error' : level === 2 ? 'warn' : level === 1 ? 'info' : 'debug';
        // channel: 'console' — 양이 많아서 로그 서버에는 warn 이상만 보낸다(logShipper).
        const payload = {level, process: 'renderer', channel: 'console', message, line, sourceId};
        return logger.logWrite(payload);
      } catch (_) {}
    });
  } catch (_) {}

  // 개발 모드에서는 개발자 도구를 별도 창으로 열기
  if (process.argv.includes("--dev")) {
    mainWindow.webContents.openDevTools({ mode: "detach" });
  }
}

// IPC 핸들러들
// 다국어(i18n:get-sync, i18n:set-lang) — 창을 띄우기 전에 등록해야 preload 가 문구를 받는다
registerI18nIpc();

// 로그인 게이트/인증 IPC (auth:get-status, auth:open-sso, auth:login-empno)
registerAuthIpc({
  getMainWindow: () => mainWindow,
  getActiveUploadCount: () => activeUploadCount,
  // 로그아웃하면 사용자별 화면(업로드 리스트)을 닫는다
  onLoggedOut: () => { try { closeUploadListWindow(); } catch (_) {} },
});

// 홈(index.html)으로 이동
ipcMain.handle("load-index", () => {
  try {
    // 로그인이 풀린 상태면 로그인 화면으로 간다.
    return loadHome();
  } catch (err) {
    return { success: false, error: err && err.message };
  }
});
ipcMain.handle("start-audio-helper", async () => {
  try {
    await audioHelper.startHelper();
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle("stop-audio-helper", async () => {
  audioHelper.stopHelper();
  return { success: true };
});

ipcMain.handle("send-helper-command", async (event, command) => {
  try {
    try {
      const payloadSize = Buffer.byteLength(JSON.stringify(command || {}));
      logger.logInfo('ipc_request', { ipcChannel: 'send-helper-command', payloadSize });
    } catch (_) {}
    // set_output_dir의 상대 경로를 사용자 문서 폴더 기준 절대 경로로 변환 (배포 환경 권한 이슈 회피)
    if (
      command &&
      command.cmd === "set_output_dir" &&
      typeof command.directory === "string"
    ) {
      const dir = command.directory;
      if (!path.isAbsolute(dir)) {
        if(process.platform === 'darwin') {
          const resolved = path.join('/tmp', dir);
          command = { ...command, directory: resolved.replace(/\\/g, '/') };
          console.log('Resolved output directory to:', command.directory);
        }else if(process.platform === 'win32') {
          // 문서\SKHynixRecApp, 안 되면 C:\SKHynixRecApp (recordingDir.js)
          const safeBase = getRecordingBase();
          const resolved = path.join(safeBase, dir);
          command = { ...command, directory: resolved.replace(/\\/g, '/') };
          console.log('Resolved output directory to:', command.directory);
        }
      }
    }
    // set_output_dir: 헬퍼의 output_dir_set 이벤트를 수신할 때까지 대기하여 순서 보장
    if (command?.cmd === "set_output_dir") {
      // 헬퍼 응답(output_dir_set)에 경로가 비어 오면 이 값으로 채운다(setOnEvent)
      requestedOutputDirectory = command.directory || null;
      // 이벤트 대기를 먼저 등록하여 레이스를 회피
      const waitAck = waitForHelperEvent((e) => e && e.ev === "output_dir_set");
      audioHelper.sendCommand(command);
      await waitAck; // output_dir_set 수신까지 대기
      // 현재 출력 디렉터리 캐싱
      try { currentOutputDirectory = command.directory || currentOutputDirectory; } catch (_) {}
      try { logger.logInfo('output_dir_set', { directory: currentOutputDirectory }); } catch (_) {}
      return { success: true };
    }

    // 녹음 시작마다 sessionId 초기화 및 즉시 session_created 브로드캐스트
    if (command?.cmd === "start") {
      audioHelper.sessionId = uuidv4();
      initialFileName = buildRecordingFileName();
      mainWindow.webContents.send("helper-event", {
        ev: "session_created",
        stage: "recording_started",
        sessionId: audioHelper.sessionId,
        fileName: initialFileName, // 렌더러가 업로드 리스트 제목 기본값으로 쓴다
      });
      try { logger.logInfo('recording_start', { sessionId: audioHelper.sessionId, fileBase: initialFileName }); } catch (_) {}
      audioHelper.sendCommand(command);
      // 부서장에게 녹음 시작 안내 메일. 녹음을 늦추지 않도록 기다리지 않는다(결과는 로그로 남음).
      // resume 은 별도 명령이라 녹음 1건당 1번만 나간다.
      if (authConfig.ALERT_ON_RECORDING_START) {
        userService.sendRecordingAlert().catch(() => {});
      }
      return { success: true };
    }

    // 기본 경로: 비동기 전송 후 즉시 반환
    audioHelper.sendCommand(command);
    return { success: true };
  } catch (error) {
    try { logger.logError('ipc_request_failed', { ipcChannel: 'send-helper-command', message: error && error.message }); } catch (_) {}
    return { success: false, error: error.message };
  }
});

// 업로드 요청
ipcMain.handle("request-upload", (event, data) => {
  mainWindow.webContents.send("request-upload", data);
});

// 업로드 작업 추가 (jobs 테이블)
ipcMain.handle("enqueue-upload", (event, recordId, data) => {
  try {
    const jobId = jobRepo.enqueueUpload(recordId);
    try { logger.logInfo('enqueue_upload', { recordId, jobId }); } catch (_) {}

    // 요약정보 DB 저장 (제목·템플릿도 — 업로드 리스트 재시도 때 같은 값으로 보낸다)
    const title = String(data.title || '').trim();
    summaryRepo.insertSummary({ recordingId: recordId, lang: data.lang, attendeeNum: data.attendeeNum, title, templateId: data.templateId });
    // 제목을 넣었으면 업로드 리스트에도 그 제목으로 보인다
    if (title) recRepo.renameRecording(recordId, title);
    // 업로드 리스트가 켜져있다면, jobs 리스트 업데이트하기
    jobsUpdated(jobRepo.listJobs());

    return { success: true, jobId };
  } catch (error) {
    try { logger.logError('enqueue_upload_failed', { message: error && error.message }); } catch (_) {}
    return { success: false, error: error.message };
  }
});


// ================
// 서버 업로드 로직
// ================

// 서버 업로드
ipcMain.handle('server-upload', async (event, data) => {
  try { logger.logInfo('server_upload_request', { recordingId: data && data.recordId, filePath: data && data.filePath }); } catch (_) {}
  return serverUpload(data);
});

// 재업로드
ipcMain.handle("retry-server-upload", async (event, data) => {
  try { logger.logInfo('retry_server_upload_request', { recordingId: data && data.recording_id, jobId: data && data.job_id }); } catch (_) {}
  const summary = summaryRepo.getSummary(data?.recording_id);
  const uploadData = { 
    jobId: data?.job_id,
    lang: summary?.lang,
    attendeeNum: summary?.attendee_num,
    title: summary?.title || '',
    templateId: summary?.template_id || '',
    recordId: data?.recording_id,
    filePath: data?.file_path,
    fileName: data?.file_name,
    type: 'retry_single'
  }

  return serverUpload(uploadData);
  
});

// 서버 업로드 함수
// 서버로 전송 중인 업로드 수. 로그아웃은 0일 때만 허용한다(전송 중 토큰이 사라지면 업로드 실패).
let activeUploadCount = 0;

// 서버가 누락 조각(missingFiles)을 알려줄 때 자동으로 다시 보내는 최대 횟수.
// 서버 그룹녹음 정책(첫 요청 1 + 자동 재시도 3)과 맞춘다.
const UPLOAD_MISSING_MAX_RESEND = 3;

// 녹음 조각 파일의 순서 번호. 헬퍼가 "{세션ID}_{번호}{확장자}" 로 저장한다. 못 읽으면 -1.
function segmentIndexOf(fp) {
  const m = /_(\d+)(\.[^._]*)?$/.exec(path.basename(fp));
  return m ? Number(m[1]) : -1;
}

// 업로드 응답 본문 해석. HTTP 200 이어도 본문에 실패/누락이 담겨 올 수 있다(서버 API 문서).
// - errorCode 가 있거나 httpCode 가 4xx/5xx → 거절
// - data.missingFiles = 누락 조각 순서 번호 배열(예: [0,1,2]) → 누락
function readUploadResult(body) {
  const b = (body && typeof body === 'object') ? body : {};
  const httpCode = Number(b.httpCode);
  if (b.errorCode || httpCode >= 400) {
    return { rejected: true, errorCode: String(b.errorCode || ''), httpCode, message: String(b.message || ''), missing: [] };
  }
  const list = (b.data && Array.isArray(b.data.missingFiles)) ? b.data.missingFiles
    : (Array.isArray(b.missingFiles) ? b.missingFiles : []);
  const missing = Array.from(new Set(list.map(Number).filter(Number.isInteger)));
  return { rejected: false, errorCode: '', httpCode, message: String(b.message || ''), missing };
}

// 본문 해석 결과로 만든 실패. catch 에서 classifyUploadError 대신 uploadInfo 를 쓴다.
function uploadResultError(kind, message, result) {
  const err = new Error(message);
  err.uploadInfo = { kind, status: result.httpCode || undefined, code: result.errorCode || undefined, message };
  return err;
}

// 조각 파일들을 한 번 전송한다. 진행률은 업로드 팝업으로 보낸다(누락분 재전송이면 그 분량 기준).
async function postUploadForm(files, data, meta) {
  const form = new FormData();
  for (const fp of files) {
    // 더 세밀한 진행률 관찰을 위해 청크 크기를 16KB로 낮춤
    form.append('files', fs.createReadStream(fp, { highWaterMark: 16 * 1024 }), path.basename(fp));
  }
  form.append('lang', data?.lang || '');
  form.append('attendeeNum', String(data?.attendeeNum ?? 0));
  form.append('deviceId', authService.getDeviceId());
  form.append('fileName', meta.uploadName);
  // 이번 요청에 담은 조각 수. 누락분 재전송이면 그 개수(서버가 jobId 기준으로 누적 관리)
  form.append('totalNum', files.length);
  if (meta.title) form.append('title', meta.title);
  if (data?.templateId) form.append('templateId', String(data.templateId));

  const total = await new Promise((resolve, reject) => {
    form.getLength((err, len) => err ? reject(err) : resolve(len));
  });

  let sent = 0;
  const startedAt = Date.now();
  let lastSpeedSampleAt = startedAt;
  let lastSpeedSampleBytes = 0;
  let smoothedBps = 0; // exponential moving average

  const formatBytesPerSec = (bps) => {
    if (!bps || !isFinite(bps)) return '0 B/s';
    const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
    let v = bps;
    let u = 0;
    while (v >= 1024 && u < units.length - 1) {
      v /= 1024;
      u += 1;
    }
    const digits = v >= 10 || u === 0 ? 0 : 1;
    return `${v.toFixed(digits)} ${units[u]}`;
  };

  const formatEta = (seconds) => {
    if (seconds == null || !isFinite(seconds) || seconds < 0) return '-';
    const s = Math.max(0, Math.round(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}h ${m}m ${sec}s`;
    if (m > 0) return `${m}m ${sec}s`;
    return `${sec}s`;
  };
  const progressIntervalMs = Math.max(50, Number(data?.progressIntervalMs) || 200);
  const progressStepPercent = Math.min(50, Math.max(1, Number(data?.progressStepPercent) || 1));
  let lastProgressEmitAt = 0;
  let lastPercentEmitted = 0;
  let uploadTerminated = false; // 성공/실패로 종료되면 true
  const onFormData = (chunk) => {
    if (uploadTerminated) return;
    sent += chunk.length;
    const progress = Math.round((sent / total) * 100);
    const now = Date.now();
    if (
      progress - lastPercentEmitted >= progressStepPercent ||
      now - lastProgressEmitAt >= progressIntervalMs ||
      progress === 100
    ) {
      // 속도 샘플링 및 스무딩
      const dt = Math.max(1, now - lastSpeedSampleAt);
      const db = Math.max(0, sent - lastSpeedSampleBytes);
      const instBps = (db * 1000) / dt;
      smoothedBps = smoothedBps ? (smoothedBps * 0.8 + instBps * 0.2) : instBps;
      lastSpeedSampleAt = now;
      lastSpeedSampleBytes = sent;

      const remaining = Math.max(0, total - sent);
      const etaSec = smoothedBps > 0 ? remaining / smoothedBps : null;

      lastProgressEmitAt = now;
      lastPercentEmitted = progress;
      const speedReadable = formatBytesPerSec(smoothedBps);
      const etaReadable = formatEta(etaSec);
      try { logger.logDebug('server_upload_progress', { jobId: data && data.jobId, percent: progress, speed: speedReadable, eta: etaReadable }); } catch (_) {}
      // popup window에 이벤트 전송
      sendUploadProgressToPopup({
        jobId: data?.jobId,
        percent: progress,
        sent,
        total,
        bps: smoothedBps,
        speedReadable,
        etaSeconds: etaSec,
        etaReadable,
      });
    }
  };
  form.on('data', onFormData);

  try { logger.logInfo('server_upload_form_prepared', { fileCount: files.length, totalBytes: total, hasTitle: !!meta.title, templateId: data?.templateId || '' }); } catch (_) {}
  // baseURL(endpoint)과 Authorization 헤더는 apiService 인터셉터가 부착한다.
  try {
    return await apiClient.post(apiEndpoints.upload.url, form, {
      headers: {
        ...form.getHeaders(),
      },
    });
  } finally {
    uploadTerminated = true;
    try { form.off('data', onFormData); } catch (_) {}
  }
}

async function serverUpload(data) {
  try { logger.logInfo('server_upload_begin', { jobId: data && data.jobId, recordingId: data && data.recordId }); } catch (_) {}
  try {
    // 업로드 상태 변경(jobs, 업로드 중)
    jobRepo.markUploaded(data.jobId);
    jobsUpdated(jobRepo.listJobs());
    if(data.type !== 'retry_multi'){
      createPopupWindow(mainWindow, {
        title: t('popup.uploading_title'),
        subtitle: t('popup.uploading_subtitle'),
        type: 'upload-progress',
        dir: data.filePath,
        data: data,
        width: 370,
        height: 170,
      });
    }

    // **파일 경로의 파일들 -> files 배열 생성**
    const dir = data?.filePath || '';
    if (!dir) throw new Error('No filePath provided');
    const stat = fs.existsSync(dir) ? fs.statSync(dir) : null;
    if (!stat || !stat.isDirectory()) {
      // 원인 추적용: 경로가 없음 / 파일임, 헬퍼 작업 폴더, 마지막으로 보낸 저장 경로
      try {
        logger.logError('upload_dir_missing', {
          jobId: data && data.jobId,
          filePath: dir,
          exists: !!stat,
          isFile: !!(stat && stat.isFile()),
          helperCwd: audioHelper && audioHelper.helperCwd,
          requestedOutputDirectory,
        });
      } catch (_) {}
      throw new Error(`filePath is not a directory: ${dir}`);
    }
    
    const dirents = await fs.promises.readdir(dir, { withFileTypes: true });
    const files = dirents
      .filter(d => d.isFile())
      .map(d => path.join(dir, d.name));

    // 녹음 시작 때 정해 둔 이름(recordings.upload_name). 예전 녹음처럼 없으면 지금 시각으로 만든다.
    let uploadName = '';
    try { uploadName = recRepo.getUploadName(data?.recordId) || ''; } catch (_) {}
    if (!uploadName) uploadName = buildRecordingFileName();

    // 제목·템플릿은 선택(docs/content-title.md). 비어 있으면 보내지 않는다 → 서버 기본값(템플릿 DEF-BASIC)
    const title = String(data?.title || '').trim();
    const meta = { uploadName, title };

    // 업로드는 기다리지 않고 진행한다(기존과 같음). 결과는 팝업·업로드 목록·알림으로 알린다.
    activeUploadCount++;
    (async () => {
      // 서버가 누락 조각 번호(missingFiles)를 돌려주면 그 조각만 다시 보낸다. 받은 조각은 서버에 남아 있다.
      let sendFiles = files;
      for (let attempt = 0; ; attempt++) {
        const res = await postUploadForm(sendFiles, data, meta);
        const result = readUploadResult(res && res.data);
        if (result.rejected) {
          throw uploadResultError('rejected', result.message || `upload_rejected ${result.errorCode}`.trim(), result);
        }
        if (result.missing.length === 0) return res;

        try { logger.logError('server_upload_missing_files', { jobId: data && data.jobId, attempt, missing: result.missing }); } catch (_) {}
        if (attempt >= UPLOAD_MISSING_MAX_RESEND) {
          throw uploadResultError('missing', `missing_files ${result.missing.join(',')}`, result);
        }
        const wanted = new Set(result.missing);
        const resend = files.filter((fp) => wanted.has(segmentIndexOf(fp)));
        if (resend.length === 0) {
          // 누락 조각이 PC 에 하나도 없다(유실) → 재업로드 포기, 웹 미완성 회의록에서 다시 올리도록 안내
          throw uploadResultError('lost', `missing_files_not_found ${result.missing.join(',')}`, result);
        }
        // 일부만 있으면 있는 것만 보낸다. 없는 번호는 다음 응답에 다시 오고, 그때 위에서 유실로 끝난다.
        try { logger.logInfo('server_upload_resend_missing', { jobId: data && data.jobId, attempt: attempt + 1, count: resend.length }); } catch (_) {}
        sendFiles = resend;
      }
    })().then((res) => {
      // 완료 시 100% 이벤트 보장 전송
      sendUploadProgressToPopup({
        jobId: data?.jobId,
        percent: 100,
        sent: 1,
        total: 1,
        bps: null,
        speedReadable: '',
        etaSeconds: 0,
        etaReadable: '0s',
      });
      
      // 녹음 파일 삭제
      deleteRecordingFile(data.filePath);
      
      // 업로드 리스트 갱신
      jobsUpdated(jobRepo.listJobs());
      
      if(data.isAppClosing) {
        closePopupWindow();
        app.quit();
      } else if (data.type !== 'retry_multi') {
        // 진행 팝업을 "업로드 완료" 안내로 바꾼다(확인을 누르면 닫힘). 다건 재시도는 아래 시스템 알림으로 알린다.
        const shown = sendUploadSucceededToPopup({ fileName: data.fileName, goHome: !!data.goHomeAfterUpload });
        // 창이 최소화/숨김 상태면 팝업을 못 볼 수 있으니 시스템 알림도 띄운다
        try {
          if (!shown || (mainWindow && (mainWindow.isMinimized() || !mainWindow.isVisible()))) {
            createSystemNotification({ title: t('notify.upload_done_title'), subtitle: t('notify.upload_done'), body: t('notify.upload_done') });
          }
        } catch (_) {}
      }

      // 장치 끊김 후 업로드 성공 시 홈으로 이동(goHomeAfterUpload)
      try {
        if (data && data.goHomeAfterUpload && mainWindow && !mainWindow.isDestroyed()) {
          loadHome();
        }
      } catch (_) {}

      try { logger.logInfo('server_upload_success', { jobId: data && data.jobId }); } catch (_) {}
      
      // retry_multi인 경우 알림 큐에 추가
      if (data.type === 'retry_multi') {
        queueUploadNotification(data.fileName || t('notify.file'), true);
      }
      
      return { success: true, result: res.data || null };
    }).catch((err) => {
      // 실패하면 녹음 파일은 지우지 않는다 → 업로드 목록에서 다시 올릴 수 있다
      const info = err.uploadInfo || classifyUploadError(err);
      try { logger.logError('server_upload_failed', { jobId: data && data.jobId, kind: info.kind, status: info.status, code: info.code, message: info.message }); } catch (_) {}
      sendUploadFailedToPopup({
        jobId: data?.jobId,
        kind: info.kind,
        status: info.status,
        code: info.code,
        isAppClosing: data.isAppClosing,
        message: info.message || 'upload_failed',
        uploadName,
      })

      jobRepo.markUploadFailed(data.jobId);
      jobsUpdated(jobRepo.listJobs());

      if (info.kind === 'lost') {
        // 팝업이 없거나(다건 재업로드) 창이 가려져 있으면 시스템 알림으로 유실 안내를 띄운다
        try {
          const hidden = !mainWindow || mainWindow.isMinimized() || !mainWindow.isVisible();
          if (data.type === 'retry_multi' || hidden) createSystemNotification({ title: t('notify.upload_failed_title'), subtitle: '', body: t('popup.upload_lost', { name: uploadName }) });
        } catch (_) {}
      } else if (data.type === 'retry_multi') {
        // retry_multi인 경우 알림 큐에 추가
        queueUploadNotification(data.fileName || t('notify.file'), false);
      }

      return { success: false, error: info.message, kind: info.kind, status: info.status, code: info.code };
    }).finally(() => {
      activeUploadCount = Math.max(0, activeUploadCount - 1);
    })
    
  } catch (error) {
    const info = classifyUploadError(error);
    try { logger.logError('server_upload_process_failed', { jobId: data && data.jobId, kind: info.kind, status: info.status, code: info.code, message: info.message }); } catch (_) {}
    // 실패 상태 브로드캐스트(uploadList)
    jobRepo.markUploadFailed(data.jobId);
    jobsUpdated(jobRepo.listJobs());

    // 팝업 실패 UI 전환 이벤트 송신
    try {
      sendUploadFailedToPopup({ jobId: data?.jobId, kind: info.kind, status: info.status, code: info.code, message: info.message || 'upload_failed' });
    } catch (_) {}

    // retry_multi인 경우 알림 큐에 추가
    if (data.type === 'retry_multi') {
      queueUploadNotification(data.fileName || t('notify.file'), false);
    }

    return { success: false, error: info.message, kind: info.kind, status: info.status, code: info.code };
  }
}

// 백그라운드 업로드(팝업 없이 다건 병렬 실행)
function serverUploadInBackground(data) {
  // 기존 serverUpload 흐름을 재사용하되, 팝업/닫기 없이 진행
  try {
    jobRepo.markUploaded(data.jobId);
    jobsUpdated(jobRepo.listJobs());
  } catch (_) {}

  // 파일 준비 및 업로드 로직은 serverUpload와 동일한 흐름을 호출
  // 단, 진행/성공/실패 이벤트는 uploadList 갱신 위주로만 전송
  return serverUploadCore(data, { showProgressPopup: false });
}

// 내부 코어: serverUpload와 공유(기존 코드를 분리하기 어렵다면, 우선 최소 동작으로 재사용)
async function serverUploadCore(data, options) {
  
  return serverUpload(data);
}

// 다건 재시도 업로드 핸들러
ipcMain.handle("retry-server-uploads", async (event, items) => {
  try {
    const list = Array.isArray(items) ? items : [];
    const tasks = [];
    for (const it of list) {
      try {
        const summary = summaryRepo.getSummary(it?.recording_id);
        const uploadData = {
          jobId: it?.job_id,
          lang: summary?.lang,
          attendeeNum: summary?.attendee_num,
          title: summary?.title || '',
          templateId: summary?.template_id || '',
          recordId: it?.recording_id,
          filePath: it?.file_path,
          fileName: it?.file_name,
          type: 'retry_multi'
        };
        // 무제한 병렬: 즉시 시작
        
        tasks.push(serverUploadInBackground(uploadData));
      } catch (_) {}
    }
    try { logger.logInfo('retry_server_uploads_begin', { count: tasks.length }); } catch (_) {}
    await Promise.allSettled(tasks);
    try { logger.logInfo('retry_server_uploads_done'); } catch (_) {}

    // 배치 완료 시 대기 중인 알림 즉시 발송
    if (notificationTimer) {
      clearTimeout(notificationTimer);
      notificationTimer = null;
      flushNotificationQueue();
    }
    
    return { success: true };
  } catch (err) {
    try { logger.logError('retry_server_uploads_failed', { message: err?.message || 'retry_server_uploads_failed' }); } catch (_) {}
    return { success: false, error: err?.message || 'retry_server_uploads_failed' };
  }
});

// DB 디버그 조회: recordings 상위 10개
ipcMain.handle("list-recordings", () => {
  try {
    const rows = recRepo.listRecordings();
    try { logger.logDebug('db_list_recordings_top10', { count: Array.isArray(rows) ? rows.length : 0 }); } catch (_) {}
    return { success: true, rows };
  } catch (error) {
    try { logger.logError('db_list_recordings_failed', { message: error && error.message }); } catch (_) {}
    return { success: false, error: error.message };
  }
});

ipcMain.handle("insert-recording", (event, recording) => {
  try { logger.logDebug('insert_recording_request', { recording: recording }); } catch (_) {}
  try {
    const fileNameRaw = (recording?.fileName || "").trim();
    const filePath = recording?.filePath || "";
    const fileName = fileNameRaw || initialFileName;

    // upload_name 은 렌더러 값이 아니라 녹음 시작 때 메인이 정한 이름을 쓴다
    const id = recRepo.insertRecording({ fileName, filePath, uploadName: initialFileName });
    return { success: true, recordingId: id };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// DB: 녹음 메타 저장
ipcMain.handle("upsert-recording", (event, recording) => {
  try {
    const fileNameRaw = (recording?.fileName || "").trim();
    const filePath = recording?.filePath || "";
    const fileName = fileNameRaw || initialFileName;
    const recordingId = recording?.id || "";

    const id = recRepo.upsertRecording({ fileName, filePath, recordingId, uploadName: initialFileName });
    return { success: true, id };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// 메모 DB 저장
ipcMain.handle("save-memos-batch", (event, recordingId, memo) => {
  try {
    try { logger.logInfo('save_memos_batch', { recordingId, count: Array.isArray(memo) ? memo.length : 0 }); } catch (_) {}
    memoRepo.saveMemosBatch(recordingId, memo);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// 메모 DB 수정
ipcMain.handle("update-memo", (event, id, text) => {
  try {
    try { logger.logInfo('update_memo', { id }); } catch (_) {}
    memoRepo.updateMemo(id, text);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// 메모 DB 삭제
ipcMain.handle("delete-memo", (event, id) => {
  try {
    try { logger.logInfo('delete_memo', { id }); } catch (_) {}
    memoRepo.deleteMemo(id);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// 태그 DB 저장
ipcMain.handle("add-tags", (event, recordingId, tags) => {
  try {
    try { logger.logInfo('add_tags', { recordingId, count: Array.isArray(tags) ? tags.length : 0 }); } catch (_) {}
    tagRepo.addTags(recordingId, tags);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// 태그 DB 수정
ipcMain.handle("replace-tags", (event, recordingId, tags) => {
  try {
    try { logger.logInfo('replace_tags', { recordingId, count: Array.isArray(tags) ? tags.length : 0 }); } catch (_) {}
    tagRepo.replaceTags(recordingId, tags);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// 업로드 리스트 삭제
ipcMain.handle("remove-job", (event, data) => {
  try {
    try { logger.logInfo('remove_job', { jobId: data && data.job_id }); } catch (_) {}

    jobRepo.removeJob(data.job_id);

    if (!data.file_path) throw new Error("No targetPath");
    const dir = data.file_path;
    if (removeRecordingTarget(dir)) {
      try { logger.logInfo('delete_recording_files', { target: dir }); } catch (_) {}
    }
    recRepo.deleteRecordingByFilePath(data.file_path);

    // 삭제 후 브로드캐스트
    jobsUpdated(jobRepo.listJobs());
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// 파일 삭제
ipcMain.handle("delete-recording", (event, dir) => {
  try { logger.logInfo('delete_recording_request', { target: dir }); } catch (_) {}
  deleteRecordingFile(dir);
});

// 녹음 1건(…\recordings\{uuid} 폴더, 또는 그 안의 파일)을 지운다.
// 녹음 폴더 아래가 아니면(recordings 폴더 자체, 다른 경로) 지우지 않고 false.
// 헬퍼 exe 폴더의 recordings 는 예전(작업 폴더 = exe 폴더) 녹음이 남아 있을 수 있어 허용한다.
function removeRecordingTarget(dir) {
  const helperDir = audioHelper && audioHelper.getPath ? path.dirname(audioHelper.getPath) : '';
  const extraRoots = helperDir ? [path.join(helperDir, 'recordings')] : [];
  if (!isSafeRecordingTarget(dir, extraRoots)) {
    try { logger.logError('delete_recording_blocked', { target: dir }); } catch (_) {}
    return false;
  }
  const stat = fs.existsSync(dir) ? fs.statSync(dir) : null;
  if (stat?.isDirectory()) {
    fs.rmSync(dir, { recursive: true, force: true });
  } else {
    fs.rmSync(dir, { force: true });
  }
  return true;
}

function deleteRecordingFile(dir){
  try {
    if (!dir) throw new Error("No targetPath");
    removeRecordingTarget(dir);
    // Recordings Column 삭제
    recRepo.deleteRecordingByFilePath(dir);

    try { logger.logInfo('delete_recording_done', { target: dir }); } catch (_) {}
    mainWindow.webContents.send("delete-recording-result", {success: true});
  } catch (err) {
    try { logger.logError('delete_recording_failed', { message: err && err.message, target: dir }); } catch (_) {}
    mainWindow.webContents.send("delete-recording-result", {success: false, error: err.message});
  }
}

// 업로드 목록 윈도우 생성
ipcMain.handle("open-upload-list", (event) => {
  const senderWindow = BrowserWindow.fromWebContents(event.sender);
  const data = jobRepo.listJobs();
  createUploadListWindow(senderWindow, data);
});

ipcMain.handle("close-upload-list", () => {
  closeUploadListWindow();
});

ipcMain.handle("toggle-upload-list", (event) => {
  const senderWindow = BrowserWindow.fromWebContents(event.sender);
  const data = jobRepo.listJobs();
  return toggleUploadListWindow(senderWindow, data);
});

ipcMain.handle("is-upload-list-open", () => {
  return isUploadListWindowOpen();
});

// 윈도우 크기 조절 핸들러
ipcMain.handle("resize-window", (event, options) => {
  const senderWindow = BrowserWindow.fromWebContents(event.sender);
  if (!senderWindow) {
    return;
  }

  if (options.center) {
    senderWindow.center();
  }
  try { logger.logDebug('resize_window', { width: options.width, height: options.height, center: !!options.center }); } catch (_) {}
  senderWindow.setSize(options.width, options.height);
});

// 윈도우 제약 설정 핸들러 (resizable, min/max 사이즈 동적 제어)
ipcMain.handle("set-window-constraints", (event, options) => {
  const senderWindow = BrowserWindow.fromWebContents(event.sender);
  if (!senderWindow) {
    return;
  }

  // 1. 리사이즈 가능 여부 설정
  if (typeof options.resizable === 'boolean') {
    senderWindow.setResizable(options.resizable);
  }

  // 2. 최소 사이즈 설정
  if (options.minWidth && options.minHeight) {
    senderWindow.setMinimumSize(options.minWidth, options.minHeight);
  }

  // 3. 최대 사이즈 설정
  if (options.maxWidth && options.maxHeight) {
    senderWindow.setMaximumSize(options.maxWidth, options.maxHeight);
  } else if (options.resizable) {
    // 최대 사이즈 제한 해제 (무제한으로 확장 가능)
    // macOS/Windows에서 충분히 큰 값으로 설정
    senderWindow.setMaximumSize(99999, 99999);
  }

  // 4. 현재 사이즈 설정
  if (options.width && options.height) {
    senderWindow.setSize(options.width, options.height);
  }

  // 5. 센터링 (옵션)
  if (options.center) {
    senderWindow.center();
  }

  // 로깅
  try { 
    logger.logDebug('set_window_constraints', {
      resizable: options.resizable,
      minSize: options.minWidth && options.minHeight ? `${options.minWidth}x${options.minHeight}` : undefined,
      maxSize: options.maxWidth && options.maxHeight ? `${options.maxWidth}x${options.maxHeight}` : 'unlimited',
      currentSize: options.width && options.height ? `${options.width}x${options.height}` : undefined
    });
  } catch (_) {}
});

// 팝업 윈도우 열기
// 메인 윈도우 최소화 상태일 경우 시스템알림
ipcMain.handle("open-popup-window", (event, options) => {
  if(mainWindow.isMinimized() || !mainWindow.isVisible()){
    // 시스템 알림 생성
    createSystemNotification(options);
    return;
  }
  createPopupWindow(mainWindow, options);
});

// 시스템 알림 생성 요청
ipcMain.handle("create-system-notification", (event, options) => {
  createSystemNotification(options);
});

// 시스템 알림 생성 함수
function createSystemNotification(options){
  try { logger.logInfo('create_system_notification', { title: options && options.title }); } catch (_) {}
  // Windows & MacOS 분기 
  if(process.platform === "win32"){
    // Windows 시스템 알림 생성
    // body가 직접 제공되면 사용, 없으면 subtitle + warning 조합
    const body = options.body || (options.subtitle + (options.warning ? options.warning : ''));
    const noti = new Notification({
      title: options.title,
      body: body,
    });
    noti.show();
  } else if(process.platform === "darwin"){
    // MacOS 시스템 알림 생성
    // subtitle 사용, body는 warning 전용
    const noti = new Notification({
      title: options.title,
      subtitle: options.subtitle,
      body: options.warning ? options.warning : '',
    });
    noti.show();
  }
}

ipcMain.handle("is-minimized", () => {  
  return (mainWindow.isMinimized() || !mainWindow.isVisible()) ? true : false;
});


// 요약 템플릿 목록 (업로드 팝업). cached: 바로 보여줄 목록, refresh: 서버에서 다시 받은 목록
ipcMain.handle('app:get-version', () => app.getVersion());
ipcMain.handle('templates:cached', () => templateService.getCached());
ipcMain.handle('templates:refresh', () => templateService.refresh());

// 요약 준비하기 윈도우 열기
ipcMain.handle("open-summarize", (event, options) => {
  createSummarizeWindow(event.sender, options);
});


// ==================
// 개발용 로깅 핸들러
// ==================
for (const level of ['info', 'error', 'warn', 'debug']) {
  ipcMain.handle(`send-${level}`, async (_event, message, context) => {
    try {
      return await logger.logFromRenderer(level, message, context);
    } catch (err) {
      return { success: false, error: err && err.message };
    }
  });
}

// 사용자 동작 로그 (렌더러 버튼 클릭 등)
ipcMain.handle('log-user-action', async (_event, action, context) => {
  try {
    return await logger.logUserAction(String(action || 'unknown_action'), context, 'renderer');
  } catch (err) {
    return { success: false, error: err && err.message };
  }
});


// 윈도우 최소화
ipcMain.handle("minimize-window", (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  win.minimize();
});

// 윈도우 닫기
ipcMain.handle("close-window", (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  if (win && !win.isDestroyed()) win.close();
});

// 앱 종료
ipcMain.handle("app-quit", () => {
  app.quit();
});

// 윈도우 상단 고정
ipcMain.handle("top-window", (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);

  if (win) {
    win.setAlwaysOnTop(!win.isAlwaysOnTop(), "floating");
  }
});
// 테스트 화면으로 이동
ipcMain.handle("go-home", (e) => {
  loadHome();
  e.sender.close();
});

// 녹음 중 앱요청 처리
ipcMain.handle("send-app-close-recording", (e, data) => {
  let payload = null;
  switch(data.cmd) {
    case 'confirm_app_close_recording': {
      payload = {
        ev: "confirm_app_close_recording",
      }
      break;
    }
    case 'select_stop_type': {
      payload = {
        ev: "stop_type_selected",
        stopType: data.stopType,
      }
      break;
    }
    default: {
      payload = {
        ev: "unknown_command",
        command: data.cmd,
      }
      break;
    }
  }

  mainWindow.webContents.send("app-close-recording", payload);
  e.sender.close();
});

ipcMain.handle('send-max-duration-stopped', (e, data) => {
  let payload = null;
  switch(data.cmd) {
    case 'select_stop_type': {
      payload = {
        ev: "stop_type_selected",
        stopType: data.stopType,
      }
      break;
    }
    default: {
      payload = {
        ev: "unknown_command",
        command: data.cmd,
      }
      break;
    }
  }
  mainWindow.webContents.send("max-duration-stopped", payload);
  e.sender.close();
});


// 단일 인스턴스 보장 및 두 번째 인스턴스 딥링크 처리 (Windows, dev 플래그 필터링)
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", (event, argv) => {
    // Windows에서는 두 번째 인스턴스 인자로 URL이 전달됨
    try {
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.focus();
      }
      const urlArg = (argv || [])
        .filter((a) => typeof a === "string")
        .find((a) =>
          a.toLowerCase().startsWith((PROTOCOL_SCHEME + "://").toLowerCase())
        );
      if (urlArg) {
        sendDeepLinkToRenderer(urlArg);
      }
    } catch (_) {}
  });
}

// macOS 딥링크 이벤트
app.on("open-url", (event, url) => {
  event.preventDefault();
  sendDeepLinkToRenderer(url);
});

// 최초 실행 시 전달된 딥링크 (Windows, Electron dev 플래그 제거 고려)
let initialDeepLink = null;
if (process.platform === "win32") {
  try {
    // Electron dev 환경에서는 argv에 --require 등 플래그가 섞여 있음
    const args = (process.argv || []).filter((a) => typeof a === "string");
    const arg = args.find((a) =>
      a.toLowerCase().startsWith((PROTOCOL_SCHEME + "://").toLowerCase())
    );
    if (arg) initialDeepLink = arg;
  } catch (_) {}
}

app.whenReady().then(async () => {
  // 로거 초기화 및 pending 흡수
  try { await logger.initMainLogger(app); } catch (_) {}

  // 로그 서버 전송 (info 이상). 모든 로그에 사번·이름을 붙여 누구의 PC 인지 구분한다.
  // 이름: 테스트 로그인은 입력한 값, SSO/사번 로그인은 내 정보 조회(userService) 결과
  try {
    logger.setRemoteSink(logShipper.enqueue);
    logShipper.start({
      getContext: () => ({
        empno: authService.getProfile().empno || '',
        userName: authService.getProfile().name || '',
        deviceId: require("./services/deviceService").getDeviceId(),
        appOs: authConfig.APP_OS,
        // PC 시간대(API 헤더 x-device-timezone 과 같은 값). 해외 접속 구분용
        timezone: require("./services/apiService").deviceTimezone(),
      }),
    });
  } catch (_) {}

  try {
    logger.logUserAction('app_started', {
      appVersion: app.getVersion(),
      platform: process.platform,
      arch: process.arch,
      osVersion: require("os").release(),
      timezone: require("./services/apiService").deviceTimezone(),
    });
  } catch (_) {}

  audioHelper = new AudioHelperManager();
  
  // 렌더러 브로드캐스트 콜백 연결
  audioHelper.setOnEvent((payload) => {
    try {
      normalizeHelperEventPaths(payload);
      // 대기자(ACK waiter) 해제
      try {
        const snapshot = Array.from(helperEventWaiters);
        for (const waiter of snapshot) {
          if (waiter && typeof waiter.match === 'function' && waiter.match(payload)) {
            helperEventWaiters.delete(waiter);
            try { clearTimeout(waiter.timeoutId); } catch (_) {}
            try { waiter.resolve(payload); } catch (_) {}
          }
        }
      } catch (_) {}

      if (mainWindow) mainWindow.webContents.send("helper-event", payload);
    } catch (_) {}
  });

  // 프로토콜 기본 앱 등록 (빌드 환경에서만)
  try {
    if (!process.defaultApp) {
      // 프로덕션 빌드에서만 등록
      app.setAsDefaultProtocolClient(PROTOCOL_SCHEME);
    }
    // 개발 모드에서는 등록하지 않음 (LaunchServices 충돌 방지)
    // 빌드 후 자동 등록: scripts/register-protocol.js (afterPack 훅)
  } catch (_) {}

  // 앱 시작 시: MainWindow 생성 전에 복구 스캔 수행
  let recoveryAction = null;
  try {
    const result = scanAndAutoQueue();
    const queuedCount = Array.isArray(result?.queued) ? result.queued.length : 0;
    const deletedCount = Array.isArray(result?.deleted) ? result.deleted.length : 0;
    if (queuedCount > 0 ) {
      // 팝업 표시: 사용자 선택(닫기 / 업로드 리스트 열기)
      const options = {
        width: 360,
        height: 220,
        type: 'recovery-result',
        title: t('popup.recovery_title'),
        subtitle: t('popup.recovery_subtitle', { count: queuedCount }),
        warning: t('popup.recovery_warning')
      };
      createPopupWindow(null, options);

      // 사용자 응답 대기
      recoveryAction = await new Promise((resolve) => {
        try {
          ipcMain.handleOnce('recovery:action', (event, payload) => {
            try { resolve(payload && payload.action); } catch (_) { resolve(null); }
          });
        } catch (_) {
          resolve(null);
        }
      });

      try { closePopupWindow(); } catch (_) {}
    }
  } catch (_) {}

  // 로그인 유지: 저장해 둔 세션이 있으면 창을 띄우기 전에 복원 → 바로 마이크 테스트 화면.
  // 내 정보·템플릿을 다시 받으면서 토큰도 확인한다(만료면 조용히 갱신, 갱신 거절이면 로그인 화면으로).
  let sessionRestored = false;
  try { sessionRestored = authService.restoreSession(); } catch (_) {}

  createWindow();
  if (sessionRestored) onAuthenticated().catch(() => {});

  let logo = nativeImage.createFromPath(path.join(__dirname, "../renderer/assets/icons/logo_big.png"));
  logo = logo.resize({ width: 24, height: 24 });
  tray = new Tray(logo);
  tray.setToolTip(require('./config').get('APP_DISPLAY_NAME', 'SKHynixRecApp'));
  
  const menu = Menu.buildFromTemplate([
    {
      label: 'Quit',
      click: () => {
        app.quit();
      }
    },
    {
      label: 'Open',
      click: () => {
        mainWindow.show();
      }
    }
  ]);
  tray.setContextMenu(menu);
  

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });

  // 사용자가 업로드 리스트 열기를 선택한 경우, 메인 윈도우 생성 직후 열기
  try {
    if (recoveryAction === 'open-upload-list' && mainWindow && !mainWindow.isDestroyed()) {
      const data = jobRepo.listJobs();
      createUploadListWindow(mainWindow, data);
    }
  } catch (_) {}

  // 초기 딥링크 전달
  if (initialDeepLink) {
    sendDeepLinkToRenderer(initialDeepLink);
  }

  // 강제 자동 업데이트(Windows 빌드본만). 새 버전이 있으면 메인 창을 업데이트 화면으로 바꾼다.
  // 실패하면 그대로 쓰게 두고, 업데이트 화면으로 바꾼 뒤 실패하면 홈으로 돌려보낸다.
  updateService
    .runStartupUpdate({ getMainWindow: () => mainWindow, onSkipped: () => loadHome() })
    .catch(() => {});
});

app.on("window-all-closed", () => {
  if (audioHelper) {
    audioHelper.stopHelper();
  }

  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (audioHelper) {
    audioHelper.stopHelper();
  }
  // 남은 로그를 한 번 더 보내 본다. 종료를 붙잡지는 않는다(못 보낸 건 로그 파일에 남아 있다).
  // app_quit 이 전송 대기열에 들어간 뒤에 보내도록 순서를 맞춘다.
  Promise.resolve(logger.logUserAction('app_quit'))
    .catch(() => {})
    .then(() => logShipper.flushOnQuit())
    .catch(() => {});
});
