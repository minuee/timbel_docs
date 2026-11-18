const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

/**
 * electron-builder afterPack 훅
 * 1. AudioHelper.app ad-hoc 재서명
 * 2. Protocol handler 등록
 */
exports.default = async function(context) {
  // macOS만 처리
  if (context.electronPlatformName !== 'darwin') {
    return;
  }

  // ========================================
  // 1. AudioHelper.app 서명 확인
  // ========================================
  // Developer ID 빌드 시 AudioHelper는 Xcode에서 이미 서명됨
  // ad-hoc 재서명 비활성화됨
  
  const appOutDir = context.appOutDir;
  const helperAppPath = path.join(
    appOutDir,
    `${context.packager.appInfo.productFilename}.app`,
    'Contents',
    'helpers',
    'macos',
    'AudioHelper.app'
  );

  // AudioHelper.app 존재 확인
  if (!fs.existsSync(helperAppPath)) {
    console.warn(`⚠️  AudioHelper.app을 찾을 수 없습니다: ${helperAppPath}`);
  } else {
    console.log(`\n📍 AudioHelper.app 경로: ${helperAppPath}`);
    
    // 서명 상태 확인만 진행
    try {
      const signature = execSync(`codesign -dv "${helperAppPath}" 2>&1`).toString();
      console.log('\n📋 AudioHelper 서명 확인:');
      console.log(signature);
      
      // Entitlements 확인
      const entitlementsResult = execSync(
        `codesign -d --entitlements - "${helperAppPath}" 2>&1`
      ).toString();
      
      if (entitlementsResult.includes('com.apple.security.device.audio-input')) {
        console.log('✅ 마이크 권한 entitlement 포함됨\n');
      } else {
        console.warn('⚠️  마이크 권한 entitlement 없음\n');
      }
    } catch (e) {
      console.warn('⚠️  AudioHelper 서명 확인 실패\n');
    }
  }

  /* 
   * ========================================
   * ad-hoc 재서명 로직 비활성화
   * ========================================
   * Developer ID 빌드 시 AudioHelper는 Xcode에서
   * 이미 Developer ID로 서명되어 있으므로 재서명 불필요
   * 
   * 개발 환경(identity: null)에서 사용하려면 아래 주석 해제
   * ========================================
   
  // Developer ID 서명 확인
  try {
    const signature = execSync(
      `codesign -dv "${helperAppPath}" 2>&1 | grep "Authority=Developer ID"`
    ).toString();
    
    if (signature.includes('Developer ID')) {
      console.log('\n✅ AudioHelper는 이미 Developer ID로 서명됨 - 재서명 생략\n');
      // Protocol handler 등록으로 건너뜀
    } else {
      throw new Error('Not Developer ID');
    }
  } catch (e) {
    // Developer ID 서명 없음 → ad-hoc 재서명 진행
    console.log('\n🔐 AudioHelper.app ad-hoc 재서명 시작...\n');

    const entitlementsPath = path.join(
      __dirname,
      '..',
      'src',
      'helpers',
      'macos',
      'AudioHelper',
      'AudioHelper',
      'AudioHelper.entitlements'
    );

    if (!fs.existsSync(entitlementsPath)) {
      console.warn(`⚠️  Entitlements 파일을 찾을 수 없습니다: ${entitlementsPath}`);
      return;
    }

    try {
      console.log('🗑️  기존 서명 제거 중...');
      execSync(`codesign --remove-signature "${helperAppPath}"`, { stdio: 'inherit' });

      console.log('✍️  ad-hoc 서명 적용 중...');
      execSync(
        `codesign --force --deep --sign - --entitlements "${entitlementsPath}" "${helperAppPath}"`,
        { stdio: 'inherit' }
      );

      console.log('\n📋 서명 확인:');
      const verifyResult = execSync(`codesign -dv "${helperAppPath}" 2>&1`).toString();
      console.log(verifyResult);

      console.log('\n📋 Entitlements 확인:');
      const entitlementsResult = execSync(
        `codesign -d --entitlements - "${helperAppPath}" 2>&1`
      ).toString();
      
      if (entitlementsResult.includes('com.apple.security.device.audio-input')) {
        console.log('✅ 마이크 권한 entitlement 포함됨');
      } else {
        console.warn('⚠️  마이크 권한 entitlement 없음');
      }

      console.log('\n✅ AudioHelper.app ad-hoc 재서명 완료!\n');
    } catch (error) {
      console.error('\n❌ AudioHelper.app 재서명 실패:', error.message);
      throw error;
    }
  }
  */

  // ========================================
  // 2. Protocol Handler 등록
  // ========================================
  try {
    const productName = context.packager.appInfo.productName;
    const appPath = path.join(appOutDir, `${productName}.app`);

    // 앱이 존재하는지 확인
    if (!fs.existsSync(appPath)) {
      console.warn(`⚠️  App not found at: ${appPath}`);
      return;
    }

    console.log(`\n🔗 Protocol handler 등록 중: ${appPath}\n`);
    
    // lsregister로 앱 등록
    const lsregister = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister';
    execSync(`${lsregister} -f "${appPath}"`, { stdio: 'inherit' });
    
    console.log('\n✅ Protocol handler 등록 완료!\n');
  } catch (error) {
    console.error('\n⚠️  Protocol handler 등록 실패:', error.message);
    // 에러가 나도 빌드는 계속 진행
  }
};

