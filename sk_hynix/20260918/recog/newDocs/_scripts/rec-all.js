const { chromium } = require('playwright');
const fs = require('fs');
const L = require('./lib');
fs.readFileSync(__dirname+'/.env','utf8').split('\n').forEach(l=>{const m=l.match(/^([A-Z_]+)=(.*)$/);if(m)process.env[m[1]]=m[2];});
const W=1440, H=900, URL=process.env.TIMBLO_URL;

// 데모용 폴더가 없으면 만들어 둔다 (촬영 시작 전이라 GIF 에는 안 나옴)
async function ensureFolder(p, name) {
  if (await L.folderRow(p, name).count()) return;
  await p.click('button[aria-label="폴더 추가"]');
  await p.waitForTimeout(900);
  const box = p.locator('div.MuiInputBase-root:has(input[placeholder*="새 폴더"])');
  await box.locator('input').fill(name);
  await p.waitForTimeout(300);
  await box.locator('button').first().click();
  await p.waitForTimeout(1600);
  console.log('  (setup) created', name);
}

async function record(name, scene, setup) {
  const b = await chromium.launch({headless:true});
  const ctx = await b.newContext({viewport:{width:W,height:H}, locale:'ko-KR',
    storageState:__dirname+'/auth.json',
    recordVideo:{dir:__dirname+'/video/'+name, size:{width:W,height:H}}});
  const p = await ctx.newPage();
  const tCreated = Date.now();
  await p.goto(URL,{waitUntil:'domcontentloaded'});
  await p.waitForSelector('text=전체 회의록',{timeout:30000});
  await p.waitForTimeout(2500);
  if (setup) await setup(p);
  // 모든 장면을 '전체 회의록' 페이지에서 시작 → 오른쪽 배경이 깔끔해짐
  await p.locator('div[role="button"][aria-label="전체 회의록"]').first().click();
  // 로딩 토스트: 먼저 '뜨는' 것을 기다린 뒤 '사라질' 때까지 대기
  const toast = p.locator('text=데이터를 불러오는 중');
  await toast.waitFor({state:'visible', timeout:6000}).catch(()=>{});
  await toast.waitFor({state:'hidden',  timeout:20000}).catch(()=>{});
  await p.waitForTimeout(1500);
  await L.hideTooltips(p);
  await L.installCursor(p, 780, 560);
  await p.waitForTimeout(400);
  const t0 = Date.now();
  await scene(p);
  await p.screenshot({path:__dirname+`/out/final-${name}.png`});
  const offset = (t0 - tCreated)/1000;
  await ctx.close();
  const vpath = await p.video().path();
  await b.close();
  console.log(`[${name}] video=${vpath} offset=${offset.toFixed(2)}`);
  return {name, vpath, offset};
}

// ── ① folderMenu : hover → ⋮ → 메뉴 3종 소개 ──────────────────
async function sceneFolderMenu(p) {
  const FOLDER='AI회의록';
  await p.waitForTimeout(1000);
  const row = L.folderRow(p, FOLDER);
  await L.moveTo(p, row, 700);                       // hover → ⋮ 등장
  await p.waitForTimeout(700);
  const dots = row.locator('button').last();
  await L.highlight(p, dots, true, 5); await p.waitForTimeout(750);
  await L.clickAt(p, dots, {ringSize:36, after:1000});
  await L.highlight(p, dots, false);

  const rec = L.menuItem(p,'녹음'), ren = L.menuItem(p,'폴더명 변경'), del = L.menuItem(p,'폴더 삭제');
  await rec.waitFor({timeout:8000});
  await p.waitForTimeout(500);

  await L.highlight(p, rec, true, 3);
  await L.callout(p, rec, '클릭하면 바로 녹음이 시작됩니다\n회의록 파일이 이 폴더에 저장됩니다', {side:'right', width:330});
  await p.waitForTimeout(3000);

  await L.hideCallout(p); await p.waitForTimeout(300);
  await L.highlight(p, ren, true, 3);
  await L.callout(p, ren, '폴더 이름을 바꿉니다 (8글자까지)', {side:'right', width:300});
  await p.waitForTimeout(2300);

  await L.hideCallout(p); await p.waitForTimeout(300);
  await L.highlight(p, del, true, 3);
  await L.callout(p, del, '폴더를 삭제합니다\n안에 있던 회의록은 휴지통으로 이동됩니다', {side:'right', width:330});
  await p.waitForTimeout(2800);

  await L.hideCallout(p); await L.highlight(p, del, false);
  await p.waitForTimeout(900);
}

