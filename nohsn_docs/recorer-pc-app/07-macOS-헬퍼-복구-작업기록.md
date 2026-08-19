# 07. macOS 헬퍼 복구 작업 기록 (인수인계용)

> 작업일: 2026-08-19
> 상태: **macOS 14.6에서 빌드·녹음·Electron 앱 연결까지 모두 성공.** 남은 건 앱 UI 경유 녹음 확인
> 이 문서는 IDE 재가동으로 대화가 끊긴 뒤 **이어서 작업하기 위한 기록**입니다.

---

## 요약

어제까지 최대 리스크였던 **"macOS 헬퍼 Swift 소스 부재"가 해소**되었습니다.

| 단계 | 결과 |
|---|---|
| Swift 소스 확보 | ✅ 사용자가 원본 회수 → `newDocs/mac_recorder-main/` |
| Xcode 빌드 (원본, macOS 15 타겟) | ✅ 성공 |
| 이 맥북에서 실행 (macOS 14.6) | ❌ `built for macOS 15.0 which is newer than running OS` |
| **macOS 14 호환 실험 (옵션 C)** | ✅ **빌드·실행 모두 성공** |
| TCC 권한 (마이크 + 화면 기록) | ✅ 획득 |
| **실제 녹음 검증** | ✅ **성공** — mic/system 캡처, 세그먼트 생성, 드리프트 0 ([5절](#5-검증-완료-항목)) |
| **Electron 앱 연결** | ✅ **성공** — 앱 기동 + 헬퍼 IPC 왕복 확인 ([7-1절](#7-1-electron-앱-연결-2026-08-19-완료)) |
| 앱 UI 경유 실제 녹음 | ⏸ 미검증 (TCC 재부여 필요) |

검증 과정에서 **mac↔Windows 차이 2건을 추가로 발견**했습니다 — `max_ms` 경계 정지 동작([6-4](#6-4-max_ms-는-세그먼트-경계에서만-정지함))과
`set_debug_files` no-op([6-5](#6-5-set_debug_files-가-macos-에서는-사실상-no-op)). Windows 이관 시 참고가 됩니다.

---

## 1. 현재 파일 상태 (중요)

**2026-08-19 정리 완료.** 실사용 소스는 `src/helpers/macos/AudioHelper/` 로 이동했습니다.

```
src/helpers/macos/                       ★ 실사용 위치
├── AudioHelper/                         ← macOS 14 호환본 소스 (실험본을 여기로 이동)
│   ├── AudioHelper.xcodeproj/           ← ★ Xcode 로 여는 파일
│   ├── AudioHelper/
│   │   ├── AudioHelper.entitlements     ← sign-helper.sh 가 찾는 경로
│   │   ├── AudioHelperController.swift  ← 수정됨 (@available, captureMicrophone)
│   │   ├── SegmentManager.swift         ← 수정됨
│   │   ├── AudioHelper.swift / FileLogger.swift / JSONModels.swift
│   │   └── Info.plist
│   ├── Assets.xcassets/
│   └── CHANGELOG.md / README.md / electron_helper_interface.md
├── AudioHelper.app                      ← 빌드 산출물 (.gitignore 대상)
└── ToDo.txt

newDocs/                                 ← 문서 전용 (432KB)
├── 01~07 *.md
├── mac_recorder-main/                   ← 원본 Swift 소스 (수정 안 함, 참조용 보존)
│   ├── AudioHelper/                     ← Swift 5개 파일, 2,615 LOC
│   ├── AudioHelper.xcodeproj/
│   └── electron_helper_interface.md     ← macOS판 (덮어쓰지 말 것, 6절 참조)
└── mac_recorder-main.zip                ← 원본 압축본
```

### 주의사항

- **깨진 심볼릭 링크는 해소되었습니다.** `src/helpers/macos/AudioHelper` 가 퇴사자 맥북
  (`/Users/jangjunho/dev/...`)을 가리키고 있어 `npm run sign-helper` 와 `afterPack.js` 가
  참조하는 entitlements 경로가 존재하지 않았습니다. 실제 소스로 교체 후 **새 위치에서
  `xcodebuild` BUILD SUCCEEDED 확인 완료.**
- `newDocs/mac_experiment/` 와 `mac_recorder-main/DerivedData/` 는 삭제했습니다 (328MB → 432KB).
  전자는 `src/helpers/macos/AudioHelper/` 로 완전 복사됨을 `diff -r` 로 확인한 뒤 지웠습니다.
- `newDocs/mac_recorder-main/` 소스는 **수정 안 된 원본의 유일한 사본**이라 보존했습니다.
  실험본과 `AudioHelperController.swift`, `SegmentManager.swift` 2개 파일이 다릅니다.
  macOS 15 전용으로 되돌릴 일이 생기면 이것이 기준점입니다.
- `newDocs/` 는 git untracked 이므로 여기서 지운 것은 **git 으로 복구되지 않습니다.**
- `src/helpers/macos/AudioHelper.app` 은 `.gitignore` 대상이라 git에 영향 없습니다.

> ⚠️ **배포 시 소스 노출 주의.** `package.json` 의 `build.files` 는 `.cpp`/`.h` 만 제외하고
> `.swift` / `.xcodeproj` 는 제외하지 않습니다. 이대로 `npm run build` 하면 Swift 소스가
> 배포 앱에 포함됩니다. `"!src/helpers/macos/AudioHelper/**"` 추가를 권합니다.

---

## 2. 옵션 C 실험 — 무엇을 바꿨나

원본이 macOS 15.0을 요구하는 원인을 특정하고, 최소 변경으로 14.0 호환을 만들었습니다.

### 원인

`SCStreamConfiguration.captureMicrophone` — **macOS 15.0부터 추가된 API**.
소스 3곳에서 참조하며, 이 때문에 클래스 전체에 `@available(macOS 15.0, *)` 가 걸려 있었습니다.

### 변경 내용 (현재 `src/helpers/macos/AudioHelper/` 에 반영됨)

| 변경 | 대상 | 개수 |
|---|---|---|
| `@available(macOS 15.0, *)` → `@available(macOS 14.0, *)` | `AudioHelperController.swift`, `SegmentManager.swift` | 12곳 |
| `captureMicrophone = false` 주석 처리 (`// [macOS14]` 표시) | `AudioHelperController.swift` 553, 1023, 1391행 | 3곳 |

### 왜 안전한가

3곳 모두 **`false`로 설정**하고 있고, **`false`가 기본값**입니다.
마이크는 ScreenCaptureKit이 아니라 `AVCaptureSession`으로 따로 캡처하므로
이 프로퍼티는 애초에 쓰이지 않습니다. 즉 **제거해도 동작이 달라지지 않습니다.**

> 다만 런타임에 다른 macOS 15 의존이 남아 있을 가능성은 배제 못 합니다.
> 실제 녹음까지 검증되어야 최종 확인입니다.

---

## 3. 빌드 방법 (재현용)

### 원본 그대로 빌드 (macOS 15+ 필요)

```bash
cd newDocs/mac_recorder-main
xcodebuild -project AudioHelper.xcodeproj -scheme AudioHelper \
  -configuration Release -derivedDataPath ./DerivedData \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY="" DEVELOPMENT_TEAM="" build
```

### macOS 14 호환 빌드 (현재 실사용본)

```bash
cd src/helpers/macos/AudioHelper
xcodebuild -project AudioHelper.xcodeproj -scheme AudioHelper \
  -configuration Release -derivedDataPath ./DerivedData \
  MACOSX_DEPLOYMENT_TARGET=14.0 \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY="" DEVELOPMENT_TEAM="" build
```

### 서명 및 배치

```bash
APP=DerivedData/Build/Products/Release/AudioHelper.app
codesign --force --deep --sign - \
  --entitlements AudioHelper/AudioHelper.entitlements "$APP"

# 앱이 찾는 위치로 배치 (cwd: src/helpers/macos/AudioHelper)
rm -rf ../AudioHelper.app
cp -R "$APP" ../AudioHelper.app
```

> **왜 `CODE_SIGNING_ALLOWED=NO` 인가**
> 프로젝트가 TIMBEL 팀(`7H4827QYPR`)의 "Mac Development" 인증서를 요구하는데
> 이 맥북에 없어서 빌드가 실패합니다. 서명 없이 빌드 후 ad-hoc 서명하면 됩니다.
> (원 개발자의 README도 Xcode 빌드 후 ad-hoc 재서명을 전제로 합니다)

---

## 4. 헬퍼 단독 테스트 방법

헬퍼는 RunLoop로 계속 살아있고 stdout이 파이프면 버퍼링되어 출력이 안 보입니다.
**`script` 로 pty를 물려야** 실시간 출력이 보입니다.

> ⚠️ **`stop` 명령을 반드시 보내야 합니다.**
> `pkill` 로 프로세스를 죽이면 flush/finalize 가 안 되어 **출력 디렉터리가 비어 있습니다.**
> `max_ms` 는 세그먼트 경계에서만 동작하므로 짧은 테스트에서는 자동 정지를 기대할 수 없습니다 ([6-4](#6-4-max_ms-는-세그먼트-경계에서만-정지함) 참조).

```bash
cd src/helpers/macos/AudioHelper
APP="$PWD/DerivedData/Build/Products/Release/AudioHelper.app/Contents/MacOS/AudioHelper"
rm -rf /tmp/mac_test_rec

# 시스템 오디오 캡처를 확인하려면 소리를 재생해 둔다 (없으면 system rms 가 계속 0)
( afplay /System/Library/Sounds/Submarine.aiff; sleep 0.3
  afplay /System/Library/Sounds/Submarine.aiff; sleep 0.3
  afplay /System/Library/Sounds/Submarine.aiff ) >/dev/null 2>&1 &

(
 (
  echo '{"cmd":"set_output_dir","directory":"/tmp/mac_test_rec"}'; sleep 1
  echo '{"cmd":"set_debug_files","enabled":"true"}'; sleep 1
  echo '{"cmd":"start","mode":"MicPlusSystem","mic":"BuiltInMicrophoneDevice","max_ms":"5000"}'; sleep 6
  echo '{"cmd":"stop"}'; sleep 4          # ★ 필수 — 이게 있어야 파일이 생성됨
 ) | script -q /dev/null "$APP" > /tmp/helper_rec.txt 2>&1
) &
sleep 14; pkill -f "MacOS/AudioHelper"

grep -v '"ev":"level"' /tmp/helper_rec.txt | grep -v '"ev":"progress"'
find /tmp/mac_test_rec -type f -exec ls -la {} \;
```

### 캡처된 오디오가 진짜인지 검증

세그먼트는 **16kHz mono s16le raw PCM** 입니다. 헤더가 없으므로 바로 재생되지 않습니다.

```bash
F=$(find /tmp/mac_test_rec -name '*.raw' | head -1)

# 구간별 RMS/피크 확인 (무음이면 전부 0 에 가깝다)
python3 - "$F" <<'EOF'
import sys, struct, math
d = open(sys.argv[1], 'rb').read(); n = len(d)//2
s = struct.unpack('<%dh' % n, d[:n*2])
print("samples:%d -> %.3fs @16kHz mono s16le" % (n, n/16000))
for i in range(0, n, 16000):
    ch = s[i:i+16000]
    if not ch: break
    r = math.sqrt(sum(x*x for x in ch)/len(ch))
    print("  sec %d: rms=%7.1f peak=%6d" % (i//16000, r, max(abs(x) for x in ch)))
EOF

# 귀로 확인하려면 WAV 헤더를 씌운다
ffmpeg -f s16le -ar 16000 -ac 1 -i "$F" /tmp/mac_test_rec/check.wav && afplay /tmp/mac_test_rec/check.wav
```

---

## 5. 검증 완료 항목

**2026-08-19 실제 녹음 검증 완료 — macOS 14.6 에서 헬퍼 단독 동작 확인.**

```
✅ 빌드 성공 (LSMinimumSystemVersion 14.0)
✅ 실행 성공 — dyld 에러 없음
✅ helper_info      {"version":"0.1.0","webrtc_aec":false,"build_date":"Aug 19 2026"}
✅ output_dir_set
✅ disk_status      {"status":"ok","free_bytes":300436625705}
✅ debug_files_set
✅ list_devices     MacBook Pro 마이크(BuiltInMicrophoneDevice), Microsoft Teams Audio
✅ 마이크 가용성 검사 로직 통과
✅ TCC 권한 통과      마이크 + 화면 기록 모두 획득 (SYS_INIT_FAILED 더 이상 발생 안 함)
✅ 마이크 캡처        level rms 0.008~0.015
✅ 시스템 오디오 캡처  level rms 최대 0.072 (소리 재생 시)
✅ 세그먼트 파일 생성  segment_ready → {UUID}/{UUID}_0.raw
✅ mic/sys 동기화     recording_stopped 에서 mic 88064 / sys 88064 — 드리프트 0
✅ PCM 내용 검증      non-zero 99.6%, 재생 구간에서 피크 4359 확인
```

실측 이벤트:
```json
{"ev":"segment_ready","index":0,"duration_ms":5504,"samples":88064,
 "size_bytes":176128,"encrypted":false,
 "path":"/tmp/mac_test_rec/7418E322-.../7418E322-..._0.raw"}
{"ev":"recording_stopped","micSamplesWritten":88064,
 "sysSamplesWritten":88064,"totalSamples":88064}
```

구간별 RMS (5.504초, Submarine 사운드를 0초/3초 부근에 재생):
```
  sec 0: rms=587.5  peak=4359   ← 시스템 오디오 재생 구간
  sec 1: rms=238.8  peak= 781
  sec 2: rms=240.3  peak= 760
  sec 3: rms=580.9  peak=3742   ← 시스템 오디오 재생 구간
  sec 4: rms=193.0  peak= 786
  sec 5: rms=221.2  peak= 690
```

### 해결된 장벽: TCC 권한 (참고용 기록)

이전에는 아래 에러로 막혀 있었습니다:
```
{"ev":"error","code":"SYS_INIT_FAILED",
 "message":"시스템 오디오 콘텐츠를 가져올 수 없습니다: 사용자가 ... 캡처의 TCC를 거절함"}
SCStreamErrorDomain Code=-3801
```

**이것은 빌드 문제가 아니라 권한 문제이며, macOS 15에서도 동일하게 필요합니다.**
macOS 14 다운그레이드와 무관합니다.

부여 방법:
```
시스템 설정 > 개인정보 보호 및 보안 > 화면 기록 및 시스템 오디오 녹음
  → 사용 중인 IDE/터미널 앱 추가 및 체크
  → 앱 재시작 (필수)
```
> 권한은 헬퍼가 아니라 **헬퍼를 실행한 부모 프로세스**(IDE/터미널, 또는 Electron)에 귀속됩니다.
> 따라서 Electron 앱에서 처음 녹음할 때 **권한을 다시 부여해야 합니다** (터미널에 준 권한은 Electron 에 상속되지 않음).

### 참고: `silence` 이벤트

시스템 오디오가 무음이면 `{"ev":"silence","state":"early","elapsedMs":...}` 가 발생합니다.
소리를 재생한 상태에서는 발생하지 않았으므로 **정상 동작**이며, 조용한 환경에서의 테스트 실패로 오인하지 마세요.

---

## 6. 발견한 macOS ↔ Windows 차이 ★

Windows 작업에도 참고가 되는 내용입니다.

### 6-1. `mic` 파라미터 규칙이 다름

| | 허용 값 |
|---|---|
| Windows | `"default"` 사용 가능 (`cmds.json` 이 그렇게 되어 있음) |
| macOS | **`"default"` 거부.** 실제 device uniqueID 필요 |

`AudioHelperController.swift:669` `isMicAvailable(for:)` 이 `uniqueID` 완전 일치를 요구하며,
코드 주석에도 *"명세상 default 사용 금지"* 라고 적혀 있습니다.

`"default"` 를 넘기면:
```json
{"ev":"mic_state","state":"unavailable"}
{"ev":"error","code":"NO_MIC_DEVICE","message":"Selected mic is not available"}
```

> ⚠️ **같은 JSON 명령이 두 플랫폼에서 다르게 동작합니다.** 테스트 스크립트 재사용 시 주의.

### 6-2. macOS `start` 는 `mode` 를 무시함

`AudioHelperController.swift:407` `start()` 시그니처에 **`mode` 파라미터가 아예 없습니다.**

```swift
self.currentMode = "MicPlusSystem"  // 현재는 MicPlusSystem 고정
self.runtimeChannels = 1            // 강제 모노 (ch 파라미터 무시)
```

| | 지원 모드 |
|---|---|
| Windows | `MicOnly` / `MicPlusSystem` / `SystemOnly` 3종 |
| macOS | **MicPlusSystem 고정** (mode 파라미터 무시) |

이 때문에 `MicOnly` 로 요청해도 시스템 캡처를 초기화하며,
화면 녹화 권한이 없으면 `MicOnly` 조차 실패합니다.

### 6-3. `version` 명령 미지원

macOS 헬퍼에 `{"cmd":"version"}` 을 보내면 `UNKNOWN_COMMAND` 가 돌아옵니다.
(Windows 헬퍼는 `version` / `get_version` 지원)

### 6-4. `max_ms` 는 세그먼트 경계에서만 정지함

**두 플랫폼 공통 설계**이지만 Windows 에만 있는 안전장치가 macOS 에는 없습니다.

동작 방식 (양쪽 동일):
- 50ms 주기 워치독이 deadline 을 넘으면 **즉시 멈추지 않고** `stopAtBoundary = true` 플래그만 세움
  (macOS `AudioHelperController.swift:1558` / Windows `AudioHelper.cpp:3427`)
- 실제 정지는 세그먼트가 완료되는 시점에 발생 (macOS `:1290`)

> ⚠️ 따라서 **`max_ms` 보다 최대 1 세그먼트(기본 180,000ms) 만큼 초과 녹음됩니다.**
> `max_ms=3000` 으로 테스트하면 3초가 아니라 180초까지 녹음됩니다.
> 소스에도 이 경고가 로그로 남습니다 (`:490` "max_ms is less than segment duration").

**실측**: `max_ms:3000` → 13.44초 시점까지 계속 녹음 중이었고 자동 정지 없음 (경계 미도달).

| 항목 | macOS | Windows |
|---|---|---|
| `max_ms` 파싱 | ✅ `:447` | ✅ `:1433` |
| 재파싱/재시도 안전장치 | ❌ **없음** | ✅ `:1707` |
| 50ms 워치독 | ✅ `:1525` | ✅ `:3427` |
| **샘플 수 기반 백업 강제** | ❌ **없음** | ✅ `:3229` |
| 세그먼트 경계에서만 정지 | ✅ | ✅ |
| **max_ms 종료 시 마지막 부분 세그먼트 폐기** | ❌ **없음** | ✅ `:1818` |

또한 macOS 파싱은 **조용히 실패**합니다 — `"600000.0"` 같은 실수 문자열은 `UInt64()` 변환에
실패해 경고 없이 `maxDurationMs = 0`(무제한)이 됩니다. Windows 는 `std::stoull` 이라 `"600000.0"` 을
`600000` 으로 받아들입니다. **앱이 max_ms 를 문자열로 만들 때 정수 포맷을 보장해야 합니다.**

### 6-5. `set_debug_files` 가 macOS 에서는 사실상 no-op

macOS 구현(`AudioHelperController.swift:191-201`)은 `debugRawEnabled` 플래그와 로그 레벨만 바꿉니다.
그 플래그는 리샘플링 디버그 로그(`:796`, `:909`)에만 쓰입니다.

| | `set_debug_files=true` 결과 |
|---|---|
| Windows | `HandleSetDebugFiles()` — 디버그 파일 출력 |
| macOS | **파일 없음.** 로그 레벨만 `.debug` 로 상승 |

> 기존 문서에 있던 "mic/system/mix WAV 3개가 나오는지 확인" 은 **macOS 에서는 성립하지 않습니다.**
> 캡처 검증은 4절의 raw PCM RMS 분석으로 대신하세요.

---

## 7. 다음에 할 일

### ✅ 완료 (2026-08-19)

1. ~~IDE/터미널 재시작~~ → TCC 권한 획득 완료
2. ~~4절의 헬퍼 단독 테스트~~ → **성공**, 5절에 실측 결과 기록
3. ~~level/progress/세그먼트 파일 확인~~ → 모두 확인, PCM 내용까지 검증
4. ~~`npm run dev` 로 Electron 앱 연결~~ → **성공** (7-1 참고)

---

## 7-1. Electron 앱 연결 (2026-08-19 완료)

### 결과

```
✅ npm run dev 로 앱 기동, 380x436 창 정상 표시
✅ helper_info    앱이 헬퍼 프로세스 spawn 성공
✅ devices        장치 목록 조회 성공
✅ test_started   {"mode":"MicPlusSystem","reuse":false} — IPC 왕복 확인
✅ window_loaded  windowId: 1
```

> 로그의 `Autofill.enable wasn't found` 에러는 **DevTools 자체 노이즈**입니다. 앱 문제가 아닙니다.

헬퍼는 이미 앱이 찾는 경로에 배치되어 있고, 5절에서 검증한 바이너리와 **해시가 동일**합니다:
```
ede32e1ca1efddeb4694bec97eeb9c0776df563d  src/helpers/macos/AudioHelper.app/Contents/MacOS/AudioHelper
ede32e1ca1efddeb4694bec97eeb9c0776df563d  (5절 검증 시점의 빌드 산출물)
```
경로 결정 로직: `src/main/audioHelperManager.js:76` (개발 모드는 `process.cwd()/src/helpers/macos/...`)

### ⚠️ 함정: `npm install` 이 Electron 압축 해제에 조용히 실패함

이번에 **1시간 가까이 잡아먹은 문제**입니다. 증상이 "Node 버전 불일치" 처럼 보이지만 아닙니다.

| 확인 항목 | 상태 |
|---|---|
| zip 다운로드 (`~/Library/Caches/electron/`) | ✅ 정상 — 112MB, `unzip -t` 무결성 통과 |
| `extract-zip` 압축 해제 (`electron/install.js`) | ❌ **에러 없이 실패.** 디렉터리만 만들고 240KB |
| `unzip` 수동 해제 | ✅ 272MB 정상 |

`npm install` 도 `node install.js` 도 **exit code 0** 을 반환하므로 성공한 줄 알게 됩니다.
실제 증상은 앱 실행 시점에 나타납니다:
```
dyld: Library not loaded: @rpath/Electron Framework.framework/Electron Framework
  Reason: tried: '.../Contents/Frameworks/Electron Framework.framework/...' (no such file)
```

**진단 한 줄** — 정상이면 약 270MB 입니다:
```bash
du -sh node_modules/electron/dist    # 240K 면 깨진 것
```

**복구 (재다운로드 불필요, 캐시 재사용)**:
```bash
cd /path/to/recording-pc-app
Z=$(find ~/Library/Caches/electron -name '*.zip' | head -1)
rm -rf node_modules/electron/dist && mkdir -p node_modules/electron/dist
unzip -q "$Z" -d node_modules/electron/dist
echo "38.0.0" > node_modules/electron/dist/version
printf 'Electron.app/Contents/MacOS/Electron' > node_modules/electron/path.txt   # 비어 있었음
```

> `npm install` 을 다시 돌리면 **재발할 수 있습니다.** 그때 위 블록만 실행하면 됩니다.

### Node 버전 / 네이티브 모듈 ABI

**Node 24.16.0 으로 문제 없습니다. 다운그레이드 불필요.**

| | 버전 | ABI |
|---|---|---|
| 로컬 Node | 24.16.0 | 137 |
| Electron 38.0.0 내장 Node | 22.18.0 | **139** |

ABI 가 다르지만 `better-sqlite3` 12.4.1 이 Electron 용 prebuild 를 올바로 물어서
**`electron-rebuild` 는 불필요**했습니다. 검증:
```bash
ELECTRON_RUN_AS_NODE=1 ./node_modules/electron/dist/Electron.app/Contents/MacOS/Electron \
  -e "require('better-sqlite3'); console.log('OK')"
```
만약 `NODE_MODULE_VERSION 137 vs 139` 에러가 나면 그때만:
```bash
npx electron-rebuild -f -w better-sqlite3
```

### 실행 스크립트 차이

| 명령 | 실제 실행 | 비고 |
|---|---|---|
| `npm run start` | `electron .` | 단순 실행 |
| `npm run dev` | `electronmon . --dev` | 파일 저장 시 자동 재시작 + **DevTools 별도 창** (`main.js:348`) |

**`npm run dev` 를 권장합니다** — 헬퍼와 주고받는 JSON 이벤트를 DevTools 에서 봐야 디버깅이 됩니다.

> ℹ️ nvm 사용 시 비대화형 셸에는 PATH 가 없어 `npm: command not found` 가 납니다.
> 스크립트에서 돌릴 때는 `export PATH="$HOME/.nvm/versions/node/v24.16.0/bin:$PATH"` 를 앞에 붙이세요.

### 남은 확인 (앱 경유 실제 녹음)

앱 기동과 헬퍼 IPC 는 확인했지만, **앱 UI 로 실제 녹음 버튼을 눌러 파일이 떨어지는 것까지는 아직 미검증**입니다.

1. 녹음 시작 → **TCC 프롬프트 재부여** (터미널에 준 권한은 Electron 에 상속되지 않음, 5절 참고)
   - 화면 기록 허용 후 **앱 재시작 필수**
2. 세그먼트 파일 생성 확인
3. 앱이 보내는 `max_ms` 가 정수 문자열인지 확인 (6-4 의 조용한 파싱 실패 주의)

### 선택

- `newDocs/mac_recorder-main/DerivedData` (164MB) 삭제
- 심볼릭 링크를 실제 소스로 교체 후 커밋 (사용자 판단)
- 6절의 차이점들을 `docs/electron_helper_interface.md` 에 반영

### 우선순위 주의

**이 작업은 Windows 업무의 보너스입니다.**
Windows 랩탑을 받으면 [02번 문서](02-Windows-빌드-가이드.md) 로 즉시 전환하세요.
macOS 검증의 가치는 "정상 동작 기준점 확보" 에 있지, 그 자체가 목표가 아닙니다.
