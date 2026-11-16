// 요약 템플릿 목록 (업로드 팝업 "AI 요약 준비하기"의 템플릿 선택)
// - 로그인 직후 한 번 받아 두고, 업로드 팝업을 열 때마다 다시 받아 갱신한다.
// - 마지막으로 받은 목록은 파일(userData/templates.json)에 남겨, 서버가 안 될 때도 그 목록을 보여준다.
// - 한 번도 못 받았으면 "기본형"만 보여주고 templateId 를 비워 보낸다(서버가 DEF-BASIC 으로 처리).
// - 주소·응답 필드 이름은 apiEndpoints.js 의 templates 항목에서 바꾼다.

const fs = require('fs');
const path = require('path');
const { app } = require('electron');
const logger = require('../logger');
const endpoints = require('./apiEndpoints');
const userService = require('./userService');

const FALLBACK = [{ code: '', name: '기본형' }];

let cached = null; // [{ code, name }]

function cacheFile() {
  return path.join(app.getPath('userData'), 'templates.json');
}

function readCacheFile() {
  try {
    const list = JSON.parse(fs.readFileSync(cacheFile(), 'utf8'));
    return Array.isArray(list) && list.length ? list : null;
  } catch (_) {
    return null;
  }
}

function writeCacheFile(list) {
  try { fs.writeFileSync(cacheFile(), JSON.stringify(list), 'utf8'); } catch (_) {}
}

// 응답 본문에서 [{ code, name }] 을 꺼낸다.
function parseList(body) {
  const def = endpoints.templates;
  const raw = def.list
    ? String(def.list).split('.').reduce((acc, key) => (acc == null ? undefined : acc[key]), body)
    : body;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => ({
      code: item && item[def.codeKey] != null ? String(item[def.codeKey]) : '',
      name: item && item[def.nameKey] != null ? String(item[def.nameKey]) : '',
    }))
    .filter((t) => t.code && t.name);
}

// 서버에서 다시 받는다. 실패하면 갖고 있던 목록을 그대로 둔다.
async function refresh() {
  const res = await userService.callApi('templates');
  if (!res.success) return getCached();
  const list = parseList(res.data);
  if (list.length === 0) {
    try { logger.logWarn('templates_empty', { hint: 'apiEndpoints.templates 의 list/codeKey/nameKey 확인' }); } catch (_) {}
    return getCached();
  }
  cached = list;
  writeCacheFile(list);
  try { logger.logInfo('templates_loaded', { count: list.length }); } catch (_) {}
  return list;
}

function getCached() {
  if (!cached) cached = readCacheFile();
  return cached || FALLBACK;
}

module.exports = { refresh, getCached };
