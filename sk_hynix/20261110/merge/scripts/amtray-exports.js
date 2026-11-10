#!/usr/bin/env node
// AM DLL 확인 — 우리가 부를 함수 4개가 있는지, 어떤 형식인지 **결론만 짧게** 보여 준다 (dumpbin 대신, Node 만 있으면 됨).
// DLL 을 실행(로드)하지 않고 파일만 읽으므로 안전하다.
//
//   node scripts/amtray-exports.js <DLL 3개가 있는 폴더>
//   node scripts/amtray-exports.js <폴더> --all      ← 함수 이름 전체 목록(필요할 때만)
//
// 결론 글자(A/B/C/D)와 함수 4개의 "있음/없음" 만 적어 오면 된다.

const fs = require('fs');
const path = require('path');

function parseExports(file) {
  const buf = fs.readFileSync(file);
  const u16 = (o) => buf.readUInt16LE(o);
  const u32 = (o) => buf.readUInt32LE(o);
  if (buf.length < 0x40 || u16(0) !== 0x5a4d) throw new Error('PE 파일이 아님 (MZ 없음)');
  const pe = u32(0x3c);
  if (u32(pe) !== 0x00004550) throw new Error('PE 파일이 아님 (PE 서명 없음)');
  const machine = u16(pe + 4);
  const numSections = u16(pe + 6);
  const optSize = u16(pe + 20);
  const characteristics = u16(pe + 22);
  const opt = pe + 24;
  const magic = u16(opt);
  const is64 = magic === 0x20b;
  const dataDir = opt + (is64 ? 112 : 96);
  const exportRva = u32(dataDir);
  const exportSize = u32(dataDir + 4);

  const sections = [];
  const secStart = opt + optSize;
  for (let i = 0; i < numSections; i++) {
    const s = secStart + i * 40;
    sections.push({
      name: buf.toString('latin1', s, s + 8).replace(/\0+$/, ''),
      vsize: u32(s + 8), va: u32(s + 12), rawSize: u32(s + 16), raw: u32(s + 20),
    });
  }
  const off = (rva) => {
    for (const s of sections) {
      const size = Math.max(s.vsize, s.rawSize);
      if (rva >= s.va && rva < s.va + size) return rva - s.va + s.raw;
    }
    throw new Error(`RVA 0x${rva.toString(16)} 위치를 찾을 수 없음`);
  };
  const cstr = (o) => {
    let e = o;
    while (e < buf.length && buf[e] !== 0) e++;
    return buf.toString('latin1', o, e);
  };

  const info = {
    file,
    machine: machine === 0x8664 ? 'x64' : machine === 0x14c ? 'x86(32bit)' : machine === 0xaa64 ? 'arm64' : `0x${machine.toString(16)}`,
    isDll: !!(characteristics & 0x2000),
    dllName: '',
    exports: [],
  };
  if (!exportRva || !exportSize) return info;

  const ed = off(exportRva);
  info.dllName = cstr(off(u32(ed + 12)));
  const base = u32(ed + 16);
  const numFuncs = u32(ed + 20);
  const numNames = u32(ed + 24);
  const addrFuncs = off(u32(ed + 28));
  const addrNames = numNames ? off(u32(ed + 32)) : 0;
  const addrOrds = numNames ? off(u32(ed + 36)) : 0;
  const named = new Set();
  for (let i = 0; i < numNames; i++) {
    const name = cstr(off(u32(addrNames + i * 4)));
    const idx = u16(addrOrds + i * 2);
    const fnRva = u32(addrFuncs + idx * 4);
    named.add(idx);
    const forwarded = fnRva >= exportRva && fnRva < exportRva + exportSize ? cstr(off(fnRva)) : '';
    info.exports.push({ ordinal: base + idx, name, forwarded });
  }
  for (let idx = 0; idx < numFuncs; idx++) {
    if (!named.has(idx) && u32(addrFuncs + idx * 4)) info.exports.push({ ordinal: base + idx, name: '(이름 없음)', forwarded: '' });
  }
  return info;
}

