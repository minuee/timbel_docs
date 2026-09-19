// 11~15 : 상세 검색 / 캘린더 / 알림 메시지 / 북마크 / 휴지통
//   node rec-menus.js            → 5개 모두
//   node rec-menus.js calendar   → 하나만
const { chromium } = require('playwright');
const fs = require('fs');
const { installCursor, highlight, moveTo, clickAt, callout, hideCallout, hideTooltips, dimRegion } = require('./lib');
fs.readFileSync(__dirname+'/.env','utf8').split('\n').forEach(l=>{const m=l.match(/^([A-Z_]+)=(.*)$/);if(m)process.env[m[1]]=m[2];});

const W = 1440, H = 900;

// 텍스트로 요소 박스 찾기 — 클래스 해시(css-xxxx)에 의존하지 않기 위해
async function boxOfText(p, text, { minW = 0, minH = 0 } = {}) {
  return await p.evaluate(({t, minW, minH}) => {
    const leaf = [...document.querySelectorAll('*')]
      .find(n => n.children.length === 0 && n.textContent.trim().includes(t));
    if (!leaf) return null;
    let e = leaf;
    while (e) {
      const r = e.getBoundingClientRect();
      if (r.width >= minW && r.height >= minH) break;
      e = e.parentElement;
    }
    const b = (e || leaf).getBoundingClientRect();
    return {x:Math.round(b.x), y:Math.round(b.y), width:Math.round(b.width), height:Math.round(b.height)};
  }, {t: text, minW, minH});
}
async function boxOf(p, sel) {
  return await p.evaluate(s => {
    const e = document.querySelector(s); if (!e) return null;
    const b = e.getBoundingClientRect();
    return {x:Math.round(b.x), y:Math.round(b.y), width:Math.round(b.width), height:Math.round(b.height)};
  }, sel);
}
// 여러 요소를 감싸는 박스 (예: 복구 + 영구삭제 열)
async function boxUnion(p, texts) {
  return await p.evaluate(ts => {
    const rects = ts.map(t => {
      const n = [...document.querySelectorAll('.MuiDataGrid-columnHeader, [role=columnheader]')]
        .find(x => x.textContent.trim() === t);
      return n ? n.getBoundingClientRect() : null;
    }).filter(Boolean);
    if (!rects.length) return null;
    const x = Math.min(...rects.map(r=>r.x)), y = Math.min(...rects.map(r=>r.y));
    const x2 = Math.max(...rects.map(r=>r.right)), y2 = Math.max(...rects.map(r=>r.bottom));
    return {x:Math.round(x), y:Math.round(y), width:Math.round(x2-x), height:Math.round(y2-y)};
  }, texts);
}

// 표를 가로로 부드럽게 민다 (휴지통의 복구/영구삭제 열은 1440 폭에서 잘려 있음)
async function smoothScrollX(p, sel, to, ms = 900) {
  await p.evaluate(({sel, to, ms}) => new Promise(res => {
    const e = document.querySelector(sel); if (!e) return res();
    const from = e.scrollLeft, t0 = performance.now();
    const tick = now => {
      const k = Math.min(1, (now - t0) / ms);
      e.scrollLeft = from + (to - from) * (k < .5 ? 2*k*k : 1 - Math.pow(-2*k+2, 2)/2);
      k < 1 ? requestAnimationFrame(tick) : res();
    };
    requestAnimationFrame(tick);
  }), {sel, to, ms});
}

// 페이지 이동 직후 뜨는 "데이터를 불러오는 중이에요" 토스트가 사라질 때까지
async function waitToast(p) {
  const t = p.locator('text=데이터를 불러오는 중이에요');
  await t.waitFor({state:'visible', timeout:2500}).catch(()=>{});
  await t.waitFor({state:'hidden',  timeout:20000}).catch(()=>{});
}

const say = async (p, box, text, hold, side='right', width=400) => {
  await moveTo(p, box, 260);
  await highlight(p, box, true, 6);
  await callout(p, box, text, {side, width, gap:18});
  await p.waitForTimeout(hold);
  await hideCallout(p);
  await highlight(p, box, false);
  await p.waitForTimeout(220);
};

