// 매뉴얼 촬영 공용 함수
// - app(): 앱 화면 하나(HTML)를 가짜 preload(mock.js)로 띄워 PNG 로 찍는다.
// - stage(): 찍은 창들을 1440x900 배경 위에 놓고 커서·강조 상자·하단 설명 줄을 그려 PNG 로 만든다.
// - gif(): stage PNG 여러 장을 슬라이드처럼 GIF 로 묶는다(ffmpeg).
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright-core');

const ROOT = path.resolve(__dirname, '../../..');
const RENDERER = path.join(ROOT, 'src/renderer');
const LOCALES = path.join(ROOT, 'src/locales');
const MOCK = fs.readFileSync(path.join(__dirname, 'mock.js'), 'utf8');
const STAGE_W = 1440;
const STAGE_H = 900;
const CAPTION_H = 70;

const LANGUAGES = [
  { code: 'ko', name: '한국어' },
  { code: 'en', name: 'English' },
  { code: 'ja', name: '日本語' },
  { code: 'zh-CN', name: '简体中文' },
];
const loc = (lang) => JSON.parse(fs.readFileSync(path.join(LOCALES, `${lang}.json`), 'utf8'));
const KO = loc('ko');

// 화면에 보이는 예시 값
const BASE_CFG = {
  languages: LANGUAGES,
  status: {
    authenticated: false, empnoLoginEnabled: true, systemLoginEnabled: true, manualLoginEnabled: false,
    keepLoginEnabled: true, loginPrefs: { rememberEmpno: false, keepLogin: true },
    termsAgreeUrl: 'https://aimeeting.skhynix.com/', profile: { name: '홍길동' },
  },
  devices: [
    { id: 'mic1', name: '마이크 배열(Realtek(R) Audio)' },
    { id: 'mic2', name: '헤드셋 마이크(USB Audio)' },
  ],
  renderDevices: [{ id: 'spk1', name: '스피커(Realtek(R) Audio)', isDefault: true }],
  templates: [
    { code: '', name: '기본형' },
    { code: 'T1', name: '회의록(안건·결정사항)' },
    { code: 'T2', name: '보고형 요약' },
  ],
  levels: { mic: 0.35, system: 0.2 },
};

let browser;
async function launch() {
  if (!browser) browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
  return browser;
}
async function close() { if (browser) await browser.close(); browser = null; }

function deepMerge(a, b) {
  const out = { ...a };
  for (const [k, v] of Object.entries(b || {})) {
    out[k] = v && typeof v === 'object' && !Array.isArray(v) && a[k] && typeof a[k] === 'object' ? deepMerge(a[k], v) : v;
  }
  return out;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 앱 화면 하나 찍기
// opts: { file, w, h, lang, cfg, storage, before(page), hl:[selector], cursor:selector|{x,y}, autoSize }
async function app(opts) {
  const b = await launch();
  const lang = opts.lang || 'ko';
  const cfg = deepMerge(BASE_CFG, { lang, messages: loc(lang), fallback: KO, ...(opts.cfg || {}) });
  if (opts.cfg && opts.cfg.status) cfg.status = deepMerge(BASE_CFG.status, opts.cfg.status);
  let w = opts.w || 380;
  let h = opts.h || 900;
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.warn('  [pageerror]', opts.file, e.message));
  const storage = opts.storage || {};
  await page.addInitScript(([c, s]) => {
    window.__MOCK_CFG = c;
    try { localStorage.clear(); Object.entries(s).forEach(([k, v]) => localStorage.setItem(k, v)); } catch (_) {}
  }, [cfg, storage]);
  await page.addInitScript(MOCK);
  await page.goto('file://' + path.join(RENDERER, opts.file));
  await page.evaluate(() => document.fonts.ready);
  await sleep(500);
  // 창 크기를 스스로 맞추는 화면(로그인·마이크 테스트)은 그 값으로 다시 맞춘다
  const resize = async () => {
    if (opts.autoSize === false) return;
    const size = await page.evaluate(() => window.__windowSize);
    if (size && size.height && (size.height !== h || size.width !== w)) {
      w = size.width || w; h = size.height;
      await page.setViewportSize({ width: w, height: h });
      await sleep(200);
    }
  };
  await resize();
  if (opts.before) { await opts.before(page); await sleep(400); }
  await resize();
  if (opts.h && opts.autoSize === false) { h = opts.h; }
  const box = async (sel) => {
    const r = await page.locator(sel).first().boundingBox();
    return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null;
  };
  const boxes = [];
  for (const s of opts.hl || []) { const r = await box(s); if (r) boxes.push(r); }
  let cursor = null;
  if (typeof opts.cursor === 'string') {
    const r = await box(opts.cursor);
    if (r) cursor = { x: r.x + r.w * 0.55, y: r.y + r.h * 0.6 };
  } else if (opts.cursor) cursor = opts.cursor;
  const png = await page.screenshot({ type: 'png' });
  await ctx.close();
  return { png, w, h, boxes, cursor, click: !!opts.click };
}

