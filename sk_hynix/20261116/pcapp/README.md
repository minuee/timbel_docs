# timbloRecApp (Meeting Recorder)

크로스플랫폼 실시간 오디오 녹음 및 관리 애플리케이션

> **지원 플랫폼**: macOS (Apple Silicon), Windows (개발 중)


## 🛠️ 기술 스택

### Frontend
- **Electron**: 크로스플랫폼 데스크톱 애플리케이션 프레임워크
- **JavaScript (ES6+)**: 메인 애플리케이션 로직
- **HTML5/CSS3**: 사용자 인터페이스
- **IPC (Inter-Process Communication)**: 메인-렌더러 프로세스 통신

### Backend
- **Node.js**: 메인 프로세스 런타임
- **Swift 5**: 네이티브 오디오 처리 헬퍼 (macOS)
- **C++**: 네이티브 오디오 처리 헬퍼 (Windows)
- **CoreAudio**: 오디오 캡처 및 처리 (macOS)
- **Windows Audio API**: 오디오 캡처 및 처리 (Windows)
- **BCrypt/CryptoSwift**: 암호화 라이브러리

### 빌드 시스템
- **electron-builder**: 앱 패키징 및 배포
- **CMake**: C++ 헬퍼 빌드 시스템
- **MSVC**: Windows C++ 컴파일러

## 📦 설치 및 실행

### 최종 사용자 (macOS)

빌드된 앱을 설치하려면 **[설치 가이드](docs/INSTALLATION_GUIDE.md)**를 참조하세요.

> ⚠️ **중요**: macOS에서 앱 설치 후 반드시 설치 가이드의 보안 설정을 따라야 합니다.

### 개발 환경 요구사항

#### macOS
- **Node.js** 22.x
- **npm** 또는 **yarn**
- **Xcode** 16+ (Swift 헬퍼 빌드용)
- **macOS** 15.0+ (Sequoia)

#### Windows
- **Node.js** 22.x 
- **npm** 또는 **yarn**
- **Visual Studio 2019+** (C++ 헬퍼 빌드용)
- **CMake** 3.15 이상
- **Windows 10/11**

### 설치 방법

1. **저장소 클론**
   ```bash
   git clone https://github.com/timbel-timblo-onpremise/recording-pc-app.git
   cd recording-pc-app.git
   ```

2. **의존성 설치**
   ```bash
   npm install
   ```

3. **네이티브 헬퍼 빌드**

   #### macOS (Swift)
   ```bash
   # Xcode 프로젝트 열기
   open src/helpers/macos/AudioHelper/AudioHelper.xcodeproj
   
   # Xcode에서 Product → Build (⌘B)
   # 빌드된 앱을 src/helpers/macos/AudioHelper.app 에 복사
   
   # ad-hoc 서명으로 재서명 (필수)
   npm run sign-helper
   ```

   #### Windows (C++)
   아래 경로의 미리 빌드된 라이브러리를 사용한다.(5735-win-x64.zip)
   https://github.com/bengreenier/webrtc/releases/tag/5735
  
   압축 해제 후 `(프로젝트 루트경로)/WebRTCLib/` 경로에 삽입
   ```bash
   WebRTCLib
   ├─debug
   ├─include
   └─release
   ```

   이후 Visual Studio 에서 Cmake 빌드
   ```bash
   cd src/helpers/windows
   ./build.bat
   ```

4. **개발 모드 실행**
   ```bash
   npm run dev
   ```

### 프로덕션 빌드

```bash
# 애플리케이션 빌드
npm run build

# 실행 파일 위치
- windows
dist/win-unpacked/Meeting Recorder.exe

- macOS
dist/mac-arm64/Meeting Recorder.app
```

## 📁 프로젝트 구조

