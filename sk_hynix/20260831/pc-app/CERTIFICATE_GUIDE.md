# Apple Developer ID Certificate 발급 가이드

## 목차
1. [CSR 파일 생성](#1-csr-파일-생성)
2. [Developer ID Certificate 요청](#2-developer-id-certificate-요청)
3. [인증서 설치](#3-인증서-설치)
4. [Xcode 설정](#4-xcode-설정)
5. [electron-builder 설정](#5-electron-builder-설정)
6. [빌드 및 검증](#6-빌드-및-검증)

---

## 1. CSR 파일 생성

### 1-1. 키체인 접근 앱 실행

```bash
# Spotlight로 실행
⌘ + Space → "Keychain Access | 키체인 접근" 입력 → Enter


# 또는 Applications에서
/Applications/Utilities/Keychain\ Access.app
```

### 1-2. CSR 파일 생성

1. **메뉴바**: `Keychain Access` → `Certificate Assistant` → `Request a Certificate From a Certificate Authority...`

2. **정보 입력**:
   ```
   User Email Address: [회사 이메일]
   Common Name: [본인 이름 또는 회사명]
   CA Email Address: [비워둠]
   Request is: Saved to disk ✅
   Let me specify key pair information: [선택 사항]
   ```

3. **저장 위치**: 
   ```
   파일명: CertificateSigningRequest.certSigningRequest
   저장 위치: 데스크탑 (찾기 쉬운 곳)
   ```

4. **키 쌍 정보** (선택 사항):
   ```
   Key Size: 2048 bits (권장)
   Algorithm: RSA
   ```

5. **완료**: `Continue` 클릭 → CSR 파일 생성 완료

---

## 2. Developer ID Certificate 요청

### 2-1. Apple Developer 사이트 접속

1. https://developer.apple.com/ 접속
2. 회사 Apple ID로 로그인
3. **Account** 클릭

### 2-2. Certificates 페이지 이동

1. **Certificates, Identifiers & Profiles** 선택
2. 왼쪽 사이드바: **Certificates** 클릭
3. 오른쪽 상단: **+** (파란색 버튼) 클릭

### 2-3. 인증서 유형 선택

⚠️ **중요**: iOS용이 아닌 **macOS용** 선택!

```
Software 섹션:
├── Apple Development
├── Apple Distribution
├── Mac App Distribution
├── Mac Installer Distribution
└── Developer ID

    ✅ Developer ID Application  ← 선택!
    (macOS 앱을 App Store 외부에 배포)
    
    Developer ID Installer
    (설치 패키지용, 선택 사항)
```

**Developer ID Application** 선택 → `Continue`

---

#### ⚠️ "Developer ID Application"이 비활성화된 경우

**증상:**
```
Developer ID Application (회색으로 비활성화)
⚠️ This operation can only be performed by the Account Holder.
```

**원인:** Developer ID 인증서는 Account Holder(계정 소유자)만 생성 가능

**해결 방법:**

##### A. Account Holder에게 인증서 생성 요청 (권장)

1. **CSR 파일을 Account Holder에게 전달**
   ```
   CertificateSigningRequest.certSigningRequest 파일 전송
   ```

2. **Account Holder가 인증서 생성**
   - Developer ID Application 선택
   - CSR 업로드
   - 인증서 다운로드

3. **Account Holder가 .p12 파일 생성 및 공유**
   ```
   Keychain Access에서:
   1. Developer ID Application 우클릭
   2. Export "Developer ID Application..."
   3. 형식: Personal Information Exchange (.p12)
   4. 비밀번호 설정
   5. .p12 파일을 팀원에게 전달
   ```

4. **본인 Mac에 .p12 설치**
   ```bash
   # .p12 파일 더블클릭 또는
   open developer_id.p12
   
   # 비밀번호 입력 → 키체인에 설치
   ```

##### B. Admin 권한 요청

Account Holder에게 Admin 권한 부여 요청:
```
Apple Developer → Users and Access
→ [본인 계정] → Edit
→ Access: Admin 선택
```

##### C. 임시: Mac Development 사용 (외부 배포 불가)

외부 배포가 필요 없는 경우:
- **Mac Development** 선택
- 팀 멤버의 Mac에서만 실행 가능
- 외부 사용자에게 배포 불가능

---

### 2-4. CSR 파일 업로드

1. `Choose File` 클릭
2. 데스크탑의 `CertificateSigningRequest.certSigningRequest` 선택
3. `Continue` 클릭

### 2-5. 인증서 생성 완료

```
✅ Your certificate is ready.
   Developer ID Application
   [팀명]
```

**Download** 클릭 → `developerID_application.cer` 다운로드

---

## 3. 인증서 설치

### 3-1. 인증서 파일 더블클릭

```bash
# 다운로드 폴더에서
open ~/Downloads/developerID_application.cer
```

**결과**: 키체인에 자동으로 추가됨

### 3-2. 키체인에서 확인

1. **Keychain Access** 앱 실행
2. 왼쪽: `login` 키체인 선택
3. 카테고리: `My Certificates` 선택
4. 찾기: `Developer ID Application: [팀명] ([TEAM_ID])`

**확인 사항**:
```
✅ 인증서 이름: Developer ID Application: [팀명]
✅ 유효 기간: ~5년
✅ 하위에 개인 키(Private Key) 존재 ✓
   (삼각형 확장 시 보임)
```

### 3-3. Team ID 확인

인증서 이름에서 괄호 안의 10자리 코드가 **Team ID**입니다:
```
Developer ID Application: My Company (ABCD123456)
                                      ^^^^^^^^^^
                                      Team ID
```

**Team ID 메모**: 나중에 사용!

---

## 4. Xcode 설정

### 4-1. Xcode Preferences

1. Xcode 실행
2. 메뉴: `Xcode` → `Settings...` (⌘,)
3. **Accounts** 탭 선택

### 4-2. Apple ID 추가 (이미 있으면 생략)

1. 왼쪽 하단 **+** 클릭
2. **Apple ID** 선택
3. 회사 Apple ID 로그인

### 4-3. Team 확인

```
Apple ID: [회사 이메일]
├── Personal Team (개인)
└── [회사팀명] (Team)  ← 이것 선택!
    Role: Admin / App Manager
    Team ID: ABCD123456
```

### 4-4. 인증서 확인

1. Team 선택
2. 오른쪽 **Manage Certificates...** 클릭
3. 확인:
   ```
   ✅ Developer ID Application
      [회사팀명]
   ```

---

## 5. AudioHelper 프로젝트 설정

### 5-1. Xcode에서 프로젝트 열기

```bash
open /recording-pc-app/src/helpers/macos/AudioHelper/AudioHelper.xcodeproj
```

### 5-2. Signing & Capabilities 설정

1. **PROJECT** (왼쪽 최상단) 클릭
2. **TARGETS** → `AudioHelper` 선택
3. **Signing & Capabilities** 탭

**설정 변경**:
```
Automatically manage signing: ✅ 체크

Team: [회사팀명] (TEAM_ID) 선택
       ^^^ 드롭다운에서 선택

Signing Certificate: Developer ID Application
                     (자동 선택됨)

Provisioning Profile: -
                      (macOS 데스크톱 앱은 불필요)
```

### 5-3. Hardened Runtime 확인

**Hardened Runtime** 섹션이 있는지 확인:
- 없으면: `+ Capability` → `Hardened Runtime` 추가

**Resource Access** 섹션:
```
✅ Audio Input  (이미 설정되어 있어야 함)
```

### 5-4. Deployment Target 확인

**Build Settings** 탭:
```
macOS Deployment Target: 12.0 이상
(현재 15.0인 경우 그대로 유지 또는 12.0으로 변경)
```

### 5-5. Clean & Build

```
Product → Clean Build Folder (⇧⌘K)
Product → Build (⌘B)
```

**빌드 성공 확인!**

---

## 6. AudioHelper 복사 및 재서명

### 6-1. 빌드된 앱 찾기

```bash
# Xcode에서
Product → Show Build Folder in Finder

# 또는 DerivedData 경로
~/Library/Developer/Xcode/DerivedData/AudioHelper-*/Build/Products/Release/AudioHelper.app
```

### 6-2. 프로젝트에 복사

```bash
# 기존 앱 백업
mv src/helpers/macos/AudioHelper.app \
   src/helpers/macos/AudioHelper.app.backup

# 새 앱 복사
cp -R [빌드된 경로]/AudioHelper.app \
      src/helpers/macos/AudioHelper.app
```

### 6-3. 서명 확인

```bash
# Developer ID로 서명되었는지 확인
codesign -dv src/helpers/macos/AudioHelper.app

# 출력 예시:
# TeamIdentifier=ABCD123456  ✅ (ad-hoc이 아님!)
```

**⚠️ 중요**: Developer ID로 서명되었으면 `npm run sign-helper` **실행하지 않음!**

---

## 7. electron-builder 설정 (package.json)

### 7-1. identity: null 제거

```json
"mac": {
  "icon": "electron-resources/logo.png",
  "hardenedRuntime": true,  // ← false에서 true로 변경!
  "gatekeeperAssess": false,
  "entitlements": "build/entitlements.mac.plist",
  "entitlementsInherit": "build/entitlements.mac.plist",
  // "identity": null,  ← 이 줄 제거!
  "extendInfo": {
    "NSMicrophoneUsageDescription": "이 앱은 회의 녹음을 위해 마이크 접근 권한이 필요합니다.",
    "NSSystemAdministrationUsageDescription": "시스템 오디오 녹음을 위해 권한이 필요합니다."
  }
}
```

### 7-2. (선택) 명시적 Team ID 지정

```json
"mac": {
  // ... 기존 설정
  "identity": "Developer ID Application: [회사팀명] (ABCD123456)"
}
```

---

## 8. afterPack.js 수정

Developer ID 빌드 시 AudioHelper 재서명을 건너뛰도록 수정:

```javascript
exports.default = async function(context) {
  if (context.electronPlatformName !== 'darwin') {
    return;
  }

  const helperAppPath = path.join(
    context.appOutDir,
    `${context.packager.appInfo.productFilename}.app`,
    'Contents',
    'helpers',
    'macos',
    'AudioHelper.app'
  );

  // Developer ID 서명 확인
  try {
    const signature = execSync(
      `codesign -dv "${helperAppPath}" 2>&1 | grep "Authority=Developer ID"`
    ).toString();
    
    if (signature.includes('Developer ID')) {
      console.log('\n✅ AudioHelper는 이미 Developer ID로 서명됨 - 재서명 생략\n');
      // Protocol handler 등록만 진행
      // ... (기존 protocol handler 코드)
      return;
    }
  } catch (e) {
    // Developer ID 서명 없음 → ad-hoc 재서명 진행
  }

  // 기존 ad-hoc 재서명 코드...
};
```

---

## 9. Electron 앱 빌드

### 9-1. 빌드 실행

```bash
npm run build
```

### 9-2. 빌드 로그 확인

**성공 시 출력**:
```
✅ AudioHelper는 이미 Developer ID로 서명됨 - 재서명 생략

• signing file=dist/mac-arm64/timbloRecApp.app
  identity=Developer ID Application: [회사팀명] (ABCD123456)
  
• building target=DMG
```

**주의**: `identity=null` 또는 `adhoc` 나타나면 설정 오류!

---

## 10. 서명 검증

### 10-1. 메인 앱 서명 확인

```bash
codesign -dv --verbose=4 dist/mac-arm64/timbloRecApp.app

# 출력 확인:
# Authority=Developer ID Application: [회사팀명] (TEAM_ID)
# TeamIdentifier=ABCD123456
```

### 10-2. AudioHelper 서명 확인

```bash
codesign -dv dist/mac-arm64/timbloRecApp.app/Contents/helpers/macos/AudioHelper.app

# 출력 확인:
# TeamIdentifier=ABCD123456  (같은 Team ID!)
```

### 10-3. Entitlements 확인

```bash
# AudioHelper 마이크 권한 확인
codesign -d --entitlements - dist/mac-arm64/timbloRecApp.app/Contents/helpers/macos/AudioHelper.app | grep audio-input

# 출력:
# <key>com.apple.security.device.audio-input</key>
# <true/>
```

---

## 11. (선택) Notarization 설정

### 11-1. App-Specific Password 생성

1. https://appleid.apple.com/ 접속
2. **Sign-In and Security** → **App-Specific Passwords**
3. **Generate Password...**
4. 이름: `timbloRecApp Notarization`
5. 생성된 비밀번호 복사 (예: `abcd-efgh-ijkl-mnop`)

### 11-2. 환경변수 설정

```bash
# ~/.zshrc 또는 ~/.bash_profile에 추가
export APPLE_ID="your-company-email@example.com"
export APPLE_ID_PASSWORD="abcd-efgh-ijkl-mnop"
export APPLE_TEAM_ID="ABCD123456"
```

### 11-3. package.json에 notarize 추가

```json
"mac": {
  // ... 기존 설정
  "notarize": {
    "teamId": "ABCD123456"
  }
}
```

### 11-4. electron-notarize 설치

```bash
npm install --save-dev @electron/notarize
```

### 11-5. afterSign.js 생성

```javascript
// scripts/afterSign.js
const { notarize } = require('@electron/notarize');

exports.default = async function(context) {
  const { electronPlatformName, appOutDir } = context;
  if (electronPlatformName !== 'darwin') {
    return;
  }

  const appName = context.packager.appInfo.productFilename;

  return await notarize({
    appBundleId: 'com.example.timblo-rec-app',
    appPath: `${appOutDir}/${appName}.app`,
    appleId: process.env.APPLE_ID,
    appleIdPassword: process.env.APPLE_ID_PASSWORD,
    teamId: process.env.APPLE_TEAM_ID,
  });
};
```

### 11-6. package.json에 afterSign 추가

```json
"build": {
  // ...
  "afterPack": "./scripts/afterPack.js",
  "afterSign": "./scripts/afterSign.js",  // ← 추가
  // ...
}
```

---

## 12. 최종 배포

### 12-1. 빌드 (Notarization 포함)

```bash
npm run build

# 시간 소요: 10-15분 (Notarization)
```

### 12-2. 배포 파일

```
dist/
├── timbloRecApp-1.0.0-arm64-mac.zip  (배포용)
└── timbloRecApp-1.0.0-arm64.dmg      (배포용)
```

### 12-3. 사용자 경험

**Developer ID만:**
```
앱 실행 → 첫 실행 시 1회 경고 → "열기" 클릭 → 이후 자동 실행
```

**Developer ID + Notarization:**
```
앱 실행 → 바로 실행! (경고 없음) ✅✅
```

---

## 트러블슈팅

### Q1. "No signing identity found" 에러

```bash
# Xcode에서 인증서 확인
Xcode → Settings → Accounts → [Team] → Manage Certificates

# 인증서 다시 다운로드
Apple Developer → Certificates → Download
```

### Q2. "The specified item could not be found in the keychain"

```bash
# 키체인에서 인증서 확인
Keychain Access → My Certificates → Developer ID Application

# Private Key가 없으면 CSR부터 다시!
```

### Q3. Team ID를 찾을 수 없음

```bash
# Apple Developer 사이트에서 확인
Account → Membership → Team ID
```

### Q4. Notarization 실패

```bash
# 로그 확인
xcrun notarytool log [submission-id] --apple-id [email] --password [app-specific-password]

# 일반적 원인:
# - Hardened Runtime 미설정
# - Entitlements 문제
# - 서명 불일치
```

---

## 요약 체크리스트

- [ ] 1. CSR 파일 생성 (Keychain Access)
- [ ] 2. Developer ID Application 인증서 요청
- [ ] 3. 인증서 다운로드 및 설치
- [ ] 4. Xcode Accounts에서 Team 확인
- [ ] 5. AudioHelper 프로젝트에 Team 설정
- [ ] 6. AudioHelper 빌드 (Developer ID 서명)
- [ ] 7. package.json에서 `identity: null` 제거
- [ ] 8. `hardenedRuntime: true` 설정
- [ ] 9. afterPack.js 수정 (재서명 생략)
- [ ] 10. Electron 앱 빌드
- [ ] 11. 서명 검증 (codesign 확인)
- [ ] 12. (선택) Notarization 설정
- [ ] 13. 최종 배포

---

© 2025 Recording PC App - Apple Developer ID 배포 가이드

