# Windows AudioHelper.exe 만들기 / 바꾸기

`AudioHelper.exe` 는 git 에 없다(`.gitignore` 의 `*.exe`). 그래서 회사 PC 에는 소스만 있고 exe 는 예전에 따로 만든 것이 들어 있다.
그 exe 가 지금 소스(v0.4.2)와 다르면 장치 목록이 안 나오거나, 녹음 폴더 구조가 달라 업로드가 실패(`filePath is not a directory`)할 수 있다.
**지금 소스로 다시 만든 exe 로 바꾸는 것**이 목적이다.

| | A. 집 Mac 에서 만든 exe | B. 회사 PC 에서 직접 빌드 (권장) |
|---|---|---|
| 에코 제거(WebRTC AEC) | **없음** | 있음 |
| 회사에서 할 일 | exe 덮어쓰기 | `build.bat` 실행 |
| 필요한 것 | 없음 | Visual Studio 2022(C++), `WebRTCLib` 폴더 |

**B 를 먼저 해 보고, 안 되면 A** 를 쓴다. A 는 마이크+스피커를 같이 녹음할 때 스피커 소리가 마이크로 다시 들어간 울림이 남을 수 있다.

### 어떤 헬퍼가 돌고 있는지 보는 법
녹음 화면 ⚙ 설정 메뉴 → **버전 정보** (오늘 `recording.js` 반영 후. 전에는 버그로 안 보였다)
- B 로 만든 것: `v0.4.2 AEC`
- A 로 만든 것: `v0.4.2`
- 마우스를 올리면 빌드 날짜가 나온다 (A 는 `Oct 13 2026`)

---

## B. 회사 PC 에서 직접 빌드

### 바뀐 점 (오늘 반영 파일)
- `src/helpers/windows/CMakeLists.txt` — json 라이브러리를 GitHub 에서 받던 것(FetchContent)을 **폴더 안 `json.hpp` 를 쓰도록** 바꿨다. 이제 인터넷 없이 빌드된다
- `src/helpers/windows/versioninfo.h` — WebRTC 를 실제로 링크했을 때만 `WebRTC AEC` 로 표시
- `src/helpers/windows/WavWriter.cpp`, `Logger.cpp` — 파일 열기를 표준 방식(`std::filesystem::path`)으로. MSVC 에서 동작은 같다

### 순서
1. 위 파일들을 교체 (`docs/update_20261014.md` 목록 참고)
2. `WebRTCLib` 위치 확인 — `build.bat` 은 **프로젝트 루트**의 `WebRTCLib` 를 찾는다
   ```
   <프로젝트>\WebRTCLib\include\...
   <프로젝트>\WebRTCLib\release\webrtc.lib
   ```
3. 시작 메뉴 → **"x64 Native Tools Command Prompt for VS 2022"** (또는 "Developer Command Prompt for VS 2022") 실행
   — 일반 cmd 에는 `cmake` 가 없을 수 있다. VS 에 들어 있는 cmake 를 쓰려면 이 창에서 해야 한다
4. ```bat
   cd <프로젝트>\src\helpers\windows
   build.bat
   ```
5. 끝에 `Build completed successfully!` → `src\helpers\windows\AudioHelper.exe` 가 새로 생긴다(기존 파일 덮어씀)
6. `npm run dev` → 마이크 테스트 화면에서 마이크/스피커 목록 확인 → 녹음 화면 설정 메뉴 "버전 정보" 가 `v0.4.2 AEC`

### 막혔을 때
| 증상 | 할 일 |
|---|---|
| `'cmake'은(는) 내부 또는 외부 명령...` | 3번의 VS 명령 프롬프트에서 실행. 그래도 없으면 VS 설치 관리자 → "C++를 사용한 데스크톱 개발" 의 "Windows용 C++ CMake 도구" |
| `ERROR: WebRTC ... not found` | 2번 경로. 폴더가 다른 곳에 있으면 루트로 복사 |
| `Visual Studio 17 2022 could not find` | VS 2022 가 아닌 버전이면 `build.bat` 의 `-G "Visual Studio 17 2022"` 를 설치된 버전으로 (2019 = `"Visual Studio 16 2019"`) |
| `json.tar.xz` / github 다운로드 오류 | `CMakeLists.txt` 가 옛 파일이다. 오늘 파일로 교체, `build` 폴더 지우고 다시 |
| 컴파일 오류 | 오류 메시지 첫 몇 줄을 가져올 것 |

> 빌드 후 기존 exe 가 쓰이는 중이면 복사 실패한다(`Failed to copy executable!`). 앱(`npm run dev`)을 끄고 다시 `build.bat`.

---

## A. 집 Mac 에서 만든 exe 쓰기

### 가져갈 것
`docs/helper-build/dist/AudioHelper.exe` (약 1.6MB) — git 에 없음. **따로 복사**
- SHA-256: `4b8d1a8ad3b405c5c638ae38340ee74747c80ff837ed56c5b79e563a2e7b5070`
- v0.4.2, WebRTC AEC 없음, Windows 10/11 기본 DLL 만 사용(별도 설치 불필요)

### 순서
1. 앱(`npm run dev`) 종료
2. 기존 `src\helpers\windows\AudioHelper.exe` 를 `AudioHelper.exe.bak` 으로 이름 바꿔 보관
3. 가져온 `AudioHelper.exe` 를 `src\helpers\windows\` 에 넣기
4. `npm run dev` → 마이크/스피커 목록 → 녹음 → 업로드 확인
5. 문제 있으면 `.bak` 을 되돌린다

### 집에서 확인한 것
- wine(Windows 호환 실행기)으로 실행: 버전 응답, **마이크·스피커 목록(한글 이름 포함) 정상**, 한글이 들어간 저장 경로 정상
- 확인 못 한 것: 실제 녹음(wine 이 Mac 마이크를 열지 못함) → 회사 PC 에서 확인

### 다시 만들 때 (집 Mac)
```bash
brew install mingw-w64 cmake   # 한 번만
src/helpers/windows/build-mingw.sh
```

---

## 설치본(`npm run build`)에 들어가는 헬퍼
`package.json` 의 `extraFiles` 가 `src/helpers/windows/AudioHelper.exe` 를 설치본에 넣는다.
**빌드 전에 위 A 또는 B 로 바꾼 exe 가 그 자리에 있어야** 설치본에도 새 헬퍼가 들어간다.
