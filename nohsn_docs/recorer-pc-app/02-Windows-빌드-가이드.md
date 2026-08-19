# 02. Windows 빌드 가이드

> **이 문서가 내일 제일 먼저 볼 문서입니다.**
> 기존 `docs/BUILD_GUIDE.md` 는 macOS 전용이므로 보지 마세요.

---

## 0. 핵심 전제 — WebRTC 라이브러리는 필수가 아닙니다

README 와 `build.bat` 만 보면 WebRTC 프리빌트 라이브러리(`5735-win-x64.zip`)가
반드시 있어야 하는 것처럼 보입니다. **아닙니다.**

**근거 1** — 코드에 자체 AEC 폴백이 이미 구현되어 있습니다.

`src/helpers/windows/AudioHelper.cpp:669`
```cpp
// AEC 초기화: 기본은 WebRTC가 가능하면 WebRTC, 아니면 NLMS
#ifdef WEBRTC_APM_AVAILABLE
    aecBackend = std::make_unique<WebRtcAecBackend>(...);   // WebRTC APM
    aecBackendType = AecBackendType::WEBRTC;
#else
    aecBackend = std::make_unique<NlmsAecBackend>(...);     // 자체 NLMS 적응 필터
    aecBackendType = AecBackendType::NLMS;
#endif
```

`AudioHelper.h` 에 `IAecBackend` 인터페이스와 `NlmsAecBackend` / `WebRtcAecBackend`
두 구현이 모두 정의되어 있습니다.

**근거 2** — CMake 옵션의 **기본값이 OFF** 입니다.

`src/helpers/windows/CMakeLists.txt`
```cmake
option(USE_WEBRTC_AEC "Use WebRTC Audio Processing AEC" OFF)
```

WebRTC 를 강제하는 것은 **오직 `build.bat` 의 파일 존재 체크뿐**이며,
CMake 를 직접 호출하면 그 체크를 건너뜁니다.

### 그래서 어떻게 되나

| | WebRTC 있음 | WebRTC 없음 |
|---|---|---|
| 빌드 | ✅ | ✅ |
| 녹음 · 믹싱 · 세그먼트 · 암호화 · 장치관리 | 동일 | 동일 |
| 에코 제거(AEC) | WebRTC APM | NLMS 적응 필터 |
| `helper_info` 이벤트의 `webrtc_aec` | `true` | `false` |

**권장 전략: 일단 WebRTC 없이 빌드해서 end-to-end 를 뚫고,
에코 품질 문제가 실제로 관측되면 그때 WebRTC 를 붙인다.**

WebRTC 를 붙이는 건 `/MT` 런타임 정합, ABI, Abseil 헤더 경로 등
부수 이슈가 많아서 첫날 하기엔 리스크가 큽니다.

---

## 1. 사전 준비

| 항목 | 버전 | 비고 |
|---|---|---|
| Node.js | **22.x** | |
| Visual Studio | **2022** (Community 가능) | "C++를 사용한 데스크톱 개발" 워크로드 필수 |
| CMake | 3.16+ | VS 2022 설치 시 동봉됨 |
| Git | | |

> ⚠️ `build.bat` 이 제너레이터를 `"Visual Studio 17 2022"` 로 **하드코딩**하고 있습니다.
> README 에는 "VS2019+" 라고 적혀 있지만 실제로는 **2022 가 필요**합니다.
> 2019 만 있다면 `-G "Visual Studio 16 2019"` 로 바꿔야 합니다.

---

## 2. AudioHelper.exe 빌드

### 방법 A — WebRTC 없이 (권장, 첫 빌드)

`build.bat` 은 WebRTC 가 없으면 그냥 죽으므로 **CMake 를 직접 호출**합니다.

```bat
cd src\helpers\windows
mkdir build
cd build

cmake .. -G "Visual Studio 17 2022" -A x64

cmake --build . --config Release

copy Release\AudioHelper.exe ..\AudioHelper.exe
cd ..
```

최종적으로 `src\helpers\windows\AudioHelper.exe` 가 생기면 성공입니다.
(이 경로는 `package.json` 의 `extraFiles` 가 참조하는 위치입니다)

### 방법 B — WebRTC 포함 (나중에)

