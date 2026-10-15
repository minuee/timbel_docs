const { BrowserWindow, screen } = require('electron');
const path = require('path');

let popupWindow;
let popupReady = false;
let pendingMessages = [];
let pendingResize = null; // { width, height }

function createPopupWindow(parentWindow, options) {
  if(popupWindow && !popupWindow.isDestroyed()) {
    // 이미 열린 팝업이 있으면 새 옵션을 즉시 반영하고 포커스만 이동
    try {
      if (options && typeof options.width === 'number' && typeof options.height === 'number') {
        try { popupWindow.setSize(options.width, options.height); } catch (_) {}
        try { popupWindow.center(); } catch (_) {}
      }
      // 즉시 렌더러에 새 옵션 전달하여 내용 업데이트
      popupWindow.webContents.send('popup-window-loaded', options);
    } catch (_) {}
    popupWindow.focus();
    return;
  }

  // 팝업을 연 창(업로드 리스트 등)이 있는 모니터 가운데에 띄운다.
  // 예전엔 항상 주 모니터 가운데라, 듀얼 모니터에서 다른 화면에 떠서 "반응이 없는 것"처럼 보였다.
  let targetArea = screen.getPrimaryDisplay().workArea;
  try {
    const focused = BrowserWindow.getFocusedWindow();
    const base = (focused && !focused.isDestroyed()) ? focused : parentWindow;
    if (base && !base.isDestroyed()) targetArea = screen.getDisplayMatching(base.getBounds()).workArea;
  } catch (_) {}

  const x = Math.floor(targetArea.x + (targetArea.width - options.width) / 2);
  const y = Math.floor(targetArea.y + (targetArea.height - options.height) / 2);

  popupWindow = new BrowserWindow({
    width: options.width,
    height: options.height,
    frame: false,
    movable: true,
    resizable: false,
    x,
    y,
    parent: parentWindow ?? null,
    modal: false,
    alwaysOnTop: true,
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, '../preload.js')
    },
  });

  popupWindow.on('closed', () => {
    popupWindow = null;
    popupReady = false;
    pendingMessages = [];
    pendingResize = null;
  });

  popupWindow.loadFile(
    path.join(__dirname, '../../renderer/pages/popupWindow.html')
  );

  popupWindow.webContents.on('did-finish-load', () => {
    options.dir = options.dir;
    popupReady = true;
    // apply pending resize first
    if (pendingResize) {
      try { popupWindow.setSize(pendingResize.width, pendingResize.height); } catch (_) {}
      try { popupWindow.center(); } catch (_) {}
      pendingResize = null;
    }
    popupWindow.webContents.send('popup-window-loaded', options);
    // flush pending messages
    const queue = pendingMessages;
    pendingMessages = [];
    for (const { channel, payload } of queue) {
      try { popupWindow.webContents.send(channel, payload); } catch (_) {}
    }
  });

  return popupWindow;
}

function closePopupWindow() {
  try {
    if (popupWindow && !popupWindow.isDestroyed()) {
      popupWindow.close();
    }
  } catch (_) {}
}

function sendUploadProgressToPopup(payload) {
  try {
    if (popupWindow && !popupWindow.isDestroyed()) {
      if (popupReady) {
        
        popupWindow.webContents.send('upload-progress', payload);
      } else {
        pendingMessages.push({ channel: 'upload-progress', payload });
      }
    }
  } catch (_) {}
}

function sendUploadFailedToPopup(payload) {
  try {
    if (popupWindow && !popupWindow.isDestroyed()) {
      // set size immediately; if not ready, also remember to re-apply once ready
      try { popupWindow.setSize(370, 250); } catch (_) {}
      if (!popupReady) {
        pendingResize = { width: 370, height: 250 };
        pendingMessages.push({ channel: 'upload-failed', payload });
      } else {
        popupWindow.webContents.send('upload-failed', payload);
      }
    }
  } catch (_) {}
}

// 업로드 성공: 진행 팝업을 "업로드 완료" 안내로 바꾼다. 열린 팝업이 없으면 false
function sendUploadSucceededToPopup(payload) {
  try {
    if (popupWindow && !popupWindow.isDestroyed()) {
      try { popupWindow.setSize(370, 210); } catch (_) {}
      if (!popupReady) {
        pendingResize = { width: 370, height: 210 };
        pendingMessages.push({ channel: 'upload-succeeded', payload });
      } else {
        popupWindow.webContents.send('upload-succeeded', payload);
      }
      return true;
    }
  } catch (_) {}
  return false;
}

module.exports = {
  createPopupWindow,
  closePopupWindow,
  sendUploadProgressToPopup,
  sendUploadFailedToPopup,
  sendUploadSucceededToPopup
}