function kind(name) {
  if (name.startsWith('?') || name.startsWith('_Z')) return 'C++';
  if (name.startsWith('Java_')) return 'JNI';
  if (name.startsWith('(')) return '-';
  return 'C';
}

// Java_com_example_am_AmInterface_GetSystemTokenIT → com.example.am.AmInterface.GetSystemTokenIT (_1 은 _ 로)
function jniToJava(name) {
  return name.slice(5).replace(/_1/g, '\u0001').replace(/_/g, '.').replace(/\u0001/g, '_');
}


// ---- 우리가 부를 함수 4개와 가정한 형식 (AmHelper.cpp "★ 가정" 과 같다) ----
const WANTED = [
  { name: 'GetSystemTokenIT', alt: [], expect: 'const char* (const char*, const char*, const char*)' },
  { name: 'ShowSSOLoginUI', alt: ['ShowSSOLoingUI'], expect: 'bool (const char*)' },
  { name: 'SSOLogout', alt: [], expect: 'bool (const char*)' },
  { name: 'GetReturnMessage', alt: [], expect: 'const char* (const char*, const char*)' },
];

// MSVC C++ 이름 풀기 (간단한 형식만): ?GetSystemTokenIT@@YAPEBDPEBD00@Z → const char* (const char*, const char*, const char*)
const BASIC = { X: 'void', D: 'char', E: 'unsigned char', F: 'short', G: 'unsigned short', H: 'int', I: 'unsigned int', J: 'long', K: 'unsigned long', M: 'float', N: 'double' };
const EXT = { N: 'bool', W: 'wchar_t', J: '__int64', K: 'unsigned __int64' };
function demangleMsvc(mangled) {
  const m = /^\?([A-Za-z0-9_]+)@@Y[A-Z](.*)$/.exec(mangled);
  if (!m) return null;
  const s = m[2];
  let i = 0;
  const backrefs = [];
  function one() {
    const c = s[i];
    if (c >= '0' && c <= '9') { i++; return backrefs[Number(c)]; }
    if (c === '_') { const t = EXT[s[i + 1]]; i += 2; return t; }
    if (BASIC[c]) { i++; return BASIC[c]; }
    if (c === 'P' || c === 'Q') {
      i++;
      if (s[i] === 'E') i++;            // 64bit 포인터 표시
      const q = s[i++];                 // A = 그냥, B = const
      const inner = one();
      if (!inner) return null;
      const t = (q === 'B' ? 'const ' : '') + inner + '*';
      return t;
    }
    return null;                        // 클래스·템플릿 등은 못 푼다
  }
  const ret = one();
  if (!ret) return null;
  const params = [];
  while (i < s.length && s[i] !== '@' && s[i] !== 'Z') {
    const before = i;
    const t = one();
    if (!t) return null;
    if (t === 'void' && params.length === 0 && (s[i] === 'Z' || s[i] === '@')) break;
    params.push(t);
    if (i - before > 1 && backrefs.length < 10) backrefs.push(t);
  }
  return `${ret} (${params.join(', ')})`;
}

function findWanted(exportsList, w) {
  const names = [w.name, ...w.alt];
  for (const e of exportsList) {
    if (names.includes(e.name)) return { how: 'C', exact: e.name, real: e.name === w.name };
  }
  for (const e of exportsList) {
    const lower = e.name.toLowerCase();
    if (names.some((n) => lower === n.toLowerCase())) return { how: 'C', exact: e.name, real: false };
  }
  for (const e of exportsList) {
    if (e.name.startsWith('?') && names.some((n) => e.name.startsWith(`?${n}@@`))) {
      return { how: 'C++', exact: e.name, sig: demangleMsvc(e.name) };
    }
    if (e.name.startsWith('_Z') && names.some((n) => e.name.includes(`${n.length}${n}`))) {
      return { how: 'C++', exact: e.name, sig: null };
    }
  }
  return null;
}