1. https://github.com/bengreenier/webrtc/releases/tag/5735 에서 `5735-win-x64.zip` 다운로드
2. 압축 해제 후 **프로젝트 루트**의 `WebRTCLib/` 에 배치
   ```
   WebRTCLib/
   ├─ debug/
   ├─ include/
   └─ release/       ← webrtc.lib 가 여기 있어야 함
   ```
3. ```bat
   cd src\helpers\windows
   build.bat
   ```
   또는 `npm run build-helper`

---

## 3. 빌드가 실패할 때 — 예상 지점 3곳

### 3-1. `nlohmann/json` 다운로드 실패 (사내망/오프라인)

`CMakeLists.txt` 가 configure 단계에서 GitHub 에 접속합니다.

```cmake
include(FetchContent)
FetchContent_Declare(json URL https://github.com/nlohmann/json/releases/download/v3.11.2/json.tar.xz)
FetchContent_MakeAvailable(json)
```

**그런데 이 라이브러리는 실제로 쓰이지 않습니다.**
코드는 전부 벤더링된 `simple_json.hpp` (`using json = SimpleJson`)를 사용하며,
`nlohmann` 을 include 하는 파일이 **하나도 없습니다.**
(옆에 있는 960KB짜리 `json.hpp` 도 미사용입니다.)

**해결**: `CMakeLists.txt` 에서 아래 두 부분을 제거하면 오프라인 빌드가 됩니다.

```cmake
# 1) 삭제
include(FetchContent)
FetchContent_Declare(json URL https://...)
FetchContent_MakeAvailable(json)

# 2) target_link_libraries 에서 아래 한 줄 삭제
    nlohmann_json::nlohmann_json
```

### 3-2. Visual Studio 제너레이터 불일치

```
CMake Error: Could not create named generator Visual Studio 17 2022
```
→ 설치된 VS 버전에 맞게 `-G` 값을 변경 (`Visual Studio 16 2019` 등)

### 3-3. `/MT` 런타임 관련 링크 에러

WebRTC 를 포함할 때만 발생합니다. WebRTC 프리빌트가 `/MT`(정적 런타임)로
빌드되어 있어 CMakeLists 도 `/MT` 로 맞춰둔 상태입니다.
→ **방법 A(WebRTC 없이)로 가면 이 문제 자체가 없습니다.**

---

## 4. 헬퍼 단독 검증 (Electron 없이) ★중요

**Electron 을 얹기 전에 헬퍼만 먼저 검증하세요.**

앱까지 올린 상태에서 문제가 나면 "오디오가 안 되는 건지 / IPC 가 안 되는 건지 /
UI 가 안 되는 건지" 가 구분되지 않습니다. 헬퍼는 stdin 에 JSON 한 줄씩 넣는 게
전부라 단독 검증이 쉽고, 테스트 파일도 이미 준비되어 있습니다.

```bat
cd src\helpers\windows

REM 마이크만 녹음
AudioHelper.exe < test_mic.json

REM 시스템 사운드 (cmds.json: 10초, SystemOnly 모드)
AudioHelper.exe < cmds.json

REM 세그먼트 동작 확인
AudioHelper.exe < test_segment.json
```

### 준비된 테스트 파일

| 파일 | 내용 |
|---|---|
| `cmds.json` | output_dir 설정 + debug 파일 ON + SystemOnly 10초 |
| `test_mic.json` | 마이크 테스트 |
| `test_segment.json` / `test_segment_real.json` | 세그먼트 롤오버 |
| `test_start_only.json` | start 명령만 |
| `test_auto.json`, `test_command.json` | 기타 |

`cmds.json` 내용 예시:
```json
{"cmd":"set_output_dir","directory":"test_recordings"}
{"cmd":"set_debug_files","enabled":"true"}
{"cmd":"start","mode":"SystemOnly","mic":"default","max_ms":"10000"}
```

### 확인할 것

1. 기동 즉시 `{"ev":"helper_info", ...}` 가 stdout 에 출력되는가
   → 여기서 `"webrtc_aec":false` 로 나오면 NLMS 모드로 정상 빌드된 것
2. `level` / `progress` 이벤트가 흐르는가
3. 지정한 출력 폴더에 파일이 생성되는가
4. `set_debug_files` 를 켰다면 mic / system / mix 각각의 WAV 가 생성되는가
   → **이 3개 WAV 를 재생해보면 캡처가 실제로 되는지 즉시 판별됩니다**

