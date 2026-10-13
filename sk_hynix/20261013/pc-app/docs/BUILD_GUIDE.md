# timbloRecApp 빌드 가이드

## 목차
- [방식 A: 개발/테스트용 빌드 (ad-hoc 서명)](#방식-a-개발테스트용-빌드-ad-hoc-서명)
- [방식 B: 배포용 빌드 (Developer ID + Notarization)](#방식-b-배포용-빌드-developer-id--notarization)

---

## 방식 A: 개발/테스트용 빌드 (ad-hoc 서명)

**용도**: 내부 개발, 빠른 테스트  
**특징**: 빌드 속도 빠름, 사용자가 `xattr -cr` 명령 필요

### 1. AudioHelper 빌드 (Xcode)

```bash
# Xcode 프로젝트 열기
open src/helpers/macos/AudioHelper/AudioHelper.xcodeproj

# Xcode에서:
1. Product → Clean Build Folder (⇧⌘K)
2. Product → Build (⌘B)
3. Product → Show Build Folder in Finder
4. Build/Products/Debug(또는Release)/AudioHelper.app 복사
```

```bash
# 빌드된 앱을 프로젝트에 복사
cp -R ~/Library/Developer/Xcode/DerivedData/.../AudioHelper.app \
      src/helpers/macos/AudioHelper.app
```

### 2. AudioHelper ad-hoc 재서명

```bash
npm run sign-helper
```

**출력:**
```
🔐 AudioHelper.app 재서명 중...
✅ 기존 서명 제거 완료
✅ ad-hoc 서명 적용 완료
✅ 재서명 완료!
```

### 3. package.json 설정 확인

```json
"mac": {
  "hardenedRuntime": false,
  "identity": null,  // ← null이어야 함
  // ...
}
```

### 4. Electron 앱 빌드

```bash
npm run build
```

**빌드 로그:**
```
📍 AudioHelper.app 경로: .../AudioHelper.app
🔐 AudioHelper.app ad-hoc 재서명 시작...
✅ AudioHelper.app ad-hoc 재서명 완료!
🔗 Protocol handler 등록 완료!

• skipped macOS code signing  reason=identity explicitly is set to null
• building target=macOS zip
• building target=DMG
```

**빌드 시간**: ~3-5분

### 5. 빌드 검증

```bash
# AudioHelper 서명 확인
codesign -dv dist/mac-arm64/timbloRecApp.app/Contents/helpers/macos/AudioHelper.app

# 출력 확인:
# Signature=adhoc
# TeamIdentifier=not set
```

### 6. 배포 및 테스트

**배포 파일:**
- `dist/timbloRecApp-1.0.0-arm64-mac.zip` (110MB)

**다른 Mac에서 설치:**
```bash
# 1. 압축 해제 후 Applications 폴더로 이동
mv timbloRecApp.app /Applications/

# 2. Quarantine 제거
xattr -cr /Applications/timbloRecApp.app

# 3. 앱 실행
open /Applications/timbloRecApp.app
```

---

## 방식 B: 배포용 빌드 (Developer ID + Notarization)

**용도**: 외부 배포, 정식 릴리스  
**특징**: Apple 공증 완료, 보안 경고 없음

### 전제 조건

- ✅ Apple Developer Program 가입
- ✅ Developer ID Application 인증서 설치
- ✅ Team ID 확인 (예: 7H4827QYPR)

### 1. AudioHelper 빌드 (Developer ID 서명)

#### 1-1. Xcode 프로젝트 열기

```bash
open src/helpers/macos/AudioHelper/AudioHelper.xcodeproj
```

#### 1-2. Signing & Capabilities 설정

```
TARGETS → AudioHelper
→ Signing & Capabilities 탭

설정:
✅ Automatically manage signing: 체크
✅ Team: [회사 팀] 선택 (Team ID 확인)
✅ Signing Certificate: Developer ID Application (자동 선택)

Hardened Runtime:
✅ Resource Access → Audio Input 체크
```

#### 1-3. 빌드

```bash
# Clean & Build
Product → Clean Build Folder (⇧⌘K)
Product → Build (⌘B)

# 또는 Archive (권장)
Product → Archive
→ Distribute App
→ Developer ID
→ Export
```

#### 1-4. 서명 확인

```bash
# 빌드된 앱 위치 확인
# Product → Show Build Folder in Finder

# 서명 검증
codesign -dv [빌드 경로]/AudioHelper.app

# 출력 확인:
# Authority=Developer ID Application: TIMBEL (7H4827QYPR)
# TeamIdentifier=7H4827QYPR
```

#### 1-5. 프로젝트에 복사

```bash
# 기존 앱 백업 (선택사항)
mv src/helpers/macos/AudioHelper.app \
   src/helpers/macos/AudioHelper.app.backup

# 새 앱 복사
cp -R [빌드 경로]/AudioHelper.app \
      src/helpers/macos/AudioHelper.app

# ⚠️ npm run sign-helper 실행하지 않기!
# (이미 Developer ID로 서명되어 있음)
```

### 2. App-Specific Password 생성

#### 2-1. Apple ID 웹사이트 접속

```bash
open https://appleid.apple.com/
```

#### 2-2. Password 생성

```
1. Account Holder Apple ID로 로그인
2. "로그인 및 보안" (Sign-In and Security)
3. "App 암호" (App-Specific Passwords)
4. "+" 또는 "암호 생성"
5. 레이블: "timbloRecApp Notarization"
6. 생성된 비밀번호 복사
   예: abcd-efgh-ijkl-mnop
   ⚠️ 한 번만 표시되므로 안전하게 보관!
```

### 3. 환경변수 설정

#### 3-1. ~/.zshrc에 추가 (영구 등록, 권장)

```bash
# 편집기로 열기
nano ~/.zshrc

# 파일 끝에 추가:
# ========================================
# Apple Developer Notarization
# ========================================
export APPLE_ID="account-holder@company.com"
export APPLE_APP_SPECIFIC_PASSWORD="abcd-efgh-ijkl-mnop"
export APPLE_TEAM_ID="7H4827QYPR"

# 저장: Ctrl+O, Enter, Ctrl+X

# 적용
source ~/.zshrc

# 확인
echo $APPLE_ID
echo $APPLE_TEAM_ID
```

#### 3-2. 또는 터미널에서 직접 설정 (임시)

```bash
export APPLE_ID="account-holder@company.com"
export APPLE_APP_SPECIFIC_PASSWORD="abcd-efgh-ijkl-mnop"
export APPLE_TEAM_ID="7H4827QYPR"

# 바로 이어서 빌드 (같은 터미널 세션에서)
npm run build
```

### 4. package.json 설정 확인

```json
"mac": {
  "hardenedRuntime": true,  // ← true여야 함
  "identity": "TIMBEL",     // ← 회사명/팀명
  "notarize": {
    "teamId": "7H4827QYPR"  // ← Team ID
  },
  // ...
}
```

### 5. Electron 앱 빌드

```bash
npm run build
```

**빌드 로그 (예상):**
```
📍 AudioHelper.app 경로: .../AudioHelper.app
✅ AudioHelper는 이미 Developer ID로 서명됨 - 재서명 생략
✅ 마이크 권한 entitlement 포함 확인됨

🔗 Protocol handler 등록 완료!

• signing file=.../timbloRecApp.app
  identity=Developer ID Application: TIMBEL (7H4827QYPR)

🍎 Apple Notarization 시작...
📧 Apple ID: account-holder@company.com
🏢 Team ID: 7H4827QYPR

⏳ Notarization 진행 중... (5-15분 소요)

[Apple 서버와 통신 중...]

✅ Notarization 성공!
🎉 앱이 Apple에 의해 공증되었습니다.
🚀 다른 Mac에서 보안 경고 없이 바로 실행 가능합니다!

• building target=DMG
• building target=macOS zip
```

**빌드 시간**: ~15-25분 (Notarization 포함)

### 6. 빌드 검증

#### 6-1. 서명 확인

```bash
# 메인 앱 서명 확인
codesign -dv dist/mac-arm64/timbloRecApp.app

# 출력 확인:
# Authority=Developer ID Application: TIMBEL (7H4827QYPR)
# TeamIdentifier=7H4827QYPR
```

```bash
# AudioHelper 서명 확인
codesign -dv dist/mac-arm64/timbloRecApp.app/Contents/helpers/macos/AudioHelper.app

# 출력 확인:
# TeamIdentifier=7H4827QYPR  (같은 Team ID!)
```

#### 6-2. Notarization 확인

```bash
# Notarization 스테이플 확인
stapler validate dist/mac-arm64/timbloRecApp.app

# 출력:
# The validate action worked!
```

#### 6-3. Gatekeeper 평가

```bash
# Gatekeeper 통과 확인
spctl -a -vv dist/mac-arm64/timbloRecApp.app

# 출력:
# dist/.../timbloRecApp.app: accepted
# source=Notarized Developer ID
```

### 7. 배포

**배포 파일:**
- `dist/timbloRecApp-1.0.0-arm64-mac.zip` (110MB)
- `dist/timbloRecApp-1.0.0-arm64.dmg` (생성된 경우)

**다른 Mac에서 설치:**
```bash
# 1. 압축 해제 후 Applications 폴더로 이동
mv timbloRecApp.app /Applications/

# 2. 바로 실행! (xattr 불필요)
open /Applications/timbloRecApp.app

# 첫 실행 시:
# - Gatekeeper 자동 검증
# - AudioHelper 마이크 권한 팝업만 나타남
# - "확인" 클릭 → 바로 사용 가능!
```

---

## 빌드 방식 비교

| 항목 | 개발/테스트 (ad-hoc) | 배포용 (Developer ID) |
|------|---------------------|---------------------|
| **빌드 시간** | 3-5분 | 15-25분 |
| **인증서** | 불필요 | Developer ID 필요 |
| **Notarization** | ❌ | ✅ |
| **사용자 설치** | `xattr -cr` 필요 | 바로 실행 |
| **보안 경고** | "손상된 앱" | 없음 |
| **용도** | 내부 테스트 | 외부 배포 |
| **권장** | 개발 중 | 최종 릴리스 |

---

## 트러블슈팅

### Q1. "Please remove prefix 'Developer ID Application:'" 에러

**원인**: package.json의 identity에 전체 이름 입력
```json
// ❌ 잘못됨
"identity": "Developer ID Application: TIMBEL"

// ✅ 올바름
"identity": "TIMBEL"
```

### Q2. Notarization 건너뛰어짐

**원인**: 환경변수 미설정
```bash
# 확인
echo $APPLE_ID
echo $APPLE_APP_SPECIFIC_PASSWORD

# 비어있으면 설정
export APPLE_ID="..."
export APPLE_APP_SPECIFIC_PASSWORD="..."
```

### Q3. "No signing identity found" 에러

**원인**: Developer ID 인증서 미설치
```bash
# 키체인 확인
security find-identity -v -p codesigning | grep "Developer ID"

# 없으면: CERTIFICATE_GUIDE.md 참조
```

### Q4. AudioHelper가 ad-hoc으로 재서명됨

**원인**: AudioHelper가 Developer ID로 서명 안 됨
```bash
# 확인
codesign -dv src/helpers/macos/AudioHelper.app

# Developer ID가 아니면:
# Xcode에서 Team 설정 확인 → 재빌드
```

### Q5. Notarization 실패

**확인 사항:**
1. ✅ 앱이 Developer ID로 서명되었는지
2. ✅ Hardened Runtime 활성화 (`hardenedRuntime: true`)
3. ✅ Entitlements 파일 존재
4. ✅ Apple ID / App-Specific Password 정확한지
5. ✅ 네트워크 연결 확인

---

## 참고 문서

- **인증서 발급**: `docs/CERTIFICATE_GUIDE.md`
- **사용자 설치 가이드**: `docs/INSTALLATION_GUIDE.md`
- **전체 아키텍처**: `docs/recording_architecture_mac_windows_v3.md`