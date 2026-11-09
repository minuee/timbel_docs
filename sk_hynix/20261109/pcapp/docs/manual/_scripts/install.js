// 1장 "앱 받기" 장면 — 회의록 웹에서 PC앱 설치 파일을 받는 흐름.
//   node install.js   → docs/manual/img/01-0*.png, docs/manual/gif/01_install.gif
// 웹의 선택창·설치 안내창은 아직 개발 전이라 웹 화면(docs/web-integration/img/00_web-record-button.png) 위에
// 예시로 그린다. 실제 웹 화면이 나오면 다시 찍는다. Windows 설치 마법사는 Windows PC 에서 따로 캡처한다.
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');
const { stage, gif, close } = require('./lib');

const OUT = path.resolve(__dirname, '..');
const IMG = (name) => path.join(OUT, 'img', `${name}.png`);
const WEB_BG = path.resolve(__dirname, '../../web-integration/img/00_web-record-button.png');
const W = 880;
const H = 522;
const LABEL = '회의록 웹 (예시 화면)';

const ICON_WEB = '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 2.5 15.3 0 18M12 3c-2.5 2.7-2.5 15.3 0 18"/></svg>';
const ICON_PC = '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="1.8"><rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20h8M12 16v4"/><circle cx="12" cy="10" r="2.2" fill="#ef4444" stroke="none"/></svg>';

const MODALS = {
  choose: `
    <div class="modal" style="width:440px">
      <div class="mt">녹음 방식 선택</div>
      <div class="ms">어떤 방법으로 녹음할지 선택해 주세요.</div>
      <div class="choices">
        <div class="choice" id="web">${ICON_WEB}<b>웹에서 녹음</b><span>브라우저에서 바로 녹음</span></div>
        <div class="choice" id="pc">${ICON_PC}<b>PC앱으로 녹음</b><span>설치형 녹음 앱으로 녹음</span></div>
      </div>
    </div>`,
  guide: `
    <div class="modal" style="width:440px">
      <div class="mt">PC앱 설치가 필요합니다</div>
      <div class="ms">이 PC에 녹음 앱이 설치되어 있지 않은 것 같습니다.<br>설치 파일을 받아 설치한 뒤 다시 [PC앱으로 녹음]을 눌러 주세요.</div>
      <div class="btns">
        <div class="btn sub" id="retry">이미 설치했어요 · 다시 열기</div>
        <div class="btn main" id="download">설치 파일 받기</div>
      </div>
    </div>`,
};

let browser;
// 웹 화면 위에 (선택) 모달을 얹어 찍는다. lib.stage 가 쓰는 shot 형태로 돌려준다.
async function webShot({ modal, hl = [], cursor, click = false }) {
  if (!browser) browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 2 });
  const bg = 'data:image/png;base64,' + fs.readFileSync(WEB_BG).toString('base64');
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap">
<style>
*{box-sizing:border-box;margin:0}
body{width:${W}px;height:${H}px;position:relative;overflow:hidden;font-family:'Noto Sans KR',sans-serif;background:#fff url(${bg}) 0 0/${W}px ${H}px no-repeat}
#rec{position:absolute;left:62px;top:2px;width:46px;height:64px}
.dim{position:absolute;inset:0;background:rgba(17,24,39,.45);display:flex;align-items:center;justify-content:center}
.modal{background:#fff;border-radius:14px;padding:24px 24px 22px;box-shadow:0 20px 50px rgba(0,0,0,.25);color:#1f2937}
.mt{font-size:18px;font-weight:700;margin-bottom:6px}
.ms{font-size:13px;color:#6b7280;line-height:1.6;margin-bottom:18px}
.choices{display:flex;gap:12px}
.choice{flex:1;border:1.5px solid #e5e7eb;border-radius:12px;padding:18px 10px 16px;display:flex;flex-direction:column;align-items:center;gap:6px}
.choice b{font-size:15px}
.choice span{font-size:12px;color:#6b7280}
.btns{display:flex;gap:8px;justify-content:flex-end}
.btn{font-size:13px;font-weight:500;padding:9px 14px;border-radius:8px}
.btn.sub{border:1px solid #d1d5db;color:#374151}
.btn.main{background:#ef4444;color:#fff}
</style></head><body><div id="rec"></div>${modal ? `<div class="dim">${MODALS[modal]}</div>` : ''}</body></html>`);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  const box = async (sel) => {
    const r = await page.locator(sel).first().boundingBox();
    return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null;
  };
  const boxes = [];
  for (const s of hl) { const r = await box(s); if (r) boxes.push(r); }
  let cur = null;
  if (cursor) { const r = await box(cursor); if (r) cur = { x: r.x + r.w * 0.55, y: r.y + r.h * 0.6 }; }
  const png = await page.screenshot({ type: 'png' });
  await page.close();
  return { png, w: W, h: H, boxes, cursor: cur, click };
}

(async () => {
  const frames = [];
  const shot = async (name, spec, sec) => {
    frames.push({ file: await stage(spec, IMG(name)), sec });
  };

  await shot('01-0a_web-record', {
    wins: [{ shot: await webShot({ hl: ['#rec'], cursor: '#rec', click: true }) }],
    step: 1, text: '회의록 웹 왼쪽 위 [녹음]을 누릅니다', label: LABEL,
  }, 2.5);

  await shot('01-0b_choose-pcapp', {
    wins: [{ shot: await webShot({ modal: 'choose', hl: ['#pc'], cursor: '#pc', click: true }) }],
    step: 2, text: '[PC앱으로 녹음]을 누릅니다 — 앱이 설치되어 있으면 바로 열립니다', label: LABEL,
  }, 3);

  await shot('01-0c_install-guide', {
    wins: [{ shot: await webShot({ modal: 'guide', hl: ['#download'], cursor: '#download', click: true }) }],
    step: 3, text: '설치되어 있지 않으면 안내창이 뜹니다 — [설치 파일 받기]', label: LABEL,
  }, 3);

  await shot('01-0d_run-installer', {
    wins: [{ shot: await webShot({ modal: 'guide', hl: ['#retry'] }), x: 40, scale: 1.05 }],
    note: {
      x: 990, y: 210, w: 410,
      html: `<div class="t">설치 파일 실행</div>
① 다운로드 폴더의<br><b>SKHynixRecApp-Setup-latest.exe</b> 실행<br>
② 설치 마법사를 끝까지 진행<br>
③ 웹으로 돌아와 <b>[이미 설치했어요 · 다시 열기]</b><br>
→ 앱이 로그인된 상태로 열립니다`,
    },
    step: 4, text: '받은 설치 파일을 실행해 설치한 뒤, 다시 열기를 누릅니다', label: LABEL,
  }, 4);

  gif(frames, path.join(OUT, 'gif', '01_install.gif'));
  if (browser) await browser.close();
  await close();
  console.log('done:', frames.map((f) => path.basename(f.file)).join(', '));
})();
