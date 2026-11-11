// X-Device-Timezone 헤더 값으로 국가 코드(ISO 3166 두 글자)를 찾는다.
//
// Node 기본 모듈만 쓴다. 대응표는 같은 폴더의 zone.tab (tzdata 2026e).
//
//   const { countryFromTimezone } = require('./zoneCountry');
//   countryFromTimezone('Asia/Seoul');        // 'KR'
//   countryFromTimezone('America/Chicago');   // 'US'
//   countryFromTimezone('UTC');               // null -> 기본 정책 적용

'use strict';

const fs = require('fs');
const path = require('path');

const HEADER_NAME = 'X-Device-Timezone';

// 대응표 위치. 환경 변수로 바꿀 수 있다.
const ZONE_TAB_PATH = process.env.ZONE_TAB_PATH || path.join(__dirname, 'zone.tab');

// zone.tab 에 없는 옛 이름 -> 현재 이름. 오래된 기기·브라우저가 보내는 값들.
const ALIASES = {
  'US/Eastern': 'America/New_York',
  'US/Central': 'America/Chicago',
  'US/Mountain': 'America/Denver',
  'US/Arizona': 'America/Phoenix',
  'US/Pacific': 'America/Los_Angeles',
  'US/Alaska': 'America/Anchorage',
  'US/Hawaii': 'Pacific/Honolulu',
  'America/Indianapolis': 'America/Indiana/Indianapolis',
  'America/Louisville': 'America/Kentucky/Louisville',
  'ROK': 'Asia/Seoul',
  'Japan': 'Asia/Tokyo',
  'PRC': 'Asia/Shanghai',
  'Asia/Chongqing': 'Asia/Shanghai',
  'Asia/Harbin': 'Asia/Shanghai',
  'Asia/Calcutta': 'Asia/Kolkata',
  'Asia/Saigon': 'Asia/Ho_Chi_Minh',
  'Asia/Katmandu': 'Asia/Kathmandu',
  'Asia/Rangoon': 'Asia/Yangon',
  'Europe/Kiev': 'Europe/Kyiv',
};

// 헤더 값으로 허용하는 형태. 그 밖의 값은 무시한다.
const VALID = /^[A-Za-z0-9_+\-/]{1,64}$/;

function load(file) {
  const table = new Map();
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (line.startsWith('#') || !line.trim()) continue;
    const cols = line.split('\t');
    if (cols.length >= 3) table.set(cols[2], cols[0]);
  }
  return table;
}

const ZONE_COUNTRY = load(ZONE_TAB_PATH);

// 시간대 이름 -> 국가 코드. 모르는 값이면 null.
function countryFromTimezone(value) {
  if (!value) return null;
  const tz = String(value).trim();
  if (!VALID.test(tz)) return null;
  return ZONE_COUNTRY.get(tz) || ZONE_COUNTRY.get(ALIASES[tz]) || null;
}

module.exports = { HEADER_NAME, countryFromTimezone };
