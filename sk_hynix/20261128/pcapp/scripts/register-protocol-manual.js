#!/usr/bin/env node

/**
 * 빌드된 앱의 protocol handler를 수동으로 시스템에 등록
 * 사용법: npm run register-protocol
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

if (os.platform() !== 'darwin') {
  console.log('This script is only for macOS');
  process.exit(0);
}

const projectRoot = path.join(__dirname, '..');
const distDir = path.join(projectRoot, 'dist');

// dist 폴더에서 .app 파일 찾기
function findAppPath() {
  const possiblePaths = [
    path.join(distDir, 'mac-arm64', 'timbloRecApp.app'),
    path.join(distDir, 'mac', 'timbloRecApp.app'),
    path.join(distDir, 'mac-universal', 'timbloRecApp.app'),
  ];

  for (const appPath of possiblePaths) {
    if (fs.existsSync(appPath)) {
      return appPath;
    }
  }

  return null;
}

try {
  const appPath = findAppPath();

  if (!appPath) {
    console.error('❌ Built app not found in dist/ directory');
    console.error('Please run "npm run build" first');
    process.exit(1);
  }

  console.log(`Found app at: ${appPath}`);
  console.log('Registering protocol handler...');

  const lsregister = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister';
  execSync(`${lsregister} -f "${appPath}"`, { stdio: 'inherit' });

  console.log('✓ Protocol handler registered successfully!');
  console.log('\nYou can now test deeplinks without running the app first:');
  console.log('  open "timbloRecApp://connect?code=test&host=aHR0cHM6Ly9kZXYudGltYmxvLmlv"');
} catch (error) {
  console.error('❌ Failed to register protocol handler:', error.message);
  process.exit(1);
}

