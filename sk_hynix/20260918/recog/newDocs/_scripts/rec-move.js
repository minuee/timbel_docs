const { chromium } = require('playwright');
const fs = require('fs');
const L = require('./lib');
fs.readFileSync(__dirname+'/.env','utf8').split('\n').forEach(l=>{const m=l.match(/^([A-Z_]+)=(.*)$/);if(m)process.env[m[1]]=m[2];});
const W=1440,H=900,URL=process.env.TIMBLO_URL,NAME='moveToFolder';

(async()=>{
  const b=await chromium.launch({headless:true});
  const ctx=await b.newContext({viewport:{width:W,height:H},locale:'ko-KR',
    storageState:__dirname+'/auth.json',
    recordVideo:{dir:__dirname+'/video/'+NAME,size:{width:W,height:H}}});
  const p=await ctx.newPage();
  const tCreated=Date.now();
  await p.goto(URL,{waitUntil:'domcontentloaded'});
  await p.waitForSelector('text=전체 회의록',{timeout:30000});
  await p.waitForTimeout(2500);
  await p.locator('div[role="button"][aria-label="전체 회의록"]').first().click();
  await p.waitForTimeout(1200);
  const toast=p.locator('text=데이터를 불러오는 중');
  await toast.waitFor({state:'visible',timeout:6000}).catch(()=>{});
  await toast.waitFor({state:'hidden',timeout:25000}).catch(()=>{});
  await p.waitForTimeout(1500);
  await L.hideTooltips(p);
  await L.installCursor(p, 900, 620);
  await p.waitForTimeout(400);

  const t0=Date.now();
  await p.waitForTimeout(1200);

  // ① 회의록 행 체크박스
  const cb = p.locator('input[type=checkbox]').nth(1);
  await L.moveTo(p, cb, 650);
  await L.highlight(p, cb, true, 4); await p.waitForTimeout(750);
  await L.clickAt(p, cb, {ringSize:34, after:1300});

  // ② 상단 [폴더 이동]
  const moveTop = p.locator('button:has-text("폴더 이동")').first();
  await L.moveTo(p, moveTop, 650);
  await L.highlight(p, moveTop, true, 5); await p.waitForTimeout(750);
  await L.clickAt(p, moveTop, {ringSize:46, after:1500});

  // ③ 팝오버에서 AI회의록 선택
  await p.waitForSelector('text=이동할 폴더를 선택해 주세요',{timeout:15000});
  await p.waitForTimeout(1300);
  let ai = p.getByRole('radio',{name:'AI회의록'});
  if (!(await ai.count())) ai = p.locator('text=AI회의록').last();
  await L.highlight(p, ai, true, 5); await p.waitForTimeout(700);
  await L.clickAt(p, ai, {ringSize:34, after:1300});

  // ④ [이동]
  let go = p.getByRole('button',{name:'이동',exact:true});
  if (!(await go.count())) go = p.locator('button:has-text("이동")').last();
  await L.highlight(p, go, true, 5); await p.waitForTimeout(700);
  await L.clickAt(p, go, {ringSize:44, after:2000});

  // ⑤ 결과: 폴더 칸이 AI회의록 으로 바뀜
  await toast.waitFor({state:'hidden',timeout:20000}).catch(()=>{});
  await p.waitForTimeout(1500);
  const cell = p.locator('text=AI회의록').last();
  try { await L.highlight(p, cell, true, 6); } catch(e){ console.log('결과 강조 스킵'); }
  await p.waitForTimeout(2400);
  await L.highlight(p, cell, false);
  await p.waitForTimeout(700);

  await p.screenshot({path:__dirname+`/out/final-${NAME}.png`});
  const offset=(t0-tCreated)/1000;
  await ctx.close();
  const vpath=await p.video().path();
  await b.close();
  fs.writeFileSync(__dirname+'/video/meta-move.json',JSON.stringify({name:NAME,vpath,offset},null,1));
  console.log('VIDEO:',vpath,'\nOFFSET:',offset.toFixed(2));
})();
