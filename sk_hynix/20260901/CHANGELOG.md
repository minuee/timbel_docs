# 변경 사항

## 26.09.01

### SystemOnly(회의 상대방 음성 단독 녹음) 모드 활성화
- **배경**:
  - Zoom/Webex 등 화상회의 상대방 음성을 **독립된 녹음 노드**로 확보하여, 다중 참석자 녹음 머지에 사용
  - 시스템 오디오 캡처는 Windows(WASAPI Loopback)에 이미 구현되어 있었으나, macOS와 UI가 `MicPlusSystem`으로 하드코딩되어 막혀 있었음
  - 상세 설계/배경: `docs/system_audio_capture_multinode.md`
- **주요 변경사항**:
  1. **src/helpers/macos/.../AudioHelperController.swift**:
     - `start` 커맨드 모드 검증 추가, `start()`에 `mode` 파라미터 배선
     - `currentMode = "MicPlusSystem"` 하드코딩 제거
     - `tryMixAndBuffer()`에 모드별 소스 게인 적용
     - **-6dB 감쇠 수정**: 고정 `/2` 대신 활성 소스 개수로 정규화 (`MicPlusSystem` 기존 동작은 유지)
     - `effectiveSilenceRms()` 추가 — 무음 감지가 현재 모드에서 실제 저장되는 소스만 반영
       (기존 `max(mic, sys)`는 SystemOnly에서 캡처 실패를 놓침)
     - `captureModeCode`(Int32) 추가 — MainActor 갱신 / audioQueue 참조 간 데이터 레이스 방지
  2. **src/renderer/index.html, styles/micTest.css**:
     - "녹음 대상" 모드 셀렉트 + 도움말 툴팁 추가
     - 스피커(출력 장치) 선택 행 추가 — 기본 숨김
     - `.sound-group[hidden]` 규칙 추가 (`display:flex`가 `[hidden]`을 덮어쓰는 문제)
  3. **src/renderer/index.js**:
     - `getCaptureMode()` / `getRenderDeviceId()` 추가, `localStorage` 영속화
     - `start_test`의 모드 하드코딩 제거, `restartTest()`로 재시작 로직 통합
     - `updateRenderDeviceList()` 추가 — Helper의 `renderDevices` 응답 유무로 표시 여부 자동 판별
       (macOS는 ScreenCaptureKit 특성상 출력 장치 선택 개념이 없어 미보고)
     - SystemOnly 선택 시 안내 문구 노출
  4. **src/renderer/scripts/recording.js**:
     - `start` 커맨드가 저장된 캡처 모드/출력 장치를 사용하도록 변경
- **검증 상태**:
  - ✅ Swift 구문 검사(`swiftc -parse`), JS 구문 검사(`node --check`) 통과
  - ⚠️ **전체 빌드 및 실동작 검증 미완료** (Xcode 라이선스 미동의로 `xcodebuild` 차단)
  - 테스트 체크리스트: `docs/system_audio_capture_multinode.md` §8
  - ⚠️ macOS 화면 기록 권한(TCC) 수동 등록 필요 — 헬퍼가 백그라운드 프로세스라 권한 팝업이 자동으로 뜨지 않음.
    증상/해결: `docs/system_audio_capture_multinode.md` §5

## 25.11.18

### 최대 녹음시간 처리 로직 추가
- **배경**:
  - 녹음 시간이 최대 허용 시간(3시간)에 도달했을 때 자동 종료 처리 필요
  - 사용자에게 녹음 파일 업로드 여부를 선택할 수 있는 UI 제공
  - 취소 시 녹음 파일 삭제, 업로드 선택 시 요약 창으로 이동
- **주요 변경사항**:
  1. **src/main/main.js**:
     - IPC 핸들러 `send-max-duration-stopped` 추가
     - 팝업 윈도우에서 선택한 종료 타입(complete/cancel)을 메인 윈도우로 전달
     - `stopType` 이벤트를 recording 윈도우로 전송
  2. **src/main/preload.js**:
     - `sendMaxDurationStopped()`: 팝업에서 메인으로 종료 타입 전송
     - `onMaxDurationStopped()`: 메인에서 종료 타입 수신
  3. **src/renderer/scripts/recording.js**:
     - 상수 추가: `SEGMENT_DURATION_MS = 3분`
     - 플래그 추가: `isStoppedByMaxDuration`
     - `recording_stopped` 이벤트에서 `totalSamples >= TOTAL_RECORD_MS` 검사
     - `recordingStoppedByMaxDuration()` 함수 구현:
       - 녹음 상태 초기화 (isRecording, isPaused)
       - 타이머 정지 및 UI 초기화
       - 팝업 창 생성 (업로드/취소 선택)
     - `onMaxDurationStopped()` 이벤트 핸들러:
       - `stopType === 'cancel'`: 녹음 파일 삭제
       - `stopType === 'complete'`: 요약 창 열기
     - `variableInitialize()`에 `isStoppedByMaxDuration` 초기화 추가
     - `serverUpload()` 조건에 `isStoppedByMaxDuration` 추가
     - 세그먼트 저장 완료 시 `isSegmentReadyForUpload = true` 설정으로 업로드 준비 상태 보장
  4. **src/renderer/scripts/popupWindow.js**:
     - `max_duration_stopped` 타입 처리 추가
     - 취소 버튼: "녹음 취소" → `stopType: 'cancel'` 전송
     - 확인 버튼: "파일 업로드" → `stopType: 'complete'` 전송 + 요약 창 열기
  5. **src/renderer/scripts/summarizeWindow.js**:
     - `isLimitDurationStopped` 옵션 추가
     - 최대 시간 도달로 종료된 경우 stop 명령 전송 안 함
- **결과**:
  - ✅ 3시간 녹음 시간 도달 시 자동 종료
  - ✅ 사용자에게 업로드/취소 선택권 제공
  - ✅ 취소 시 녹음 파일 자동 삭제
  - ✅ 업로드 선택 시 요약 창으로 원활하게 전환
  - ✅ 세그먼트 저장 후 업로드 프로세스 정상 동작

