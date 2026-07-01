/**
 * table_editor.js — Phase 4 V1 KMS MVP table editor (vanilla JS).
 *
 * For blocks of block_type='table'. Renders a contentEditable HTML table built
 * from either:
 *   - block.table_markdown (preferred — markdown table)
 *   - block.content        (fallback — parsed as markdown table)
 *
 * Operations: cell edit, add row, add column, delete row, delete column.
 * Save: serializes back to markdown and PATCH /blocks/{id} { content, block_type:'table' }.
 *
 * Public API:
 *   const ed = window.KmsTableEditor.mount(rootEl, { block, onSave });
 *   ed.flush();   // immediately persist current state
 *   ed.destroy();
 *
 * Dependencies: window.KmsApi.
 *
 * 메모리 절칙 — 하드코딩 행/열 max 없음, 이모지 없음, vanilla JS.
 */
(function (root) {
  'use strict';

  const DEBOUNCE_MS = 500;

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function debounce(fn, ms) {
    let t = null;
    const w = function () {
      const args = arguments;
      if (t) clearTimeout(t);
      t = setTimeout(function () { t = null; fn.apply(null, args); }, ms);
    };
    w.flush = function () { if (t) { clearTimeout(t); t = null; fn.apply(null, arguments); } };
    w.cancel = function () { if (t) { clearTimeout(t); t = null; } };
    return w;
  }

  /** Parse a markdown table into { headers: string[], rows: string[][] }. */
  function parseMarkdownTable(md) {
    if (!md || typeof md !== 'string') return { headers: [''], rows: [['']] };
    const lines = md.split('\n').map(function (l) { return l.trim(); }).filter(Boolean);
    if (!lines.length) return { headers: [''], rows: [['']] };

    function parseRow(line) {
      return line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (c) { return c.trim(); });
    }
    const headers = parseRow(lines[0]);
    let start = 1;
    if (lines.length > 1 && /^[\s|:\-]+$/.test(lines[1])) start = 2;

    const rows = [];
    for (let i = start; i < lines.length; i++) {
      const cells = parseRow(lines[i]);
      // pad / truncate to header length
      while (cells.length < headers.length) cells.push('');
      if (cells.length > headers.length) cells.length = headers.length;
      rows.push(cells);
    }
    if (!rows.length) rows.push(headers.map(function () { return ''; }));
    return { headers: headers, rows: rows };
  }

  /** Serialize { headers, rows } back to a markdown table. */
  function serializeMarkdownTable(data) {
    const h = (data.headers && data.headers.length) ? data.headers : [''];
    const out = ['| ' + h.map(function (c) { return (c || '').replace(/\|/g, '\\|'); }).join(' | ') + ' |'];
    out.push('|' + h.map(function () { return '---'; }).join('|') + '|');
    (data.rows || []).forEach(function (r) {
      const cells = [];
      for (let i = 0; i < h.length; i++) {
        cells.push(((r[i] != null ? r[i] : '') + '').replace(/\|/g, '\\|').replace(/\n/g, ' '));
      }
      out.push('| ' + cells.join(' | ') + ' |');
    });
    return out.join('\n');
  }

  function readDomState(rootEl) {
    const headerCells = rootEl.querySelectorAll('thead th[data-role="hcell"]');
    const headers = [];
    headerCells.forEach(function (c) { headers.push(c.innerText.trim()); });
    const rowEls = rootEl.querySelectorAll('tbody tr[data-role="row"]');
    const rows = [];
    rowEls.forEach(function (tr) {
      const cells = tr.querySelectorAll('td[data-role="cell"]');
      const arr = [];
      cells.forEach(function (td) { arr.push(td.innerText.trim()); });
      rows.push(arr);
    });
    return { headers: headers, rows: rows };
  }

  function renderTable(rootEl, data) {
    const h = data.headers || [''];
    const r = data.rows || [[]];
    let html = '<div class="kte-toolbar">';
    html += '<button type="button" class="kte-btn" data-action="add-row">행 추가</button>';
    html += '<button type="button" class="kte-btn" data-action="add-col">열 추가</button>';
    html += '<button type="button" class="kte-btn" data-action="del-row">행 삭제</button>';
    html += '<button type="button" class="kte-btn" data-action="del-col">열 삭제</button>';
    html += '<span class="kte-status" data-role="status" aria-live="polite"></span>';
    html += '</div>';
    html += '<table class="kte-table"><thead><tr>';
    h.forEach(function (c, i) {
      html += '<th data-role="hcell" data-col="' + i + '" contenteditable="true">' + esc(c) + '</th>';
    });
    html += '</tr></thead><tbody>';
    r.forEach(function (row, ri) {
      html += '<tr data-role="row" data-row="' + ri + '">';
      for (let i = 0; i < h.length; i++) {
        const v = row[i] != null ? row[i] : '';
        html += '<td data-role="cell" data-row="' + ri + '" data-col="' + i + '" contenteditable="true">' + esc(v) + '</td>';
      }
      html += '</tr>';
    });
    html += '</tbody></table>';
    rootEl.innerHTML = html;
  }

  function mount(rootEl, options) {
    if (!rootEl) throw new Error('[table_editor] rootEl required');
    const opts = options || {};
    let block = opts.block || {};
    const onSave = typeof opts.onSave === 'function' ? opts.onSave : null;

    rootEl.classList.add('kte-block');
    rootEl.dataset.blockId = block.id || '';

    const md = block.table_markdown || block.content || '';
    let data = parseMarkdownTable(md);
    let selectedCol = 0;
    let selectedRow = 0;

    function refresh() {
      renderTable(rootEl, data);
      bind();
    }

    function setStatus(t, kind) {
      const el = rootEl.querySelector('[data-role="status"]');
      if (!el) return;
      el.textContent = t || '';
      el.dataset.kind = kind || '';
    }

    async function persist() {
      if (!root.KmsApi) { setStatus('API 미연결', 'error'); return; }
      if (!block.id) { setStatus('blockId 없음', 'error'); return; }
      const current = readDomState(rootEl);
      data = current;
      const newMd = serializeMarkdownTable(current);
      setStatus('저장 중...', 'pending');
      try {
        const updated = await root.KmsApi.patch('/blocks/' + block.id, {
          content: newMd,
          block_type: 'table',
          metadata: { table_markdown: newMd },
        });
        if (updated && typeof updated === 'object') {
          block = Object.assign({}, block, updated);
          rootEl.dataset.blockId = block.id;
        } else {
          block.content = newMd;
          block.table_markdown = newMd;
        }
        setStatus('저장됨', 'ok');
        if (onSave) onSave(block);
      } catch (e) {
        setStatus('저장 실패: ' + (e.message || e), 'error');
      }
    }

    const debouncedPersist = debounce(persist, DEBOUNCE_MS);

    function bind() {
      // cell focus tracking
      rootEl.querySelectorAll('[data-role="cell"], [data-role="hcell"]').forEach(function (el) {
        el.addEventListener('focus', function () {
          selectedCol = parseInt(el.dataset.col, 10) || 0;
          const r = el.dataset.row;
          if (r != null) selectedRow = parseInt(r, 10) || 0;
        });
        el.addEventListener('input', function () {
          setStatus('편집 중...', 'pending');
          debouncedPersist();
        });
      });

      // toolbar
      rootEl.querySelectorAll('[data-action]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          const action = btn.dataset.action;
          const cur = readDomState(rootEl);
          if (action === 'add-row') {
            cur.rows.push(cur.headers.map(function () { return ''; }));
          } else if (action === 'add-col') {
            cur.headers.push('');
            cur.rows.forEach(function (r) { r.push(''); });
          } else if (action === 'del-row') {
            if (cur.rows.length > 1) cur.rows.splice(selectedRow, 1);
          } else if (action === 'del-col') {
            if (cur.headers.length > 1) {
              cur.headers.splice(selectedCol, 1);
              cur.rows.forEach(function (r) { r.splice(selectedCol, 1); });
            }
          }
          data = cur;
          refresh();
          debouncedPersist();
        });
      });
    }

    refresh();

    return {
      get block() { return block; },
      get data() { return data; },
      flush: function () { debouncedPersist.flush(); },
      destroy: function () {
        debouncedPersist.cancel();
        rootEl.innerHTML = '';
        rootEl.classList.remove('kte-block');
      },
      // exposed for tests
      _parse: parseMarkdownTable,
      _serialize: serializeMarkdownTable,
    };
  }

  function injectStyles() {
    if (!root.document || root.document.getElementById('kte-styles')) return;
    const s = root.document.createElement('style');
    s.id = 'kte-styles';
    s.textContent = [
      '.kte-block { border:1px solid var(--border,#30363d); border-radius:6px; padding:10px; margin-bottom:8px; background:var(--bg,#0e1117); color:var(--text,#e6edf3); font-size:13px; overflow-x:auto; }',
      '.kte-toolbar { display:flex; gap:6px; align-items:center; margin-bottom:8px; font-size:11px; }',
      '.kte-btn { padding:3px 8px; border:1px solid var(--border,#30363d); background:transparent; color:inherit; border-radius:4px; cursor:pointer; font-size:11px; }',
      '.kte-btn:hover { border-color:var(--accent,#6c8cff); color:var(--accent,#6c8cff); }',
      '.kte-status[data-kind="pending"] { color:var(--yellow,#e3b341); margin-left:auto; }',
      '.kte-status[data-kind="ok"] { color:var(--green,#3fb950); margin-left:auto; }',
      '.kte-status[data-kind="error"] { color:var(--red,#f87171); margin-left:auto; }',
      '.kte-table { width:100%; border-collapse:collapse; font-size:12px; }',
      '.kte-table th, .kte-table td { border:1px solid var(--border,#30363d); padding:6px 8px; vertical-align:top; }',
      '.kte-table th { background:var(--surface2,#1a1d2e); text-align:left; }',
      '.kte-table th:focus, .kte-table td:focus { outline:2px solid var(--accent,#6c8cff); outline-offset:-2px; background:rgba(108,140,255,0.08); }',
    ].join('\n');
    root.document.head.appendChild(s);
  }

  root.KmsTableEditor = {
    mount: function (el, opts) { injectStyles(); return mount(el, opts); },
    _parse: parseMarkdownTable,
    _serialize: serializeMarkdownTable,
  };
})(typeof window !== 'undefined' ? window : globalThis);
