#!/usr/bin/env node

/**
 * 빌드 후 protocol handler를 시스템에 자동 등록
 * electron-builder의 afterPack 훅에서 호출됨
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

exports.default = async function(context) {
  // macOS에서만 실행
  if (context.electronPlatformName !== 'darwin') {
    console.log('Skipping protocol registration (not macOS)');
    return;
  }

  try {
    const appOutDir = context.appOutDir;
    const productName = context.packager.appInfo.productName;
    const appPath = path.join(appOutDir, `${productName}.app`);

    // 앱이 존재하는지 확인
    if (!fs.existsSync(appPath)) {
      console.warn(`App not found at: ${appPath}`);
      return;
    }

    console.log(`Registering protocol handler for: ${appPath}`);
    
    // lsregister로 앱 등록
    const lsregister = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister';
    execSync(`${lsregister} -f "${appPath}"`, { stdio: 'inherit' });
    
    console.log('✓ Protocol handler registered successfully');
  } catch (error) {
    console.error('Failed to register protocol handler:', error.message);
    // 에러가 나도 빌드는 계속 진행
  }
};

