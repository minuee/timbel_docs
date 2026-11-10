// 다국어(화면 언어)
//
// - 문구: src/locales/<언어>.json  (키 → 문구, {name} 자리에 값이 들어간다)
// - MULTI_LANG_ENABLED 가 true 일 때만 언어를 고를 수 있다. false(기본)면 저장된 값과 상관없이 항상 한국어.
// - 고른 언어는 userData/language.json 에 남겨 다음 실행에도 쓴다.
// - 화면(렌더러)은 preload 가 i18n:get-sync 로 받아 쓰고, 언어가 바뀌면 i18n:changed 로 모든 창에 알린다.
// - 한 언어에 키가 없으면 한국어 문구, 그것도 없으면 키를 그대로 보여준다.

const fs = require('fs');
const path = require('path');
const { app, BrowserWindow, ipcMain } = require('electron');
const config = require('./config');

const DEFAULT_LANG = 'ko';
// 메뉴에 보이는 이름은 각 언어 자기 이름으로 둔다(지금 언어와 상관없이 같은 글자)
const LANGUAGES = [
  { code: 'ko', name: '한국어' },
  { code: 'en', name: 'English' },
  { code: 'ja', name: '日本語' },
  { code: 'zh-CN', name: '简体中文' },
];

const messagesCache = {};
let currentLang = null;

function isEnabled() {
  return config.getBool('MULTI_LANG_ENABLED', false);
}

function isSupported(lang) {
  return LANGUAGES.some((l) => l.code === lang);
}

function loadMessages(lang) {
  if (messagesCache[lang]) return messagesCache[lang];
  try {
    const file = path.join(__dirname, '../locales', `${lang}.json`);
    messagesCache[lang] = JSON.parse(fs.readFileSync(file, 'utf8')) || {};
  } catch (_) {
    messagesCache[lang] = {};
  }
  return messagesCache[lang];
}

function settingsFile() {
  return path.join(app.getPath('userData'), 'language.json');
}

function readSavedLang() {
  try {
    const saved = JSON.parse(fs.readFileSync(settingsFile(), 'utf8'));
    return saved && isSupported(saved.lang) ? saved.lang : null;
  } catch (_) {
    return null;
  }
}

function getLang() {
  if (!isEnabled()) return DEFAULT_LANG;
  if (!currentLang) currentLang = readSavedLang() || DEFAULT_LANG;
  return currentLang;
}

function format(text, params) {
  if (!params) return text;
  return String(text).replace(/\{(\w+)\}/g, (all, name) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : all
  );
}

function t(key, params) {
  const lang = getLang();
  const own = loadMessages(lang)[key];
  const text = own !== undefined ? own : loadMessages(DEFAULT_LANG)[key];
  return format(text !== undefined ? text : key, params);
}

// 렌더러로 넘기는 값(preload 가 그대로 쓴다)
function snapshot() {
  const lang = getLang();
  return {
    enabled: isEnabled(),
    lang,
    languages: LANGUAGES,
    messages: loadMessages(lang),
    fallback: loadMessages(DEFAULT_LANG),
  };
}

function setLang(lang) {
  if (!isEnabled()) return { success: false, error: 'disabled' };
  if (!isSupported(lang)) return { success: false, error: 'unsupported' };
  currentLang = lang;
  try {
    fs.writeFileSync(settingsFile(), JSON.stringify({ lang }), 'utf8');
  } catch (_) {}
  const state = snapshot();
  BrowserWindow.getAllWindows().forEach((win) => {
    try {
      if (!win.isDestroyed()) win.webContents.send('i18n:changed', state);
    } catch (_) {}
  });
  return { success: true, lang };
}

function registerI18nIpc() {
  ipcMain.on('i18n:get-sync', (event) => {
    event.returnValue = snapshot();
  });
  ipcMain.handle('i18n:set-lang', (event, lang) => setLang(lang));
}

module.exports = { t, getLang, setLang, registerI18nIpc };
