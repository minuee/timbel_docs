// AM-Tray DLL 작업 프로세스 (Electron utilityProcess)
// - amTrayService.js 가 utilityProcess.fork 로 띄운다. DLL 호출(amTrayDll.js)은 여기서만 한다.
//   DLL 이 잘못돼 이 프로세스가 죽어도 앱 본체는 살아 있고, 다음 호출 때 다시 띄운다.
// - 메시지: 부모 → { id, cmd, args, opts } / 이 프로세스 → { id, res }
//   cmd: 'token' | 'show-ui' | 'logout' | 'message' | 'version'

const dll = require('./amTrayDll');

function run(cmd, args) {
  switch (cmd) {
    case 'token': return dll.getSystemToken(args);
    case 'show-ui': return dll.showLoginUI(args);
    case 'logout': return dll.logout(args);
    case 'message': return dll.getReturnMessage(args);
    case 'version': return dll.info();
    default: return { ok: false, cmd, error: 'unknown_command' };
  }
}

process.parentPort.on('message', (e) => {
  const msg = (e && e.data) || {};
  let res;
  try {
    if (msg.opts) dll.configure(msg.opts);
    res = run(msg.cmd, msg.args || {});
  } catch (err) {
    res = { ok: false, cmd: msg.cmd, error: 'exception', message: String((err && err.message) || err) };
  }
  process.parentPort.postMessage({ id: msg.id, res });
});