> 💡 `set_debug_files` 로 나오는 디버그 WAV 는 문제 진단에 가장 강력한 도구입니다.
> 마이크 WAV 는 소리가 나는데 시스템 WAV 가 무음이면 → 루프백 캡처 문제,
> 둘 다 되는데 mix 가 이상하면 → 믹싱/타이밍 문제로 바로 좁혀집니다.

---

## 5. Electron 앱 실행

```bat
npm install
npm run dev
```

`npm run dev` = `electronmon . --dev` (핫리로드 + DevTools 자동 오픈)

### 예상 이슈: `better-sqlite3` 네이티브 모듈

`better-sqlite3` 는 네이티브 모듈이라 **Electron 의 ABI 에 맞게 리빌드**가 필요할 수 있습니다.
현재 `package.json` 에 `postinstall` 스크립트가 없고 `electron-rebuild` 는
devDependencies 에만 들어 있습니다.

`Error: The module '...better_sqlite3.node' was compiled against a different Node.js version`
같은 에러가 나면:

```bat
npx electron-rebuild -f -w better-sqlite3
```

### 예상 이슈: `form-data`

`src/main/main.js:3` 이 `require("form-data")` 를 하는데
**`package.json` 의 dependencies 에 선언되어 있지 않습니다.**
현재는 `axios` 의 전이 의존성으로 호이스팅되어 우연히 동작합니다.

`Cannot find module 'form-data'` 가 뜨면:
```bat
npm install form-data
```
(어차피 선언하는 게 맞습니다 — [04번 문서](04-알려진-이슈.md) 참조)

---

## 6. 패키징

```bat
npm run build
```

산출물:
- `dist\timbloRecApp Setup 1.0.0.exe` (NSIS 설치본)
- `dist\win-unpacked\` (압축 해제 상태)

### 빌드 훅 안전성 ✅

`package.json` 의 `afterPack` / `afterSign` 훅은 macOS 전용 로직(codesign, notarize)이지만,
**둘 다 첫 줄에서 non-darwin 이면 조기 반환**하므로 Windows 빌드를 깨뜨리지 않습니다.

```js
// scripts/afterPack.js
if (context.electronPlatformName !== 'darwin') return;

// scripts/afterSign.js
if (electronPlatformName !== 'darwin') return;
```

### 헬퍼 배치 확인

`package.json` 의 `extraFiles` 가 아래처럼 복사합니다.
```
src/helpers/windows/AudioHelper.exe  →  helpers/windows/AudioHelper.exe
```

런타임에 `audioHelperManager.getHelperPath()` 가 후보 경로를 순서대로 탐색합니다:
1. `resources/app.asar.unpacked/helpers/windows/AudioHelper.exe`
2. `resources/helpers/windows/AudioHelper.exe`
3. `resources/../helpers/windows/AudioHelper.exe` ← **extraFiles 배치 위치**
4. `src/helpers/windows/AudioHelper.exe` (개발 모드)

`asar` 내부 경로는 spawn 불가라 자동으로 건너뜁니다.

### ⚠️ 코드 서명 미설정

`package.json` 의 `win` 블록에 서명 설정이 전혀 없습니다.
```json
"win": { "target": "nsis", "icon": "electron-resources/logo.ico" }
```
→ 설치 시 SmartScreen 경고가 뜹니다. 사내 배포라도 마찬가지입니다.
자세한 내용은 [04번 문서](04-알려진-이슈.md).

---

## 7. 딥링크 프로토콜 등록

앱은 `timbloRecApp://` 스킴을 사용합니다.

- 설치본(NSIS)으로 설치하면 자동 등록됩니다.
- 개발 모드에서 수동 등록이 필요하면:
  ```bat
  npm run register-protocol
  ```
  (`scripts/register-protocol-manual.js`)

---

## 요약 체크리스트

```
[ ] VS 2022 + "C++ 데스크톱 개발" 워크로드 설치
[ ] Node 22.x 설치
[ ] cmake .. -G "Visual Studio 17 2022" -A x64   (WebRTC 없이)
[ ] cmake --build . --config Release
[ ] AudioHelper.exe 를 src\helpers\windows\ 로 복사
[ ] AudioHelper.exe < cmds.json  으로 단독 검증  ★
[ ] 디버그 WAV 재생해서 실제 캡처 확인          ★
[ ] npm install  (+ 필요시 electron-rebuild, form-data)
[ ] npm run dev  → 장치목록 → 녹음 → 세그먼트 생성
[ ] npm run build → NSIS 설치본
```
