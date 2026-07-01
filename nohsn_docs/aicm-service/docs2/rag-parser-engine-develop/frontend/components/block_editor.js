/**
 * block_editor.js — Phase 4 V1 KMS MVP block editor (vanilla JS).
 *
 * Renders a single block as a contentEditable card with:
 *   - inline text editing (contentEditable)
 *   - validity_status toggle (active / archived / disputed — backend allowed values)
 *   - debounced auto-save (500ms) — PATCH /blocks/{id}
 *
 * Public API:
 *   const editor = window.KmsBlockEditor.mount(rootEl, { block, onChange, onSave, onValiditySave });
 *   editor.update(newBlock);   // re-render with fresh block
 *   editor.destroy();          // remove + flush pending
 *
 * Dependencies: window.KmsApi (lib/api.js).
 *
 * 메모리 절칙 — no hardcoded label lists in HTML (driven by VALIDITY_OPTIONS const),
 *               no emoji, vanilla JS, no React.
 */
(function (root) {
  'use strict';

  if (!root.KmsApi) {
    // soft-warn — caller may load order issue. We still expose API.
    if (root.console) root.console.warn('[block_editor] KmsApi not loaded — auto-save will fail');
  }

  const DEBOUNCE_MS = 500;

  // Backend allowed values (src/api/routers/blocks.py VALID_VALIDITY_STATUSES).
  // Spec named "active / needs_review / excluded" — backend exposes
  //   active / historical / superseded / archived / purged / disputed.
  // MVP shows the three matching user-facing intents:
  //   active   = "유효"
  //   disputed = "검토 필요"  (matches spec's needs_review)
  //   archived = "제외"        (matches spec's excluded)
  const VALIDITY_OPTIONS = [
    { value: 'active',   label: '유효' },
    { value: 'disputed', label: '검토 필요' },
    { value: 'archived', label: '제외' },
  ];

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function debounce(fn, ms) {
    let t = null;
    const wrapped = function () {
      const args = arguments, ctx = this;
      if (t) clearTimeout(t);
      t = setTimeout(function () { t = null; fn.apply(ctx, args); }, ms);
    };
    wrapped.flush = function () {
      if (t) {
        clearTimeout(t); t = null;
        return fn.apply(null, arguments);
      }
    };
    wrapped.cancel = function () { if (t) { clearTimeout(t); t = null; } };
    return wrapped;
  }

  function buildShell(block) {
    const validity = (block && block.metadata && block.metadata.validity_status) || 'active';
    const indexed = block && block.is_indexed;
    const optsHtml = VALIDITY_OPTIONS.map(function (o) {
      const sel = (o.value === validity) ? ' selected' : '';
      return '<option value="' + esc(o.value) + '"' + sel + '>' + esc(o.label) + '</option>';
    }).join('');
    return [
      '<div class="kbe-header">',
      '  <span class="kbe-type" data-role="type">' + esc(block.block_type || 'paragraph') + '</span>',
      '  <span class="kbe-idx">#' + esc(block.block_index != null ? block.block_index : '-') + '</span>',
      '  <select class="kbe-validity" data-role="validity" aria-label="유효성 상태">' + optsHtml + '</select>',
      '  <span class="kbe-status" data-role="status" aria-live="polite"></span>',
      '  <span class="kbe-indexed" data-role="indexed" title="인덱싱 상태">' + (indexed ? '색인됨' : '재색인 필요') + '</span>',
      '</div>',
      '<div class="kbe-body" data-role="content" contenteditable="true" spellcheck="false">' + esc(block.content || '') + '</div>',
    ].join('');
  }

  function mount(rootEl, options) {
    if (!rootEl) throw new Error('[block_editor] rootEl required');
    const opts = options || {};
    let block = opts.block || {};
    const onChange = typeof opts.onChange === 'function' ? opts.onChange : null;
    const onSave = typeof opts.onSave === 'function' ? opts.onSave : null;
    const onValiditySave = typeof opts.onValiditySave === 'function' ? opts.onValiditySave : null;

    rootEl.classList.add('kbe-block');
    rootEl.dataset.blockId = block.id || '';
    rootEl.innerHTML = buildShell(block);

    const contentEl = rootEl.querySelector('[data-role="content"]');
    const statusEl = rootEl.querySelector('[data-role="status"]');
    const validityEl = rootEl.querySelector('[data-role="validity"]');

    function setStatus(text, kind) {
      if (!statusEl) return;
      statusEl.textContent = text || '';
      statusEl.dataset.kind = kind || '';
    }

    async function persistContent(newContent) {
      if (!root.KmsApi) { setStatus('API 미연결', 'error'); return; }
      if (!block.id) { setStatus('blockId 없음', 'error'); return; }
      setStatus('저장 중...', 'pending');
      try {
        const updated = await root.KmsApi.patch('/blocks/' + block.id, { content: newContent });
        if (updated && typeof updated === 'object') {
          block = Object.assign({}, block, updated);
          rootEl.dataset.blockId = block.id;
        } else {
          block.content = newContent;
        }
        setStatus('저장됨', 'ok');
        if (onSave) onSave(block);
      } catch (e) {
        setStatus('저장 실패: ' + (e.message || e), 'error');
      }
    }

    const debouncedSave = debounce(persistContent, DEBOUNCE_MS);

    if (contentEl) {
      contentEl.addEventListener('input', function () {
        const txt = contentEl.innerText;
        if (onChange) {
          try { onChange({ block: block, content: txt }); } catch (_) {/* noop */}
        }
        setStatus('편집 중...', 'pending');
        debouncedSave(txt);
      });
      // Save on blur (flush debounced)
      contentEl.addEventListener('blur', function () {
        debouncedSave.flush(contentEl.innerText);
      });
    }

    async function persistValidity(newStatus) {
      if (!root.KmsApi) { setStatus('API 미연결', 'error'); return; }
      if (!block.id) { setStatus('blockId 없음', 'error'); return; }
      setStatus('상태 저장 중...', 'pending');
      try {
        await root.KmsApi.patch('/blocks/' + block.id + '/validity', { status: newStatus, reason: '' });
        if (!block.metadata) block.metadata = {};
        block.metadata.validity_status = newStatus;
        setStatus('상태 저장됨', 'ok');
        if (onValiditySave) onValiditySave(block, newStatus);
      } catch (e) {
        setStatus('상태 저장 실패: ' + (e.message || e), 'error');
      }
    }

    if (validityEl) {
      validityEl.addEventListener('change', function () {
        persistValidity(validityEl.value);
      });
    }

    return {
      get block() { return block; },
      update: function (newBlock) {
        block = newBlock || {};
        rootEl.dataset.blockId = block.id || '';
        rootEl.innerHTML = buildShell(block);
        // re-bind
        const newContent = rootEl.querySelector('[data-role="content"]');
        const newValidity = rootEl.querySelector('[data-role="validity"]');
        if (newContent) {
          newContent.addEventListener('input', function () {
            debouncedSave(newContent.innerText);
          });
          newContent.addEventListener('blur', function () {
            debouncedSave.flush(newContent.innerText);
          });
        }
        if (newValidity) {
          newValidity.addEventListener('change', function () {
            persistValidity(newValidity.value);
          });
        }
      },
      flush: function () {
        const el = rootEl.querySelector('[data-role="content"]');
        if (el) debouncedSave.flush(el.innerText);
      },
      destroy: function () {
        debouncedSave.cancel();
        rootEl.innerHTML = '';
        rootEl.classList.remove('kbe-block');
      },
    };
  }

  // Minimal default CSS — host page may override.
  function injectStyles() {
    if (root.document && root.document.getElementById('kbe-styles')) return;
    if (!root.document) return;
    const s = root.document.createElement('style');
    s.id = 'kbe-styles';
    s.textContent = [
      '.kbe-block { border:1px solid var(--border,#30363d); border-radius:6px; padding:10px 12px; margin-bottom:8px; background:var(--bg,#0e1117); color:var(--text,#e6edf3); font-size:13px; }',
      '.kbe-block .kbe-header { display:flex; gap:8px; align-items:center; margin-bottom:6px; font-size:11px; color:var(--text2,#8b8fa3); }',
      '.kbe-block .kbe-type { padding:2px 6px; border-radius:3px; background:var(--surface2,#1a1d2e); }',
      '.kbe-block .kbe-validity { background:transparent; color:inherit; border:1px solid var(--border,#30363d); border-radius:4px; padding:2px 6px; font-size:11px; }',
      '.kbe-block .kbe-status[data-kind="pending"] { color:var(--yellow,#e3b341); }',
      '.kbe-block .kbe-status[data-kind="ok"] { color:var(--green,#3fb950); }',
      '.kbe-block .kbe-status[data-kind="error"] { color:var(--red,#f87171); }',
      '.kbe-block .kbe-body { min-height:32px; line-height:1.55; white-space:pre-wrap; word-break:break-word; outline:none; padding:6px 4px; border-radius:4px; }',
      '.kbe-block .kbe-body:focus { background:rgba(108,140,255,0.06); }',
    ].join('\n');
    root.document.head.appendChild(s);
  }

  root.KmsBlockEditor = {
    mount: function (el, opts) { injectStyles(); return mount(el, opts); },
    VALIDITY_OPTIONS: VALIDITY_OPTIONS,
    _debounce: debounce, // exposed for tests
  };
})(typeof window !== 'undefined' ? window : globalThis);
