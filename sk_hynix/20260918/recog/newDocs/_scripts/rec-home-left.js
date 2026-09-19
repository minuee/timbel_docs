// 09 홈 화면 둘러보기 ① 좌측 영역 — 로고 / 녹음 / 회의록 메뉴 / 관리 메뉴
const { chromium } = require('playwright');
const fs = require('fs');
const { installCursor, highlight, moveTo, callout, hideCallout, hideTooltips, dimRegion } = require('./lib');
fs.readFileSync(__dirname+'/.env','utf8').split('\n').forEach(l=>{const m=l.match(/^([A-Z_]+)=(.*)$/);if(m)process.env[m[1]]=m[2];});

const W = 1920, H = 1080;

// 좌측 사이드바의 네 구역 좌표를 실제 DOM 에서 계산
async function regions(p) {
  return await p.evaluate(() => {
    const R = e => { const b = e.getBoundingClientRect();
      return {x:Math.round(b.x), y:Math.round(b.y), width:Math.round(b.width), height:Math.round(b.height)}; };
    const col  = document.querySelector('.sidebar .MuiPaper-root > div');
    const kids = [...col.children];
    const logo = R(document.querySelector('img[src*="sk_logo"]'));
    const head = R(kids[0]);                       // 로고 + 녹음 버튼 묶음
    const rec  = { x: head.x, y: logo.y + logo.height + 6,
                   width: head.width, height: head.y + head.height - (logo.y + logo.height) - 10 };
    const lnb  = R(kids[1].children[0]);           // 홈 ~ 휴지통
    const adm  = ['이용현황','개인 환경 설정','로그아웃'].map(l => R(document.querySelector(`[aria-label="${l}"]`)));
    const admin = { x: adm[0].x, y: adm[0].y,
                    width: adm[0].width, height: adm[2].y + adm[2].height - adm[0].y };
    return { logo, rec, lnb, admin };
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
  await p.waitForTimeout(4500);                  // 대시보드 카드가 다 그려질 때까지
  await hideTooltips(p);
  await installCursor(p, 900, 560);
  await p.waitForTimeout(400);

  const r = await regions(p);
  console.log('regions:', JSON.stringify(r));

  // 우측 본문을 흐리게 — 좌측 메뉴에 시선을 모은다 (크롭 경계의 잘린 카드도 같이 가려짐)
  await dimRegion(p, { x: 240, y: 0, width: W - 240, height: H }, 0.80);

  const t0 = Date.now();                         // ← GIF 시작 지점
  await p.waitForTimeout(1000);                  // 도입: 좌측 메뉴 전체 보여주기

  const step = async (box, text, hold, calloutOpts = {}) => {
    await moveTo(p, box, 320);
    await highlight(p, box, true, 6);
    await callout(p, box, text, { side:'right', width: 400, gap: 18, ...calloutOpts });
    await p.waitForTimeout(hold);
    await hideCallout(p);
    await highlight(p, box, false);
    await p.waitForTimeout(260);
  };

  await step(r.logo,  '로고를 누르면 어느 화면에서든\n홈 화면으로 돌아옵니다.', 2200);
  await step(r.rec,   '회의 녹음을 시작하는 버튼입니다.\n어느 화면에 있든 여기서 바로 녹음할 수 있습니다.', 2500);
  await step(r.lnb,   '회의록을 찾아보는 메뉴입니다.\n전체 회의록 · 내 회의록 · 폴더\n캘린더 · 알림 메시지 · 북마크 · 휴지통', 3200);
  await step(r.admin, '이용 현황과 개인 환경 설정, 로그아웃이\n모여 있는 영역입니다.', 2500);

  await p.waitForTimeout(1500);                  // 마지막 정지

  const offset = (t0 - tCreated) / 1000;
  await p.screenshot({ path: __dirname + '/out/final-home-left.png' });
  await ctx.close();
  const vpath = await p.video().path();
  await b.close();
  fs.writeFileSync(__dirname + '/video/meta-home-left.json', JSON.stringify({ vpath, offset }, null, 1));
  console.log('VIDEO:', vpath);
  console.log('TRIM_OFFSET:', offset.toFixed(2), 's');
})();
