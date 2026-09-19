// 17 사전 관리 — 개인 환경 설정 → 사전 관리 → 신규 등록
//   DRY=1 node rec-dict.js  → 실제 등록하지 않고 [취소] 로 빠진다 (구도 확인용)
const { chromium } = require('playwright');
const fs = require('fs');
const { installCursor, highlight, moveTo, clickAt, typeText, callout, hideCallout, hideTooltips } = require('./lib');
fs.readFileSync(__dirname+'/.env','utf8').split('\n').forEach(l=>{const m=l.match(/^([A-Z_]+)=(.*)$/);if(m)process.env[m[1]]=m[2];});

const W = 1920, H = 1080;            // 1440 에서는 모달이 화면 밖으로 잘린다
const BEFORE = '세미컨덕터';
const AFTER  = '반도체';
const DRY = !!process.env.DRY;

// 텍스트를 품은 조상 중 충분히 큰 박스 (모달 패널 잡기용)
// minX: '사전 관리' 는 좌측 팝업 메뉴에도 같은 글자가 있어서 x 로 걸러야 모달 제목이 잡힌다
async function panelOf(p, text, minW, minX = 0) {
  return await p.evaluate(({t, minW, minX}) => {
    const leaf = [...document.querySelectorAll('*')]
      .find(n => n.children.length === 0 && n.textContent.trim() === t
                 && n.getBoundingClientRect().width && n.getBoundingClientRect().x >= minX);
    if (!leaf) return null;
    let e = leaf;
    while (e && e.getBoundingClientRect().width < minW) e = e.parentElement;
    const b = (e || leaf).getBoundingClientRect();
    return {x:Math.round(b.x), y:Math.round(b.y), width:Math.round(b.width), height:Math.round(b.height)};
  }, {t: text, minW, minX});
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
  await p.waitForTimeout(4200);
  await hideTooltips(p);
  await installCursor(p, 900, 620);
  await p.waitForTimeout(400);

  const say = async (box, text, hold, side='right', width=420) => {
    await highlight(p, box, true, 6);
    await callout(p, box, text, {side, width, gap:18});
    await p.waitForTimeout(hold);
    await hideCallout(p);
    await highlight(p, box, false);
    await p.waitForTimeout(220);
  };

  const t0 = Date.now();
  await p.waitForTimeout(900);

  // ① 개인 환경 설정 열기
  const gear = p.locator('[aria-label="개인 환경 설정"]');
  await moveTo(p, gear, 300);
  await highlight(p, gear, true, 5);
  await p.waitForTimeout(520);
  await clickAt(p, gear, {ringSize: 40, after: 1200});

  // ② 팝업 안의 '사전 관리'  (바깥 li 도 같은 텍스트를 품고 있어 .last() 를 써야 한다)
  const dictItem = p.locator('li').filter({hasText:'사전 관리'}).last();
  await moveTo(p, dictItem, 320);
  await say(await dictItem.boundingBox(), '개인 환경 설정을 누르면\n사전 관리가 나옵니다.', 2200, 'right');
  await clickAt(p, dictItem, {ringSize: 40, after: 1800});

  // ③ 사전 목록 설명 — 모달 전체를 강조하고, 말풍선은 표 머리글에 붙인다
  const modal  = await panelOf(p, '사전 관리', 800, 300);
  const header = await panelOf(p, '변경 전 단어', 0, 300);
  await moveTo(p, header, 300);
  await highlight(p, modal, true, 6);
  await callout(p, header, '회의록의 음성 기록(STT)에 쓰이는 사전입니다.\n변경 전 단어가 인식되면\n변경 후 단어로 바꿔서 보여줍니다.', {side:'bottom', width:460, gap:16});
  await p.waitForTimeout(3000);
  await hideCallout(p);
  await highlight(p, modal, false);
  await p.waitForTimeout(220);

  // ④ 신규 등록
  const newBtn = p.getByRole('button', {name:'신규 등록'});
  await clickAt(p, newBtn, {ringSize: 42, after: 1400});

  const form = await panelOf(p, '사전 신규 등록', 380, 300);
  await say(form, '바꾸기 전 단어와 바꾼 뒤 단어를 넣습니다.', 1900, 'left');

  const before = p.locator('input[placeholder="단어를 입력하세요.(필수)"]');
  const after  = p.locator('input[placeholder="변경할 단어를 입력하세요.(필수)"]');
  await clickAt(p, before, {ringSize: 30, after: 400});
  await typeText(p, before, BEFORE, 170);
  await p.waitForTimeout(500);
  await clickAt(p, after, {ringSize: 30, after: 400});
  await typeText(p, after, AFTER, 170);
  await p.waitForTimeout(900);

  if (DRY) {
    await clickAt(p, p.getByRole('button', {name:'취소'}), {ringSize: 36, after: 1500});
    console.log('DRY: 등록하지 않고 취소했습니다.');
  } else {
    await clickAt(p, p.getByRole('button', {name:'등록', exact:true}), {ringSize: 36, after: 2200});
    const row = await panelOf(p, BEFORE, 700, 300);
    if (row) await say(row, '등록하면 목록에 추가되고,\n이후 회의록의 음성 기록에 자동으로 반영됩니다.', 2800, 'bottom');
  }
  await p.waitForTimeout(1400);

  const offset = (t0 - tCreated) / 1000;
  await p.screenshot({ path: __dirname + '/out/final-dict.png' });
  await ctx.close();
  const vpath = await p.video().path();
  await b.close();
  fs.writeFileSync(__dirname + '/video/meta-dict.json', JSON.stringify({vpath, offset}, null, 1));
  console.log('VIDEO:', vpath, ' TRIM_OFFSET:', offset.toFixed(2));
})();
