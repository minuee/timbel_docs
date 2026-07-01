/**
 * api.js — V1 frontend JWT + tenant aware fetch wrapper (Phase 4 KMS MVP).
 *
 * - JWT from localStorage.jwt (JWT 미사용 — 무인증 모드 default)
 * - X-Tenant-Id from localStorage.tenant_id (fallback to globalThis.TENANT_ID)
 * - Base URL from globalThis.API (fallback /api/v1)
 *
 * Usage (vanilla, no bundler):
 *   <script src="/lib/api.js"></script>
 *   const list = await window.KmsApi.get(`/documents/${id}/blocks?limit=50`);
 *   await window.KmsApi.patch(`/blocks/${bid}`, { content: '...' });
 *
 * 메모리 절칙 — no hardcoded keyword lists, no emoji, V1 stack (vanilla JS).
 */
(function (root) {
  'use strict';

  const STORAGE_JWT_KEY = 'jwt';
  const STORAGE_TENANT_KEY = 'tenant_id';
  const DEFAULT_BASE = '/api/v1';

  function getBase() {
    if (typeof root.API === 'string' && root.API) return root.API;
    // Lucas-KMS — config.js 의 LUCAS_API_BASE 가 있으면 사용 (host:port + /api/v1).
    if (typeof root.LUCAS_API_BASE === 'string' && root.LUCAS_API_BASE) {
      return root.LUCAS_API_BASE.replace(/\/$/, '') + '/api/v1';
    }
    return DEFAULT_BASE;
  }

  function getJwt() {
    try { return root.localStorage && root.localStorage.getItem(STORAGE_JWT_KEY); }
    catch (_) { return null; }
  }

  function getTenantId() {
    try {
      const v = root.localStorage && root.localStorage.getItem(STORAGE_TENANT_KEY);
      if (v) return v;
    } catch (_) {/* ignore */}
    if (typeof root.LUCAS_TENANT_ID === 'string' && root.LUCAS_TENANT_ID) return root.LUCAS_TENANT_ID;
    if (typeof root.TENANT_ID === 'string' && root.TENANT_ID) return root.TENANT_ID;
    return '00000000-0000-0000-0000-000000000000';
  }

  function buildHeaders(extra, hasBody) {
    const h = {};
    h['X-Tenant-Id'] = getTenantId();
    const jwt = getJwt();
    if (jwt) h['Authorization'] = 'Bearer ' + jwt;
    if (hasBody) h['Content-Type'] = 'application/json';
    if (extra) Object.keys(extra).forEach(function (k) { h[k] = extra[k]; });
    return h;
  }

  function joinUrl(path) {
    if (/^https?:\/\//i.test(path)) return path;
    const base = getBase();
    if (path.charAt(0) === '/') return base + path;
    return base + '/' + path;
  }

  async function request(method, path, body, opts) {
    const o = opts || {};
    const url = joinUrl(path);
    const hasBody = body !== undefined && body !== null;
    const init = {
      method: method,
      headers: buildHeaders(o.headers, hasBody),
    };
    if (hasBody) init.body = JSON.stringify(body);
    if (o.signal) init.signal = o.signal;

    const res = await fetch(url, init);
    const ct = res.headers.get('content-type') || '';
    let data = null;
    if (o.rawBlob) {
      data = await res.blob();
    } else if (ct.indexOf('application/json') >= 0) {
      data = await res.json().catch(function () { return null; });
    } else {
      data = await res.text().catch(function () { return null; });
    }

    if (!res.ok) {
      let msg = res.statusText || ('HTTP ' + res.status);
      if (data && typeof data === 'object') {
        msg = (data.error && data.error.message) || data.detail || data.message || msg;
      }
      const err = new Error(msg);
      err.status = res.status;
      err.body = data;
      throw err;
    }

    // unwrap ApiResponse { success, data } if present
    if (data && typeof data === 'object' && data.success === true && 'data' in data) {
      return data.data;
    }
    return data;
  }

  const KmsApi = {
    getBase: getBase,
    getJwt: getJwt,
    getTenantId: getTenantId,
    request: request,
    get: function (path, opts) { return request('GET', path, null, opts); },
    post: function (path, body, opts) { return request('POST', path, body, opts); },
    patch: function (path, body, opts) { return request('PATCH', path, body, opts); },
    put: function (path, body, opts) { return request('PUT', path, body, opts); },
    delete: function (path, opts) { return request('DELETE', path, null, opts); },
    // Build URL for raw resource (PDF blob etc.) — caller may fetch directly.
    url: function (path) { return joinUrl(path); },
  };

  root.KmsApi = KmsApi;
  if (typeof module !== 'undefined' && module.exports) module.exports = KmsApi;
})(typeof window !== 'undefined' ? window : globalThis);
