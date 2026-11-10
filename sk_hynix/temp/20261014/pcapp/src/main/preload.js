const { contextBridge, ipcRenderer } = require('electron');

// 렌더러 프로세스에서 사용할 API 정의
contextBridge.exposeInMainWorld('electronAPI', {
  // 오디오 헬퍼 관리
  startAudioHelper: () => ipcRenderer.invoke('start-audio-helper'),
  stopAudioHelper: () => ipcRenderer.invoke('stop-audio-helper'),
  sendHelperCommand: (command) => ipcRenderer.invoke('send-helper-command', command),
  // 앱 버전(package.json version) — 설정 메뉴 "버전 정보"
  getAppVersion: () => ipcRenderer.invoke('app:get-version'),
  
  // 헬퍼 이벤트 수신
  onHelperEvent: (callback) => {
    ipcRenderer.on('helper-event', (event, data) => callback(data));
  },

  // 딥링크 수신
  onDeepLink: (callback) => {
    ipcRenderer.on('deep-link', (event, url) => callback(url));
  },

  // 토큰 교환 결과 수신
  onAuthExchanged: (callback) => {
    ipcRenderer.on('auth-exchanged', (event, payload) => callback(payload));
  },
  
  // 이벤트 리스너 제거
  removeAllListeners: (channel) => {
    ipcRenderer.removeAllListeners(channel);
  },

  // 업로드 리스트 화면 열기
  openUploadList: () => {
    ipcRenderer.invoke('open-upload-list')
  },

  // 업로드 리스트 화면 닫기
  closeUploadList: () => {
    ipcRenderer.invoke('close-upload-list')
  },

  // 업로드 리스트 토글
  toggleUploadList: async () => {
    return ipcRenderer.invoke('toggle-upload-list')
  },

  // 업로드 리스트 열림 상태 조회
  isUploadListOpen: async () => {
    return ipcRenderer.invoke('is-upload-list-open')
  },

  // 업로드 리스트 화면 열기 이벤트 수신
  onUploadListOpen: (callback) => {
    ipcRenderer.on('upload-list-open', (event, data) => callback(data));
  },

  // 업로드 리스트 상태 이벤트 수신(opened/closed)
  onUploadListState: (callback) => {
    ipcRenderer.on('upload-list-state', (event, payload) => callback(payload));
  },

  // 복구 액션 선택(닫기/업로드 리스트)
  sendRecoveryAction: (action) => {
    ipcRenderer.invoke('recovery:action', { action });
  },

  // 화면 사이즈 조절
  resizeWindow: (options) => {
    ipcRenderer.invoke('resize-window', options)
  },

  // 윈도우 제약 설정 (resizable, min/max 사이즈)
  setWindowConstraints: (options) => {
    return ipcRenderer.invoke('set-window-constraints', options)
  },

  // 팝업 윈도우 열기
  openPopupWindow: (options) => {
    ipcRenderer.invoke('open-popup-window', options)
  },

  // 메인 윈도우를 홈(index.html)으로 이동
  loadIndex: () => {
    return ipcRenderer.invoke('load-index')
  },

  onApplyPopupWindow: (callback) => {
    ipcRenderer.on('popup-window-loaded', (event, options) => callback(options));
  },

  // 업로드 진행 이벤트 수신
  onUploadProgress: (callback) => {
    ipcRenderer.on('upload-progress', (event, payload) => callback(payload));
  },

  // 업로드 실패 이벤트 수신
  onUploadFailed: (callback) => {
    ipcRenderer.on('upload-failed', (event, payload) => callback(payload));
  },

  // AI 요약 윈도우 열기
  openSummarize: (options) => {
    ipcRenderer.invoke('open-summarize', options)
  },

  onApplySummarizeWindow: (callback) => {
    ipcRenderer.on('summarize-window-loaded', (event, options) => callback(options));
  },

  // 파일 삭제
  deleteRecording: (dir) => {
    ipcRenderer.invoke('delete-recording', dir)
  },

  // 업로드 요청
  requestUpload: (options) => {
    ipcRenderer.invoke('request-upload', options)
  },

  onRequestUpload: (callback) => {
    ipcRenderer.on('request-upload', (event, data) => callback(data));
  },

  // 파일 삭제 결과 이벤트 수신
  onDeleteRecordingResult: (callback) => {
    ipcRenderer.on('delete-recording-result', (event, payload) => callback(payload));
  },

  createSystemNotification: (options) => {
    ipcRenderer.invoke('create-system-notification', options);
  },
});

// 로그인/인증 (토큰은 메인 프로세스에만 있고, 여기서는 성공 여부만 오간다)
contextBridge.exposeInMainWorld('authAPI', {
  getStatus: () => ipcRenderer.invoke('auth:get-status'),
  openSso: () => ipcRenderer.invoke('auth:open-sso'),
  loginWithEmpno: (empno, password) => ipcRenderer.invoke('auth:login-empno', { empno, password }),
  loginManual: (fields) => ipcRenderer.invoke('auth:login-manual', fields),
});

