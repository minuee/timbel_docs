// 가이드 GIF 촬영용 연출 라이브러리: 가짜 커서 / 클릭 링 / 요소 하이라이트
const CURSOR_CSS = `
#__gcur{position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483000;pointer-events:none;
  transition:transform .55s cubic-bezier(.4,0,.2,1);will-change:transform;
  filter:drop-shadow(0 2px 4px rgba(0,0,0,.35))}
#__gring{position:fixed;left:0;top:0;z-index:2147482999;pointer-events:none;border-radius:9999px;
  border:3px solid #FFB020;opacity:0;transform:translate(-50%,-50%) scale(.4)}
#__gring.go{animation:__gpulse .6s ease-out}
@keyframes __gpulse{0%{opacity:1;transform:translate(-50%,-50%) scale(.4)}
  70%{opacity:.9;transform:translate(-50%,-50%) scale(1.15)}
  100%{opacity:0;transform:translate(-50%,-50%) scale(1.5)}}
#__ghl{position:fixed;z-index:2147482998;pointer-events:none;border-radius:8px;
  box-shadow:0 0 0 3px #FFB020, 0 0 0 9px rgba(255,176,32,.28);opacity:0;transition:opacity .25s}
`;
const CURSOR_SVG = `<svg viewBox="0 0 24 24" width="22" height="22" xmlns="http://www.w3.org/2000/svg">
<path d="M5 2.5 L5 19 L9.2 15.2 L11.9 21.3 L14.9 20 L12.2 14 L18 13.6 Z"
 fill="#1a1a1a" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>`;

async function installCursor(page, startX = 700, startY = 500) {
  await page.evaluate(({css, svg, x, y}) => {
    if (document.getElementById('__gcur')) return;
    const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s);
    const c = document.createElement('div'); c.id = '__gcur'; c.innerHTML = svg;
    c.style.transform = `translate(${x}px, ${y}px)`; document.body.appendChild(c);
    const r = document.createElement('div'); r.id = '__gring'; document.body.appendChild(r);
    const h = document.createElement('div'); h.id = '__ghl'; document.body.appendChild(h);
    window.__gpos = {x, y};
  }, {css: CURSOR_CSS, svg: CURSOR_SVG, x: startX, y: startY});
}

// 커서를 요소 중앙으로 이동 (실제 마우스도 같이 옮겨서 hover 발생)
async function moveTo(page, locator, ms = 650) {
  const box = await toBox(locator);
  const x = Math.round(box.x + box.width / 2), y = Math.round(box.y + box.height / 2);
  await page.evaluate(({x, y}) => {
    const c = document.getElementById('__gcur');
    if (c) c.style.transform = `translate(${x}px, ${y}px)`;
    window.__gpos = {x, y};
  }, {x, y});
  await page.mouse.move(x, y, {steps: 20});
  await page.waitForTimeout(ms);
  return {x, y};
}

// 로케이터 또는 {x,y,width,height} 둘 다 받는다 (영역 단위 설명용)
async function toBox(target) {
  if (target && typeof target.x === 'number' && typeof target.width === 'number') return target;
  return await target.boundingBox();
}

// 요소 테두리 하이라이트 on/off
async function highlight(page, locator, on = true, pad = 4) {
  if (!on) { await page.evaluate(() => { const h=document.getElementById('__ghl'); if(h) h.style.opacity='0'; }); return; }
  const b = await toBox(locator);
  await page.evaluate(({b, pad}) => {
    const h = document.getElementById('__ghl'); if (!h) return;
    h.style.left = (b.x - pad) + 'px'; h.style.top = (b.y - pad) + 'px';
    h.style.width = (b.width + pad*2) + 'px'; h.style.height = (b.height + pad*2) + 'px';
    h.style.opacity = '1';
  }, {b, pad});
}

