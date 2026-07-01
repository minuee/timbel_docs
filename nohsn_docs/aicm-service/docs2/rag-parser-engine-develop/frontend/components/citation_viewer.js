/**
 * citation_viewer.js — Phase 4 V1 KMS MVP PDF.js viewer + citation deep-link.
 *
 * - Lazy-loads PDF.js from CDN (cdnjs 3.11.174 — matches existing doc-detail.js).
 * - Renders all pages of /api/v1/documents/{docId}/pdf into <canvas> stack.
 * - jumpTo(citation) / jumpToBlock(block) scrolls to page + draws bbox highlight.
 *
 * Public API:
 *   const v = window.KmsCitationViewer.mount(rootEl, { docId, blocks });
 *   v.jumpToBlock(blockId);
 *   v.jumpToCitation({ page_number, bbox });
 *   v.destroy();
 *
 * Dependencies: window.KmsApi.
 *
 * bbox convention: PDF-point [x0, y0, x1, y1] with y bottom-up (matches v3 PdfPageViewer).
 *
 * 메모리 절칙 — vanilla JS, 이모지 X, CDN URL 은 const 로만 분리 (도메인 enum 아님).
 */
(function (root) {
  'use strict';

  const PDFJS_CDN_BASE = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174';
  const PDFJS_MAIN = PDFJS_CDN_BASE + '/pdf.min.js';
  const PDFJS_WORKER = PDFJS_CDN_BASE + '/pdf.worker.min.js';
  const PDFJS_CMAP = PDFJS_CDN_BASE + '/cmaps/';
  const DEFAULT_SCALE = 1.2;

  function loadPdfJs() {
    if (typeof root.pdfjsLib !== 'undefined') return Promise.resolve(root.pdfjsLib);
    if (root._kmsPdfJsLoading) return root._kmsPdfJsLoading;
    root._kmsPdfJsLoading = new Promise(function (resolve, reject) {
      const s = root.document.createElement('script');
      s.src = PDFJS_MAIN;
      s.onload = function () {
        if (root.pdfjsLib && root.pdfjsLib.GlobalWorkerOptions) {
          root.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
        }
        resolve(root.pdfjsLib);
      };
      s.onerror = function () { reject(new Error('PDF.js 로딩 실패')); };
      root.document.head.appendChild(s);
    });
    return root._kmsPdfJsLoading;
  }

  function mount(rootEl, options) {
    if (!rootEl) throw new Error('[citation_viewer] rootEl required');
    const opts = options || {};
    const docId = opts.docId;
    let blocks = opts.blocks || [];
    const scale = opts.scale || DEFAULT_SCALE;

    rootEl.classList.add('kcv-viewer');
    rootEl.innerHTML = '<div class="kcv-status">PDF 로딩 중...</div>';

    let pdfDoc = null;
    let pageMeta = {}; // pageNumber -> { canvas, wrap, originalWidth, originalHeight, renderedWidth, renderedHeight }

    async function render() {
      if (!docId) {
        rootEl.innerHTML = '<div class="kcv-status kcv-error">docId 없음</div>';
        return;
      }
      if (!root.KmsApi) {
        rootEl.innerHTML = '<div class="kcv-status kcv-error">KmsApi 미연결</div>';
        return;
      }
      try {
        await loadPdfJs();
      } catch (e) {
        rootEl.innerHTML = '<div class="kcv-status kcv-error">' + (e.message || 'PDF.js 로딩 실패') + '</div>';
        return;
      }
      const pdfUrl = root.KmsApi.url('/documents/' + docId + '/pdf');
      const headers = { 'X-Tenant-Id': root.KmsApi.getTenantId() };
      const jwt = root.KmsApi.getJwt();
      if (jwt) headers['Authorization'] = 'Bearer ' + jwt;

      try {
        const loadingTask = root.pdfjsLib.getDocument({
          url: pdfUrl,
          httpHeaders: headers,
          cMapUrl: PDFJS_CMAP,
          cMapPacked: true,
        });
        pdfDoc = await loadingTask.promise;
      } catch (e) {
        rootEl.innerHTML = '<div class="kcv-status kcv-error">PDF 로딩 실패: ' + (e.message || e) + '</div>';
        return;
      }

      rootEl.innerHTML = '<div class="kcv-pages" data-role="pages"></div>';
      const pagesContainer = rootEl.querySelector('[data-role="pages"]');

      for (let i = 1; i <= pdfDoc.numPages; i++) {
        const page = await pdfDoc.getPage(i);
        const viewport = page.getViewport({ scale: scale });

        const wrap = root.document.createElement('div');
        wrap.className = 'kcv-page-wrap';
        wrap.dataset.page = String(i);

        const canvas = root.document.createElement('canvas');
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.style.maxWidth = '100%';
        canvas.style.height = 'auto';
        const ctx = canvas.getContext('2d');

        const overlay = root.document.createElement('div');
        overlay.className = 'kcv-overlay';
        overlay.dataset.page = String(i);

        const label = root.document.createElement('div');
        label.className = 'kcv-page-label';
        label.textContent = i + ' / ' + pdfDoc.numPages + ' 페이지';

        wrap.appendChild(canvas);
        wrap.appendChild(overlay);
        wrap.appendChild(label);
        pagesContainer.appendChild(wrap);

        // Capture original viewport (PDF point) for bbox mapping
        const baseViewport = page.getViewport({ scale: 1 });
        pageMeta[i] = {
          canvas: canvas,
          wrap: wrap,
          overlay: overlay,
          originalWidth: baseViewport.width,
          originalHeight: baseViewport.height,
          renderedScale: scale,
        };

        await page.render({ canvasContext: ctx, viewport: viewport }).promise;
      }
    }

    function clearHighlights() {
      Object.keys(pageMeta).forEach(function (k) {
        const m = pageMeta[k];
        if (m && m.overlay) m.overlay.innerHTML = '';
        if (m && m.wrap) m.wrap.classList.remove('kcv-active');
      });
    }

    function highlightBbox(pageNumber, bbox) {
      const m = pageMeta[pageNumber];
      if (!m) return false;
      m.wrap.classList.add('kcv-active');
      if (!bbox || bbox.length < 4) return true;
      const x0 = bbox[0], y0 = bbox[1], x1 = bbox[2], y1 = bbox[3];
      const W = m.originalWidth, H = m.originalHeight;
      const left = (x0 / W) * 100;
      const width = ((x1 - x0) / W) * 100;
      // PDF y is bottom-up — flip to CSS top-down
      const top = ((H - y1) / H) * 100;
      const height = ((y1 - y0) / H) * 100;
      const box = root.document.createElement('div');
      box.className = 'kcv-bbox';
      box.style.left = left + '%';
      box.style.top = top + '%';
      box.style.width = width + '%';
      box.style.height = height + '%';
      m.overlay.appendChild(box);
      return true;
    }

    function jumpToCitation(citation) {
      if (!citation) return false;
      const page = citation.page_number || citation.page || null;
      if (!page) return false;
      clearHighlights();
      const m = pageMeta[page];
      if (!m) return false;
      m.wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
      highlightBbox(page, citation.bbox || null);
      return true;
    }

    function jumpToBlock(blockOrId) {
      let b = blockOrId;
      if (typeof blockOrId === 'string') {
        b = blocks.find(function (x) { return x.id === blockOrId; });
      }
      if (!b) return false;
      const sl = b.source_location || {};
      return jumpToCitation({
        page_number: sl.page_number,
        bbox: sl.bbox || (b.metadata && b.metadata.bbox) || null,
      });
    }

    // Auto-render
    render();

    return {
      jumpToCitation: jumpToCitation,
      jumpToBlock: jumpToBlock,
      clearHighlights: clearHighlights,
      setBlocks: function (newBlocks) { blocks = newBlocks || []; },
      destroy: function () {
        rootEl.innerHTML = '';
        rootEl.classList.remove('kcv-viewer');
        pageMeta = {};
        pdfDoc = null;
      },
    };
  }

  function injectStyles() {
    if (!root.document || root.document.getElementById('kcv-styles')) return;
    const s = root.document.createElement('style');
    s.id = 'kcv-styles';
    s.textContent = [
      '.kcv-viewer { background:var(--surface,#161b22); border-radius:6px; padding:8px; overflow-y:auto; }',
      '.kcv-status { padding:24px; text-align:center; color:var(--text2,#8b8fa3); font-size:13px; }',
      '.kcv-status.kcv-error { color:var(--red,#f87171); }',
      '.kcv-pages { display:flex; flex-direction:column; gap:12px; align-items:center; }',
      '.kcv-page-wrap { position:relative; border:1px solid var(--border,#30363d); background:#fff; }',
      '.kcv-page-wrap.kcv-active { border-color:var(--accent,#6c8cff); box-shadow:0 0 0 2px rgba(108,140,255,0.25); }',
      '.kcv-page-label { position:absolute; bottom:4px; right:6px; font-size:10px; padding:2px 6px; background:rgba(0,0,0,0.55); color:#fff; border-radius:3px; pointer-events:none; }',
      '.kcv-overlay { position:absolute; inset:0; pointer-events:none; }',
      '.kcv-bbox { position:absolute; border:2px solid var(--accent,#6c8cff); background:rgba(108,140,255,0.18); border-radius:2px; animation:kcv-pulse 1.4s ease-in-out infinite; }',
      '@keyframes kcv-pulse { 0%,100% { opacity:1; } 50% { opacity:0.45; } }',
    ].join('\n');
    root.document.head.appendChild(s);
  }

  root.KmsCitationViewer = {
    mount: function (el, opts) { injectStyles(); return mount(el, opts); },
    _loadPdfJs: loadPdfJs,
  };
})(typeof window !== 'undefined' ? window : globalThis);