### 최대 녹음시간 팝업 UI/UX 개선
- **문제**: 
  - 팝업 메시지가 한 줄로 표시되어 가독성 저하
  - 팝업 창 크기가 내용에 비해 부적절
  - 제목과 부제목 간격 조정 필요
- **변경 사항**:
  - **src/renderer/scripts/popupWindow.js**:
    - `popupSubtitle.textContent` → `popupSubtitle.innerHTML` 변경
    - HTML 태그를 통한 줄바꿈 지원
  - **src/renderer/scripts/recording.js**:
    - 팝업 메시지 개선:
      - 제목: "최대 녹음 시간에 도달하여<br>녹음이 자동 종료되었습니다."
      - 부제목: "지금까지 녹음된 파일을 업로드할까요?<br>(취소 시 녹음 파일은 삭제됩니다.)"
    - 팝업 창 크기 조정: `width: 380px → 341px`
  - **src/renderer/styles/popupWindow.css**:
    - `.popup-header` margin-bottom 제거 (여백 최적화)
- **결과**:
  - ✅ 가독성 향상된 줄바꿈 메시지
  - ✅ 적절한 팝업 창 크기
  - ✅ 개선된 사용자 경험

## 25.11.13

### Developer ID 인증서를 통한 정식 서명 및 Notarization 적용
- **배경**: 
  - Apple Developer Program 가입 및 Developer ID 인증서 발급
  - 외부 배포를 위한 정식 서명 체계 구축
  - macOS Gatekeeper 완전 통과 목표
- **주요 변경사항**:
  1. **package.json**:
     - `identity`: "TIMBEL" 설정 (Developer ID)
     - `notarize`: Team ID 설정 (7H4827QYPR)
     - `afterSign`: Notarization 훅 추가
  2. **scripts/afterSign.js** 생성:
     - Apple Notarization 자동화
     - 환경변수 기반 인증 (APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD)
     - 5-15분 소요되는 공증 프로세스 자동 처리
  3. **scripts/afterPack.js** 수정:
     - ad-hoc 재서명 로직 완전 비활성화 (주석 처리)
     - AudioHelper 서명 확인만 수행
     - Developer ID로 서명된 AudioHelper를 그대로 유지
  4. **@electron/notarize** 패키지 설치
- **빌드 플로우**:
  ```bash
  1. Xcode에서 AudioHelper 빌드 (Developer ID 서명)
  2. AudioHelper.app → src/helpers/macos/ 복사
  3. 환경변수 설정 (APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID)
  4. npm run build
     ├─ afterPack: AudioHelper 서명 확인 (재서명 안 함)
     ├─ signing: timbloRecApp Developer ID 서명
     └─ afterSign: Apple Notarization 자동 실행 ⏳
  ```
- **결과**:
  - ✅ 메인 앱: Developer ID 서명
  - ✅ AudioHelper.app: Developer ID 서명
  - ✅ 같은 Team ID로 통일 (7H4827QYPR)
  - ✅ Apple 공증 완료
  - ✅ 외부 PC에서 **보안 경고 없이 바로 실행 가능!**
- **사용자 경험 개선**:
  - 이전: `xattr -cr` 명령어 + 시스템 설정에서 수동 허용
  - 이후: **DMG 실행 → 바로 사용 가능** (아무 설정 불필요)

### Apple Developer ID 인증서 발급 가이드 문서 작성
- **목적**: 팀원들이 Developer ID 인증서를 발급받고 설정하는 전체 절차 문서화
- **추가 파일**: `docs/CERTIFICATE_GUIDE.md` (636줄)
- **주요 내용**:
  1. CSR 파일 생성 방법 (Keychain Access)
  2. Developer ID Application 인증서 요청 절차
  3. G2 Sub-CA vs Previous Sub-CA 설명
  4. 인증서 설치 및 검증
  5. Xcode Signing & Capabilities 설정
  6. electron-builder 설정 변경사항
  7. Notarization 설정 (App-Specific Password, 환경변수)
  8. 권한 문제 해결 (Account Holder vs Admin)
  9. .p12 파일 export 및 공유 방법
  10. 트러블슈팅 가이드
  11. 단계별 체크리스트
- **권한 이슈 해결**:
  - Developer ID는 Account Holder만 생성 가능함을 명시
  - Admin 권한으로도 불가능
  - .p12 파일 공유를 통한 팀원 인증서 배포 방법 제공
- **인증서 종류 설명**:
  - Apple Development, Apple Distribution
  - Mac Development, Mac App Distribution
  - Developer ID Application/Installer
  - 각 인증서의 용도, 권한, 배포 방식 상세 설명

### 개발환경 빌드 가이드 작성
- **추가 파일**: `docs/BUILD_GUIDE.md`
- **내용**: 
  - macOS/Windows 개발 환경 설정
  - AudioHelper 빌드 방법 (Xcode)
  - Electron 앱 빌드 절차
  - 테스트 실행 방법
  - Deployment Target 설정 안내

### macOS 15 필수 요구사항 명시
- **문제**: AudioHelper가 macOS 15 전용 Swift API 사용 중
- **원인**: `@available(macOS 15.0, *)` 어노테이션으로 코드 작성됨
- **해결**: 
  - `docs/INSTALLATION_GUIDE.md`에 macOS 15 필수 명시
  - "이전 버전에서 실행되지 않습니다" 경고 추가
- **검증**:
  - timbloRecApp: LSMinimumSystemVersion = 12.0
  - AudioHelper: LSMinimumSystemVersion = 15.0
  - 실제 동작: macOS 15 (Sequoia) 이상 필수
- **시스템 요구사항**: macOS 15.0 (Sequoia) 이상 [필수]

### afterPack 배열 처리 및 protocol handler 통합
- **문제**: electron-builder의 `afterPack`이 배열을 제대로 지원하지 않음
- **원인**: 
  ```javascript
  "afterPack": [
    "./scripts/afterPack.js",
    "./scripts/register-protocol.js"
  ]
  ```
  - `handler is not a function` 에러 발생
