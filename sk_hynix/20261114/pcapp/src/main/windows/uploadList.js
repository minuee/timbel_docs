const path = require('path');
const { BrowserWindow, screen } = require('electron');

let uploadListWindow;
let parentRef = null;

const createUploadListWindow = (parentWindow, data) => {
  if (uploadListWindow && !uploadListWindow.isDestroyed()) {
    uploadListWindow.focus();
    return;
  }

  const parentBounds = parentWindow.getBounds();
  const childWidth = 479;
  const childHeight = 470;

  // 부모 창이 있는 디스플레이의 작업영역(작업표시줄 제외)
  const { workArea } = screen.getDisplayMatching(parentBounds);

  // 왼쪽에 붙이기 (세로는 상단 정렬)
  let x = parentBounds.x - childWidth;
  let y = parentBounds.y;

  // 화면 밖으로 나가면 오른쪽으로 붙이기
  if (x < workArea.x) {
    x = parentBounds.x + parentBounds.width;
  }

  uploadListWindow = new BrowserWindow({
    width: childWidth,
    height: childHeight,
    x,
    y,
    frame: false,
    movable: true,
    parent: parentWindow ?? null,
    modal: false,
    autoHideMenuBar: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, '../preload.js')
    },
  });
  parentRef = parentWindow ?? null;

  uploadListWindow.on('closed', () => {
    uploadListWindow = null;
    try {
      if (parentRef && !parentRef.isDestroyed()) {
        parentRef.webContents.send('upload-list-state', { state: 'closed' });
        parentRef.focus();
      }
    } catch (_) {}
  });

  uploadListWindow.loadFile(
    path.join(__dirname, '../../renderer/pages/uploadList.html')
  );

  uploadListWindow.webContents.on('did-finish-load', () => {
    
    uploadListWindow.webContents.send('upload-list-open', data);
    try {
      if (parentRef && !parentRef.isDestroyed()) {
        parentRef.webContents.send('upload-list-state', { state: 'opened' });
      }
    } catch (_) {}
  });
};

const closeUploadListWindow = () => {
  if (uploadListWindow && !uploadListWindow.isDestroyed()) {
    try { uploadListWindow.close(); } catch (_) {}
  }
};

const isUploadListWindowOpen = () => {
  return !!(uploadListWindow && !uploadListWindow.isDestroyed());
};

const toggleUploadListWindow = (parentWindow, data) => {
  if (isUploadListWindowOpen()) {
    closeUploadListWindow();
    return 'closed';
  }
  createUploadListWindow(parentWindow, data);
  return 'opened';
};

const jobsUpdated = (data) => {
  if (uploadListWindow && !uploadListWindow.isDestroyed()) {
    uploadListWindow.webContents.send('jobs-updated', data);
  }
  return;
};

module.exports = {
  createUploadListWindow,
  closeUploadListWindow,
  isUploadListWindowOpen,
  toggleUploadListWindow,
  jobsUpdated,
};