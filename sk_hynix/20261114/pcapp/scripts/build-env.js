#!/usr/bin/env node
// 개발/운영 설치 파일 만들기
//   npm run build:dev   → APP_ENV=dev  (app.config.json 의 "dev" 묶음 값)
//   npm run build:prod  → APP_ENV=prod (app.config.json 의 "prod" 묶음 값)
//
// 하는 일: src/config/app.env.json 에 { "APP_ENV": "..." } 를 잠깐 써서 설치본에 같이 넣고,
//          electron-builder 를 돌린 뒤 그 파일을 지운다. app.config.json 은 건드리지 않는다.
// (기존 npm run build 는 app.config.json 의 "APP_ENV" 를 그대로 쓴다)

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const env = String(process.argv[2] || '').toLowerCase();
if (!['dev', 'prod'].includes(env)) {
  console.error('사용법: node scripts/build-env.js dev|prod');
  process.exit(1);
}

const envFile = path.join(__dirname, '..', 'src', 'config', 'app.env.json');
fs.writeFileSync(envFile, JSON.stringify({ APP_ENV: env }, null, 2) + '\n');
console.log(`[build-env] APP_ENV=${env} 로 빌드합니다 (${path.relative(process.cwd(), envFile)})`);

let status = 1;
try {
  const bin = path.join(__dirname, '..', 'node_modules', '.bin', process.platform === 'win32' ? 'electron-builder.cmd' : 'electron-builder');
  const args = ['--publish', 'never', ...process.argv.slice(3)];
  const r = spawnSync(bin, args, { stdio: 'inherit', shell: process.platform === 'win32' });
  status = r.status === null ? 1 : r.status;
} finally {
  try { fs.unlinkSync(envFile); } catch (_) {}
}
process.exit(status);
