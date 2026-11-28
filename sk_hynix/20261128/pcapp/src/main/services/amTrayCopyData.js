// AM-Tray 로그인 알림(WM_COPYDATA)의 lParam → 사용자 hash 문자열 읽기
// - AM C++ 샘플(docs/sso-amtray-java/window-message.md 165~173행)과 같게 읽는다:
//     COPYDATASTRUCT *pCopyData = reinterpret_cast<COPYDATASTRUCT*>(lParam);
//     string LoginHashID(static_cast<char*>(pCopyData->lpData), pCopyData->cbData);
// - COPYDATASTRUCT (x64): dwData(8바이트) @0, cbData(4바이트) @8, (빈칸 4), lpData(8바이트) @16
// - Electron hookWindowMessage 는 lParam 을 "주소 값이 든 Buffer" 로 준다 → koffi 로 그 주소의 메모리를 읽는다.
//   DLL 을 부르는 게 아니라 메모리만 읽는다. 읽는 동안만 유효하므로 알림 처리 안에서 바로 부른다.
// - 실패하면 null (자동 로그인은 hash 없이도 계속된다).

const crypto = require('crypto');

const MAX_HASH_BYTES = 1024;

let koffi = null;
function loadKoffi() {
  if (!koffi) koffi = require('../vendor/koffi/index.cjs');
  return koffi;
}

function bufToAddress(buf) {
  if (!Buffer.isBuffer(buf)) return BigInt(buf || 0);
  return buf.length >= 8 ? buf.readBigUInt64LE(0) : BigInt(buf.readUInt32LE(0));
}

// lParam(Buffer | 주소) → { text, cbData } 또는 null
function readCopyData(lParam) {
  const k = loadKoffi();
  const base = typeof lParam === 'bigint' ? lParam : bufToAddress(lParam);
  if (!base) return null;
  const head = Buffer.from(k.view(base, 24));
  const cbData = head.readUInt32LE(8);
  const lpData = head.readBigUInt64LE(16);
  if (!lpData || !cbData) return { text: '', cbData };
  const len = Math.min(cbData, MAX_HASH_BYTES);
  const bytes = Buffer.from(k.view(lpData, len));
  // 샘플은 cbData 길이만큼 문자열로 읽는다. 끝에 NUL 이 들어 있으면 떼어 낸다.
  const end = bytes.indexOf(0);
  return { text: bytes.subarray(0, end < 0 ? bytes.length : end).toString('latin1'), cbData };
}

// hash 모양 (로그용 — 전체 값은 남기지 않고 앞 8글자만. 집에서 후보 값(사번·AD 계정 등)의 SHA-256 앞 8글자와 맞춰 본다)
function describeHash(text) {
  const s = String(text || '');
  const hex = /^[0-9a-fA-F]+$/.test(s);
  return {
    length: s.length,
    head: s.slice(0, 8),
    hex,
    case: !hex ? 'n/a' : /[a-f]/.test(s) && !/[A-F]/.test(s) ? 'lower' : /[A-F]/.test(s) && !/[a-f]/.test(s) ? 'upper' : /[a-fA-F]/.test(s) ? 'mixed' : 'digits',
  };
}

// 받은 hash 가 사번의 SHA-256 과 같은지. 대소문자는 무시(hex 일 때). 사번이 없으면 null(판단 불가).
function sameUser(hashText, empno) {
  const id = String(empno || '').trim();
  if (!id || !hashText) return null;
  const mine = crypto.createHash('sha256').update(id, 'utf8').digest('hex');
  return String(hashText).trim().toLowerCase() === mine;
}

// 내 사번의 SHA-256 앞 8글자 (로그 비교용)
function myHashHead(empno) {
  const id = String(empno || '').trim();
  return id ? crypto.createHash('sha256').update(id, 'utf8').digest('hex').slice(0, 8) : '';
}

module.exports = { readCopyData, describeHash, sameUser, myHashHead };
