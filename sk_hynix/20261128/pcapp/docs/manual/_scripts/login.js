// 2장 "로그인" 장면 — AM-Tray 통합 SSO 로그인(로그인 화면 ver2, 2026-11-18).
//   node login.js   → docs/manual/img/02-*.png, docs/manual/gif/02_login.gif
// 앱 화면은 실제 화면(loginV2.html)을 흉내 preload 로 찍는다.
// 회사 화면은 캡처할 수 없어서 작업 표시줄·브라우저(MyAccess 로그인·AM-Tray 설치 페이지)·Windows 팝업은 "예시"로 그린다.
const path = require('path');
const { app, html, stage, gif, close, KO } = require('./lib');

const OUT = path.resolve(__dirname, '..');
const IMG = (name) => path.join(OUT, 'img', `${name}.png`);
const GIF = (name) => path.join(OUT, 'gif', `${name}.gif`);
const L = '2. 로그인';
const t = (k) => KO[k] || k;

const loginV2 = (o = {}) => app({ file: 'pages/loginV2.html', ...o });
const AM = {
  notLoggedIn: { success: false, error: 'amtray_not_logged_in', code: '504011' },
  shown: { success: false, pending: true, error: 'amtray_login_ui_shown' },
};

// ---- 그림 재료 ----
const AM_ICON = (size) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#1d5bd8"/><text x="12" y="16.6" text-anchor="middle" font-family="Arial,sans-serif" font-weight="700" font-size="13" fill="#fff">A</text></svg>`;

// Windows 작업 표시줄(오른쪽 아래)
const TASKBAR_CSS = `
body{background:linear-gradient(160deg,#4a78c2,#1f3f7a)}
.bar{position:absolute;left:0;right:0;bottom:0;height:56px;background:rgba(32,32,36,.92);display:flex;align-items:center;justify-content:flex-end;padding-right:14px;gap:6px;color:#fff}
.ic{width:38px;height:38px;border-radius:6px;display:flex;align-items:center;justify-content:center}
.ic svg{display:block}
.clock{font-size:13px;text-align:right;line-height:1.35;margin-left:8px}
.tip{position:absolute;background:#2b2b2f;color:#fff;font-size:14px;padding:7px 12px;border-radius:6px;border:1px solid #444;box-shadow:0 6px 18px rgba(0,0,0,.35)}
.ex{position:absolute;left:14px;top:12px;background:rgba(255,255,255,.85);color:#374151;font-size:13px;padding:3px 10px;border-radius:12px}`;
const TASKBAR = `
<div class="ex">Windows 작업 표시줄 (예시)</div>
<div class="tip" style="right:170px;bottom:66px">AM-Tray</div>
<div class="bar">
  <div class="ic"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M6 15l6-6 6 6"/></svg></div>
  <div class="ic" id="am">${AM_ICON(24)}</div>
  <div class="ic"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8"><path d="M2 9c5.5-5 14.5-5 20 0M5 12.5c4-3.5 10-3.5 14 0M8.5 16c2-1.6 5-1.6 7 0"/><circle cx="12" cy="19" r="1.2" fill="#fff"/></svg></div>
  <div class="ic"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8"><path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16 9a4 4 0 0 1 0 6"/></svg></div>
  <div class="clock">오전 9:30<br>2026-11-19</div>
</div>`;