// 클릭 링 이펙트 + 실제 클릭
async function clickAt(page, locator, {ringSize = 44, after = 700} = {}) {
  const {x, y} = await moveTo(page, locator);
  await page.evaluate(({x, y, s}) => {
    const r = document.getElementById('__gring'); if (!r) return;
    r.style.width = s + 'px'; r.style.height = s + 'px';
    r.style.left = x + 'px'; r.style.top = y + 'px';
    r.classList.remove('go'); void r.offsetWidth; r.classList.add('go');
  }, {x, y, s: ringSize});
  await page.waitForTimeout(200);
  await locator.click();
  // 클릭 직후 하이라이트를 끈다 — 대상이 사라져도 빈 테두리가 남지 않도록
  await page.evaluate(() => { const h=document.getElementById('__ghl'); if(h) h.style.opacity='0'; });
  await page.waitForTimeout(after);
}

// 한 글자씩 타이핑
async function typeText(page, locator, text, delay = 170) {
  await locator.pressSequentially(text, {delay});
}


// ── 말풍선(콜아웃) ──────────────────────────────────────────────
const CALLOUT_CSS = `
#__gcall{position:fixed;z-index:2147483001;pointer-events:none;box-sizing:border-box;
  background:#FFF8EC;border:2px solid #FFB020;border-radius:12px;
  padding:11px 15px;color:#6B3E00;font-size:14px;line-height:1.55;font-weight:600;
  font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
  box-shadow:0 6px 20px rgba(120,70,0,.18);opacity:0;transition:opacity .3s, transform .3s;
  transform:translateY(6px)}
#__gcall.on{opacity:1;transform:translateY(0)}
#__gcall .tail{position:absolute;width:0;height:0}
#__gcall.right .tail{left:-11px;top:var(--ty,22px);
  border-top:9px solid transparent;border-bottom:9px solid transparent;border-right:11px solid #FFB020}
#__gcall.right .tail::after{content:'';position:absolute;left:3px;top:-7px;
  border-top:7px solid transparent;border-bottom:7px solid transparent;border-right:9px solid #FFF8EC}
#__gcall.left .tail{right:-11px;top:var(--ty,22px);
  border-top:9px solid transparent;border-bottom:9px solid transparent;border-left:11px solid #FFB020}
#__gcall.left .tail::after{content:'';position:absolute;right:3px;top:-7px;
  border-top:7px solid transparent;border-bottom:7px solid transparent;border-left:9px solid #FFF8EC}
#__gcall.bottom .tail{top:-11px;left:var(--tx,26px);
  border-left:9px solid transparent;border-right:9px solid transparent;border-bottom:11px solid #FFB020}
#__gcall.bottom .tail::after{content:'';position:absolute;left:-7px;top:3px;
  border-left:7px solid transparent;border-right:7px solid transparent;border-bottom:9px solid #FFF8EC}
`;

// 툴팁 숨기기 (촬영 시 화면 가림 방지)
// - MUI 기본 툴팁: 폴더에 hover 하면 검은 박스가 아래 항목을 가림
// - echarts: 차트 위에 커서가 지나가면 값 툴팁 + 세로 기준선이 떠서 설명을 가림
//   → pointer-events 를 꺼서 hover 자체를 막는다 (차트는 클릭할 일이 없음)
async function hideTooltips(page) {
  await page.addStyleTag({ content:
    '.MuiTooltip-popper{display:none!important}' +
    '.echarts-for-react{pointer-events:none!important}'
  }).catch(()=>{});
}

