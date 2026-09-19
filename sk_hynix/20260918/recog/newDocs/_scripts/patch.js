// 가이드용 화면 보정: 템플릿 목록 4종 + 유형별 설명
// ※ 촬영 브라우저의 DOM 만 바꾼다. 서버/실제 사이트에는 아무 영향 없음.
const COMMON = ['*** 제목 ***', '** 키워드 **', '** 회의기본정보 **'];

const PATCH_ARGS = {
  templates: [
    { name: '기본형',     lines: COMMON },
    { name: '운영형',     lines: [...COMMON, '** 주제별 요약 **', '** 액션 아이템 **'] },
    { name: '의사결정형', lines: [...COMMON, '** 안건 및 논의사항 **', '** 결정사항 **'] },
    { name: '보고형',     lines: [...COMMON, '** 진행 경과 **', '** 보고 요약 **'] },
  ],
};

// 페이지 컨텍스트에서 실행 (인자는 객체 하나로)
function applyPatch({ templates }) {
  const findLeaf = (t) => [...document.querySelectorAll('*')]
    .find(n => n.children.length === 0 && n.textContent.trim() === t);

  const descHtml = (tpl) => `
    <div style="padding:20px 24px;font-size:16px;line-height:2.2;color:#1f2328">
      <div style="font-size:17px;font-weight:800;color:#1558d6;margin-bottom:14px">📑 ${tpl.name}</div>
      ${tpl.lines.map(l => `<div style="font-weight:700">${l}</div>`).join('<div style="height:10px"></div>')}
    </div>`;

  function setDesc(i) {
    const el = window.__gdescEl;
    if (el && templates[i]) el.innerHTML = descHtml(templates[i]);
  }
  window.__gsetDesc = setDesc;

  function patchOnce() {
    // ── 템플릿 설명 패널 (먼저 확보해야 목록 클릭 시 갱신 가능) ──
    const head = findLeaf('템플릿 설명');
    if (head) {
      const col = head.parentElement.parentElement;
      if (!col.hasAttribute('data-gpatched-desc')) {
        const body = [...col.children].filter(c => c !== head.parentElement);
        if (body.length) {
          col.setAttribute('data-gpatched-desc', '1');
          window.__gdescEl = body[body.length - 1];      // 아래쪽 넓은 영역
          body.slice(0, -1).forEach(c => c.remove());    // 높이 고정된 작은 박스 제거
          setDesc(window.__gcur || 0);
        }
      }
    }

    // ── 템플릿 목록 ──
    let list = document.querySelector('[data-gpatched-list]');
    if (!list) {
      const leaf = findLeaf('일반 회의록');
      if (leaf) list = leaf.parentElement.parentElement;   // <p> → 항목 div → 목록 컨테이너
    }
    if (list && !list.hasAttribute('data-gpatched-list')) {
      const items = [...list.children];
      const selP  = items[0].querySelector('p') || items[0];
      const othP  = (items[1] && items[1].querySelector('p')) || selP;
      const selCls = selP.getAttribute('class') || '';
      const norCls = othP.getAttribute('class') || '';
      const itemCls = items[0].getAttribute('class') || '';
      list.setAttribute('data-gpatched-list', '1');
      list.innerHTML = '';
      templates.forEach((tpl, i) => {
        const d = document.createElement('div');
        d.setAttribute('class', itemCls);
        d.style.cursor = 'pointer';
        const q = document.createElement('p');
        q.setAttribute('class', i === 0 ? selCls : norCls);
        q.textContent = tpl.name;
        d.appendChild(q);
        d.addEventListener('click', () => {
          window.__gcur = i;
          [...list.children].forEach((c, j) => {
            const pp = c.querySelector('p');
            if (pp) pp.setAttribute('class', j === i ? selCls : norCls);
          });
          setDesc(i);
        });
        list.appendChild(d);
      });
      window.__gcur = 0;
      setDesc(0);
    }
    return !!list;
  }

  patchOnce();
  if (!window.__gpatchMO) {                 // React 리렌더 / 모달 등장 시 자동 적용
    let last = 0, timer = null;
    const run = () => {
      const now = Date.now();
      if (now - last < 200) {
        if (!timer) timer = setTimeout(() => { timer = null; last = Date.now(); patchOnce(); }, 200);
        return;
      }
      last = now; patchOnce();
    };
    window.__gpatchMO = new MutationObserver(run);
    window.__gpatchMO.observe(document.body, { childList: true, subtree: true });
  }
  return true;
}

// ── LNB 보정 : '내 회의록' → '미완성 회의록' 으로 바꾸고 폴더 아래로 옮긴다 ──────────
// 실제 제품의 의도된 순서는  전체 회의록 / 생성한 폴더 / 미완성 회의록  인데
// 2026-09-19 기준 사이트에는 '미완성 회의록' 이 없고 '내 회의록' 이 폴더 위에 있다.
// 사이트에 반영되면 rec-lnb.js 에서 applyLnbPatch 호출 두 줄만 지우면 진짜 화면으로 재생성된다.
const LNB_ARGS = { from: '내 회의록', to: '미완성 회의록' };

function applyLnbPatch({ from, to }) {
  function patchOnce() {
    const ul = document.querySelector('.sidebar .MuiPaper-root ul.MuiList-root');
    if (!ul) return false;
    const liWith = (al) => [...ul.children].find(li => li.querySelector(`[aria-label="${al}"]`));

    // ① 이름 바꾸기
    const src = liWith(from);
    if (src) {
      const leaf = [...src.querySelectorAll('*')]
        .find(n => n.children.length === 0 && n.textContent.trim() === from);
      if (leaf) leaf.textContent = to;
      const btn = src.querySelector(`[aria-label="${from}"]`);
      if (btn) btn.setAttribute('aria-label', to);
    }

    // ② 사용자가 만든 폴더 아래로 옮기기
    //    사용자 폴더 행만 ⋮(더보기) 버튼을 갖는다 — '전체 회의록' 은 폴더 추가/접기라 걸리지 않는다
    const target = liWith(to);
    if (target) {
      const folders = [...ul.children].filter(li => li.querySelector('[aria-label="더보기"]'));
      const last = folders[folders.length - 1];
      if (last && last !== target && last.nextElementSibling !== target) last.after(target);
    }
    return true;
  }

  patchOnce();
  if (!window.__glnbMO) {                  // React 리렌더로 되돌아가면 다시 적용
    let last = 0, timer = null;
    const run = () => {
      const now = Date.now();
      if (now - last < 200) {
        if (!timer) timer = setTimeout(() => { timer = null; last = Date.now(); patchOnce(); }, 200);
        return;
      }
      last = now; patchOnce();
    };
    window.__glnbMO = new MutationObserver(run);
    window.__glnbMO.observe(document.body, { childList: true, subtree: true });
  }
  return true;
}

module.exports = { PATCH_ARGS, applyPatch, LNB_ARGS, applyLnbPatch };
