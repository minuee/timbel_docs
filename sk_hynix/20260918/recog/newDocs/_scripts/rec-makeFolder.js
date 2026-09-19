const { chromium } = require('playwright');
const fs = require('fs');
const { installCursor, highlight, clickAt, typeText, moveTo } = require('./lib');
fs.readFileSync(__dirname+'/.env','utf8').split('\n').forEach(l=>{const m=l.match(/^([A-Z_]+)=(.*)$/);if(m)process.env[m[1]]=m[2];});

const FOLDER = process.env.FOLDER_NAME || 'AI회의록';
const W = 1440, H = 900;

(async () => {
  const b = await chromium.launch({ headless: true });
  const ctx = await b.newContext({
    viewport: {width: W, height: H}, locale: 'ko-KR',
    storageState: __dirname + '/auth.json',
    recordVideo: { dir: __dirname + '/video', size: {width: W, height: H} },
  });
  const p = await ctx.newPage();
  const tCreated = Date.now();

  await p.goto(process.env.TIMBLO_URL, { waitUntil: 'domcontentloaded' });
  await p.waitForSelector('text=전체 회의록', { timeout: 30000 });
  await p.waitForTimeout(2500);
  await installCursor(p, 760, 520);
  await p.waitForTimeout(400);

  const t0 = Date.now();                       // ← GIF 시작 지점
  await p.waitForTimeout(1100);                // 도입: 현재 화면 보여주기

  // ① [+] 버튼
  const plus = p.locator('button[aria-label="폴더 추가"]');
  await moveTo(p, plus, 500);
  await highlight(p, plus, true, 5);
  await p.waitForTimeout(650);
  await clickAt(p, plus, { ringSize: 40, after: 900 });
  await highlight(p, null && plus, false);

  // ② 인라인 입력칸 등장
  const inputRow = p.locator('div.MuiInputBase-root:has(input[placeholder*="새 폴더"])');
  const input = inputRow.locator('input');
  await input.waitFor({ timeout: 10000 });
  await highlight(p, inputRow, true, 5);
  await p.waitForTimeout(1000);

  // ③ 폴더명 타이핑
  await typeText(p, input, FOLDER, 180);
  await p.waitForTimeout(900);                 // ✓ 가 활성화되는 순간
  await highlight(p, inputRow, false);

  // ④ [✓] 확인
  const ok = inputRow.locator('button').first();
  await highlight(p, ok, true, 4);
  await p.waitForTimeout(600);
  await clickAt(p, ok, { ringSize: 34, after: 1400 });
  await highlight(p, ok, false);

  // ⑤ 생성된 폴더 강조
  const made = p.getByText(FOLDER, { exact: true }).first();
  try {
    await made.waitFor({ timeout: 8000 });
    await highlight(p, made, true, 6);
  } catch (e) { console.log('생성된 폴더 강조 스킵:', e.message.split('\n')[0]); }
  await p.waitForTimeout(2200);
  await highlight(p, made, false);
  await p.waitForTimeout(500);

  const offset = (t0 - tCreated) / 1000;
  await p.screenshot({ path: __dirname + '/out/10-made.png' });
  await ctx.close();
  const vpath = await p.video().path();
  await b.close();
  fs.writeFileSync(__dirname + '/video/meta.json', JSON.stringify({ vpath, offset }, null, 1));
  console.log('VIDEO:', vpath);
  console.log('TRIM_OFFSET:', offset.toFixed(2), 's');
})();