- **해결**:
  - afterPack.js 하나로 통합
  - AudioHelper 재서명 + Protocol handler 등록을 순차 실행
  - `package.json`에서 afterPack을 단일 파일로 변경
- **결과**:
  - 빌드 프로세스 정상 동작
  - 두 작업 모두 안정적으로 수행

### identity 설정 최적화
- **변경 이력**:
  1. `identity: null` 제거 (ad-hoc 서명을 위해)
  2. electron-builder가 자동으로 개발자 인증서 사용
  3. `identity: null` 재추가 (메인 앱 서명 비활성화)
  4. AudioHelper는 ad-hoc 재서명 유지
- **목적**: 메인 앱과 AudioHelper 모두 ad-hoc 서명으로 통일
- **결과**: 개발/테스트 환경에서 안정적인 배포 가능

## 25.11.11

### variableInitialize에서 업로드 플래그 초기화 제거
- **문제**:
  - 세그먼트 저장 완료 후 업로드 프로세스 진행 중 `handleRecordingStopped` 호출
  - `variableInitialize()`가 업로드 플래그를 중간에 초기화
  - `isSegmentReadyForUpload`가 `false`로 변경되어 업로드 실패
- **원인**:
  - `handleRecordingStopped()`에서 `variableInitialize()` 호출
  - `variableInitialize()`에서 업로드 관련 변수 초기화:
    - `uploadData = null`
    - `isSegmentReadyForUpload = false`
    - `isUploadDataReady = false`
  - 녹음 종료 시점에 업로드가 진행 중인 경우 플래그가 초기화되어 업로드 실패
- **해결**:
  - `variableInitialize()`에서 업로드 관련 변수 초기화 제거
  - 업로드 변수는 `startRecording()`에서만 초기화하도록 변경
  - 녹음 종료 후에도 업로드 프로세스가 정상 진행되도록 보장
- **결과**:
  - 녹음 종료와 업로드 프로세스 독립적으로 동작
  - 세그먼트 저장 완료 후 업로드 정상 진행
  - 업로드 플래그가 중간에 초기화되지 않음

### 업로드 안전성 강화 - 녹음 시작 시 변수 초기화 및 recordId 검증 추가
- **문제**:
  - 이전 녹음 세션의 `uploadData`가 초기화되지 않고 남아있음
  - 새로운 녹음 완료 시 이전 세션의 데이터로 업로드 시도
  - 잘못된 jobId, filePath로 인한 업로드 실패
  - `tryStartUpload()`가 중복 호출되는 문제
- **원인**:
  - `startRecording()` 함수에서 업로드 관련 변수를 초기화하지 않음
  - 이전 세션의 `uploadData`, `isUploadDataReady` 값이 남아있어 비동기 작업 중 잘못된 데이터 사용
  - 세그먼트 저장 완료 시 이전 세션의 데이터로 업로드 시도 → 실패
  - 이후 새로운 `uploadData` 준비 완료 시 다시 `tryStartUpload()` 호출 → 조건 미충족
- **해결**:
  - `startRecording()`에 업로드 관련 변수 초기화 추가:
    - `uploadData = null`
    - `isSegmentReadyForUpload = false`
    - `isUploadDataReady = false`
  - `tryStartUpload()`에 recordId 검증 로직 추가:
    - `uploadData.recordId !== recordId` 체크
    - 현재 세션의 데이터가 아니면 업로드 중단
- **결과**:
  - 새 녹음 시작 시 이전 세션 데이터 완전 초기화
  - recordId 검증으로 이중 안전장치 구현
  - 잘못된 데이터로 업로드 시도 방지
  - 중복 업로드 시도 문제 해결

### 업로드 타이밍 이슈 수정 - 세그먼트 저장과 업로드 데이터 준비 동기화
- **문제**: 
  - 빌드된 앱에서 "No filePath provided" 에러 발생
  - `serverUpload` 함수에 `null`이 전달됨
  - 녹음 완료 버튼 클릭 → 요약 정보 입력 → 업로드 프로세스에서 타이밍 문제 발생
- **원인**:
  - 세그먼트 저장 완료(`handleSegmentReady`) 시점과 업로드 데이터 준비(`onRequestUpload`) 시점이 비동기적으로 발생
  - 빌드 환경에서는 세그먼트 저장이 빠르게 완료되어 `uploadData`가 아직 `null`인 상태에서 업로드 시도
  - 개발 환경에서는 느린 실행으로 타이밍이 맞아 문제 미발생
- **해결**:
  - 상태 플래그 기반 동기화 로직 구현:
    - `isSegmentReadyForUpload`: 세그먼트 저장 완료 여부
    - `isUploadDataReady`: 업로드 데이터 준비 완료 여부
  - `tryStartUpload()` 함수 추가: 두 조건이 모두 만족될 때만 업로드 시작
  - `handleSegmentReady`: 세그먼트 저장 완료 시 플래그 설정 및 업로드 시도
  - `onRequestUpload`: 업로드 데이터 준비 완료 시 플래그 설정 및 업로드 시도
  - `variableInitialize`: 플래그 초기화 추가
- **결과**: 
  - 세그먼트 저장과 업로드 데이터 준비 순서에 관계없이 안전하게 업로드 시작
  - 빌드/개발 환경 모두에서 안정적인 업로드 동작 보장
  - 중복 업로드 방지 및 디버깅 로그 추가

## 25.11.10

### electron-builder afterPack 훅으로 AudioHelper.app 자동 재서명
- **문제**: 
  - electron-builder가 패키징 시 AudioHelper.app을 개발자 인증서로 재서명
  - 다른 PC에서 AudioHelper.app 실행 불가
  - 마이크 권한 팝업이 나타나지 않음
- **원인**:
  - `npm run sign-helper`로 ad-hoc 서명해도 electron-builder가 다시 개발자 인증서로 서명
  - `TeamIdentifier=UDV599Z2P7`로 서명되어 다른 Mac에서 차단
