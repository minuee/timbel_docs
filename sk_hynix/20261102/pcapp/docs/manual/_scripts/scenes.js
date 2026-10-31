// 매뉴얼 장면 목록 — 실행하면 docs/manual/img/*.png, docs/manual/gif/*.gif 를 다시 만든다.
//   node scenes.js            전체
//   node scenes.js 05 06      해당 장만
// 화면 문구는 src/locales/*.json 그대로, 사번·이름·장치 이름·템플릿은 예시 값(lib.js BASE_CFG).
const path = require('path');
const { app, stage, gif, close, KO } = require('./lib');

const OUT = path.resolve(__dirname, '..');
const IMG = (name) => path.join(OUT, 'img', `${name}.png`);
const GIF = (name) => path.join(OUT, 'gif', `${name}.gif`);
const only = process.argv.slice(2);
const want = (ch) => only.length === 0 || only.includes(ch);

// --- 화면별 촬영 도우미 ---
const login = (o = {}) => app({ file: 'pages/login.html', ...o });
const micTest = (o = {}) => app({ file: 'index.html', ...o });
// 녹음 화면: 들어오자마자 녹음이 시작된다. elapsed(초)만큼 진행된 것처럼 시계를 돌려 둔다
const recording = (o = {}) => app({
  file: 'pages/recordingWindow.html', w: 360, h: 320, autoSize: false, ...o,
  before: async (page) => {
    await page.waitForTimeout(500);
    await page.evaluate((sec) => { startTime = Date.now() - sec * 1000; }, o.elapsed ?? 754);
    await page.waitForTimeout(1200);
    if (o.before) await o.before(page);
  },
});
const popup = (options, o = {}) => app({
  file: 'pages/popupWindow.html', w: options.width, h: options.height, autoSize: false, ...o,
  before: async (page) => {
    await page.evaluate((opt) => window.__emit('popup-window-loaded', opt), options);
    if (o.before) await o.before(page);
  },
});
const lastPopupCall = (page) => page.evaluate(() => {
  const c = window.__calls.filter((x) => x[0] === 'openPopupWindow').pop();
  return c ? c[1] : null;
});

// 창 배치 (1440x900 무대, 아래 70px 은 설명 줄)
const REC_LEFT = { x: 170, y: 130, scale: 1.5 };

