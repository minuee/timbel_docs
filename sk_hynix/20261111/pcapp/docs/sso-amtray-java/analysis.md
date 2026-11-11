# AM-Tray 시스템 로그인 — 분석 및 구현 현황

> 작성: 2026-11-09 · 갱신: 2026-11-10 (손그림 2장 + `window-message.md` 반영) · **2026-11-11: DLL 호출을 AmHelper.exe → koffi 로 바꿈 (ver.16)**
> 근거: 담당자가 준 DLL 3개(반출 불가)·Java 샘플을 손으로 옮긴 자료(원본: 이 폴더, 정리본: `clean/`), AM 명세 옮긴 것 `window-message.md`
> 흐름도: `1.AM-Tray-인증프로세스.drawio`, `2.AM-Tray-DLL호출흐름도.drawio` (원본 사진: 같은 이름 `.jpeg`)
> 회사 확인 목록: **`company-check.md`** (이전 questions-am.md / request-backend.md 를 합침)

## 1. 한 줄 요약
AM-Tray 로그인은 **두 단계**다. PC앱이 DLL에서 **인가토큰**을 받고, 그 토큰을 **우리 백엔드가 SSO 서버에서 검증**해 사번을 얻은 뒤 우리 토큰을 발급한다.
→ **앱만으로는 끝나지 않는다. 백엔드 API 가 새로 필요하다.**

## 2. 전체 흐름 (11-10 기준)

### 2-1. 시작점 — AM-Tray 메시지 (그림 1 ⑤~⑦, 그림 2 왼쪽)
AM-Tray 는 **로그인할 때 / 다른 사용자로 바꿔 로그인할 때** 연계 시스템에 메시지를 보낸다(등록되지 않은 시스템이면 안 보냄 — 그림 1 ④).
```
WM_COPYDATA  wParam = 30001(운영) / 31001(개발)   lpData = SHA-256(사번)   ← 로그인
WM_USER + 30001/31001   wParam = 같은 값                                ← 로그아웃

메시지 수신 ─┬ 앱 미로그인 ─────────────────────────▶ 인가토큰 요청 (2-2)
             └ 앱 로그인 중 ─ hash 비교 ─┬ 같음 ─▶ 아무것도 안 함 (로그인 유지)
                                          └ 다름 ─▶ 앱 로그아웃 → 인가토큰 요청 (2-2)
로그아웃 메시지 ─▶ 확인 팝업 [로그아웃] / [취소] (취소면 유지)          ← 결정 D
```

### 2-2. 인가토큰 요청 → 결과별 처리 (그림 2 가운데)
```
[PC앱]                                    [우리 백엔드]                       [SSO 서버 samlam]
GetSystemTokenIT(ssoKey, sid, systemID)   ※ C 선언은 확인 중 — Bool 반환 + lpReturnCode (company-check A-1)
   ├ 203030 성공(인가토큰) ─────────────▶ POST /tray/api/ValidateToken ──▶ 검증
   │                                        {systemID, authzToken}          ◀── status 300, attr{Result:"Success", USERID}
   │                                      USERID(사번)로 우리 토큰 발급
   │  ◀──────── accessToken / refreshToken ┘   (검증 실패 → SSO 응답값 표시 → 자체 로그인)
   │  약관 확인 → 권한 확인 → 마이크 테스트 화면 (기존 로그인과 같음)
   │
   ├ 504011 미로그인          → ShowSSOLoginUI(sid) → 로그인 메시지 오면 2-1 부터     ← 결정 A
   ├ 503031~503036            → 코드별 메시지 팝업 → 종료                              ← 명세 표 (샘플보다 우선)
   ├ 509090 / 공백            → 안내 팝업만 → 종료                                    ← 결정 B
   └ 500001 / 500003          → 자체 로그인(사번 · MyAccess)
```

### 2-3. 에러코드 · 안내 문구 (`window-message.md`)
| 코드 | 뜻 | 앱 처리 | 문구 |
|---|---|---|---|
| 203030 | 인가토큰 발급 성공 | 백엔드로 보냄 | — |
| 504011 | AM-Tray 미로그인 | AM 로그인 창 | 통합인증이 필요합니다(미 로그인 상태) |
| 503031 | 접근 불가(신뢰 점수 미달) | 팝업 | 접속환경 Risk평가 결과 허가된 접근 범위를 초과하여 접속이 차단되었습니다. |
| 503032 | 접근 불가(권한 없음) | 팝업 | 시스템 접근 권한이 없습니다. |
| 503033 | 접근 불가(장기 미사용 권한 회수) | 팝업 | 시스템 장기 미사용으로 인하여 권한이 회수되었습니다. |
| 503034 | 토큰 만료 | 팝업 | 사용자 인증 정보가 만료되어 AM-Tray로그아웃 후 재로그인이 필요합니다. |
| 503035 | 토큰 발급 API 통신 실패 | 팝업 | 인가토큰 발급에 실패하였습니다. |
| 503036 | 인증토큰 ID 검증 실패 | 팝업 | 인증토큰 ID검증에 실패하였습니다. |
| 509090 / 공백 | AM-Tray 통신 실패 | 안내 팝업 | AM-Tray가 설치되지 않았습니다. |
| 500001 | DLL 로드 실패 | 자체 로그인 | (없음 — 확인 중) |
| 500003 | DLL API 통신 실패 | 자체 로그인 | (없음 — 확인 중) |