- **해결**:
  - `scripts/afterPack.js` 추가: electron-builder 패키징 **후** 자동으로 AudioHelper.app을 ad-hoc으로 재서명
  - `package.json`의 `afterPack` 배열에 스크립트 추가
  - 마이크 권한 entitlements 유지하면서 재서명
- **결과**: 
  - 메인 앱과 AudioHelper.app 모두 ad-hoc 서명으로 통일
  - AudioHelper가 마이크 권한을 정상적으로 요청 가능
- **빌드 플로우**:
  ```bash
  1. npm run sign-helper  # Xcode 빌드 후 AudioHelper 재서명
  2. npm run build        # afterPack.js가 자동 실행되어 재서명
  ```

### AudioHelper.app ad-hoc 서명 자동화 및 서명 통일
- **문제**: AudioHelper.app이 개발자 인증서로 서명되어 다른 Mac에서 실행 불가
- **원인**: 
  - Xcode 빌드 시 개발자 인증서로 자동 서명
  - 메인 앱과 Helper 앱의 서명 불일치
- **해결**:
  - `scripts/sign-helper.sh` 추가: AudioHelper.app을 ad-hoc 서명으로 재서명
  - `package.json`에 `sign-helper` 스크립트 명령어 추가
  - `identity: null` 제거 → electron-builder가 자동으로 ad-hoc 서명 적용
  - 마이크 권한 entitlements 유지하면서 재서명
- **사용법**:
  ```bash
  # Xcode에서 빌드 후
  npm run sign-helper
  ```
- **결과**: 메인 앱과 Helper 앱 모두 ad-hoc 서명으로 통일

### macOS 사용자용 설치 가이드 및 문서 작성
- **추가 파일**: `docs/INSTALLATION_GUIDE.md` (192줄)
- **배경**:
  - 개발자 인증서 없이 빌드된 앱의 설치 가이드 필요
  - "손상되었기 때문에 열 수 없습니다" 에러 해결 방법
  - 마이크 권한 설정 방법
- **주요 내용**:
  1. DMG/ZIP 설치 방법
  2. **방법 1**: 터미널 명령어 (권장)
     ```bash
     xattr -cr /Applications/timbloRecApp.app
     ```
  3. **방법 2**: 시스템 설정에서 수동 허용 (단계별 스크린샷 설명)
  4. 마이크 권한 설정 방법 상세 안내
  5. 7가지 FAQ 및 문제 해결
  6. 시스템 요구사항
- **README.md 업데이트**:
  - 크로스플랫폼 지원 명시 (macOS/Windows)
  - 설치 가이드 링크 추가
  - Swift/CoreAudio 기술 스택 정보
  - macOS 문제 해결 섹션 추가
  - 로그 위치 정보

### macOS 배포를 위한 서명 설정 비활성화
- **문제**: 다른 Mac에서 테스트 시 인증서 없이 앱 실행 불가
- **원인**: 
  - Apple Developer 인증서 없이 `hardenedRuntime: true` 설정
  - macOS Gatekeeper가 서명되지 않은 앱 실행 차단
- **해결**:
  - `package.json`의 mac 빌드 설정 수정:
    - `hardenedRuntime`: `true` → `false`
    - `identity`: `null` 추가 (서명 비활성화)
- **영향**: 
  - 개발/테스트 환경에서 앱 실행 가능 (`xattr -cr` 필요)
  - 정식 배포 시 Apple Developer Program 가입 필요
- **관련 작업**: 
  - AudioHelper.app에 마이크 권한 entitlement 추가
  - `com.apple.security.device.audio-input` 설정
  - AudioHelper.entitlements 파일 생성

### macOS 빌드를 위한 entitlements.mac.plist 파일 복원
- **문제**: `npm run build` 실행 시 코드 사이닝 에러 발생
  ```
  build/entitlements.mac.plist: cannot read entitlement data
  ```
- **원인**: 
  - 10월 29일: `build/entitlements.mac.plist` 파일 생성 (hardenedRuntime 크래시 해결)
  - 10월 31일: ignore 적용 커밋에서 해당 파일이 실수로 삭제됨
  - `package.json`의 mac 빌드 설정에서 여전히 파일 참조 중
- **해결**:
  - git 히스토리에서 `build/entitlements.mac.plist` 파일 복원
  - `.gitignore`에서 `build/` 디렉토리 무시 규칙 제거
  - 파일 내용:
    - 마이크 권한 (`com.apple.security.device.audio-input`)
    - V8 JIT 컴파일러 허용 (`com.apple.security.cs.allow-jit`)
    - 동적 라이브러리 로딩 허용 (`com.apple.security.cs.allow-unsigned-executable-memory`)
    - 라이브러리 검증 비활성화 (`com.apple.security.cs.disable-library-validation`)
    - 동적 링커 환경 변수 허용 (`com.apple.security.cs.allow-dyld-environment-variables`)
- **결과**: macOS 빌드 시 코드 사이닝 정상 동작

## 25.10.31

### 앱 종료 로직 완성 - 파일 처리 후 자동 앱 종료 기능 추가
- **목적**: 녹음 중 앱 종료 시 파일 삭제/업로드 처리가 완료되면 자동으로 앱 종료
- **기존 문제**:
  - 파일 삭제/업로드 후에도 사용자가 수동으로 앱을 다시 종료해야 함
  - 업로드 실패 시 앱 종료 의사가 있었음에도 계속 실행 중
- **개선된 플로우**:
  ```
  앱 종료 버튼 클릭
    → 앱 종료 확인 팝업 (공통)
      → [확인] 
        → 녹음 중: 파일 처리 선택 팝업
          → [녹음 삭제] isAppClosing=true 설정 
            → 파일 삭제 완료 → 자동 앱 종료 ✅
          → [파일 업로드] isAppClosing=true 설정 
            → 업로드 성공 → 자동 앱 종료 ✅
            → 업로드 실패 → 확인 버튼 클릭 → 앱 종료 ✅
  ```
