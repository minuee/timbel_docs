// 매뉴얼 촬영용 가짜 preload.
// 화면(HTML)을 Electron 없이 Chromium 으로 띄우기 위해 preload.js 가 만들던 window.* API 를 흉내 낸다.
// 설정은 shoot.js 가 window.__MOCK_CFG 로 먼저 넣는다:
//   { lang, messages, fallback, languages, status, devices, renderDevices, templates, levels }
(function () {
  const cfg = window.__MOCK_CFG || {};
  const listeners = {};
  const on = (ch) => (cb) => { (listeners[ch] = listeners[ch] || []).push(cb); };
  const emit = (ch, payload) => (listeners[ch] || []).forEach((cb) => { try { cb(payload); } catch (e) { console.error(e); } });
  window.__emit = emit;
  window.__calls = [];
  window.__windowSize = null;
  // 창 높이를 화면 높이로 자르는 계산이 있어 화면을 넉넉하게 둔다
  try {
    Object.defineProperty(window.screen, 'availHeight', { get: () => 1600 });
    Object.defineProperty(window.screen, 'availTop', { get: () => 0 });
    Object.defineProperty(window, 'screenY', { get: () => 0 });
  } catch (_) {}

  // --- i18n (preload.js 와 같은 동작) ---
  let state = { enabled: true, lang: cfg.lang || 'ko', languages: cfg.languages || [], messages: cfg.messages || {}, fallback: cfg.fallback || {} };
  const i18nListeners = [];
  function t(key, params) {
    let text = state.messages[key];
    if (text === undefined) text = state.fallback[key];
    if (text === undefined) return key;
    if (!params) return text;
    return String(text).replace(/\{(\w+)\}/g, (all, name) => (Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : all));
  }
  const ATTRS = [['data-i18n-placeholder', 'placeholder'], ['data-i18n-title', 'title'], ['data-i18n-alt', 'alt'], ['data-i18n-aria-label', 'aria-label']];
  function applyI18n() {
    document.documentElement.lang = state.lang;
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.getAttribute('data-i18n')); });
    document.querySelectorAll('[data-i18n-html]').forEach((el) => { el.innerHTML = t(el.getAttribute('data-i18n-html')); });
    ATTRS.forEach(([d, a]) => document.querySelectorAll(`[${d}]`).forEach((el) => el.setAttribute(a, t(el.getAttribute(d)))));
  }
  window.addEventListener('DOMContentLoaded', applyI18n);
  window.i18n = {
    t, lang: () => state.lang, enabled: () => state.enabled, languages: () => state.languages,
    setLang: async () => ({ success: true }), onChange: (cb) => i18nListeners.push(cb),
  };

  // --- 헬퍼(오디오) 흉내: 장치 목록, 레벨, 녹음 시작 ---
  let levelTimer = null;
  function startLevels() {
    if (levelTimer) return;
    const lv = cfg.levels || { mic: 0.35, system: 0.2 };
    let k = 0;
    levelTimer = setInterval(() => {
      k++;
      const wob = (base) => Math.max(0, base * (0.75 + 0.25 * Math.sin(k / 2)));
      if (lv.mic) emit('helper-event', { ev: 'level', source: 'mic', rms: wob(lv.mic) });
      if (lv.system) emit('helper-event', { ev: 'level', source: 'system', rms: wob(lv.system) });
    }, 50);
  }
  async function sendHelperCommand(cmd) {
    window.__calls.push(['helper', cmd]);
    setTimeout(() => {
      switch (cmd.cmd) {
        case 'list_devices':
          emit('helper-event', { ev: 'devices', devices: cfg.devices || [], renderDevices: cfg.renderDevices || [] });
          break;
        case 'start_test':
          emit('helper-event', { ev: 'test_started' }); startLevels(); break;
        case 'start':
          emit('helper-event', { ev: 'session_created', sessionId: 'S1', fileName: 'A.Biz_p_rec_20261029_100000' });
          emit('helper-event', { ev: 'recording_started' }); startLevels(); break;
        case 'get_version':
          emit('helper-event', { ev: 'version_info', version: '0.4.2', webrtc_aec: true, product_name: 'AudioHelper', description: '', build_date: '2026-10-29', build_time: '10:00', copyright: '' });
          break;
      }
    }, 10);
    return { success: true };
  }

  const noop = () => {};
  const rec = (name) => (...args) => { window.__calls.push([name, ...args]); };
  window.electronAPI = {
    startAudioHelper: async () => ({ success: true }),
    stopAudioHelper: async () => ({ success: true }),
    sendHelperCommand,
    getAppVersion: async () => cfg.appVersion || '0.0.7',
    onHelperEvent: on('helper-event'), onDeepLink: on('deep-link'), onAuthExchanged: on('auth-exchanged'),
    removeAllListeners: noop, openUploadList: rec('openUploadList'), closeUploadList: noop,
    toggleUploadList: async () => 'opened', isUploadListOpen: async () => false,
    onUploadListOpen: on('upload-list-open'), onUploadListState: on('upload-list-state'),
    sendRecoveryAction: noop, resizeWindow: noop,
    setWindowConstraints: async (o) => { window.__windowSize = { width: o.width, height: o.height }; },
    openPopupWindow: rec('openPopupWindow'), loadIndex: async () => {},
    onApplyPopupWindow: on('popup-window-loaded'), onUploadProgress: on('upload-progress'),
    onUploadFailed: on('upload-failed'), onUploadSucceeded: on('upload-succeeded'),
    openSummarize: rec('openSummarize'), onApplySummarizeWindow: on('summarize-window-loaded'),
    deleteRecording: noop, requestUpload: rec('requestUpload'), onRequestUpload: on('request-upload'),
    onDeleteRecordingResult: on('delete-recording-result'), createSystemNotification: noop,
  };
  window.authAPI = {
    getStatus: async () => cfg.status || {},
    openSso: async () => ({ success: true }),
    systemLogin: async () => ({ success: false, error: 'system_login_not_ready' }),
    loginWithEmpno: async () => (cfg.empnoResult || { success: true }),
    loginManual: async () => ({ success: true }),
    setLoginOptions: async () => ({ success: true }),
    logout: async () => ({ success: true }),
    takeTermsNotice: async () => ({ show: !!cfg.termsNotice }),
    openTermsPage: async () => ({ success: true }),
  };
  window.templateAPI = { getCached: async () => cfg.templates || [], refresh: async () => cfg.templates || [] };
  window.updateAPI = { onStatus: on('update-status') };
  window.dbAPI = {
    insertRecording: async () => ({ success: true, id: 1 }), upsertRecording: async () => ({ success: true, id: 1 }),
    deleteRecording: noop, markDeleted: noop, saveMemosBatch: async () => ({}), updateMemo: async () => ({}), deleteMemo: async () => ({}),
    addTags: noop, replaceTags: noop, enqueueUpload: async () => ({ success: true, jobId: 1 }), listPendingUploads: noop,
    markUploaded: noop, removeJob: async () => ({}), listJobs: async () => [], onJobsUpdated: on('jobs-updated'),
    debugListRecordings: async () => [],
  };
  window.serviceAPI = { serverUpload: () => ({ success: true }), retryServerUpload: async () => ({}), retryServerUploads: async () => ({}) };
  window.windowAPI = {
    minimizeWindow: noop, closeWindow: noop, maximizeWindow: noop, topWindow: noop, appQuit: noop,
    isMinimized: async () => false, goHome: noop, sendAppCloseRecording: noop, onAppCloseRecording: on('app-close-recording'),
    sendMaxDurationStopped: noop, onMaxDurationStopped: on('max-duration-stopped'),
  };
  window.developerAPI = { sendInfo: noop, sendError: noop, sendWarn: noop, sendDebug: noop, logAction: noop };
})();