// 브라우저 창(예시)
const BROWSER_CSS = `
body{background:#fff}
.chrome{height:40px;background:#dfe3ea;display:flex;align-items:flex-end;padding:0 10px;gap:8px}
.tab{background:#fff;border-radius:8px 8px 0 0;padding:8px 14px;font-size:13px;color:#1f2937;display:flex;gap:8px;align-items:center;min-width:220px}
.addr{height:40px;background:#fff;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;padding:0 14px}
.url{flex:1;background:#f1f3f6;border-radius:16px;padding:6px 14px;font-size:13px;color:#4b5563}
.page{position:absolute;top:80px;left:0;right:0;bottom:0;background:#f5f7fb;display:flex;align-items:center;justify-content:center}
.ex{position:absolute;right:14px;top:8px;background:#fff7ed;color:#c2410c;font-size:12px;padding:2px 10px;border-radius:10px;border:1px solid #fed7aa}
.card{width:380px;background:#fff;border-radius:14px;box-shadow:0 10px 30px rgba(20,30,50,.12);padding:30px 32px}
.card h1{font-size:21px;margin-bottom:20px;color:#111827}
.card label{display:block;font-size:13px;color:#4b5563;margin:12px 0 6px}
.inp{height:42px;border:1px solid #d1d5db;border-radius:8px;padding:0 12px;display:flex;align-items:center;font-size:14px;color:#9ca3af}
.btn{margin-top:22px;height:46px;border-radius:8px;background:#1d5bd8;color:#fff;font-weight:700;display:flex;align-items:center;justify-content:center;font-size:15px}
.steps{font-size:13px;color:#4b5563;line-height:1.8;margin-top:16px}`;
const browser = (tab, url, page) => `
<div class="chrome"><div class="tab">${AM_ICON(14)} ${tab}</div></div>
<div class="addr"><div class="url">${url}</div></div>
<div class="ex">예시 화면</div>
<div class="page">${page}</div>`;

const MYACCESS = browser('MyAccess SSO 로그인', 'https:// … (AM-Tray 가 여는 로그인 페이지)', `
<div class="card">
  <h1>MyAccess SSO 로그인</h1>
  <label>아이디</label><div class="inp" id="id">아이디</div>
  <label>비밀번호</label><div class="inp">비밀번호</div>
  <div class="btn" id="go">로그인</div>
</div>`);

const INSTALL_PAGE = browser('AM-Tray 설치', 'https://csam.skhynix.com/tray/view/install.do', `
<div class="card">
  <h1>AM-Tray 설치</h1>
  <div class="steps">통합 SSO 프로그램 AM-Tray 설치 파일을 받아 실행합니다.</div>
  <div class="btn" id="dl">설치 파일 다운로드</div>
  <div class="steps">① 받은 설치 파일 실행 → 설치 완료<br>② AM-Tray 에 로그인<br>③ PC 녹음 앱 다시 실행</div>
</div>`);

// Windows 대화상자(앱이 띄우는 팝업) 예시
const DIALOG_CSS = `
body{background:transparent}
.dlg{position:absolute;inset:0;background:#fff;border:1px solid #9aa3b0;display:flex;flex-direction:column}
.tb{height:34px;display:flex;align-items:center;justify-content:space-between;padding:0 4px 0 12px;font-size:13px;color:#111}
.tb span{width:40px;text-align:center;font-size:16px;color:#333}
.bd{flex:1;display:flex;gap:14px;padding:12px 20px 14px}
.msg{font-size:15px;color:#1e3a8a;margin-bottom:8px;line-height:1.5}
.det{font-size:13px;color:#374151;line-height:1.6}
.ft{background:#f0f0f0;border-top:1px solid #e1e1e1;padding:12px 16px;display:flex;justify-content:flex-end;gap:8px}
.b{min-width:92px;height:30px;border:1px solid #adadad;background:#e1e1e1;font-size:13px;display:flex;align-items:center;justify-content:center;padding:0 12px}
.b.def{border:2px solid #0078d7}`;
const ICON_WARN = '<svg width="34" height="34" viewBox="0 0 24 24"><path d="M12 2 1 21h22z" fill="#f2c200"/><path d="M12 9v6" stroke="#111" stroke-width="2"/><circle cx="12" cy="18" r="1.2" fill="#111"/></svg>';
const ICON_ERR = '<svg width="34" height="34" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#e81123"/><path d="M8 8l8 8M16 8l-8 8" stroke="#fff" stroke-width="2.2"/></svg>';
const dialog = ({ title, icon, message, detail, buttons }) => html({
  w: 460, h: 210, css: DIALOG_CSS, hl: ['#b0'], cursor: '#b0',
  body: `<div class="dlg">
  <div class="tb">${title}<span>✕</span></div>
  <div class="bd"><div>${icon}</div><div><div class="msg">${message}</div><div class="det">${detail || ''}</div></div></div>
  <div class="ft">${buttons.map((b, i) => `<div class="b${i === 0 ? ' def' : ''}" id="b${i}">${b}</div>`).join('')}</div>
</div>`,
});