- **구현 방식**:
  - **isAppClosing 플래그**: 앱 종료 의사를 전체 프로세스에 전달
  - **처리 완료 시점 감지**: 각 처리가 완료되면 플래그 확인 후 자동 종료
- **수정 파일**:
  - `src/renderer/scripts/recording.js`:
    - `isAppClosing` 전역 변수 추가
    - `stop_type_selected` 이벤트: 사용자 선택 시 `isAppClosing = true` 설정
    - `serverUpload()`: 업로드 데이터에 `isAppClosing` 플래그 포함
    - `onDeleteRecordingResult`: 삭제 성공 시 `isAppClosing`이면 `appQuit()` 호출
    - `cancel` 타입 선택 시에만 `handleRecordingPause()` 즉시 호출 (삭제 처리)
    - `complete` 타입은 summarizeWindow에서 처리되도록 대기
  - `src/main/main.js`:
    - `serverUpload()`: 업로드 성공 시 `data.isAppClosing`이면 `app.quit()` 호출
    - 업로드 실패 시 `isAppClosing` 플래그를 팝업으로 전달
  - `src/renderer/scripts/popupWindow.js`:
    - `isAppClosing` 전역 변수 추가
    - `upload-progress` 타입 확인 버튼: `isAppClosing`이면 앱 종료
    - `onUploadFailed`: 실패 시 메시지 및 버튼 UI 변경
      - 일반: "다시 시도해 주세요" (재시도/취소 버튼)
      - 앱 종료 모드: "애플리케이션을 종료합니다" (확인 버튼만)
- **처리 시나리오**:
  1. **녹음 삭제 선택**: 
     - `isAppClosing = true` 설정
     - `handleRecordingPause()` → segmentReady → 파일 삭제
     - 삭제 완료 → `onDeleteRecordingResult`에서 `appQuit()` 자동 호출
  2. **파일 업로드 선택 (성공)**:
     - `isAppClosing = true` 설정
     - summarizeWindow에서 업로드 → main.js `serverUpload()`
     - 업로드 성공 → `app.quit()` 자동 호출
  3. **파일 업로드 선택 (실패)**:
     - 업로드 진행 팝업에 "애플리케이션을 종료합니다" 메시지 표시
     - 확인 버튼 클릭 → `appQuit()` 호출
- **결과**: 
  - 파일 처리가 완료되면 추가 조작 없이 자동으로 앱 종료
  - 업로드 실패 시에도 명확한 안내와 함께 앱 종료 가능
  - 사용자 의사(앱 종료)가 끝까지 존중됨

### 앱 종료 로직 개선 - 녹음 중 파일 처리 선택 UX 개선
- **목적**: 녹음 중 앱 종료 시 사용자가 파일을 삭제할지 업로드할지 명확히 선택할 수 있도록 개선
- **기존 문제**:
  - 녹음 중일 때와 아닐 때 다른 팝업이 표시되어 일관성 부족
  - 녹음 중 앱 종료 시 바로 파일 처리 선택 팝업이 표시되어 사용자가 앱 종료 의사를 재확인할 기회가 없음
- **개선된 플로우**:
  ```
  앱 종료 버튼 클릭
    → 앱 종료 확인 팝업 (공통, 녹음 상태를 data로 전달)
      → [취소] 아무 일도 없음
      → [확인] 
        → 녹음 중이 아님: 즉시 앱 종료
        → 녹음 중: IPC 통신으로 recording.js에 이벤트 전달
          → 파일 처리 선택 팝업 표시
            → [녹음 삭제] stopType='cancel' 설정 → handleRecordingPause() 호출
            → [파일 업로드] stopType='complete' 설정 → summarizeWindow 열림
  ```
- **구현 방식**:
  - **IPC 통신 추가**: popupWindow ↔ recording.js 간 통신
  - **이벤트 기반 처리**: 기존 `stopType` + `handleRecordingPause()` 로직 활용
  - **상태 체크 위치**: popupWindow에서 녹음 상태 확인 후 분기
- **수정 파일**:
  - `src/main/main.js`:
    - `send-app-close-recording` IPC 핸들러 추가
    - 이벤트 종류: `confirm_app_close_recording` (녹음 중 확인), `stop_type_selected` (사용자 선택 전달)
  - `src/main/preload.js`:
    - `sendAppCloseRecording()`: 녹음 중 앱 종료 명령 전송
    - `onAppCloseRecording()`: recording.js에서 이벤트 수신
  - `src/renderer/scripts/recording.js`:
    - `closeAppBtn` 이벤트: 항상 공통 팝업 표시 (녹음 상태는 data로 전달)
    - `onAppCloseRecording` 이벤트 리스너 추가:
      - `confirm_app_close_recording`: 파일 처리 선택 팝업 표시
      - `stop_type_selected`: stopType 설정 후 `handleRecordingPause()` 호출
  - `src/renderer/scripts/popupWindow.js`:
    - `app-close-recording` 팝업 타입 UI 설정 (버튼 텍스트: "녹음 삭제", "파일 업로드")
    - `app-close` 타입 확인 버튼 로직 수정: 녹음 상태 확인 후 분기 처리
    - 취소 버튼: `select_stop_type` 명령으로 'cancel' stopType 전달
    - 확인 버튼: `select_stop_type` 명령으로 'complete' stopType 전달 후 summarizeWindow 열기
- **장점**:
  - 기존 `stopType` + `handleRecordingPause()` 로직 최대한 재사용
  - 간단한 IPC 통신만 추가하여 최소한의 변경
  - segmentReady 이벤트 타이밍은 기존 로직에서 보장
- **결과**: 
  - 사용자가 앱 종료 의사를 먼저 확인한 후 파일 처리 방법 선택 가능
  - 일관된 UX 제공 (항상 동일한 첫 단계 팝업)

## 25.10.30