async function callout(page, locator, text, {side = 'right', width = 360, gap = 16} = {}) {
  const b = await toBox(locator);
  await page.evaluate(({b, text, side, width, gap, css}) => {
    if (!document.getElementById('__gcallcss')) {
      const s = document.createElement('style'); s.id='__gcallcss'; s.textContent = css; document.head.appendChild(s);
    }
    let el = document.getElementById('__gcall');
    if (!el) { el = document.createElement('div'); el.id = '__gcall'; document.body.appendChild(el); }
    el.className = side;
    el.style.width = width + 'px';
    el.innerHTML = '<div class="tail"></div>' +
      text.split('\n').map(t => '<div>' + t.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</div>').join('');
    if (side === 'right') {
      el.style.left = Math.round(b.x + b.width + gap) + 'px';
      el.style.top  = Math.round(b.y + b.height/2 - 26) + 'px';
      el.style.setProperty('--ty', '18px');
    } else if (side === 'left') {
      el.style.left = Math.round(b.x - gap - width) + 'px';
      el.style.top  = Math.round(b.y + b.height/2 - 26) + 'px';
      el.style.setProperty('--ty', '18px');
    } else {
      el.style.left = Math.round(b.x) + 'px';
      el.style.top  = Math.round(b.y + b.height + gap) + 'px';
      el.style.setProperty('--tx', '26px');
    }
    // 화면 밖으로 나가면 안쪽으로 물리고, 꼬리 위치를 앵커에 맞춰 다시 잡는다
    requestAnimationFrame(() => {
      const M = 10;
      const h = el.offsetHeight;
      let L = parseFloat(el.style.left), T = parseFloat(el.style.top);
      const L2 = Math.min(Math.max(M, L), window.innerWidth  - width - M);
      const T2 = Math.min(Math.max(M, T), window.innerHeight - h     - M);
      if (side === 'bottom') {
        const ax = b.x + 26;                                  // 원래 꼬리가 가리키던 x
        el.style.setProperty('--tx', Math.min(Math.max(14, ax - L2), width - 26) + 'px');
      } else {
        const ay = b.y + b.height / 2;                        // 원래 꼬리가 가리키던 y
        el.style.setProperty('--ty', Math.min(Math.max(12, ay - T2 - 9), h - 21) + 'px');
      }
      el.style.left = L2 + 'px';
      el.style.top  = T2 + 'px';
      el.classList.add('on');
    });
  }, {b, text, side, width, gap, css: CALLOUT_CSS});
}

async function hideCallout(page) {
  await page.evaluate(() => { const e = document.getElementById('__gcall'); if (e) e.classList.remove('on'); });
}

// 지정한 영역을 반투명 흰색으로 덮어 시선을 뺏지 않게 한다 (영역 설명용)
async function dimRegion(page, rect, alpha = 0.78) {
  await page.evaluate(({r, a}) => {
    let el = document.getElementById('__gdim');
    if (!el) {
      el = document.createElement('div'); el.id = '__gdim';
      el.style.cssText = 'position:fixed;z-index:2147482990;pointer-events:none;transition:opacity .35s';
      document.body.appendChild(el);
    }
    el.style.left = r.x+'px'; el.style.top = r.y+'px';
    el.style.width = r.width+'px'; el.style.height = r.height+'px';
    el.style.background = `rgba(255,255,255,${a})`;
    el.style.opacity = '1';
  }, {r: rect, a: alpha});
}

async function undim(page) {
  await page.evaluate(() => { const e=document.getElementById('__gdim'); if(e) e.style.opacity='0'; });
}

// 폴더 행 / ⋮ 메뉴 헬퍼
function folderRow(page, name) {
  return page.locator(`div[role="button"]:has-text("${name}")`).first();
}
function menuPaper(page) {
  return page.locator('.MuiPopover-paper').first();
}
function menuItem(page, label) {
  const m = menuPaper(page);
  // '녹음' 은 아이콘+텍스트가 Stack 으로 묶여 있어 Stack 전체를 잡아야 강조가 예쁨
  if (label === '녹음') return m.locator('.MuiStack-root').first();
  return m.getByText(label, { exact: true }).first();
}

module.exports = { installCursor, moveTo, highlight, clickAt, typeText, callout, hideCallout, hideTooltips, folderRow, menuItem, menuPaper, toBox, dimRegion, undim };
