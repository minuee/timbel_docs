// 6장 "업로드 실패 → 재시도" 장면.
//   node retry.js   → docs/manual/img/06-6*.png, docs/manual/gif/06b_retry.gif
// 업로드 리스트(실패 목록)에서 [재시도] → 확인 → 업로드 중 → 완료 알림까지.
const path = require('path');
const { app, stage, gif, close, KO } = require('./lib');

const OUT = path.resolve(__dirname, '..');
const IMG = (name) => path.join(OUT, 'img', `${name}.png`);
const L = '6. 업로드 실패 → 재시도';

// scenes.js 와 같은 촬영 도우미
const recording = (o = {}) => app({
  file: 'pages/recordingWindow.html', w: 360, h: 320, autoSize: false, ...o,
  before: async (page) => {
    await page.waitForTimeout(500);
    await page.evaluate((sec) => { startTime = Date.now() - sec * 1000; }, 754);
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
const uploadList = (jobs, o = {}) => app({
  file: 'pages/uploadList.html', w: 479, h: 470, autoSize: false, ...o,
  before: async (p) => { await p.evaluate((j) => window.__emit('upload-list-open', j), jobs); },
});

const FAILED = [
  { job_id: 2, file_name: '프로젝트 점검 회의', recording_created_at: '2026-10-28 14:30:12', is_uploading: false },
  { job_id: 3, file_name: '고객사 요구사항 검토', recording_created_at: '2026-10-27 09:05:40', is_uploading: false },
];
const LIST = { x: 130, y: 130, scale: 1.3 };
const REC = { x: 760, y: 130, scale: 1.3 };

(async () => {
  const frames = [];
  const shot = async (name, spec, sec) => { frames.push({ file: await stage(spec, IMG(name)), sec }); };

  const rec1 = await recording({ hl: ['#upload-list-btn'], cursor: '#upload-list-btn', click: true });
  await shot('06-6a_open-list', {
    wins: [{ shot: rec1, x: 170, y: 130, scale: 1.5 }], step: 1, text: '녹음 화면 오른쪽 위 파일 아이콘 → 업로드 리스트', label: L,
    note: { x: 820, y: 200, w: 500, html: '<div class="t">업로드에 실패하면</div>네트워크·서버 오류로 업로드에 실패한 녹음은 <b>PC에 그대로 남아</b> 업로드 리스트에 보입니다. 여기서 다시 올릴 수 있습니다.' },
  }, 3);

  const ul2 = await uploadList(FAILED, { hl: ['.upload-list-item:first-child .retry-btn'], cursor: '.upload-list-item:first-child .retry-btn', click: true });
  await shot('06-6b_retry-click', {
    wins: [{ shot: ul2, ...LIST }],
    step: 2, text: '실패한 항목(빨간 아이콘)의 [재시도]를 누릅니다', label: L,
    note: { x: 820, y: 250, w: 480, html: '<b>회의명·회의시간</b>으로 어떤 녹음인지 확인하세요.<br>필요 없는 녹음은 휴지통 아이콘으로 지웁니다.' },
  }, 3);

  const conf = { width: 360, height: 200, type: 'confirm-retry-multi', title: KO['upload_list.retry_title'], subtitle: KO['upload_list.retry_subtitle'], data: [FAILED[0]] };
  const p3 = await popup(conf, { cursor: '#confirmBtn', click: true });
  await shot('06-6c_confirm', {
    wins: [{ shot: ul2, ...LIST }, { shot: p3, scale: 1.5, x: 790, y: 300 }],
    step: 3, text: '“업로드를 하시겠습니까?” → [확인]', label: L,
  }, 2.5);

  const uploading = [{ ...FAILED[0], is_uploading: true }, FAILED[1]];
  const ul4 = await uploadList(uploading, { hl: ['.upload-list-item:first-child .item-status'] });
  await shot('06-6d_uploading', {
    wins: [{ shot: ul4, ...LIST }],
    step: 4, text: '리스트에 “업로드 중”으로 바뀌고 뒤에서 올라갑니다', label: L,
    note: { x: 820, y: 250, w: 480, html: '업로드는 뒤에서 진행됩니다.<br><b>끝날 때까지 앱을 끄지 마세요.</b>' },
  }, 3);

  const ul5 = await uploadList([FAILED[1]]);
  await shot('06-6e_done', {
    wins: [{ shot: ul5, ...LIST }],
    step: 5, text: '완료되면 알림이 뜨고 리스트에서 사라집니다', label: L,
    note: {
      x: 820, y: 200, w: 500,
      html: `<div class="t">${KO['notify.upload_done_title']}</div>${KO['notify.upload_success_one'].replace('{name}', FAILED[0].file_name)}<br><br>
<span style="font-size:15px;color:#4b5563">화면 오른쪽 아래 Windows 알림으로 표시됩니다. 결과는 AI 회의록 웹에서 확인합니다.<br>
다시 실패하면 리스트에 남아 있으니 다시 [재시도] 하세요.</span>`,
    },
  }, 3.5);

  gif(frames, path.join(OUT, 'gif', '06b_retry.gif'));
  await close();
  console.log('done:', frames.map((f) => path.basename(f.file)).join(', '));
})();