### 녹음 종료 후 취소/종료 버튼 비활성화 기능 추가
- **목적**: 녹음 완료 후 중복 클릭 방지 및 UX 개선
- **문제**: 녹음 종료 후에도 취소/종료 버튼이 활성화되어 있어 의도하지 않은 중복 작업 가능
- **해결**:
  - `src/renderer/scripts/recording.js`:
    - `startRecording()`: 녹음 시작 시 취소/종료 버튼 활성화 (disabled 클래스 제거)
    - `variableInitialize()`: 녹음 종료/초기화 시 취소/종료 버튼 비활성화 (disabled 클래스 추가)
  - `src/renderer/styles/recordingWindow.css`:
    - `.record-control.disabled` 스타일 추가 (opacity: 0.6, pointer-events: none)
    - `#pause-btn`에 user-select: none 추가
- **동작**:
  - 녹음 시작: 취소/종료 버튼 활성화
  - 정상 종료: 모든 로직 처리 후 버튼 비활성화
  - 오류 종료: 일시정지 버튼만 비활성화, 취소/종료는 사용자 선택 대기
- **결과**: `isRecording === false`일 때 취소/종료 버튼이 비활성화되어 안정성 향상

## 25.10.30

### 마이크 장치 물리적 추가/제거 시 테스트 재시작 타이밍 이슈 수정
- **문제**: 마이크를 물리적으로 제거 후 다시 연결하면 레벨 미터가 작동하지 않음
- **원인**: 
  - `audio_device_change` 이벤트에서 `stop_test` 명령 전송 후 즉시 장치 목록 갱신
  - `test_stopped` 이벤트는 나중에 도착하여 `isTestStarted` 플래그가 갱신 시점에 여전히 `true`
  - `updateDeviceList()`에서 `isTestStarted === true`로 인식하여 테스트 재시작 건너뜀
- **해결 방법**:
  - `deviceChanged` 플래그 추가하여 장치 변경 이벤트 처리 순서 제어
  - `audio_device_change` 이벤트: `deviceChanged = true` 설정 후 `stop_test` 전송
  - `test_stopped` 이벤트: `deviceChanged` 확인 후 `changeDeviceEvent()` 호출
  - 이를 통해 `isTestStarted`가 확실히 `false`로 변경된 후 장치 목록 갱신 및 테스트 재시작
- **영향**: 마이크 제거/추가 시 항상 올바르게 테스트 재시작

### recording.js 리팩터링 - 코드 구조 개선
- **목적**: 가독성 향상 및 유지보수성 개선
- **작업 내용**:
  - 1923줄의 코드를 10개의 명확한 섹션으로 재구조화
  - Helper Event 리스너를 파일 상단(128-547줄)에 배치하여 이벤트 흐름 추적 용이
  - 기능별 함수 그룹화 (녹음 제어, 타이머, 메모/태그, UI 컨트롤, 설정 메뉴)
  - 중복 코드 제거 (약 400줄 이상)
  - 이벤트 리스너를 하단 섹션(9번)에 집중 배치
- **구조 개선**:
  1. DOM 요소 선택 및 상수 (1-69줄)
  2. 전역 변수 (75-126줄)
  3. Helper Event 처리 (128-547줄) ⭐ 핵심 개선
  4. 녹음 제어 함수 (573-821줄)
  5. 타이머 및 시간 표시 (827-941줄)
  6. 메모 및 태그 관련 (943-1007줄)
  7. UI 컨트롤 (1009-1172줄)
  8. 설정 메뉴 UI (1174-1410줄)
  9. 이벤트 리스너 등록 (1412-1900줄)
  10. 초기화 (1902-1949줄)
- **버그 수정**:
  - PauseBtnImg 중복 선언 제거
  - sessionId 변수 누락 문제 해결 (전역 변수 추가 및 초기화)
  - Always On Top 버튼 토글 기능 복구
  - 녹음 취소/종료 버튼 정상 동작 확인
- **효과**:
  - Helper 이벤트에서 핸들러 함수까지 10줄 이내로 이동 가능
  - 기능별 코드가 물리적으로 인접하여 스크롤 최소화
  - 린터 오류 0개 유지
  - 모든 기능 로직 변경 없이 순수 위치만 이동

### 재업로드 완료 시 스마트 알림 기능 추가 (하이브리드 방식)
- **목적**: 재업로드(retry_multi) 완료 시 사용자에게 결과를 알림으로 전달
- **기능**: 
  - 업로드 완료 시점에 따라 개별 알림/요약 알림 자동 선택
  - 4초 디바운싱으로 연속 완료 시 요약 알림 생성
  - 간격이 긴 완료는 개별 알림으로 표시
  - Windows/macOS 크로스 플랫폼 지원
- **구현**:
  - `src/main/main.js`: 알림 큐 시스템 추가
    - `notificationQueue`: 완료된 업로드 정보 저장 배열
    - `notificationTimer`: 4초 디바운스 타이머
    - `flushNotificationQueue()`: 큐 처리 함수
      - 1개: "파일A이(가) 성공적으로 업로드되었습니다."
      - 2개 이상: "3개 파일이 모두 성공적으로 업로드되었습니다." 또는 "성공 2개, 실패 1개"
      - Windows/macOS 모두 지원하도록 subtitle과 body 동시 전달
    - `queueUploadNotification()`: 알림 큐 추가 및 타이머 관리
  - `serverUpload()` 함수 수정
    - 성공 시(662번 라인): `retry_multi` 타입이면 큐에 추가
    - 실패 시(684, 704번 라인): `retry_multi` 타입이면 큐에 추가
  - `retry-server-uploads` 핸들러 수정(757번 라인)
    - `Promise.allSettled` 완료 후 대기 중인 알림 즉시 발송
    - 모든 업로드 완료 시 결과 요약 표시
  - `createSystemNotification()` 함수 개선(1028번 라인)
    - Windows: body 속성을 직접 지원하도록 수정 (options.body 우선 사용)
    - macOS: subtitle 유지, body는 warning 전용으로 유지
- **시나리오별 동작**:
  - **작은 파일 3개 (거의 동시)**: 요약 알림 "3개 파일이 모두 성공적으로 업로드되었습니다."
  - **큰 파일 2개 (간격 있음)**: 개별 알림 2회 표시
  - **혼합 (성공 2개, 실패 1개)**: 요약 알림 "성공 2개, 실패 1개"
