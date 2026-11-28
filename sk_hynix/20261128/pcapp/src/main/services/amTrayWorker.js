// AM-Tray DLL 작업 프로세스 (Electron utilityProcess)
// - amTrayService.js 가 utilityProcess.fork 로 띄운다. DLL 호출(amTrayDll.js)은 보통 여기서만 한다.
//   (11-18 시험용 AMTRAY_DLL_PROCESS=main 이면 본체가 이 파일의 handle() 을 직접 부른다 — amTrayService.js runInMain)
//   DLL 이 잘못돼 이 프로세스가 죽어도 앱 본체는 살아 있고, 다음 호출 때 다시 띄운다.
// - 메시지: 부모 → { id, cmd, args, opts } / 이 프로세스 → { id, res }
//   cmd: 'init' | 'token' | 'show-ui' | 'is-login' | 'check-user' | 'sm-session' | 'message' | 'version'

const dll = require('./amTrayDll');

function run(cmd, args) {
  switch (cmd) {
    case 'init': return dll.init(args);
    case 'token': return dll.getSystemToken(args);
    case 'show-ui': return dll.showLoginUI(args);
    case 'is-login': return dll.isLogin(args);
    case 'check-user': return dll.checkLoginUser(args);
    case 'sm-session': return dll.getSmSessionToken(args);
    case 'message': return dll.getReturnMessage(args);
    case 'version': return dll.info();
    default: return { ok: false, cmd, error: 'unknown_command' };
  }
}

// 명령 하나 실행(설정 → 호출). 작업 프로세스와 본체(AMTRAY_DLL_PROCESS=main, 11-18 시험용)가 같이 쓴다.
function handle(msg) {
  try {
    if (msg.opts) dll.configure(msg.opts);
    return run(msg.cmd, msg.args || {});
  } catch (err) {
    return { ok: false, cmd: msg.cmd, error: 'exception', message: String((err && err.message) || err) };
  }
}

// 작업 프로세스로 떴을 때만 메시지를 받는다(본체에서 require 하면 parentPort 가 없다)
if (process.parentPort) {
  process.parentPort.on('message', (e) => {
    const msg = (e && e.data) || {};
    process.parentPort.postMessage({ id: msg.id, res: handle(msg) });
  });
}

module.exports = { handle };