### 2-4. 우리 결정 (11-10)
| # | 상황 | 결정 |
|---|---|---|
| A | 504011 | AM 로그인 창(ShowSSOLoginUI) |
| B | 509090 / 공백 | 안내 팝업만 (설치 페이지 이동 안 함) |
| B-2 | 503031~503036 | 코드별 메시지 팝업 |
| C | 로그인 중 hash 다름(특히 녹음 중) | 백엔드 refreshToken 확인 후 결정 |
| D | 로그아웃 메시지 | [로그아웃]/[취소] 팝업, 취소면 유지 |
| - | `sid` | 우리가 정함 — 제안 `timbloRecApp`(운영) / `timbloRecAppDev`(개발) |

## 3. DLL 3개

| DLL | 역할 | 우리 앱 |
|---|---|---|
| `AmInterface-RT-X64.dll` | AM 기능 본체 | **앱이 koffi 로 직접 부른다** (별도 작업 프로세스) |
| `Rathon-CS-Crypt-X64.dll` | 암호화 (본체가 내부에서 씀) | 같은 폴더에 두기만 |
| `AmInterface-JNI-RT-X64.dll` | Java 다리 | **안 쓴다** (Java 가 아니므로) |

자료에 `char *`, `Bool` 같은 C 형식이 섞여 있음 → 매뉴얼에 C 선언도 있었던 것으로 보인다 → 본체 DLL 을 C 로 바로 부를 수 있을 가능성이 높다.

## 4. 구현 방식 (이번에 만든 것)

```
login.js ─[시스템 로그인]─▶ handleAuth.js auth:system-login
                              └ amTrayService.js ─utilityProcess─▶ amTrayWorker.js ─koffi(amTrayDll.js)─▶ AmInterface-RT-X64.dll
                                 (AMTRAY_ENGINE="helper" 이면 예전처럼 ─execFile─▶ AmHelper.exe)
                              └ authService.loginWithAmToken ─▶ 우리 백엔드(AMTRAY_LOGIN_PATH)
                              └ 메인 창 hookWindowMessage(WM_COPYDATA, WM_USER+env) ◀─ AM-Tray
```

| 파일 | 내용 |
|---|---|
| `src/main/services/amTrayDll.js` | **DLL 직접 호출(koffi).** `token` / `show-ui` / `logout` / `message`. 함수 모양 "★ 가정" 블록이 여기 |
| `src/main/services/amTrayWorker.js` | 위 파일을 별도 프로세스(Electron utilityProcess)에서 돌림 → DLL 이 죽어도 앱은 안 죽음 |
| `src/main/vendor/koffi/` | koffi 3.3.4 (MIT). npm 설치 없이 묶어 둔 것 — Windows x64 용 `koffi.node` 포함 |
| `scripts/amtray-koffi-test.js` | 앱 없이 DLL 만 시험 (6-2) |
| `src/helpers/windows/amtray/AmHelper.cpp` | (비교용으로 남김) 예전 DLL 호출 중계 exe. `token` / `show-ui` / `logout` / `message`. 결과는 JSON 한 줄. DLL 이 죽어도 앱은 안 죽음 |
| `src/helpers/windows/amtray/bin/AmHelper.exe` | Mac 에서 mingw 로 빌드한 결과물 (회사 빌드 불필요) |
| `src/helpers/windows/amtray/test/` | 테스트용 가짜 DLL (`FAKE_AM` 환경변수로 결과 바꿈) — 배포 금지 |
| `scripts/amtray-exports.js` | **DLL 확인 — 결론만 짧게**(A/B/C/D + 함수 4개 있음/없음). dumpbin 대신, Node 만 있으면 됨, DLL 을 실행하지 않음 |
| `src/main/services/amTrayService.js` | 작업 프로세스(또는 AmHelper) 호출·결과 해석·흉내(MOCK) |
| `src/main/services/authService.js` | `loginWithAmToken` — 백엔드 호출 (요청/응답은 가정) |
| `src/main/ipc/handleAuth.js` | 시스템 로그인 흐름, 윈도우 메시지 받기, 대기 시간 |
| `src/main/services/authConfig.js` | `AMTRAY_*` 설정 (값은 `src/config/app.config.json` 에 넣는다) |
| `src/renderer/scripts/login.js`, `src/locales/*.json` | 안내 문구 |

