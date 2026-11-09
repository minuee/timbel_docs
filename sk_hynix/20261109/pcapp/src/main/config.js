// 앱 설정값 읽기
//
// 읽는 순서 (앞에 있는 것이 이긴다)
//   1. 환경변수 / .env   — 개발할 때만. .env 는 설치본에 포함되지 않는다.
//   2. src/config/app.config.json — 빌드할 때 설치본에 같이 들어간다. 운영 값은 여기에.
//   3. 코드에 적힌 기본값
//
// 값의 이름과 설명은 저장소 루트의 .env.example 에 모두 적혀 있다.

const fs = require('fs');
const path = require('path');

let fileConfig = null;

function loadFileConfig() {
  if (fileConfig) return fileConfig;
  try {
    const file = path.join(__dirname, '../config/app.config.json');
    fileConfig = JSON.parse(fs.readFileSync(file, 'utf8')) || {};
  } catch (_) {
    // 파일이 없거나 깨졌으면 기본값으로 동작한다(앱이 못 뜨는 것보다 낫다).
    fileConfig = {};
  }
  return fileConfig;
}

function get(name, fallback) {
  const fromEnv = process.env[name];
  if (fromEnv !== undefined && fromEnv !== '') return fromEnv;
  const fromFile = loadFileConfig()[name];
  if (fromFile !== undefined && fromFile !== null && fromFile !== '') return fromFile;
  return fallback;
}

function getBool(name, fallback) {
  const value = get(name, fallback);
  if (typeof value === 'boolean') return value;
  return String(value).toLowerCase() === 'true';
}

module.exports = { get, getBool };
