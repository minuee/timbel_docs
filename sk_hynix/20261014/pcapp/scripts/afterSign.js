const { notarize } = require('@electron/notarize');

/**
 * electron-builder afterSign 훅
 * 앱 서명 후 Apple Notarization 수행
 */
exports.default = async function(context) {
  const { electronPlatformName, appOutDir } = context;
  
  // macOS만 처리
  if (electronPlatformName !== 'darwin') {
    return;
  }

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