// ── ② renameFolder : 주간회의 → 팀회의록 ───────────────────────
async function sceneRename(p) {
  const FROM='주간회의', TO='팀회의록';
  await p.waitForTimeout(1000);
  const row = L.folderRow(p, FROM);
  await L.moveTo(p, row, 650); await p.waitForTimeout(500);
  await L.clickAt(p, row.locator('button').last(), {ringSize:36, after:900});

  const ren = L.menuItem(p,'폴더명 변경');
  await ren.waitFor({timeout:8000});
  await L.highlight(p, ren, true, 3); await p.waitForTimeout(600);
  await L.clickAt(p, ren, {ringSize:40, after:1000});
  await L.highlight(p, ren, false);

  const box = p.locator('div.MuiInputBase-root:has(input[placeholder*="폴더명"])');
  const input = box.locator('input');
  await input.waitFor({timeout:8000});
  await L.highlight(p, box, true, 5);
  await L.callout(p, box, '기존 이름이 채워져 있습니다', {side:'right', width:250});
  await p.waitForTimeout(1600);
  await L.hideCallout(p);

  await input.press('ControlOrMeta+a');               // 전체 선택
  await p.waitForTimeout(900);
  await input.press('Backspace');
  await p.waitForTimeout(500);
  await input.pressSequentially(TO, {delay:180});
  await p.waitForTimeout(800);
  await L.highlight(p, box, false);

  const ok = box.locator('button').first();
  await L.highlight(p, ok, true, 4); await p.waitForTimeout(550);
  await L.clickAt(p, ok, {ringSize:34, after:1500});
  await L.highlight(p, ok, false);

  const done = L.folderRow(p, TO);
  try { await done.waitFor({timeout:8000}); await L.highlight(p, done, true, 6); } catch(e){ console.log('rename 강조 스킵'); }
  await p.waitForTimeout(2200);
  await L.hideCallout(p); await L.highlight(p, done, false);
  await p.waitForTimeout(600);
}

// ── ③ deleteFolder : 팀회의록 삭제 ────────────────────────────
async function sceneDelete(p) {
  const TARGET='팀회의록';
  await p.waitForTimeout(1000);
  const row = L.folderRow(p, TARGET);
  await L.moveTo(p, row, 650); await p.waitForTimeout(500);
  await L.clickAt(p, row.locator('button').last(), {ringSize:36, after:900});

  const del = L.menuItem(p,'폴더 삭제');
  await del.waitFor({timeout:8000});
  await L.highlight(p, del, true, 3); await p.waitForTimeout(650);
  await L.clickAt(p, del, {ringSize:40, after:1300});
  await L.highlight(p, del, false);

  const dlg = p.locator('[role="dialog"], .MuiDialog-paper').first();
  await dlg.waitFor({timeout:8000});
  await p.waitForTimeout(1800);                       // 경고 문구 읽을 시간

  const ok = dlg.getByRole('button', {name:'확인'}).first();
  await L.highlight(p, ok, true, 5); await p.waitForTimeout(700);
  await L.clickAt(p, ok, {ringSize:44, after:1800});
  await L.highlight(p, ok, false);
  await p.waitForTimeout(2000);                       // 목록에서 사라진 상태
}

(async () => {
  const only = process.argv[2];
  const jobs = [
    ['folderMenu',   sceneFolderMenu, null],
    ['renameFolder', sceneRename,     p => ensureFolder(p, '주간회의')],
    ['deleteFolder', sceneDelete,     p => ensureFolder(p, '팀회의록')],
  ].filter(([n]) => !only || n === only);
  const meta = [];
  for (const [n, fn, su] of jobs) meta.push(await record(n, fn, su));
  fs.writeFileSync(__dirname+'/video/meta-all.json', JSON.stringify(meta, null, 1));
})();
