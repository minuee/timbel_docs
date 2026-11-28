// PC 고유 디바이스 ID
//
// 사용법:
//   const { getDeviceId } = require('./services/deviceService');
//   getDeviceId();  // 예: 'pc-3f9a1c0b7e2d4a58b6c1d0e9f8a7b6c5' (항상 같은 PC 면 같은 값)
//
// 만드는 방법
//   1. OS 가 가진 기기 고유값을 읽는다.
//        Windows: 레지스트리 HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid (OS 설치 시 생성)
//        macOS  : IOPlatformUUID (메인보드 기준)
//   2. 앱 고유 문자열과 섞어 SHA-256 → 앞 32자리. 원래 하드웨어 값은 밖으로 나가지 않고,
//      다른 앱이 같은 방식으로 만든 ID 와도 겹치지 않는다.
//   3. 1번이 실패하면(권한·정책 등) 무작위 UUID 를 만들어 앱 데이터 폴더에 저장해 두고 계속 쓴다.
//
// 특성
//   - 앱을 지웠다 다시 깔아도 같은 값 (1번 경로일 때)
//   - Windows 를 새로 설치하거나 이미지로 복제한 PC 는 MachineGuid 가 바뀌거나 겹칠 수 있다
//     (사내 PC 를 같은 이미지로 찍어 배포했는데 sysprep 을 안 했다면 여러 대가 같은 값일 수 있음)
//   - 'pc-' 접두어로 모바일 디바이스 ID 와 구분한다

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { app } = require('electron');

const SALT = 'timbloRecApp:device:v1';
const FILE_NAME = 'device-id';
let cached = null;
let cachedSource = null;

function readOsMachineId() {
  try {
    if (process.platform === 'win32') {
      // 64비트 레지스트리를 명시한다. 32비트 프로세스로 돌면 다른 위치를 볼 수 있다.
      const out = execFileSync(
        'reg',
        ['query', 'HKLM\\SOFTWARE\\Microsoft\\Cryptography', '/v', 'MachineGuid', '/reg:64'],
        { encoding: 'utf8', windowsHide: true, timeout: 3000 }
      );
      const m = out.match(/MachineGuid\s+REG_SZ\s+([0-9a-fA-F-]{36})/);
      return m ? m[1].toLowerCase() : null;
    }
    if (process.platform === 'darwin') {
      const out = execFileSync('ioreg', ['-rd1', '-c', 'IOPlatformExpertDevice'], { encoding: 'utf8', timeout: 3000 });
      const m = out.match(/"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]+)"/);
      return m ? m[1].toLowerCase() : null;
    }
  } catch (_) {}
  return null;
}

function readOrCreateStoredId() {
  const file = path.join(app.getPath('userData'), FILE_NAME);
  try {
    const saved = fs.readFileSync(file, 'utf8').trim();
    if (saved) return saved;
  } catch (_) {}
  const created = crypto.randomUUID();
  try { fs.writeFileSync(file, created, 'utf8'); } catch (_) {}
  return created;
}

function getDeviceId() {
  if (cached) return cached;
  let raw = readOsMachineId();
  cachedSource = raw ? 'os' : 'stored';
  if (!raw) raw = readOrCreateStoredId();
  const hash = crypto.createHash('sha256').update(`${SALT}:${raw}`).digest('hex').slice(0, 32);
  cached = `pc-${hash}`;
  return cached;
}

// 로그용: 어떤 경로로 만들어졌는지('os' | 'stored')
function getDeviceIdSource() {
  getDeviceId();
  return cachedSource;
}

module.exports = { getDeviceId, getDeviceIdSource };
