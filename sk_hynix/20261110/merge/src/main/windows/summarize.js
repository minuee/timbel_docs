const { BrowserWindow, screen } = require('electron');
const path = require('path');

let summarizeWindow;

// 업로드 팝업(AI 요약 준비하기) 크기. 부르는 곳(popupWindow.js)마다 넘기던 값 대신 여기서 정한다.
const SUMMARIZE_WIDTH = 560;
const SUMMARIZE_HEIGHT = 500;

function createSummarizeWindow(parentWindow, options) {
  options = { ...(options || {}), width: SUMMARIZE_WIDTH, height: SUMMARIZE_HEIGHT };
  if(summarizeWindow && !summarizeWindow.isDestroyed()) {
    summarizeWindow.focus();
    return;
  }

  // 윈도우 위치 설정
  const targetArea = screen.getPrimaryDisplay().workArea;
  const x = Math.floor(targetArea.x + (targetArea.width - options.width) / 2);
  const y = Math.floor(targetArea.y + (targetArea.height - options.height) / 2);


  summarizeWindow = new BrowserWindow({
    width: options.width,
    height: options.height,
    frame: false,
    x,
    y,
    parent: parentWindow ?? null,
    modal: false,
    autoHideMenuBar: false,
    alwaysOnTop: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, '../preload.js')
    },
  });

  summarizeWindow.on('closed', () => {
    summarizeWindow = null;
  });

  summarizeWindow.loadFile(
    path.join(__dirname, '../../renderer/pages/summarizeWindow.html')
  );

  summarizeWindow.webContents.on('did-finish-load', () => {
    options.isError = options.isError || false;
    summarizeWindow.webContents.send('summarize-window-loaded', options);
  });

  return summarizeWindow;
}



module.exports = {
  createSummarizeWindow
};