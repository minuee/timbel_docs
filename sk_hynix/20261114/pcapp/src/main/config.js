// 앱 설정값 읽기
//
// 읽는 순서 (앞에 있는 것이 이긴다)
//   1. 환경변수 / .env   — 개발할 때만. .env 는 설치본에 포함되지 않는다.
//   2. src/config/app.config.json 의 "dev" 또는 "prod" 묶음 — APP_ENV 로 고른 쪽 (URL·SSO 처럼 개발/운영이 다른 값)
//   3. src/config/app.config.json 의 바깥(공통) 값
//   4. 코드에 적힌 기본값
//
// APP_ENV (개발 "dev" / 운영 "prod") 정하는 순서:
//   환경변수 APP_ENV → src/config/app.env.json(빌드 명령 build:dev / build:prod 가 잠깐 만든다) → app.config.json 의 "APP_ENV" → "dev"
//
// 값의 이름과 설명은 저장소 루트의 .env.example 에 모두 적혀 있다.

const fs = require('fs');
const path = require('path');

const CONFIG_DIR = path.join(__dirname, '../config');
const ENVS = ['dev', 'prod'];

let fileConfig = null;
let envConfig = null;
let appEnv = null;

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8')) || {};
  } catch (_) {
    return null;
  }
}

function loadFileConfig() {
  if (fileConfig) return fileConfig;
  // 파일이 없거나 깨졌으면 기본값으로 동작한다(앱이 못 뜨는 것보다 낫다).
  fileConfig = readJson(path.join(CONFIG_DIR, 'app.config.json')) || {};
  return fileConfig;
}

// 지금 쓰는 환경: 'dev' | 'prod'
function getAppEnv() {
  if (appEnv) return appEnv;
  const candidates = [
    process.env.APP_ENV,
    (readJson(path.join(CONFIG_DIR, 'app.env.json')) || {}).APP_ENV,
    loadFileConfig().APP_ENV,
  ];
  appEnv = 'dev';
  for (const c of candidates) {
    const v = String(c || '').trim().toLowerCase();
    if (ENVS.includes(v)) { appEnv = v; break; }
  }
  return appEnv;
}

function loadEnvConfig() {
  if (envConfig) return envConfig;
  const section = loadFileConfig()[getAppEnv()];
  envConfig = section && typeof section === 'object' ? section : {};
  return envConfig;
}

function has(value) {
  return value !== undefined && value !== null && value !== '';
}

function get(name, fallback) {
  const fromEnv = process.env[name];
  if (has(fromEnv)) return fromEnv;
  const fromSection = loadEnvConfig()[name];
  if (has(fromSection)) return fromSection;
  const fromFile = loadFileConfig()[name];
  // "dev"/"prod" 묶음 자체는 값이 아니다
  if (has(fromFile) && !ENVS.includes(name)) return fromFile;
  return fallback;
}

function getBool(name, fallback) {
  const value = get(name, fallback);
  if (typeof value === 'boolean') return value;
  return String(value).toLowerCase() === 'true';
}

module.exports = { get, getBool, getAppEnv };
