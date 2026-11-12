#!/usr/bin/env node
// AM-Tray DLL 시험 (koffi) — 앱을 띄우지 않고 DLL 만 바로 불러 본다. AmHelper.exe 시험을 대신한다.
// 회사 PC(Windows)에서, 프로젝트 폴더에서 실행:
//
//   node scripts/amtray-koffi-test.js version  --dll-dir <DLL 3개 폴더>
//   node scripts/amtray-koffi-test.js token    --dll-dir <폴더> --sso-key Dev_CASSO --sid timbloRecAppDev --system-id <시스템ID>
//   node scripts/amtray-koffi-test.js show-ui  --dll-dir <폴더> --sid timbloRecAppDev
//   node scripts/amtray-koffi-test.js message  --dll-dir <폴더> --code 504011 --locale ko
//
//   공통 옵션: --signature string|bool_out (기본 string)  --wide (wchar_t* 일 때)  --utf8 (DLL 문자열이 UTF-8 일 때)
//
// 결과는 JSON 한 줄. 토큰 값은 앞 6글자만 보여 준다(그대로 옮겨 적지 않도록).
// 창이 아무 말 없이 꺼지면 = DLL 안에서 죽은 것 → --signature 를 바꿔 보고, 그래도 같으면 그 사실을 적어 온다.

const path = require('path');
const dll = require(path.join(__dirname, '..', 'src', 'main', 'services', 'amTrayDll.js'));

const argv = process.argv.slice(2);
const cmd = argv[0];
const get = (name, def) => {
  const i = argv.indexOf('--' + name);
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : def;
};
const has = (name) => argv.includes('--' + name);

if (!cmd || has('help')) {
  console.log('사용법: 파일 맨 위 주석 참고 (version / token / show-ui / message)');
  process.exit(1);
}

dll.configure({
  dllDir: get('dll-dir', '.'),
  dllName: get('dll', 'AmInterface-RT-X64.dll'),
  signature: get('signature', 'string'),
  wide: has('wide'),
  utf8Result: has('utf8'),
  allowNonWindows: has('allow-non-windows'), // Mac 에서 가짜 dylib 시험용
});

let res;
switch (cmd) {
  case 'version': res = dll.info(); break;
  case 'token':
    res = dll.getSystemToken({ ssoKey: get('sso-key', 'Dev_CASSO'), sid: get('sid', ''), systemId: get('system-id', '') });
    if (res.ok && res.result && res.result.length > 6) {
      res = { ...res, result: res.result.slice(0, 6) + '…', length: res.result.length, kind: '인가토큰' };
    }
    break;
  case 'show-ui': res = dll.showLoginUI({ sid: get('sid', '') }); break;
  case 'logout': res = dll.logout({ sid: get('sid', '') }); break;
  case 'message': res = dll.getReturnMessage({ code: get('code', ''), locale: get('locale', 'ko') }); break;
  default: res = { ok: false, error: 'unknown_command' };
}
console.log(JSON.stringify(res));
process.exit(res && res.ok ? 0 : 1);
