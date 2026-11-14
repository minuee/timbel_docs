#!/usr/bin/env node
// AM-Tray DLL 시험 (koffi) — 앱을 띄우지 않고 DLL 만 바로 불러 본다.
// 함수 모양은 AM C++ 매뉴얼 기준(2026-11-14). src/main/services/amTrayDll.js 맨 위 참고.
// 회사 PC(Windows)에서, 프로젝트 폴더에서 실행:
//
//   node scripts/amtray-koffi-test.js version    --dll-dir <폴더>
//   node scripts/amtray-koffi-test.js init       --dll-dir <폴더> --sso-key Prod_CASSO --sid timbloRecApp
//   node scripts/amtray-koffi-test.js token      --dll-dir <폴더> --sso-key Prod_CASSO --sid timbloRecApp --system-id <시스템ID>
//   node scripts/amtray-koffi-test.js is-login   --dll-dir <폴더> --sid timbloRecApp
//   node scripts/amtray-koffi-test.js check-user --dll-dir <폴더> --sid timbloRecApp --user-id <사번>
//   node scripts/amtray-koffi-test.js show-ui    --dll-dir <폴더> --sid timbloRecApp
//   node scripts/amtray-koffi-test.js message    --dll-dir <폴더> --code 504011 --locale ko
//
//   공통 옵션: --dll <파일이름> (기본 AmInterface_RT_X64.dll)  --no-init (token 때 Init 을 먼저 부르지 않음)  --utf8 (문구가 UTF-8 일 때)
//
// 결과는 JSON 한 줄. 토큰 값은 앞 6글자만 보여 준다(그대로 옮겨 적지 않도록).
// 창이 아무 말 없이 꺼지면 = DLL 안에서 죽은 것 → 그 사실(명령·옵션)을 적어 온다.

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
  console.log('사용법: 파일 맨 위 주석 참고 (version / init / token / is-login / check-user / show-ui / message)');
  process.exit(1);
}

dll.configure({
  dllDir: get('dll-dir', '.'),
  dllName: get('dll', dll.DEFAULT_DLL),
  useInit: !has('no-init'),
  utf8Result: has('utf8'),
  allowNonWindows: has('allow-non-windows'), // Mac 에서 가짜 dylib 시험용
});

const ssoKey = get('sso-key', 'Dev_CASSO');
const sid = get('sid', '');

let res;
switch (cmd) {
  case 'version': res = dll.info(); break;
  case 'init': res = dll.init({ ssoKey, sid }); break;
  case 'token':
    res = dll.getSystemToken({ ssoKey, sid, systemId: get('system-id', '') });
    if (res.ok && res.code === dll.CODE_SUCCESS && res.result) {
      res = { ...res, result: res.result.slice(0, 6) + '…', length: res.result.length, kind: '인가토큰' };
    }
    break;
  case 'is-login': res = dll.isLogin({ sid }); break;
  case 'check-user': res = dll.checkLoginUser({ sid, userId: get('user-id', '') }); break;
  case 'show-ui': res = dll.showLoginUI({ sid }); break;
  case 'message': res = dll.getReturnMessage({ code: get('code', ''), locale: get('locale', 'ko') }); break;
  default: res = { ok: false, error: 'unknown_command' };
}
console.log(JSON.stringify(res));
process.exit(res && res.ok ? 0 : 1);