```
meeting-recorder/
├── src/
│   ├── main/                    # 메인 프로세스
│   │   ├── main.js             # 앱 엔트리포인트
│   │   ├── preload.js          # 프리로드 스크립트
│   │   └── notificationManager.js # 알림 관리
│   ├── renderer/               # 렌더러 프로세스
│   │   ├── index.html          # 메인 UI
│   │   ├── app.js              # 애플리케이션 로직
│   │   └── styles.css          # 스타일시트
│   └── helpers/                # 네이티브 헬퍼
│       └── windows/
│           ├── AudioHelper.cpp # C++ 오디오 처리
│           ├── AudioHelper.h   # 헤더 파일
│           ├── WavWriter.cpp   # WAV 파일 작성
│           └── CMakeLists.txt  # 빌드 설정
├── dist/                       # 빌드 출력
├── docs/                       # 문서
├── test_recordings/            # 테스트 녹음 파일
├── package.json               # npm 설정
└── README.md                  # 프로젝트 문서
```

## 🚀 사용 방법

### 1. 오디오 시스템 초기화
- "오디오 시스템 초기화" 버튼 클릭
- 사용 가능한 마이크 디바이스 자동 검색
- 원하는 마이크 선택

### 2. 오디오 테스트
- "오디오 테스트" 섹션에서 테스트 실행
- 마이크 입력 레벨 확인
- 음질 및 설정 조정

### 3. 녹음 시작
- "녹음 준비" 섹션으로 이동
- 세션 정보 입력 (선택사항)
- "녹음 시작" 버튼으로 녹음 개시

### 4. 녹음 관리
- 실시간 녹음 상태 모니터링
- 일시정지/재개 기능 활용
- 메모 기능으로 중요 시점 기록

### 5. 로깅
- 전체 프로세스의 로그를 파일로 기록
- `%appData%` 의 `timbloRecApp/logs` 경로에서 확인 가능
- 에러 로그는 추가로 `error-{data}.log` 로 기록

## 🔧 설정 및 커스터마이징

### 환경 변수
```env
# 개발 모드 활성화
NODE_ENV=development

# 로그 레벨 설정
LOG_LEVEL=debug
```

### 빌드 설정
`package.json`의 `build` 섹션에서 패키징 옵션 수정 가능:
- 앱 ID 및 제품명
- 아이콘 및 리소스
- 설치 관련 설정

## 🔐 보안 고려사항

- **암호화 키**: 각 세션마다 고유한 AES-256 키 생성
- **파일 저장**: 암호화된 상태로만 디스크에 저장
- **메모리 보안**: 민감한 데이터의 메모리 정리
- **권한 관리**: 최소 권한 원칙 적용

## 🐛 문제 해결

### macOS 관련 문제

**Q: "손상되었기 때문에 열 수 없습니다" 에러**
- 해결: [설치 가이드](docs/INSTALLATION_GUIDE.md) 참조
- 터미널에서 `xattr -cr /Applications/timbloRecApp.app` 실행

**Q: 마이크가 작동하지 않습니다**
- 시스템 설정 → 개인정보 보호 및 보안 → 마이크
- `timbloRecApp` 찾아서 체크박스 활성화
- 앱 재시작

**Q: "확인 없이 열기" 버튼이 보이지 않습니다**
- 앱을 실행 시도하고 에러 메시지 확인 클릭
- 10초 후 시스템 설정 다시 확인
- 또는 터미널 명령어 사용 ([설치 가이드](docs/INSTALLATION_GUIDE.md))

### Windows 관련 문제

**Q: 마이크가 감지되지 않습니다**
- Windows 개인정보 설정에서 마이크 액세스 허용 확인
- 디바이스 관리자에서 오디오 드라이버 상태 확인

**Q: 알림이 표시되지 않습니다**
- Windows 설정 > 알림에서 앱 알림 허용 확인
- 방해 금지 모드 비활성화

**Q: 빌드가 실패합니다**
- Visual Studio Build Tools 설치 확인
- CMake 경로 설정 확인
- 관리자 권한으로 PowerShell 실행

### 로그 확인
- 개발자 도구 (F12) 콘솔 확인
- 메인 프로세스 로그 모니터링
- 네이티브 헬퍼 출력 확인
- 로그 위치:
  - **macOS**: `~/Library/Application Support/timbloRecApp/logs/`
  - **Windows**: `%appData%/timbloRecApp/logs/`