function pickMainDll(files) {
  return files.find((f) => /aminterface-rt-x64\.dll$/i.test(path.basename(f)))
    || files.find((f) => /aminterface/i.test(path.basename(f)) && !/jni/i.test(path.basename(f)));
}

const argv = process.argv.slice(2);
const showAll = argv.includes('--all');
const targets = argv.filter((a) => a !== '--all');
if (!targets.length) {
  console.log('사용법: node scripts/amtray-exports.js <DLL 3개가 있는 폴더> [--all]');
  process.exit(1);
}
const files = [];
for (const t of targets) {
  if (fs.existsSync(t) && fs.statSync(t).isDirectory()) {
    for (const f of fs.readdirSync(t)) if (/\.dll$/i.test(f)) files.push(path.join(t, f));
  } else {
    files.push(t);
  }
}

if (showAll) {
  for (const f of files) {
    console.log('='.repeat(60));
    try {
      const info = parseExports(f);
      console.log(`${path.basename(f)}  (${info.machine}, 함수 ${info.exports.length}개)`);
      for (const e of info.exports) {
        let line = `  [${kind(e.name)}] ${e.name}`;
        if (kind(e.name) === 'JNI') line += `  → ${jniToJava(e.name)}`;
        const sig = e.name.startsWith('?') ? demangleMsvc(e.name) : null;
        if (sig) line += `  → ${sig}`;
        console.log(line);
      }
    } catch (err) {
      console.log(`${path.basename(f)}  오류: ${err.message}`);
    }
  }
  process.exit(0);
}

// ---- 결론 ----
console.log('');
const main = pickMainDll(files);
if (!main) {
  console.log('[결론] D — AmInterface-RT-X64.dll 을 찾지 못함 (폴더 확인)');
  process.exit(1);
}
let info;
try {
  info = parseExports(main);
} catch (err) {
  console.log(`[결론] D — ${path.basename(main)} 을 읽을 수 없음: ${err.message}`);
  process.exit(1);
}
if (info.machine !== 'x64') {
  console.log(`[결론] D — ${path.basename(main)} 이 64비트가 아님 (${info.machine})`);
  process.exit(1);
}

const found = WANTED.map((w) => ({ w, r: findWanted(info.exports, w) }));
const allFound = found.every((x) => x.r);
const anyCpp = found.some((x) => x.r && x.r.how === 'C++');

let verdict;
if (allFound && !anyCpp) verdict = 'A — C 함수로 바로 부를 수 있음 (다음: AmHelper 실행으로 형식 확인)';
else if (allFound) verdict = 'B — C++ 함수임 (아래 형식이 "가정과 같음" 인지 확인)';
else if (found.some((x) => x.r)) verdict = 'C — 함수 일부만 있음 (없는 것 이름이 다름)';
else verdict = 'C — 함수 4개 모두 이름이 다름';

console.log(`[결론] ${verdict}`);
for (const { w, r } of found) {
  const label = w.name.padEnd(17);
  if (!r) { console.log(`  ${label} 없음`); continue; }
  if (r.how === 'C') {
    console.log(`  ${label} 있음${r.real ? '' : `  (실제 이름: ${r.exact})`}`);
  } else if (r.sig) {
    const same = r.sig.replace(/\s/g, '') === w.expect.replace(/\s/g, '');
    console.log(`  ${label} 있음(C++)  ${same ? '가정과 같음' : `가정과 다름 → ${r.sig}`}`);
  } else {
    console.log(`  ${label} 있음(C++)  형식 못 풂 → --all 로 이 줄만 보기`);
  }
}
if (!allFound) {
  // 이름이 다를 때 힌트: 공개 함수가 적으면 이름만 보여 준다
  const names = info.exports.map((e) => e.name).filter((n) => !n.startsWith('('));
  console.log(`  공개 함수 ${names.length}개${names.length && names.length <= 12 ? ': ' + names.join(', ') : ' — --all 로 목록 보기'}`);
}
console.log('');