(async () => {
  const frames = [];
  const shot = async (name, spec, sec) => { frames.push({ file: await stage(spec, IMG(name)), sec }); };

  // 1. AM-Tray 아이콘
  await shot('02-1_amtray-icon', {
    wins: [{ shot: await html({ w: 760, h: 300, css: TASKBAR_CSS, body: TASKBAR, hl: ['#am'] }), x: 90, scale: 1.1 }],
    step: 1, text: 'AM-Tray(통합 SSO)는 작업 표시줄 오른쪽 아래 파란 "A" 아이콘입니다', label: L,
    note: { x: 960, y: 170, w: 420, html: `<div class="t">AM-Tray 란</div>사내 통합 SSO 프로그램입니다. PC 녹음 앱은 <b>AM-Tray 로그인 정보로</b> 로그인합니다.<br><br>아이콘: <b>파란 동그라미 안의 흰 "A"</b><br>안 보이면 작업 표시줄의 <b>^</b>(숨겨진 아이콘)를 눌러 보세요.` },
  }, 3.5);

  // 2. 방법 ① AM-Tray 먼저 → 앱 실행하면 자동 로그인
  await shot('02-2_auto-login', {
    wins: [{ shot: await loginV2({ cfg: { am: { auto: 'hang' } }, hl: ['#amCard'] }), x: 260 }],
    step: 2, text: '방법 ① AM-Tray 에 로그인되어 있으면 앱을 켜는 것만으로 로그인됩니다', label: L,
    note: { x: 880, y: 250, w: 440, html: `<div class="t">AM-Tray 먼저 로그인한 경우</div>앱을 실행하면 "${t('loginV2.checking')}" 가 잠깐 보인 뒤 <b>입력 없이</b> 다음 화면으로 넘어갑니다.` },
  }, 3);

  // 3. 방법 ② 앱 먼저 → [AM-Tray 로그인]
  await shot('02-3_need-login', {
    wins: [{ shot: await loginV2({ cfg: { am: { auto: AM.notLoggedIn } }, hl: ['#amPrimaryBtn'], cursor: '#amPrimaryBtn', click: true }), x: 260 }],
    step: 3, text: '방법 ② 앱을 먼저 켰다면 [AM-Tray 로그인]을 누릅니다', label: L,
    note: { x: 880, y: 250, w: 440, html: `<div class="t">AM-Tray 에 로그인되어 있지 않은 경우</div>"${t('loginV2.need_login_title')}" 가 보입니다.<br><b>[${t('loginV2.am_login_btn')}]</b> 을 누르면 브라우저에 로그인 창이 열립니다.` },
  }, 3);

  // 4. 브라우저 MyAccess 로그인
  const waiting = await loginV2({ cfg: { am: { auto: AM.notLoggedIn, show: AM.shown } }, before: async (p) => { await p.click('#amPrimaryBtn'); await p.mouse.move(1, 1); } });
  await shot('02-4_myaccess-login', {
    wins: [
      { shot: waiting, x: 60, y: 140, scale: 1.05 },
      { shot: await html({ w: 820, h: 560, css: BROWSER_CSS, body: MYACCESS, hl: ['#id', '#go'], cursor: '#go' }), x: 520, y: 70, scale: 1.0 },
    ],
    step: 4, text: '브라우저의 MyAccess SSO 로그인 창에서 아이디·비밀번호로 로그인합니다', label: L,
  }, 3.5);

  // 5. 앱으로 돌아오면 자동 / [다시 확인]
  await shot('02-5_back-to-app', {
    wins: [{ shot: await loginV2({ cfg: { am: { auto: AM.notLoggedIn, show: AM.shown } }, before: async (p) => { await p.click('#amPrimaryBtn'); await p.mouse.move(1, 1); }, hl: ['#amPrimaryBtn', '#amSecondaryBtn'] }), x: 260 }],
    step: 5, text: '로그인을 마치고 앱 창을 누르면 자동으로 넘어갑니다', label: L,
    note: { x: 880, y: 230, w: 450, html: `<div class="t">앱으로 돌아오기</div>브라우저 로그인을 마친 뒤 <b>앱 창을 한 번 누르면</b> 자동으로 로그인됩니다.<br><br>안 넘어가면 <b>[${t('loginV2.recheck_btn')}]</b><br>로그인 창을 닫아 버렸으면 <b>[${t('loginV2.reopen_btn')}]</b>` },
  }, 3.5);

  // 6. 로그인 완료
  await shot('02-6_login-done', {
    wins: [{ shot: await app({ file: 'index.html' }) }],
    step: 6, text: '로그인되면 녹음 준비(마이크 테스트) 화면으로 넘어갑니다', label: L,
  }, 2.5);

  gif(frames, GIF('02_login'));

  // ---- 이럴 때는 (GIF 에는 넣지 않음) ----
  await stage({
    wins: [
      { shot: await dialog({ title: t('amtray.install_title'), icon: ICON_WARN, message: t('amtray.install_message'), detail: t('amtray.install_detail'), buttons: [t('amtray.install_btn'), t('common.close')] }), x: 40, y: 200, scale: 1.0 },
      { shot: await html({ w: 820, h: 560, css: BROWSER_CSS, body: INSTALL_PAGE, hl: ['#dl'], cursor: '#dl' }), x: 540, y: 70, scale: 1.0 },
    ],
    step: 'A', text: 'AM-Tray 가 없으면 설치 안내 → [설치 페이지로 이동] → 설치 파일 받기', label: L,
  }, IMG('02-7_amtray-install'));

  await stage({
    wins: [
      { shot: await dialog({ title: t('amtray.denied_title'), icon: ICON_WARN, message: t('amtray.code_503032'), detail: '(코드 503032)', buttons: [t('common.ok')] }), x: 60, y: 140, scale: 1.25 },
      { shot: await dialog({ title: t('amtray.sso_title'), icon: ICON_ERR, message: t('amtray.sso_blocked'), detail: '(코드 502052)', buttons: [t('loginV2.retry_btn'), t('amtray.quit_btn')] }), x: 760, y: 140, scale: 1.25 },
    ],
    note: { x: 60, y: 470, w: 1300, html: `<b>왼쪽</b> 권한이 없거나 접근이 막힌 경우 — AM 이 준 문구를 그대로 보여 줍니다. [확인] 뒤에도 앱은 열려 있고, 로그인 화면에 같은 문구와 [다시 시도]가 남습니다. 담당자에게 문의하세요.<br><b>오른쪽</b> AM-Tray 로그인 창을 열 수 없는 경우 — [다시 시도]는 로그인 창을 다시 엽니다.` },
    step: 'B', text: '로그인할 수 없을 때 나오는 안내 (예시)', label: L,
  }, IMG('02-8_amtray-errors'));

  await stage({
    wins: [
      { shot: await dialog({ title: t('amtray.logout_title'), icon: ICON_WARN, message: t('amtray.logout_message'), detail: t('amtray.logout_detail'), buttons: [t('amtray.logout_btn'), t('common.cancel')] }), x: 60, y: 140, scale: 1.25 },
      { shot: await dialog({ title: t('amtray.other_user_title'), icon: ICON_WARN, message: t('amtray.other_user_message'), detail: t('amtray.other_user_detail'), buttons: [t('amtray.logout_btn'), t('common.cancel')] }), x: 760, y: 140, scale: 1.25 },
    ],
    note: { x: 60, y: 470, w: 1300, html: `<b>왼쪽</b> 앱을 쓰는 중 AM-Tray 에서 로그아웃한 경우 — 창을 다시 누르거나 녹음을 시작할 때 확인합니다.<br><b>오른쪽</b> 녹음을 시작할 때 AM-Tray 사용자가 바뀐 것을 확인한 경우.<br>녹음·업로드 중에는 묻지 않고, 끝난 뒤에 묻습니다.` },
    step: 'C', text: '쓰는 중에 AM-Tray 로그아웃·사용자 변경을 확인했을 때 (예시)', label: L,
  }, IMG('02-9_amtray-logout'));

  // 약관·권한 안내(로그인 화면 ver2)
  await stage({
    wins: [{ shot: await loginV2({ cfg: { termsNotice: true }, hl: ['#termsModal .terms-box'] }), x: 260 }],
    step: 'D', text: '약관에 동의하지 않은 사용자는 로그인되지 않고 안내 팝업이 뜹니다', label: L,
    note: { x: 880, y: 230, w: 450, html: '<div class="t">약관 안내</div>링크(AI 회의록 시스템)를 누르면 브라우저가 열립니다. PC에서 약관에 동의한 뒤 다시 로그인하세요.<br><br><b>이전에 동의한 사용자도 재동의가 필요합니다.</b>' },
  }, IMG('02-10_terms-notice'));

  await stage({
    wins: [{ shot: await loginV2({ cfg: { accessNotice: true }, hl: ['#accessModal .terms-box'], cursor: '#accessOkBtn' }), x: 260 }],
    step: 'E', text: 'AI회의록 이용 권한이 없으면 안내 팝업이 뜨고, [확인]을 누르면 앱이 종료됩니다', label: L,
    note: { x: 880, y: 230, w: 450, html: '<div class="t">권한 안내</div><b>myAccess</b> 에서 AI회의록 권한을 승인받은 뒤 다시 실행해 로그인하세요.<br><br><span style="color:#6b7280;font-size:15px">권한 확인 API 는 서버에서 준비 중입니다. 적용 전에는 확인 없이 로그인됩니다.</span>' },
  }, IMG('02-11_access-denied'));

  // 로그인 만료(11-28) — 토큰 갱신·AM-Tray 자동 재로그인까지 안 될 때
  await stage({
    wins: [
      { shot: await dialog({ title: t('auth.expired_title'), icon: ICON_WARN, message: t('auth.expired_message'), detail: t('auth.expired_detail'), buttons: [t('auth.relogin_btn')] }), x: 60, y: 140, scale: 1.25 },
      { shot: await dialog({ title: t('auth.expired_title'), icon: ICON_WARN, message: t('auth.expired_message'), detail: t('auth.expired_after_recording_detail'), buttons: [t('common.ok')] }), x: 760, y: 140, scale: 1.25 },
    ],
    note: { x: 60, y: 470, w: 1300, html: `<b>왼쪽</b> 마이크 테스트 화면에서 로그인이 만료된 경우 — [다시 로그인]을 누르면 로그인 화면으로 가고, AM-Tray 로그인을 다시 확인합니다.<br><b>오른쪽</b> 녹음 중에 만료된 경우 — 녹음은 끊기지 않습니다. 녹음을 마치고 돌아오면 안내가 뜹니다. 다시 로그인한 뒤 업로드 목록에서 다시 보냅니다.<br>보통은 앱이 AM-Tray 로 알아서 다시 로그인하므로 이 안내가 뜨지 않습니다.` },
    step: 'F', text: '로그인이 만료되었을 때 (예시)', label: L,
  }, IMG('02-12_session-expired'));

  await close();
  console.log('done');
})().catch((e) => { console.error(e); process.exit(1); });
