// 18 왼쪽 메뉴 하나씩 보기 — LNB 항목 10개를 위에서 아래로 한 번씩 설명
// 09(홈 좌측)는 구역 단위로 묶어 설명하므로, 이 단원이 항목별 설명을 맡는다.
const { chromium } = require('playwright');
const fs = require('fs');
const { installCursor, highlight, moveTo, callout, hideCallout, hideTooltips, dimRegion } = require('./lib');
const { LNB_ARGS, applyLnbPatch } = require('./patch');
fs.readFileSync(__dirname+'/.env','utf8').split('\n').forEach(l=>{const m=l.match(/^([A-Z_]+)=(.*)$/);if(m)process.env[m[1]]=m[2];});

const W = 1920, H = 1080;

// aria-label 로 LNB 행(li) 박스 잡기 — 항목 전체가 강조돼야 보기 좋다
async function rowBox(p, label) {
  return await p.evaluate(al => {
    const el = document.querySelector(`[aria-label="${al}"]`);
    if (!el) return null;
    const li = el.closest('li') || el;
    const b = li.getBoundingClientRect();
    return {x:Math.round(b.x), y:Math.round(b.y), width:Math.round(b.width), height:Math.round(b.height)};
  }, label);
}

// 설명할 항목 — 위에서 아래 순서 (관리자 설정은 사용자 요청으로 제외)
const ITEMS = [
  ['홈',             '지금 보고 있는 이 홈 화면으로 돌아옵니다.',                    1700],
  ['전체 회의록',     '내가 등록한 회의록이 전부 여기에 모입니다.',                   1900],
  ['AI회의록',        '직접 만든 폴더입니다.\n회의록을 주제별로 나눠 담을 수 있습니다.', 2200],
  ['미완성 회의록',   '녹음이나 AI 요약이 끝나지 않은 회의록이\n여기에 남습니다.',      2200],
  ['캘린더',          '회의록을 날짜별로 모아서 봅니다.',                            1700],
  ['알림 메시지',     '요약이 끝났거나 오류가 났을 때\n알림이 여기에 쌓입니다.',        2000],
  ['북마크',          '북마크해 둔 회의록이 모입니다.',                              1700],
  ['휴지통',          '삭제한 회의록이 30일 동안 보관됩니다.',                       1800],
  ['이용현황',        '녹음 시간, 재요약 횟수 같은\n내 사용 기록을 봅니다.',           2000],
  ['개인 환경 설정',  '사전 관리 같은 개인 설정을 엽니다.',                          1800],
];

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
  await p.waitForTimeout(4200);
  await hideTooltips(p);

  // '내 회의록' → '미완성 회의록' (이름 변경 + 폴더 아래로 이동). 사이트에 반영되면 이 두 줄만 지운다.
  await p.evaluate(applyLnbPatch, LNB_ARGS);
  await p.waitForTimeout(900);

  await installCursor(p, 900, 560);
  await dimRegion(p, { x: 240, y: 0, width: W - 240, height: H }, 0.80);
  await p.waitForTimeout(400);

  const t0 = Date.now();
  await p.waitForTimeout(800);

  for (const [label, text, hold] of ITEMS) {
    const box = await rowBox(p, label);
    if (!box) { console.log('건너뜀(못 찾음):', label); continue; }
    await moveTo(p, box, 190);
    await highlight(p, box, true, 5);
    await callout(p, box, text, {side:'right', width: 400, gap: 18});
    await p.waitForTimeout(hold);
    await hideCallout(p);
    await highlight(p, box, false);
    await p.waitForTimeout(200);
  }

  await p.waitForTimeout(1200);

  const offset = (t0 - tCreated) / 1000;
  await p.screenshot({ path: __dirname + '/out/final-lnb.png' });
  await ctx.close();
  const vpath = await p.video().path();
  await b.close();
  fs.writeFileSync(__dirname + '/video/meta-lnb.json', JSON.stringify({vpath, offset}, null, 1));
  console.log('VIDEO:', vpath, ' TRIM_OFFSET:', offset.toFixed(2));
})();
