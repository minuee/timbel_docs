// 흐름 그림 촬영: flow.html → ../img/01_flow.png
// 실행: NODE_PATH=<playwright-core 가 있는 node_modules> node docs/web-integration/_scripts/shot.js
const path = require('path');
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
  const page = await browser.newPage({ viewport: { width: 1200, height: 400 }, deviceScaleFactor: 2 });
  await page.goto('file://' + path.join(__dirname, 'flow.html'));
  await page.screenshot({ path: path.join(__dirname, '../img/01_flow.png'), fullPage: true });
  await browser.close();
})();