// 1440x900 배경 위에 창들을 놓는다
// spec: { wins:[{shot, x, y, scale}], step, text, label, note }
// 창 위치를 안 주면 가운데. 첫 창 기준 scale 기본 1.5 (높으면 줄인다)
async function stage(spec, outFile) {
  const b = await launch();
  const area = STAGE_H - CAPTION_H;
  const wins = spec.wins.map((wn, i) => {
    let scale = wn.scale || Math.min(1.5, (area - 80) / wn.shot.h);
    const W = wn.shot.w * scale;
    const H = wn.shot.h * scale;
    const x = wn.x !== undefined ? wn.x : (STAGE_W - W) / 2;
    const y = wn.y !== undefined ? wn.y : Math.max(30, (area - H) / 2);
    return { ...wn, scale, W, H, x, y, i };
  });
  let html = '';
  for (const wn of wins) {
    const src = 'data:image/png;base64,' + wn.shot.png.toString('base64');
    html += `<img class="win" src="${src}" style="left:${wn.x}px;top:${wn.y}px;width:${wn.W}px;height:${wn.H}px">`;
    for (const r of wn.shot.boxes) {
      const pad = 5;
      html += `<div class="hl" style="left:${wn.x + r.x * wn.scale - pad}px;top:${wn.y + r.y * wn.scale - pad}px;width:${r.w * wn.scale + pad * 2}px;height:${r.h * wn.scale + pad * 2}px"></div>`;
    }
    if (wn.shot.cursor) {
      const cx = wn.x + wn.shot.cursor.x * wn.scale;
      const cy = wn.y + wn.shot.cursor.y * wn.scale;
      if (wn.shot.click) html += `<div class="ring" style="left:${cx - 22}px;top:${cy - 22}px"></div>`;
      html += `<svg class="cur" style="left:${cx - 3}px;top:${cy - 2}px" width="26" height="34" viewBox="0 0 26 34"><path d="M2 2 L2 26 L8 20 L12.5 31 L17 29 L12.5 18.5 L21 18.5 Z" fill="#111" stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>`;
    }
  }
  if (spec.note) {
    const n = spec.note;
    html += `<div class="note" style="left:${n.x}px;top:${n.y}px;${n.w ? `width:${n.w}px;` : ''}">${n.html}</div>`;
  }
  const page = await b.newPage({ viewport: { width: STAGE_W, height: STAGE_H }, deviceScaleFactor: 1 });
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap">
<style>
*{box-sizing:border-box;margin:0}
body{width:${STAGE_W}px;height:${STAGE_H}px;position:relative;overflow:hidden;font-family:'Noto Sans KR',sans-serif;
 background:linear-gradient(135deg,#eef1f6 0%,#e3e8f0 55%,#eceff4 100%)}
.win{position:absolute;border-radius:10px;box-shadow:0 18px 50px rgba(20,30,50,.28),0 2px 8px rgba(20,30,50,.15)}
.hl{position:absolute;border:3px solid #f5a623;border-radius:10px;box-shadow:0 0 0 4px rgba(245,166,35,.22)}
.ring{position:absolute;width:44px;height:44px;border-radius:50%;border:3px solid rgba(245,166,35,.95);background:rgba(245,166,35,.18)}
.cur{position:absolute;filter:drop-shadow(0 2px 2px rgba(0,0,0,.35))}
.note{position:absolute;background:#fff;color:#1f2633;border-radius:12px;padding:16px 20px;font-size:17px;line-height:1.6;
 box-shadow:0 10px 30px rgba(20,30,50,.18);border:1px solid #d9dfe8}
.note b{color:#c2410c}
.note .t{font-weight:700;font-size:18px;margin-bottom:6px}
.cap{position:absolute;left:0;right:0;bottom:0;height:${CAPTION_H}px;background:#272d3a;color:#fff;display:flex;align-items:center;padding:0 30px;gap:18px}
.num{width:40px;height:40px;border-radius:50%;background:#f5a623;color:#272d3a;font-weight:700;font-size:19px;display:flex;align-items:center;justify-content:center;flex:none}
.txt{font-size:22px;font-weight:700;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lbl{font-size:17px;color:#c9cfdb;white-space:nowrap}
</style></head><body>${html}
<div class="cap">${spec.step !== undefined ? `<div class="num">${spec.step}</div>` : ''}<div class="txt">${spec.text || ''}</div><div class="lbl">${spec.label || ''}</div></div>
</body></html>`);
  await page.evaluate(() => document.fonts.ready);
  await sleep(300);
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  await page.screenshot({ path: outFile, type: 'png' });
  await page.close();
  return outFile;
}

// PNG 여러 장 → GIF. frames: [{file, sec}]
function gif(frames, outFile, width = 1200) {
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  const tmp = path.join(path.dirname(outFile), `.${path.basename(outFile)}.txt`);
  const lines = [];
  frames.forEach((f) => { lines.push(`file '${f.file}'`, `duration ${f.sec || 2.5}`); });
  lines.push(`file '${frames[frames.length - 1].file}'`);
  fs.writeFileSync(tmp, lines.join('\n'));
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', tmp,
    '-vf', `scale=${width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`,
    '-loop', '0', outFile]);
  fs.unlinkSync(tmp);
  return outFile;
}

module.exports = { app, stage, gif, close, sleep, KO, loc, STAGE_W, STAGE_H, CAPTION_H };
