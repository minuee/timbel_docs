const { chromium } = require('playwright');
require('fs').readFileSync(__dirname + '/.env', 'utf8').split('\n').forEach(l => {
  const m = l.match(/^([A-Z_]+)=(.*)$/); if (m) process.env[m[1]] = m[2];
});

(async () => {
  const b = await chromium.launch({ headless: true });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ko-KR' });
  const p = await ctx.newPage();
  await p.goto(process.env.TIMBLO_URL, { waitUntil: 'networkidle' });
  await p.fill('input[placeholder="아이디(이메일)"]', process.env.TIMBLO_ID);
  await p.fill('input[placeholder="비밀번호"]', process.env.TIMBLO_PW);
  await p.click('button:has-text("로그인")');
  await p.waitForTimeout(5000);
  console.log('AFTER LOGIN URL:', p.url());
  await p.screenshot({ path: __dirname + '/out/02-after-login.png', fullPage: false });
  await ctx.storageState({ path: __dirname + '/auth.json' });
  console.log('storageState saved');
  await b.close();
})();