(async () => {
  // =========================================================
  // 01 설치와 첫 실행
  // =========================================================
  if (want('01')) {
    const s = await login();
    await stage({
      wins: [{ shot: s, x: 260 }], step: 1, text: '설치 후 처음 실행하면 로그인 화면이 나타납니다', label: '1. 설치와 첫 실행',
      note: { x: 880, y: 250, w: 440, html: '<div class="t">처음 실행</div>바탕화면·시작 메뉴의 <b>SKHynixRecApp</b> 아이콘으로 실행합니다.<br>로그인 상태가 아니면 항상 이 화면부터 시작합니다.' },
    }, IMG('01-1_first-launch'));
  }

  // =========================================================
  // 02 로그인
  // =========================================================
  if (want('02')) {
    const L = '2. 로그인';
    const s1 = await login({ hl: ['#empnoForm', '#ssoBtn', '#systemLoginBtn'] });
    await stage({
      wins: [{ shot: s1, x: 220 }], step: 1, text: '로그인 방법은 3가지입니다', label: L,
      note: { x: 860, y: 190, w: 480, html: '<div class="t">로그인 방법</div>① <b>사번·비밀번호</b> — 앱에서 바로 입력<br>② <b>MyAccess 로그인</b> — 브라우저에서 사내 계정으로<br>③ <b>시스템 로그인</b> — PC(Windows) 로그인 정보로 자동 <span style="color:#6b7280">(SSO 엔진 연동 예정)</span><br><br><span style="color:#6b7280;font-size:15px">세 방법은 관리자 설정으로 각각 켜고 끌 수 있습니다.</span>' },
    }, IMG('02-1_login-methods'));

    const s2 = await login({
      before: async (p) => { await p.fill('#empnoInput', '2026001'); await p.fill('#passwordInput', 'password'); await p.locator('#passwordInput').blur(); },
      cursor: '#empnoSubmitBtn', click: true, hl: ['#empnoSubmitBtn'],
    });
    await stage({ wins: [{ shot: s2 }], step: 2, text: '① 사번·비밀번호를 입력하고 [로그인]을 누릅니다', label: L }, IMG('02-2_login-empno'));

    const s3 = await login({ before: async (p) => { await p.click('#ssoBtn'); await p.mouse.move(1, 1); }, cursor: '#ssoBtn', click: true, hl: ['#ssoBtn'] });
    await stage({
      wins: [{ shot: s3, x: 260 }], step: 3, text: '② [MyAccess 로그인] → 브라우저에서 로그인하면 앱으로 자동 복귀', label: L,
      note: { x: 880, y: 260, w: 440, html: '<div class="t">MyAccess 로그인</div>PC 기본 브라우저에 MyAccess 로그인 화면이 열립니다.<br>로그인을 마치면 브라우저가 앱을 호출해 <b>자동으로 다음 화면</b>으로 넘어갑니다.' },
    }, IMG('02-3_login-myaccess'));

    const s4 = await login({ before: async (p) => { await p.click('#systemLoginBtn'); await p.mouse.move(1, 1); }, cursor: '#systemLoginBtn', click: true, hl: ['#systemLoginBtn'] });
    await stage({
      wins: [{ shot: s4, x: 260 }], step: 4, text: '③ [시스템 로그인] — PC 로그인 정보로 입력 없이 로그인 (연동 예정)', label: L,
      note: { x: 880, y: 250, w: 450, html: '<div class="t">시스템 로그인</div>사내 SSO 엔진(트레이 에이전트)에서 Windows 로그인 정보를 받아 <b>입력 없이</b> 로그인합니다.<br><br><span style="color:#6b7280;font-size:15px">현재는 화면만 준비되어 있어 “준비 중” 안내가 나옵니다. SSO 엔진 연동 자료를 받으면 적용합니다.</span>' },
    }, IMG('02-4_login-system'));

    const s5 = await micTest();
    await stage({ wins: [{ shot: s5 }], step: 5, text: '로그인되면 녹음 준비(마이크 테스트) 화면으로 넘어갑니다', label: L }, IMG('02-5_login-done'));

    const s6 = await login({ cfg: { termsNotice: true }, hl: ['.terms-note'] });
    await stage({
      wins: [{ shot: s6, x: 260 }], step: 6, text: '약관에 동의하지 않은 사용자는 안내 팝업이 뜨고 로그아웃됩니다', label: L,
      note: { x: 880, y: 230, w: 450, html: '<div class="t">약관 안내</div>링크(AI 회의록 시스템)를 누르면 브라우저가 열립니다. PC에서 약관에 동의한 뒤 다시 로그인하세요.<br><br><b>이전에 동의한 사용자도 재동의가 필요합니다.</b>' },
    }, IMG('02-6_terms-notice'));

    gif([
      { file: IMG('02-1_login-methods'), sec: 3.5 },
      { file: IMG('02-2_login-empno'), sec: 2.5 },
      { file: IMG('02-3_login-myaccess'), sec: 3 },
      { file: IMG('02-4_login-system'), sec: 3 },
      { file: IMG('02-5_login-done'), sec: 2.5 },
    ], GIF('02_login'));
  }

  // =========================================================
  // 03 녹음 준비 (마이크 테스트)
  // =========================================================
  if (want('03')) {
    const L = '3. 녹음 준비';
    const s1 = await micTest({ hl: ['#mode-select', '#mic-select', '#micMeter', '#sysMeter', '#render-select'] });
    await stage({
      wins: [{ shot: s1, x: 230 }], step: 1, text: '녹음 대상·마이크를 고르고 소리 막대가 움직이는지 확인합니다', label: L,
      note: { x: 860, y: 150, w: 480, html: '<div class="t">마이크 테스트 화면</div><b>녹음 대상</b> — 무엇을 녹음할지 (4장 참고)<br><b>마이크</b> — 사용할 마이크 선택, 파란 막대가 내 목소리<br><b>시스템 사운드</b> — 노란 막대가 PC에서 나오는 소리<br><b>출력 장치</b> — 회의 소리가 나오는 스피커 (Windows)<br><br><span style="color:#6b7280;font-size:15px">막대가 움직이지 않으면 장치 연결·음소거를 확인하세요.</span>' },
    }, IMG('03-1_mic-test'));

    const s2 = await micTest({
      before: async (p) => { await p.hover('.sound-text .help-icon >> nth=0'); await p.waitForTimeout(300); },
      cursor: '.help-icon >> nth=0',
    });
    await stage({ wins: [{ shot: s2 }], step: 2, text: '? 아이콘에 마우스를 올리면 설명이 나옵니다', label: L }, IMG('03-2_help-tooltip'));

    const s3 = await micTest({
      before: async (p) => { await p.check('#check'); },
      cursor: '#start-recording-btn', hl: ['.check-box-group', '#start-recording-btn'],
    });
    await stage({
      wins: [{ shot: s3, x: 260 }], step: 3, text: '안내를 확인하고 체크하면 녹음 버튼이 켜집니다 → 눌러서 녹음 시작', label: L,
      note: { x: 880, y: 250, w: 440, html: '<div class="t">녹음 전 확인</div>· 참석자에게 녹음 동의를 받아 주세요<br>· 최대 녹음 시간은 <b>3시간</b><br>· 저장 공간이 부족하면 녹음이 실패할 수 있어요<br><br>체크하지 않으면 녹음을 시작할 수 없습니다.' },
    }, IMG('03-3_agree-start'));

    gif([
      { file: IMG('03-1_mic-test'), sec: 3.5 },
      { file: IMG('03-2_help-tooltip'), sec: 2.5 },
      { file: IMG('03-3_agree-start'), sec: 3 },
    ], GIF('03_ready'));
  }

  // =========================================================
  // 04 녹음 대상 3가지
  // =========================================================
  if (want('04')) {
    const L = '4. 녹음 대상 3가지';
    const modes = [
      { mode: 'MicPlusSystem', file: '04-1_mode-mic-plus-system', levels: { mic: 0.35, system: 0.2 },
        text: '내 목소리 + 회의 소리 — 마이크와 PC 소리를 함께 녹음 (기본)',
        note: '<div class="t">내 목소리 + 회의 소리</div>마이크(내 목소리)와 PC에서 나오는 소리(화상회의 상대방)를 <b>함께</b> 녹음합니다.<br><br>대면 회의 + 온라인 참석자가 섞인 회의에 알맞습니다.' },
      { mode: 'MicOnly', file: '04-2_mode-mic-only', levels: { mic: 0.35, system: 0 },
        text: '내 목소리만 — 마이크 소리만 녹음',
        note: '<div class="t">내 목소리만</div><b>마이크 소리만</b> 녹음합니다. PC에서 나오는 소리(알림음·음악 등)는 녹음되지 않습니다.<br><br>회의실 대면 회의에 알맞습니다.' },
      { mode: 'SystemOnly', file: '04-3_mode-system-only', levels: { mic: 0.35, system: 0.25 },
        text: '회의 소리만 (상대방) — PC에서 나오는 소리만 녹음',
        note: '<div class="t">회의 소리만 (상대방)</div>Zoom·Webex·Teams 등에서 나오는 <b>상대방 목소리만</b> 녹음하고, 내 목소리는 빠집니다.<br><br>여러 참석자의 녹음을 나중에 하나로 합칠 때 사용합니다. 마이크는 시간 맞춤용으로만 씁니다.' },
    ];
    for (const [i, m] of modes.entries()) {
      const s = await micTest({ storage: { captureMode: m.mode }, cfg: { levels: m.levels }, hl: ['#mode-select', ...(m.mode === 'SystemOnly' ? ['#modeHint'] : [])] });
      await stage({ wins: [{ shot: s, x: 230 }], step: i + 1, text: m.text, label: L, note: { x: 860, y: 230, w: 480, html: m.note } }, IMG(m.file));
    }
    gif(modes.map((m) => ({ file: IMG(m.file), sec: 3.5 })), GIF('04_capture-modes'));
  }

  // =========================================================
  // 05 녹음 중
  // =========================================================
  if (want('05')) {
    const L = '5. 녹음 중';
    const s1 = await recording({ hl: ['.left-info', '.progress-time', '#upload-list-btn'] });
    await stage({
      wins: [{ shot: s1, ...REC_LEFT }], step: 1, text: '녹음이 바로 시작됩니다 — 진행 시간·남은 시간·소리 막대 확인', label: L,
      note: { x: 820, y: 140, w: 520, html: '<div class="t">녹음 화면</div><b>진행 시간</b> — 빨간 점이 깜빡이면 녹음 중<br><b>남은 시간</b> — 최대 3시간, 시간이 줄면 막대 색이 바뀜<br><b>마이크·스피커 아이콘</b> — 누르면 각각 음소거<br><b>업로드 리스트</b> — 오른쪽 위 아이콘<br><b>파형</b> — 소리가 들어오면 움직임<br><br><span style="color:#6b7280;font-size:15px">녹음 중에도 다른 프로그램을 쓸 수 있습니다. (최소화 가능)</span>' },
    }, IMG('05-1_recording'));

    const s2 = await recording({ before: async (p) => { await p.click('#pause-btn'); await p.evaluate(() => window.__calls.length = 0); }, cursor: '#pause-btn', hl: ['#pause-btn'] });
    await stage({ wins: [{ shot: s2 }], step: 2, text: '가운데 버튼으로 일시정지 / 다시 누르면 이어서 녹음', label: L }, IMG('05-2_pause'));

    const s3 = await recording({ cfg: { levels: { mic: 0.001, system: 0 } }, before: async (p) => { await p.evaluate(() => setNoti('sustained')); }, hl: ['.noti-area'] });
    await stage({
      wins: [{ shot: s3, ...REC_LEFT }], step: 3, text: '소리가 들어오지 않으면 안내 문구가 바뀝니다', label: L,
      note: { x: 820, y: 260, w: 500, html: '<div class="t">음성 감지 알림</div>소리가 감지되지 않으면 빨간 안내가 나옵니다. <b>30초 이상</b> 계속되면 창을 내려 두었을 때 Windows 알림도 띄웁니다.<br><br>마이크 연결·음소거·소리 설정을 확인하세요.' },
    }, IMG('05-3_silence'));

    const s4 = await recording({ before: async (p) => { await p.locator('#settingBtn').click(); await p.locator('#alwaysOnTab').hover(); await p.waitForTimeout(500); await p.click('#aot-item-1'); await p.mouse.move(5, 300); }, hl: ['#topBtn', '#micIcon', '#sysIcon'] });
    await stage({
      wins: [{ shot: s4, ...REC_LEFT }], step: 4, text: '항상 위·음소거는 아이콘으로 바로 켜고 끌 수 있습니다', label: L,
      note: { x: 820, y: 240, w: 500, html: '<div class="t">빠른 버튼</div><b>핀 아이콘</b>(오른쪽 위) — 항상 위: 다른 창에 가려지지 않음<br><b>마이크 아이콘</b> — 내 목소리 음소거<br><b>스피커 아이콘</b> — 회의 소리 음소거<br><br><span style="color:#6b7280;font-size:15px">같은 기능을 설정 메뉴(7장)에서도 쓸 수 있습니다.</span>' },
    }, IMG('05-4_quick-buttons'));

    // 녹음 취소 → 삭제 확인
    let opt;
    const s5 = await recording({ before: async (p) => { await p.click('#recordCancelBtn'); opt = await lastPopupCall(p); }, cursor: '#recordCancelBtn', click: true });
    const p5 = await popup(opt, { cursor: '#confirmBtn' });
    await stage({ wins: [{ shot: s5, ...REC_LEFT }, { shot: p5, scale: 1.5, x: 760, y: 300 }], step: 5, text: '[녹음 취소] — 확인을 누르면 녹음 파일을 삭제합니다 (복구 불가)', label: L }, IMG('05-5_cancel'));

    gif([
      { file: IMG('05-1_recording'), sec: 3.5 },
      { file: IMG('05-2_pause'), sec: 2.5 },
      { file: IMG('05-3_silence'), sec: 3 },
      { file: IMG('05-4_quick-buttons'), sec: 3 },
      { file: IMG('05-5_cancel'), sec: 3 },
    ], GIF('05_recording'));
  }

  // =========================================================
  // 06 녹음 종료와 업로드
  // =========================================================
  if (want('06')) {
    const L = '6. 종료와 업로드';
    let opt;
    const s1 = await recording({ before: async (p) => { await p.click('#recordCompleteBtn'); opt = await lastPopupCall(p); }, cursor: '#recordCompleteBtn', click: true });
    const p1 = await popup(opt, { cursor: '#confirmBtn', click: true });
    await stage({ wins: [{ shot: s1, ...REC_LEFT }, { shot: p1, scale: 1.5, x: 760, y: 300 }], step: 1, text: '[녹음 종료] → “파일을 업로드 할까요?”에서 [확인]', label: L }, IMG('06-1_complete'));

    const sum = await app({
      file: 'pages/summarizeWindow.html', w: 560, h: 500, autoSize: false,
      before: async (p) => {
        await p.fill('#titleInput', '10월 주간 회의');
        await p.click('label[for=speaker2]');
        await p.waitForTimeout(200);
      },
      cursor: '#uploadBtn', click: true, hl: ['#titleInput', '.left-select', '.template-select'],
    });
    await stage({
      wins: [{ shot: sum, x: 120, y: 60, scale: 1.35 }], step: 2, text: 'AI 요약 준비 — 제목·요약 언어·발화자 수·템플릿을 고르고 [AI요약 시작]', label: L,
      note: { x: 920, y: 200, w: 440, html: '<div class="t">AI 요약 준비하기</div><b>제목</b> — 비워 두면 녹음 일시로 자동 이름<br><b>요약 언어</b> — 한국어·영어·일본어·중국어<br><b>발화자 수</b> — 회의 참석 인원<br><b>템플릿</b> — 서버에 등록된 요약 양식<br><br>[AI요약 시작]을 누르면 업로드가 시작됩니다.' },
    }, IMG('06-2_summarize'));

    const progOpt = { title: KO['popup.uploading_title'], subtitle: KO['popup.uploading_subtitle'], type: 'upload-progress', width: 370, height: 170 };
    const p3 = await popup(progOpt, {
      before: async (p) => {
        await p.evaluate(() => window.__emit('upload-progress', { percent: 46, speedReadable: '4.8MB/초', etaReadable: '12초 ' }));
        await p.waitForTimeout(1500);
      },
    });
    const rec3 = await recording({ before: async (p) => { await p.click('#recordCompleteBtn'); await p.mouse.move(1, 300); } });
    await stage({ wins: [{ shot: rec3, ...REC_LEFT }, { shot: p3, scale: 1.5, x: 760, y: 320 }], step: 3, text: '업로드가 진행됩니다 — 완료될 때까지 앱을 끄지 마세요', label: L }, IMG('06-3_uploading'));

    const p4 = await popup(progOpt, {
      before: async (p) => { await p.evaluate(() => window.__emit('upload-succeeded', {})); },
      cursor: '#confirmBtn',
    });
    await stage({
      wins: [{ shot: rec3, ...REC_LEFT }, { shot: p4, scale: 1.5, x: 760, y: 320 }], step: 4, text: '업로드 완료 — 결과는 AI 회의록(웹)에서 확인합니다', label: L,
      note: { x: 790, y: 120, w: 520, html: '업로드가 끝나면 서버에서 음성 인식·요약이 진행됩니다. 결과는 <b>AI 회의록 웹</b>에서 확인하세요. 녹음 버튼을 누르면 바로 다음 녹음을 시작할 수 있습니다.' },
    }, IMG('06-4_upload-done'));

    const jobs = [
      { job_id: 1, file_name: '10월 주간 회의', recording_created_at: '2026-10-29 10:00:00', is_uploading: true },
      { job_id: 2, file_name: '프로젝트 점검 회의', recording_created_at: '2026-10-28 14:30:12', is_uploading: false },
    ];
    const ul = await app({
      file: 'pages/uploadList.html', w: 479, h: 470, autoSize: false,
      before: async (p) => { await p.evaluate((j) => window.__emit('upload-list-open', j), jobs); },
      hl: ['.retry-btn'], cursor: '.retry-btn',
    });
    const rec5 = await recording({ hl: ['#upload-list-btn'] });
    await stage({
      wins: [{ shot: ul, x: 130, y: 130, scale: 1.3 }, { shot: rec5, x: 760, y: 130, scale: 1.3 }], step: 5, text: '업로드 리스트 — 실패한 파일은 [재시도], 필요 없으면 삭제', label: L,
      note: { x: 760, y: 590, w: 560, html: '녹음 화면 오른쪽 위 아이콘으로 엽니다. 네트워크 오류 등으로 <b>업로드에 실패한 녹음은 PC에 남아</b> 있으니 [재시도]로 다시 올리세요.' },
    }, IMG('06-5_upload-list'));

    gif([
      { file: IMG('06-1_complete'), sec: 3 },
      { file: IMG('06-2_summarize'), sec: 4 },
      { file: IMG('06-3_uploading'), sec: 2.5 },
      { file: IMG('06-4_upload-done'), sec: 3 },
      { file: IMG('06-5_upload-list'), sec: 3.5 },
    ], GIF('06_upload'));
  }

  // =========================================================
  // 07 설정 메뉴
  // =========================================================
  if (want('07')) {
    const L = '7. 설정 메뉴';
    const openMenu = async (p) => { await p.click('#settingBtn'); await p.waitForTimeout(300); };
    const s1 = await recording({ before: openMenu, hl: ['#settings-menu'], cursor: '#settingBtn' });
    await stage({
      wins: [{ shot: s1, ...REC_LEFT }], step: 1, text: '녹음 화면 왼쪽 위 톱니바퀴 → 설정 메뉴', label: L,
      note: { x: 820, y: 150, w: 520, html: '<div class="t">설정 메뉴</div><b>항상 위</b> — 창을 다른 창 위에 고정<br><b>음소거</b> — 마이크·회의 소리 한 번에<br><b>언어</b> — 화면 언어 (녹음 중이 아닐 때)<br><b>장치 변경</b> — 마이크 테스트 화면으로<br><b>로그아웃</b><br><b>버전 정보</b> — 앱·헬퍼 버전<br><b>앱 종료</b>' },
    }, IMG('07-1_menu'));

    const sub = async (tab) => async (p) => { await openMenu(p); await p.hover(tab); await p.waitForTimeout(500); };
    const s2 = await recording({ before: await sub('#alwaysOnTab'), hl: ['#settings-aot-items'], cursor: '#aot-item-1' });
    await stage({ wins: [{ shot: s2 }], step: 2, text: '항상 위 — 켜기 / 끄기', label: L }, IMG('07-2_always-on-top'));
    const s3 = await recording({ before: await sub('#muteTab'), hl: ['#settings-mute-items'], cursor: '#mute-item-1' });
    await stage({ wins: [{ shot: s3 }], step: 3, text: '음소거 — 마이크와 회의 소리를 한 번에 설정 / 해제', label: L }, IMG('07-3_mute'));

    // 언어: 녹음 중이 아닐 때만 바꿀 수 있다 → 녹음을 멈춘 상태로 찍는다
    const idle = async (p) => {
      await p.evaluate(() => {
        isRecording = false; isPaused = false; sessionId = null; stopRecordingTimer(); variableInitialize();
        recordingStatusCircle.classList.add('hidden');
        PauseBtnImg.src = '../assets/icons/recordingIcon.svg'; PauseBtnImg.style.width = '36px'; PauseBtnImg.style.height = '36px';
      });
    };
    const s4 = await recording({ before: async (p) => { await idle(p); await (await sub('#languageTab'))(p); }, hl: ['#settings-language-items'], cursor: '#settings-language-items button >> nth=1' });
    await stage({ wins: [{ shot: s4 }], step: 4, text: '언어 — 한국어 / English / 日本語 / 简体中文 (녹음 중이 아닐 때)', label: L }, IMG('07-4_language'));

    let opt;
    const s5 = await recording({ before: async (p) => { await openMenu(p); await p.hover('#languageTab'); await p.waitForTimeout(500); await p.click('#settings-language-items button >> nth=1'); await p.waitForTimeout(300); opt = await lastPopupCall(p); await p.mouse.move(1, 300); } });
    const p5 = opt ? await popup(opt) : null;
    await stage({ wins: [{ shot: s5, ...REC_LEFT }, ...(p5 ? [{ shot: p5, scale: 1.5, x: 760, y: 300 }] : [])], step: 5, text: '녹음 중에는 언어 변경·장치 변경·로그아웃을 막고 안내합니다', label: L }, IMG('07-5_busy'));

    const s6 = await recording({ before: async (p) => { await idle(p); await openMenu(p); await p.click('#logoutBtn'); opt = await lastPopupCall(p); } });
    const p6 = await popup(opt, { cursor: '#confirmBtn' });
    await stage({
      wins: [{ shot: s6, ...REC_LEFT }, { shot: p6, scale: 1.5, x: 760, y: 300 }], step: 6, text: '로그아웃 — 확인하면 로그인 화면으로 (업로드 리스트는 남음)', label: L,
    }, IMG('07-6_logout'));

    gif([
      { file: IMG('07-1_menu'), sec: 3.5 },
      { file: IMG('07-2_always-on-top'), sec: 2.2 },
      { file: IMG('07-3_mute'), sec: 2.2 },
      { file: IMG('07-4_language'), sec: 2.5 },
      { file: IMG('07-5_busy'), sec: 3 },
      { file: IMG('07-6_logout'), sec: 3 },
    ], GIF('07_settings'));
  }

  // =========================================================
  // 08 다국어 (녹음 전 확인 화면 4개 언어)
  // =========================================================
  if (want('08')) {
    const langs = [
      ['ko', '한국어'], ['en', 'English'], ['ja', '日本語'], ['zh-CN', '简体中文'],
    ];
    for (const [i, [code, name]] of langs.entries()) {
      const devCfg = code === 'ko' ? {} : {
        devices: [{ id: 'mic1', name: 'Microphone Array (Realtek(R) Audio)' }],
        renderDevices: [{ id: 'spk1', name: 'Speakers (Realtek(R) Audio)', isDefault: true }],
      };
      const s = await micTest({ lang: code, cfg: devCfg, hl: ['.check-section', '#languageSelectWrap'] });
      await stage({ wins: [{ shot: s }], step: i + 1, text: `화면 언어: ${name}`, label: '8. 다국어 (4개 언어)' }, IMG(`08-${i + 1}_lang-${code}`));
    }
  }

  // =========================================================
  // 09 자동 업데이트
  // =========================================================
  if (want('09')) {
    const L = '9. 자동 업데이트';
    const upd = (status) => app({
      file: 'pages/update.html', w: 380, h: 300, autoSize: false,
      before: async (p) => { await p.evaluate((s) => window.__emit('update-status', s), status); await p.waitForTimeout(500); },
    });
    const items = [
      [{ stage: 'downloading', version: '0.0.8', percent: 42 }, '09-1_update-download', '새 버전이 있으면 실행할 때 자동으로 내려받습니다',
        '<div class="t">자동 업데이트</div>앱을 켤 때 한 번 새 버전을 확인합니다. 새 버전이 있으면 이 화면이 나오고 <b>자동으로</b> 내려받습니다.<br><br><span style="color:#6b7280;font-size:15px">녹음 중에는 끼어들지 않고 다음 실행으로 미룹니다.</span>'],
      [{ stage: 'installing', version: '0.0.8', percent: 100 }, '09-2_update-install', '내려받기가 끝나면 설치 후 앱이 자동으로 다시 실행됩니다',
        '<div class="t">설치</div>잠시 앱이 꺼졌다 다시 켜집니다.<br>Windows <b>관리자 권한 확인 창</b>이 뜨면 [예]를 눌러 주세요.'],
      [{ stage: 'failed', version: '0.0.8', percent: 42 }, '09-3_update-failed', '실패해도 지금 버전으로 계속 쓸 수 있습니다',
        '<div class="t">업데이트 실패</div>네트워크 등으로 실패하면 잠시 안내 후 원래 화면으로 돌아갑니다. <b>다음 실행 때 다시 시도</b>합니다.'],
    ];
    for (const [i, [st, file, text, note]] of items.entries()) {
      const s = await upd(st);
      await stage({ wins: [{ shot: s, x: 230 }], step: i + 1, text, label: L, note: { x: 860, y: 260, w: 460, html: note } }, IMG(file));
    }
    gif(items.map(([, file]) => ({ file: IMG(file), sec: 3 })), GIF('09_update'));
  }

  await close();
  console.log('done');
})().catch(async (e) => { console.error(e); await close(); process.exit(1); });