**안전장치**: `AMTRAY_SYSTEM_ID` 가 비어 있으면(지금 기본) [시스템 로그인] 은 예전처럼 "준비 중" 만 나온다. 이번 반영으로 기존 로그인이 바뀌지 않는다.

### ★ 가정 (확인되면 고칠 곳)
| 가정 | 고칠 곳 |
|---|---|
| DLL 함수 모양: `string`(문자열 반환, Java 선언 모양) 또는 `bool_out`(Bool 반환 + lpToken·lpReturnCode, 명세 문구 기준 추측) | `amTrayDll.js` "★ 가정" 블록. 설정 `AMTRAY_DLL_SIGNATURE`. wchar_t* 면 `AMTRAY_DLL_WIDE=true` |
| DLL 이 주는 한글 문구는 CP949 | `amTrayDll.js` `bytesToString` (시험 스크립트 `--utf8`) |
| 함수 이름 대소문자/오타 차이 | 후보를 차례로 찾음 (`amTrayDll.js` `FN_NAMES`) |
| AM-Tray 가 **앱 메인 창**으로 메시지를 보냄 | `handleAuth.js` `ensureAmWindowHook` |
| 백엔드 API: `POST {AMTRAY_LOGIN_PATH}` body `{ authzToken }`, 응답은 HMP 로그인과 같은 봉투 | `authService.js` `loginWithAmToken` "★ 요청/응답" |
| `sid` = 시스템 ID 와 같은 값 | 설정 `AMTRAY_SID` |

## 5. ver.14 구현과 다른 점 (코드 수정 대상 — ver.15)

| # | 다른 점 | ver.14 | 고칠 곳 |
|---|---|---|---|
| 1 | **DLL 선언**: Bool 반환 + lpReturnCode 일 가능성 | `const char*` 반환 가정 | ✅ ver.16: `amTrayDll.js` 에서 두 방식 선택 가능(`AMTRAY_DLL_SIGNATURE`). A-1 답 받으면 확정 |
| 2 | 성공 판단: 203030 | 길이 6 초과 = 토큰 | ✅ ver.16: `bool_out` 방식은 203030 일 때만 토큰. `string` 방식은 그대로 |
| 3 | **메시지는 아무 때나 옴** → 미로그인=토큰 요청, 로그인 중=hash 비교 | 버튼 누르고 기다리는 중일 때만 처리, hash 비교 없음 | `handleAuth.js` `ensureAmWindowHook` / `onAmLoginMessage` (훅도 앱 시작 시 걸어야 함) |
| 4 | 503034·503035 → 팝업 | 자체 로그인 안내 | `amTrayService` `CODES_UNAVAILABLE` |
| 5 | 공백 코드 → 509090 과 같게 | 처리 없음 ("error") | ✅ ver.16: `CODES_UNAVAILABLE` 에 `''` 추가 (Bool=false 도 공백으로) |
| 6 | 500001 → 자체 로그인 | "그 밖의 오류" | 같은 곳 |
| 7 | 안내 문구: 표 문구 사용 | `GetReturnMessage` 호출 | `locales/*.json` (A-2 답에 따라) |
| 8 | 로그아웃 메시지 → 확인 팝업 | 로그만 | `handleAuth.js` `WM_USER + env` |
| 9 | `sid` 기본값 | 시스템 ID 와 같은 값 | `authConfig.js` `AMTRAY_SID` |
| 10 | ValidateToken 응답 `Result: "Success"` | 백엔드 요청서에 RESULTID/SUCCESS 로 적었음 | 백엔드 몫 — `company-check.md` B 에 반영함 |

남은 확인은 모두 **`company-check.md`** 에 있다 (AM 담당 A-1~A-4, 백엔드 B, myAccess C, 회사 PC 확인 D).

## 6. 확인 방법 (회사)

### 6-1. DLL 확인 — 가장 먼저
```
node scripts\amtray-exports.js C:\DLL3개있는폴더
```
결론만 짧게 나온다. **결론 글자(A/B/C/D)와 함수 4개의 "있음/없음"(B 면 "가정과 같음/다름")만 적어 온다.**
| 결론 | 뜻 | 다음 |
|---|---|---|
| A | C 함수로 바로 부를 수 있음 | 6-2 AmHelper 실행 |
| B | C++ 함수. 형식이 이름에서 풀려 "가정과 같음/다름" 표시 | 다르면 그 한 줄만 적어 온다 |
| C | 이름이 다름 | 함수가 12개 이하면 이름이 바로 나옴, 많으면 `--all` |
| D | DLL 못 찾음 / 64비트 아님 | 폴더·파일 확인 |