- **설정**:
  - `NOTIFICATION_DEBOUNCE_MS = 4000` (4초 디바운스)
- **결과**: 
  - 사용자가 백그라운드에서 작업 중에도 업로드 결과 확인 가능
  - 불필요한 중복 알림 방지
  - 상황에 맞는 스마트한 알림 제공
  - Windows와 macOS 모두에서 올바르게 동작

### 녹음 종료 후 타임바 색상 초기화 버그 수정
- **문제**: 녹음이 10분 미만 남은 상태(빨간색)에서 종료 시, 타임바가 100%로 복귀하지만 빨간색이 유지됨
- **원인**: 
  - `variableInitialize()` 함수에서 타임바 width와 텍스트만 초기화
  - CSS 클래스(`.ok`, `.warn`, `.danger`)는 초기화하지 않음
  - 이전 녹음의 `.danger` 클래스가 남아 빨간색 표시
- **해결**:
  - `src/renderer/scripts/recording.js:875` 수정
  - 타임바 초기화 시 클래스 제거 후 `.ok` 클래스 추가
  - 녹음 종료 시 항상 파란색(정상 상태)으로 초기화
- **결과**: 녹음 종료 후 타임바가 올바르게 파란색 100%로 표시됨

### 윈도우 사이즈 제약 동적 제어 기능 추가
- **목적**: 화면별로 사이즈 조절 가능 여부와 최소/최대 사이즈를 동적으로 제어
- **구현**:
  - `src/main/main.js`: `set-window-constraints` IPC 핸들러 추가
    - `resizable`: 윈도우 리사이즈 가능 여부 설정
    - `minWidth/minHeight`: 최소 사이즈 설정
    - `maxWidth/maxHeight`: 최대 사이즈 설정 (없으면 무제한)
  - `src/main/preload.js`: `setWindowConstraints` API 노출
  - `src/renderer/index.js`: 마이크 테스트 화면 적용
    - 초기화 시 380x336~436 범위 제약 설정
    - `textToggleOff/On`에서 확인사항 접기/펼치기 시 높이 조절
    - 녹음 시작 시 메모 모드 제약으로 전환
  - `src/renderer/scripts/recording.js`: 녹음 화면 적용
    - 페이지 로드 시 메모 모드 제약 설정 (360x520 이상)
    - `toggleMode`에서 모드별 제약 설정
- **화면별 동작**:
  - **마이크 테스트**: 380x336~436 범위 조절 가능 (확인사항 접기/펼치기)
  - **메모 모드**: 360x520 이상 무제한 조절 가능
  - **플레이어 모드**: 360x236 고정 (리사이즈 불가)
- **결과**: 각 화면 특성에 맞는 윈도우 사이즈 제어, UX 개선

## 25.10.30

### 디스크 여유 공간 critical 상태 UI 피드백 개선
- **문제**: `disk_status` 이벤트에서 `status: "critical"`일 때 콘솔 로그만 출력하여 사용자가 상태 변화를 인지할 수 없음
- **원인**: 
  - `updateDiskStatus()` 함수에서 `status === "critical"` 조건 처리 시 `console.log`만 실행
  - 디스크 여유 공간이 50MB 미만으로 떨어져도 UI에 알림 없음
- **해결**:
  - `src/renderer/scripts/recording.js:1837` 수정
  - `console.log("디스크 여유공간 부족으로 곧 녹음이 종료됩니다.")` → `diskSpaceCritical(event)` 호출
  - 팝업 표시로 사용자에게 즉시 피드백 ("약 3분 후 녹음이 자동 종료됩니다.")
- **이벤트 흐름**:
  1. `disk_status` (status: "critical") → UI 경고 표시
  2. `error` (DISK_SPACE_LOW_STOP) → 실제 중지 처리
  3. `recording_stopped` → 녹음 종료 처리
- **결과**: 디스크 부족 상황을 사용자가 즉시 인지하고 대응 가능

### 시스템 알림 최소화 감지 Promise 처리 개선
- **문제**: `isMinimized()` 호출 시 Promise 객체를 동기적으로 처리하여 조건문이 정상 작동하지 않음
  - `window.windowAPI.isMinimized()` 호출 결과가 `Promise { <pending> }` 형태로 반환
  - Promise 객체는 항상 truthy이므로 `if(isMinimized)` 조건이 항상 true로 평가됨
  - 창이 보이는 상태에서도 시스템 알림이 발송되는 문제 발생
- **원인**:
  - `ipcRenderer.invoke()`는 항상 Promise를 반환
  - `handleSilenceEvent()` 함수에서 `await` 없이 동기적으로 호출
- **해결**:
  - `src/renderer/scripts/recording.js:1438` 수정
  - `function handleSilenceEvent(event)` → `async function handleSilenceEvent(event)`
  - `const isMinimized = window.windowAPI.isMinimized()` → `const isMinimized = await window.windowAPI.isMinimized()`
- **결과**: 창 최소화 상태를 정확히 판단하여 시스템 알림 발송

### macOS 화면 공유/미러링 중 알림 표시 이슈
- **문제**: macOS에서 시스템 알림이 표시되지 않음
- **원인**: 
  - MacMini 환경에서 디스플레이 미러링 또는 화면 공유 중
  - macOS 시스템 설정 > 알림에서 "디스플레이를 미러링하거나 공유할 때" 알림 허용 비활성화 상태
- **해결**: 시스템 설정에서 해당 옵션 활성화 필요
- **참고**: 원격 개발 환경이나 화면 공유 시 알림 설정 확인 필요

### 장치 변경 알림 기능 추가
- `audio_device_change` 이벤트 대응 로직 추가
  1. 녹음 중일 때 장치 추가/제거
    - 제거 시 `MIC_DEVICE_LOST` 이벤트 발행 예정이기 때문에 무시
    - 추가 시 녹음 중 이기 때문에 무시
  2. 녹음 중이 아닐 때 장치 추가/제거
    - 제거 시 초기화면으로 돌아갈지 여부 묻는 팝업 창 생성
    - 추가 시 초기화면으로 돌아갈지 여부 묻는 팝업 창 생성