// 요약 템플릿 목록 (업로드 팝업) — [{ code, name }]
contextBridge.exposeInMainWorld('templateAPI', {
  getCached: () => ipcRenderer.invoke('templates:cached'),
  refresh: () => ipcRenderer.invoke('templates:refresh'),
});

// 자동 업데이트 화면(pages/update.html) 진행 상태 수신
contextBridge.exposeInMainWorld('updateAPI', {
  onStatus: (callback) => {
    ipcRenderer.on('update-status', (event, status) => callback(status));
  },
});

// 데이터베이스 관리
contextBridge.exposeInMainWorld('dbAPI', {
  // 녹음 관리
  insertRecording: (recording) => {
    return ipcRenderer.invoke('insert-recording', recording)
  },
  upsertRecording: (recording) => {
    return ipcRenderer.invoke('upsert-recording', recording)
  },
  deleteRecording: (id) => {
    ipcRenderer.invoke('delete-recording', id)
  },
  markDeleted: (id) => {
    ipcRenderer.invoke('mark-deleted', id)
  },
  
  // 메모 관리
  saveMemosBatch: (recordingId, memo) => {
    return ipcRenderer.invoke('save-memos-batch', recordingId, memo)
  },
  updateMemo: (id, text) => {
    return ipcRenderer.invoke('update-memo', id, text)
  },
  deleteMemo: (id) => {
    return ipcRenderer.invoke('delete-memo', id)
  },

  // 태그 관리
  addTags: (recordingId, tags) => {
    ipcRenderer.invoke('add-tags', recordingId, tags)
  },
  replaceTags: (recordingId, tags) => {
    ipcRenderer.invoke('replace-tags', recordingId, tags)
  },

  // 업로드 관리
  enqueueUpload: (recordId, data) => {
    return ipcRenderer.invoke('enqueue-upload', recordId, data)
  },
  listPendingUploads: () => {
    ipcRenderer.invoke('list-pending-uploads')
  },
  markUploaded: (jobId) => {
    ipcRenderer.invoke('mark-uploaded', jobId)
  },
  removeJob: (data) => {
    return ipcRenderer.invoke('remove-job', data)
  },
  listJobs: () => {
    return ipcRenderer.invoke('list-jobs')
  },
  onJobsUpdated: (callback) => {
    ipcRenderer.on('jobs-updated', (event, data) => callback(data));
  },

  // 디버그 조회
  debugListRecordings: () => {
    return ipcRenderer.invoke('list-recordings')
  },
});

// 서비스 관리
contextBridge.exposeInMainWorld('serviceAPI', {
  serverUpload: (data, event) => {
    return ipcRenderer.invoke('server-upload', data, event)
  },

  retryServerUpload: (data, event) => {
    return ipcRenderer.invoke('retry-server-upload', data, event)
  },

  // 다건 재시도 업로드
  retryServerUploads: (items) => {
    return ipcRenderer.invoke('retry-server-uploads', items)
  },
});

// 윈도우 관리
contextBridge.exposeInMainWorld('windowAPI', {
  minimizeWindow: () => {
    ipcRenderer.invoke('minimize-window')
  },
  closeWindow: () => {
    ipcRenderer.invoke('close-window')
  },
  maximizeWindow: () => {
    ipcRenderer.invoke('maximize-window')
  },
  topWindow: () => {
    ipcRenderer.invoke('top-window')
  },
  appQuit: () => {
    ipcRenderer.invoke('app-quit')
  },
  isMinimized: () => {
    return ipcRenderer.invoke('is-minimized')
  },
  goHome: (event) => {
    ipcRenderer.invoke('go-home', event)
  },
  sendAppCloseRecording: (event, data) => {
    ipcRenderer.invoke('send-app-close-recording', event, data)
  },
  onAppCloseRecording: (callback) => {
    ipcRenderer.on('app-close-recording', (event, data) => callback(data));
  },

  sendMaxDurationStopped: (event, data) => {
    ipcRenderer.invoke('send-max-duration-stopped', event, data)
  },

  onMaxDurationStopped: (callback) => {
    ipcRenderer.on('max-duration-stopped', (event, data) => callback(data));
  },
});


// 개발용 ContextBridge 정의
contextBridge.exposeInMainWorld('developerAPI', {
  
  sendInfo: (message, context) => {
    ipcRenderer.invoke('send-info', message, context)
  },
  sendError: (message, context) => {
    ipcRenderer.invoke('send-error', message, context)
  },
  sendWarn: (message, context) => {
    ipcRenderer.invoke('send-warn', message, context)
  },
  sendDebug: (message, context) => {
    ipcRenderer.invoke('send-debug', message, context)
  },
  // 사용자 동작 로그(로그 서버에서 category:"user_action"). action 은 snake_case 이벤트 이름
  logAction: (action, context) => {
    ipcRenderer.invoke('log-user-action', action, context)
  },
});