// LNB 항목을 눌러 페이지로 이동
const gotoMenu = async (p, label) => {
  const item = p.locator(`[aria-label="${label}"]`);
  await moveTo(p, item, 320);
  await highlight(p, item, true, 5);
  await p.waitForTimeout(550);
  await clickAt(p, item, {ringSize: 40, after: 900});
  await waitToast(p);
  await p.waitForTimeout(1200);
};

const SCENES = {
  // 11 상세 검색
  async search(p) {
    await dimRegion(p, {x: 0, y: 500, width: W, height: H - 500}, 0.85);
    await p.waitForTimeout(800);
    const input = p.locator('input[placeholder="검색어를 입력해주세요."]');
    await say(p, input, '회의록을 검색합니다.\n제목이나 키워드로 바로 찾을 수 있습니다.', 2000, 'bottom');

    const detail = p.getByText('상세 검색').first();
    await clickAt(p, detail, {ringSize: 40, after: 1300});

    const panel = await boxOf(p, '.detail-search-container');
    await say(p, panel, '상세 검색을 누르면\n조회 기간 · 저장 폴더 · 참석자 · 공유 · 유형으로\n범위를 좁혀 찾을 수 있습니다.', 3000, 'bottom');

    const btn = p.getByRole('button', {name:'검색', exact:true}).first();
    await say(p, btn, '조건을 고르고 검색을 누릅니다.\n초기화를 누르면 조건이 모두 풀립니다.', 2400, 'bottom');
    await p.waitForTimeout(1200);
  },

  // 12 캘린더
  async calendar(p) {
    await p.waitForTimeout(700);
    await gotoMenu(p, '캘린더');

    const grid = await boxOf(p, '.calendar');
    const head = await boxOfText(p, '2026년', {minW: 200});
    await moveTo(p, head, 260);
    await highlight(p, grid, true, 5);
    await callout(p, head, '회의록을 날짜별로 봅니다.\n회의가 있던 날에는 칸 안에 회의록 제목이 보입니다.', {side:'bottom', width:400, gap:16});
    await p.waitForTimeout(2600);
    await hideCallout(p);
    await highlight(p, grid, false);
    await p.waitForTimeout(220);

    // 회의록이 있는 9일을 눌러 우측 패널이 바뀌는 걸 보여준다
    const day9 = p.locator('.component').getByText('9', {exact:true}).first();
    await clickAt(p, day9, {ringSize: 38, after: 1500});
    const side = await boxOf(p, '.day-contents');
    await say(p, side, '날짜를 누르면 그날의 회의록이 오른쪽에 나타나고,\n눌러서 바로 열 수 있습니다.', 2800, 'left');
    await p.waitForTimeout(1200);
  },

  // 13 알림 메시지
  async inbox(p) {
    await p.waitForTimeout(700);
    await gotoMenu(p, '알림 메시지');
    const tabs = await boxOf(p, '.MuiTabs-root');
    await say(p, tabs, '요약이 끝났거나 오류가 났을 때\n알림이 여기에 쌓입니다.\n전체 · 회의록 · 오류 로 걸러 볼 수 있습니다.', 2900, 'bottom');
    const all = p.getByRole('button', {name:'전체 확인'});
    await say(p, all, '전체 확인을 누르면\n쌓인 알림이 한 번에 읽음 처리됩니다.', 2300, 'left');
    await p.waitForTimeout(1200);
  },

  // 14 북마크
  async bookmark(p) {
    await p.waitForTimeout(700);
    await gotoMenu(p, '북마크');
    const empty = await boxOfText(p, '북마크가 없습니다', {minW: 200});
    await say(p, empty, '자주 보는 회의록을 북마크해 두면\n여기에 모입니다.\n회의록 단위로 즐겨찾기하는 기능입니다.', 3000, 'right');
    await p.waitForTimeout(1200);
  },

  // 15 휴지통
  async recycle(p) {
    await p.waitForTimeout(700);
    await gotoMenu(p, '휴지통');
    const notice = await boxOfText(p, '30일이 지나면', {minW: 300});
    await say(p, notice, '삭제한 회의록은 30일 동안 여기에 보관되고,\n30일이 지나면 자동으로 삭제됩니다.', 2500, 'bottom');
    await smoothScrollX(p, '.MuiDataGrid-virtualScroller', 9999, 900);
    await p.waitForTimeout(600);
    const cols = await boxUnion(p, ['복구', '영구삭제']);
    if (cols) await say(p, cols, '표를 오른쪽으로 밀면 복구 · 영구삭제 가 있습니다.\n복구로 되살리거나, 영구삭제로 완전히 지웁니다.', 2400, 'left');
    await smoothScrollX(p, '.MuiDataGrid-virtualScroller', 0, 700);
    await p.waitForTimeout(400);
    const empty = p.getByRole('button', {name:'휴지통 비우기'});
    await say(p, empty, '휴지통 비우기를 누르면\n보관된 회의록이 전부 지워집니다.', 2100, 'left');
    await p.waitForTimeout(1200);
  },

  // 16 이용 현황  (차트 수치는 손대지 않고 "무엇이 표시되는지"만 설명)
  async usage(p) {
    await p.waitForTimeout(700);
    await gotoMenu(p, '이용현황');

    const period = await p.evaluate(() => {
      const bs = ['오늘','1주','1개월','3개월','6개월']
        .map(t => [...document.querySelectorAll('button')].find(n => n.innerText.trim() === t))
        .filter(Boolean).map(n => n.getBoundingClientRect());
      const x = Math.min(...bs.map(r=>r.x)), y = Math.min(...bs.map(r=>r.y));
      return {x:Math.round(x), y:Math.round(y),
              width: Math.round(Math.max(...bs.map(r=>r.right)) - x),
              height: Math.round(Math.max(...bs.map(r=>r.bottom)) - y)};
    });
    await say(p, period, '보고 싶은 기간을 고릅니다.\n오늘 · 1주 · 1개월 · 3개월 · 6개월 중에서 고르면\n아래 내용이 그 기간 기준으로 바뀝니다.', 2400, 'bottom');

    // 카드 좌표는 제목 텍스트로 찾는다 (클래스 해시에 기대지 않기 위해)
    const card = async (t) => boxOfText(p, t, {minW: 280, minH: 150});
    const heat = await p.evaluate(() => { const e=document.querySelector('.echarts-for-react');
      const b=e.getBoundingClientRect(); return {x:Math.round(b.x),y:Math.round(b.y),width:Math.round(b.width),height:Math.round(b.height)}; });

    await say(p, heat,                       '날짜별 녹음량을 색 농도로 보여줍니다.\n진할수록 많이 녹음한 날입니다.', 1900, 'right');
    await say(p, await card('기록된 회의 시간'), '날짜별 녹음 시간 추이와\n총 누적 시간이 표시됩니다.', 1900, 'left');
    await say(p, await card('회의록 재요약'),   '회의록을 다시 요약한 횟수입니다.\n요약 품질 등급(상 · 중 · 하)별로 나눠 보여줍니다.', 2200, 'right');
    await say(p, await card('파일 다운로드'),   '회의록을 문서 파일로 내려받은 횟수가 표시됩니다.', 1700, 'left');
    await say(p, await card('사전'),           '등록한 사전 단어 수입니다.\n새로 추가한 개수와 전체 누적 개수를 보여줍니다.', 2000, 'left');
    await p.waitForTimeout(1200);
  },
};

(async () => {
  const only = process.argv[2];
  const names = only ? [only] : Object.keys(SCENES);
  for (const name of names) {
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
    await p.waitForTimeout(4000);
    await hideTooltips(p);
    await installCursor(p, 700, 500);
    await p.waitForTimeout(400);

    const t0 = Date.now();
    await SCENES[name](p);

    const offset = (t0 - tCreated) / 1000;
    await p.screenshot({ path: `${__dirname}/out/final-${name}.png` });
    await ctx.close();
    const vpath = await p.video().path();
    await b.close();
    fs.writeFileSync(`${__dirname}/video/meta-${name}.json`, JSON.stringify({vpath, offset}, null, 1));
    console.log(`[${name}] VIDEO: ${vpath}  TRIM_OFFSET: ${offset.toFixed(2)}s`);
  }
})();