### 마이크 테스트 화면 로직 개선
- `audio_device_change` 이벤트를 통해 장치 변경 감지가 가능해짐
- 이벤트 감지시 장치 목록 재요청

## 25.10.29

### macOS 한글 입력 시 엔터 키 중복 입력 문제 해결
- **문제**: macOS 환경에서 제목/메모 입력 시 한글 입력 후 엔터를 누르면 마지막 글자가 다음 줄에 중복 입력됨
- **원인**: 
  - IME(Input Method Editor) 조합 완료 이벤트(`compositionend`)와 `keydown` 이벤트 타이밍 충돌
  - 한글 조합이 완료되기 전에 Enter 키 이벤트가 먼저 처리됨
- **해결**:
  - `src/renderer/scripts/recording.js` 3개 위치 수정:
    1. 제목 입력 (`titleInput`) - 1007줄: `if (e.key === "Enter" && !e.isComposing)`
    2. 메모 입력 (`contentsInput`) - 1037줄: `if (e.key === "Enter" && !e.isComposing)`
    3. 메모 수정 (`input`) - 1187줄: `if (ev.key === "Enter" && !ev.isComposing)`
  - KeyboardEvent의 `isComposing` 속성을 체크하여 IME 조합 중에는 Enter 키 이벤트 무시
- **결과**: 한글 입력 시 정상적으로 엔터 키 동작, 문자 중복 입력 없음

### 파일 경로 구분자 크로스 플랫폼 호환성 수정
- **문제**: macOS에서 녹음 파일 삭제 및 업로드 실패
  - `recording.js`에서 Windows 경로 구분자 `\\`를 하드코딩
  - macOS에서 잘못된 경로 생성: `/tmp/recordings\session-id`
  - DB에 저장된 경로와 실제 파일 경로 불일치
- **원인**:
  - `session_created` 이벤트 처리 시 `outputDir + "\\" + sessionId` 사용
  - Windows 전용 경로 구분자로 인한 cross-platform 호환성 부족
- **해결**:
  - `src/renderer/scripts/recording.js:487` 수정
  - `\\` → `/` 변경 (Node.js는 양쪽 OS에서 `/` 지원)
- **결과**: Windows와 macOS 모두에서 파일 시스템 작업 정상 동작

### macOS 앱 크래시 문제 해결 (hardenedRuntime + V8 엔진)
- **문제**: dmg 설치 후 앱 실행 시 즉시 크래시
  - `SecCodeCheckValidity: Code=-2147409622` (코드 서명 검증 실패)
  - `Fatal process out of memory: Failed to reserve virtual memory for CodeRange`
- **원인**: 
  1. `hardenedRuntime: true` 활성화 시 Electron V8 엔진에 필요한 entitlements 누락
  2. JIT 컴파일러가 메모리 할당 불가
  3. 네이티브 모듈(better-sqlite3) 로딩 실패
- **해결**:
  1. `build/entitlements.mac.plist`에 필수 권한 추가
     - `com.apple.security.cs.allow-jit` - V8 JIT 컴파일러
     - `com.apple.security.cs.allow-dyld-environment-variables` - 동적 링커
     - `com.apple.security.cs.disable-library-validation` - 네이티브 모듈
- **결과**: 앱 정상 실행

### macOS 마이크 권한 문제 해결
- **문제**: Helper 실행 후 `MIC_PERMISSION_DENIED` 에러 발생, 시스템 설정에 앱이 나타나지 않음
- **원인**: 
  1. Helper의 Info.plist가 서명에 바인딩되지 않음 (`Info.plist=not bound`)
  2. Electron 메인 앱에 마이크 권한 entitlements 누락
  3. macOS TCC(투명성, 동의 및 제어) 시스템에 앱이 등록되지 않음
- **해결**:
  1. `build/entitlements.mac.plist` 생성 (마이크 권한 포함)
  2. `package.json`의 mac 빌드 설정 개선
     - `hardenedRuntime: true` 추가
     - `entitlements` 및 `entitlementsInherit` 설정
     - `extendInfo`에 `NSMicrophoneUsageDescription` 추가
  3. 빌드 후 시스템이 자동으로 권한 요청 다이얼로그 표시
- **결과**: 앱 최초 실행 시 시스템 권한 요청, 시스템 설정에 앱 등록됨

### macOS 빌드 환경에서 Helper 실행 오류 해결
- **문제**: dmg로 설치한 앱에서 AudioHelper가 실행되지 않는 문제
- **원인**: 
  1. `package.json`의 `extraFiles`에 macOS helper가 포함되지 않음
  2. Helper 경로 계산 로직이 패키징된 앱 구조와 불일치
  3. `app.isPackaged` 체크가 제대로 동작하지 않음
  4. electron 모듈 import 방식 오류
- **해결**:
  1. `package.json`에 macOS AudioHelper.app extraFiles 추가
  2. `audioHelperManager.js`에서 여러 후보 경로를 순차 확인하도록 개선
  3. `app.isPackaged` 체크 대신 실제 파일 존재 여부로 판단
  4. `const app = require('electron')` → `const { app } = require('electron')` 수정
  5. 경로 디버깅 로그 추가
- **결과**: Helper 정상 시작 확인

## 25.10.29 (이전)

### macos 환경에서 SQLite 실행문제
```bash
Uncaught (in promise) Error: Error invoking remote method 'toggle-upload-list': Error: The module '/Users/recording-pc-app/node_modules/better-sqlite3/build/Release/better_sqlite3.node'
was compiled against a different Node.js version using
NODE_MODULE_VERSION 137. This version of Node.js requires
NODE_MODULE_VERSION 139. Please try re-compiling or re-installing
the module (for instance, using `npm rebuild` or `npm install`).
```
발생하여 

```bash
npm install --save-dev electron-rebuild
npx electron-rebuild
```
하여 해결
