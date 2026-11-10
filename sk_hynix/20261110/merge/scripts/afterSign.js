const path = require('path');

// 사용자에게 보이는 앱 이름(고객사 이름). 내부 이름(productName)은 timbloRecApp 그대로 둔다.
const DISPLAY_NAME = 'SKHynixRecApp';

/**
 * Windows: exe 의 "파일 설명"·"제품 이름"을 DISPLAY_NAME 으로 바꾼다.
 * electron-builder 는 이 둘에 productName 을 넣는데, 브라우저가 앱 주소(timbloRecApp://)를 열 때
 * "○○을(를) 여시겠습니까?" 와 작업 관리자에 이 값이 그대로 보인다.
 * electron-builder 가 쓰는 같은 도구(rcedit, 반입한 winCodeSign 캐시)를 쓰므로 추가 설치는 없다.
 * ⚠️ 서명 단계 뒤에 exe 를 고친다. 지금은 Windows 코드 서명을 하지 않아 문제없지만,
 *    나중에 서명을 붙이면 서명이 깨지므로 그때 이 방법을 다시 검토해야 한다.
 */
async function setWindowsDisplayName(context) {
  const { executeAppBuilder } = require('builder-util');
  const exe = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.exe`);
  const args = [
    exe,
    '--set-version-string', 'FileDescription', DISPLAY_NAME,
    '--set-version-string', 'ProductName', DISPLAY_NAME,
  ];
  await executeAppBuilder(['rcedit', '--args', JSON.stringify(args)], undefined, {}, 3);
  console.log(`[afterSign] ${path.basename(exe)} 파일 설명·제품 이름 → ${DISPLAY_NAME}`);
}

/**
 * electron-builder afterSign 훅
 * - Windows: exe 표시 이름 변경
 * - macOS: 앱 서명 후 Apple Notarization 수행
 */
exports.default = async function(context) {
  const { electronPlatformName, appOutDir } = context;

  if (electronPlatformName === 'win32') {
    await setWindowsDisplayName(context);
    return;
  }

  // 이하 macOS만 처리
  if (electronPlatformName !== 'darwin') {
    return;
  }
  const { notarize } = require('@electron/notarize');

  // 환경변수 확인
  if (!process.env.APPLE_ID || !process.env.APPLE_APP_SPECIFIC_PASSWORD) {
    console.warn('\n⚠️  Notarization 건너뜀: 환경변수 미설정');
    console.warn('   APPLE_ID 및 APPLE_APP_SPECIFIC_PASSWORD 설정 필요\n');
    return;
  }

  const appName = context.packager.appInfo.productFilename;
  const appPath = `${appOutDir}/${appName}.app`;

  console.log('\n🍎 Apple Notarization 시작...');
  console.log(`📍 앱 경로: ${appPath}`);
  console.log(`📧 Apple ID: ${process.env.APPLE_ID}`);
  console.log(`🏢 Team ID: ${process.env.APPLE_TEAM_ID || '7H4827QYPR'}`);
  console.log('\n⏳ Notarization 진행 중... (5-15분 소요)\n');

  try {
    await notarize({
      appBundleId: 'net.timbel.timblo.recapp',
      appPath: appPath,
      appleId: process.env.APPLE_ID,
      appleIdPassword: process.env.APPLE_APP_SPECIFIC_PASSWORD,
      teamId: process.env.APPLE_TEAM_ID || '7H4827QYPR',
    });

    console.log('\n✅ Notarization 성공!\n');
    console.log('🎉 앱이 Apple에 의해 공증되었습니다.');
    console.log('🚀 다른 Mac에서 보안 경고 없이 바로 실행 가능합니다!\n');
  } catch (error) {
    console.error('\n❌ Notarization 실패:', error.message);
    console.error('\n📋 실패 원인 확인:');
    console.error('   1. Apple ID / App-Specific Password 확인');
    console.error('   2. Team ID 확인 (7H4827QYPR)');
    console.error('   3. 앱이 Developer ID로 서명되었는지 확인');
    console.error('   4. Hardened Runtime 활성화 확인\n');
    throw error;
  }
};