### 6-2. DLL 직접 시험 — koffi (ver.16, 앱 없이)
프로젝트 폴더에서 (DLL 3개 폴더 경로를 넣는다. `src\helpers\windows\amtray\bin\` 에 복사해 두면 앱도 그대로 찾는다)
```
node scripts\amtray-koffi-test.js version --dll-dir C:\DLL폴더
node scripts\amtray-koffi-test.js token   --dll-dir C:\DLL폴더 --sso-key Dev_CASSO --sid timbloRecAppDev --system-id <시스템ID>
node scripts\amtray-koffi-test.js message --dll-dir C:\DLL폴더 --code 504011 --locale ko
```
| 결과 | 뜻 |
|---|---|
| `"ok":true,"result":"504011"` 등 | **DLL 호출 성공** (가정한 형식이 맞음) |
| `"ok":true,...,"kind":"인가토큰"` | 토큰 받음 (AM-Tray 로그인 상태). 토큰은 앞 6글자만 보인다 |
| `"error":"koffi_load_failed"` | `src\main\vendor\koffi\build\koffi\win32_x64\koffi.node` 빠짐 (따로 복사 파일) |
| `"error":"dll_load_failed"` | 같이 필요한 DLL 없음(Rathon DLL·VC 런타임) 또는 32/64비트 불일치 — `message` 내용을 적어 온다 |
| `"error":"fn_not_found"` | 함수 이름 다름 → 6-1 결과를 적어 온다 |
| **아무 출력 없이 끝남** | DLL 안에서 죽음 = **함수 모양 가정이 틀림** → `--signature bool_out` 로 다시, 그래도면 `--wide` 도 붙여 본다 |
| 결과가 깨진 글자 | `--wide` 또는 `--utf8` |

진짜 DLL 없이 먼저 해 보려면: `--dll-dir src\helpers\windows\amtray\test\fake-dll` (`set FAKE_AM=notlogin` / `unavailable` / `error` / `crash`)

### 6-3. (비교용) AmHelper.exe — koffi 결과가 이상할 때만
```
cd src\helpers\windows\amtray\bin
AmHelper.exe token --sso-key Dev_CASSO --sid <sid> --system-id <시스템ID>
```
앱에서 이 방식으로 돌리려면 `app.config.json` 에 `"AMTRAY_ENGINE": "helper",` 한 줄.

### 6-4. 앱 화면 흐름 (Mac·Windows 모두, DLL 없이)
`src/config/app.config.json` 에 `"AMTRAY_MOCK": "notlogin",` 한 줄 추가 → `npm start` → [시스템 로그인] (확인 후 그 줄을 지운다)
→ "AM 로그인 창에서 로그인해 주세요" → 3초 뒤 → 토큰 → (백엔드 API 없음) "시스템 로그인 서버가 준비 중입니다"
`token` / `uifail` / `unavailable` / `error` 도 같은 식.

### 6-5. 앱 로그에서 볼 이름
로그 파일: `%APPDATA%\timbloRecApp\logs\combined-날짜.log`

| 로그 이름 | 뜻 |
|---|---|
| `amtray_window_hook_installed` | AM-Tray 메시지 받을 준비 완료 (`env: 31001`) |
| `amtray_token_received` | 토큰 받음 (길이만, 값은 안 남김) |
| `amtray_token_code` | 에러코드 받음 (`code: 504011` 등) |
| `amtray_token_helper_error` | AmHelper·DLL 문제 (`dll_load_failed` / `dll_crashed` / `function_not_found` …) |
| `amtray_show_ui` | AM 로그인 창 띄우기 결과 |
| `amtray_login_message` | **AM-Tray 로그인 메시지 받음** |
| `amtray_copydata_ignored` | 메시지는 왔는데 wParam 이 31001 이 아님 (실제 값이 찍힘) |
| `amtray_login_message_ignored` | 기다리는 중이 아닐 때 메시지가 옴 |
| `amtray_logout_message` | 로그아웃 메시지 받음 (지금은 기록만) |
| `amtray_login_wait_timeout` | 5분 동안 메시지 없음 → AM-Tray 가 다른 창으로 보내는 듯 (Q4) |

## 7. 다음 단계
1. 회사: `company-check.md` 칸 채우기 — 특히 **A-1 cpp 용 헤더/예제**, 6-1 결론(A/B/C/D), 6-2 결과
2. 백엔드: `company-check.md` B 전달 (새 API + refreshToken)
3. 코드(ver.15): 5장 표 1~9. DLL 선언(1)은 A-1 답이 오면 확정
