const { chromium } = require('playwright');
const fs = require('fs');
const L = require('./lib');
const { PATCH_ARGS, applyPatch } = require('./patch');
fs.readFileSync(__dirname+'/.env','utf8').split('\n').forEach(l=>{const m=l.match(/^([A-Z_]+)=(.*)$/);if(m)process.env[m[1]]=m[2];});
const W=1440, H=900, URL=process.env.TIMBLO_URL, NAME='recordMeeting';

(async () => {
  const b = await chromium.launch({ headless:true,
    args:['--use-fake-device-for-media-capture','--use-fake-ui-for-media-stream'] });
  const ctx = await b.newContext({ viewport:{width:W,height:H}, locale:'ko-KR',
    storageState:__dirname+'/auth.json', permissions:['microphone'],
    recordVideo:{ dir:__dirname+'/video/'+NAME, size:{width:W,height:H} } });
  const p = await ctx.newPage();
  const tCreated = Date.now();

  await p.goto(URL,{waitUntil:'domcontentloaded'});
  await p.waitForSelector('text=전체 회의록',{timeout:30000});
  await p.waitForTimeout(2500);
  await L.hideTooltips(p);
  await L.installCursor(p, 700, 520);
  await p.waitForTimeout(400);

  const t0 = Date.now();
  await p.waitForTimeout(1000);

  // ① 좌상단 마이크(녹음) 버튼
  const mic = p.locator('text=녹음').first();
  await L.moveTo(p, mic, 650);
  await L.highlight(p, mic, true, 8); await p.waitForTimeout(700);
  await L.clickAt(p, mic, {ringSize:52, after:2400});

  // ② 동의 체크
  const agree = p.locator('text=위 내용을 확인했습니다');
  await L.highlight(p, agree, true, 5); await p.waitForTimeout(900);
  await L.clickAt(p, agree, {ringSize:30, after:1300});

  // ③ 녹음 시작
  const start = p.locator('.record button.circle-icon-box');
  await L.highlight(p, start, true, 5); await p.waitForTimeout(700);
  await L.clickAt(p, start, {ringSize:56, after:1200});

  // 모달이 뜨는 순간 자동으로 템플릿이 보정되도록 미리 설치
  await p.evaluate(applyPatch, PATCH_ARGS);

  // ④ 녹음 진행 (타이머 도는 것 보여주기)
  await p.waitForTimeout(7000);

  // ⑤ 녹음 종료
  const stop = p.locator('text=녹음 종료').first();
  await L.moveTo(p, stop, 600);
  await L.highlight(p, stop, true, 6); await p.waitForTimeout(700);
  await L.clickAt(p, stop, {ringSize:44, after:1200});

  // ⑥ AI요약 준비하기 모달
  await p.waitForSelector('text=AI요약 준비하기',{timeout:40000});
  await p.waitForTimeout(2200);

  // 언어 선택 — 한 번씩 눌러 바뀌는 것 보여주기
  const en = p.locator('text=영어').first(), ko = p.locator('text=한국어').first();
  await L.clickAt(p, en, {ringSize:30, after:1200});
  await L.clickAt(p, ko, {ringSize:30, after:1300});

  // 발화자수 선택
  await L.clickAt(p, p.locator('text=3~6명').first(), {ringSize:30, after:1200});
  await L.clickAt(p, p.locator('text=7~10명').first(), {ringSize:30, after:1400});

  // 템플릿 선택 — 4종 순회
  const tpl = p.locator('[data-gpatched-list] > *');
  for (const i of [1,2,3,0]) {
    await L.clickAt(p, tpl.nth(i), {ringSize:34, after:1600});
  }
  await p.waitForTimeout(1800);

  await p.screenshot({path:__dirname+`/out/final-${NAME}.png`});
  const offset = (t0 - tCreated)/1000;
  await ctx.close();
  const vpath = await p.video().path();
  await b.close();
  fs.writeFileSync(__dirname+'/video/meta-record.json', JSON.stringify({name:NAME, vpath, offset},null,1));
  console.log('VIDEO:', vpath, '\nOFFSET:', offset.toFixed(2));
})();
