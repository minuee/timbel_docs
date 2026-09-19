// 10 홈 화면 둘러보기 ② 우측 대시보드 — 캘린더 / 최근 회의록 / 최근 검색어 / 최근 북마크 / 녹음량 / 기록된 회의 시간
const { chromium } = require('playwright');
const fs = require('fs');
const { installCursor, highlight, moveTo, clickAt, callout, hideCallout, hideTooltips, dimRegion } = require('./lib');
fs.readFileSync(__dirname+'/.env','utf8').split('\n').forEach(l=>{const m=l.match(/^([A-Z_]+)=(.*)$/);if(m)process.env[m[1]]=m[2];});

const W = 1920, H = 1080;

// 대시보드 카드 6개의 좌표를 실제 DOM 에서 계산 (상단 3 + 하단 3)
async function cards(p) {
  return await p.evaluate(() => {
    const R = e => { const b = e.getBoundingClientRect();
      return {x:Math.round(b.x), y:Math.round(b.y), width:Math.round(b.width), height:Math.round(b.height)}; };
    const wrap = document.querySelector('.home-container > div');
    const top    = [...wrap.children[0].children].map(R);   // 캘린더 / 최근 회의록 / 최근 검색어
    const bottom = [...wrap.children[1].children].map(R);   // 최근 북마크 / 녹음량 / 기록된 회의 시간
    return { cal: top[0], recent: top[1], keyword: top[2],
             bookmark: bottom[0], heat: bottom[1], hours: bottom[2] };
  });
}

(async () => {
  const b = await chromium.launch({ headless: true });
  const ctx = await b.newContext({
    viewport: {width: W, height: H}, locale: 'ko-KR',
    storageState: __dirname + '/auth.json',
    recordVideo: { dir: __dirname + '/video', size: {width: W, height: H} },
  });
  const p = await ctx.newPage();
  const tCreated = Date.now();

  for (let i=0;i<3;i++){ try { await p.goto(process.env.TIMBLO_URL, {waitUntil:'domcontentloaded', timeout:60000}); break; } catch(e){} }
  await p.waitForSelector('text=전체 회의록', { timeout: 30000 });
  await p.waitForTimeout(5000);                  // 차트까지 다 그려질 때까지
  await hideTooltips(p);
  await installCursor(p, 1000, 560);
  await p.waitForTimeout(400);

  const c = await cards(p);
  console.log('cards:', JSON.stringify(c));

  // 좌측 메뉴를 흐리게 — 우측 대시보드에 시선을 모은다
  await dimRegion(p, { x: 0, y: 0, width: 240, height: H }, 0.80);

  const t0 = Date.now();                         // ← GIF 시작 지점
  await p.waitForTimeout(800);

  const step = async (box, text, hold, side = 'right') => {
    await moveTo(p, box, 220);
    await highlight(p, box, true, 6);
    await callout(p, box, text, { side, width: 400, gap: 18 });
    await p.waitForTimeout(hold);
    await hideCallout(p);
    await highlight(p, box, false);
    await p.waitForTimeout(200);
  };

  // ① 캘린더 — 설명 후 9일을 눌러 "1개의 회의록이 있습니다." 를 보여준다
  await moveTo(p, c.cal, 220);
  await highlight(p, c.cal, true, 6);
  await callout(p, c.cal, '이번 달 회의 일정을 봅니다.\n회의가 있는 날에는 점이 표시되고,\n날짜를 누르면 그날의 회의록을 볼 수 있습니다.', {side:'right', width:400, gap:18});
  await p.waitForTimeout(2000);
  const day9 = p.locator('.MuiDateCalendar-root').getByText('9', {exact:true}).first();
  await clickAt(p, day9, { ringSize: 36, after: 1200 });
  await highlight(p, c.cal, true, 6);            // 클릭 후 하이라이트 복구
  await p.waitForTimeout(1000);
  await hideCallout(p);
  await highlight(p, c.cal, false);
  await p.waitForTimeout(200);

  await step(c.recent,   '최근에 만들어진 회의록이 최신순으로 쌓입니다.\n폴더 · 유형 · 회의 시간 · 소요 시간을 한눈에 보고\n바로 열 수 있습니다.', 1700, 'bottom');
  await step(c.keyword,  '최근에 검색한 검색어가 여기에 남습니다.', 1300, 'left');
  await step(c.bookmark, '북마크해 둔 회의록이 모입니다.\n자주 보는 회의록을 빠르게 열 수 있습니다.', 1500, 'right');
  await step(c.heat,     '날짜별 녹음량을 색 농도로 보여줍니다.\n진할수록 많이 녹음한 날입니다.', 1700, 'right');
  await step(c.hours,    '날짜별 녹음 시간 추이와\n총 누적 시간을 보여줍니다.', 1600, 'left');

  await p.waitForTimeout(1200);                  // 마지막 정지

  const offset = (t0 - tCreated) / 1000;
  await p.screenshot({ path: __dirname + '/out/final-home-right.png' });
  await ctx.close();
  const vpath = await p.video().path();
  await b.close();
  fs.writeFileSync(__dirname + '/video/meta-home-right.json', JSON.stringify({ vpath, offset }, null, 1));
  console.log('VIDEO:', vpath);
  console.log('TRIM_OFFSET:', offset.toFixed(2), 's');
})();
