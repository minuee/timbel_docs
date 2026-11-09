# AM-Tray 시스템 로그인 — 분석 및 구현 현황

> 작성: 2026-11-09 · 근거: 담당자가 준 DLL 3개(반출 불가)와 Java 샘플을 손으로 옮긴 자료(원본: 이 폴더, 정리본: `clean/`)
> 관련: 질문서 `questions-am.md`(AM 담당자용), 요청서 `request-backend.md`(백엔드용)

## 1. 한 줄 요약
AM-Tray 로그인은 **두 단계**다. PC앱이 DLL에서 **인가토큰**을 받고, 그 토큰을 **우리 백엔드가 SSO 서버에서 검증**해 사번을 얻은 뒤 우리 토큰을 발급한다.
→ **앱만으로는 끝나지 않는다. 백엔드 API 가 새로 필요하다.**

## 2. 전체 흐름

```
[PC앱]                                    [우리 백엔드]                       [SSO 서버 samlam]
① GetSystemTokenIT(ssoKey, sid, systemID)
   ├ 6자리 초과 = 인가토큰 ─────────────▶ ② POST /tray/api/ValidateToken ──▶ 검증
   │                                        {systemID, authzToken}          ◀── RESULTID=SUCCESS, USERID
   │                                      ③ USERID(사번)로 우리 토큰 발급
   │  ◀──────── accessToken / refreshToken ┘
   │  ④ 약관 확인 → 권한 확인 → 마이크 테스트 화면 (기존 로그인과 같음)
   │
   ├ "504011" 미로그인 → ShowSSOLoginUI(sid)
   │     true  → AM 로그인 창 → 사용자가 로그인 → AM-Tray 가 앱 창에 WM_COPYDATA → ① 다시
   │     false → SSO 웹서버 이상 → 사번 / MyAccess 로그인 안내
   ├ "509090" "503035" "503034" "500003" → AM-Tray 처리 불가 → 사번 / MyAccess 로그인 안내
   └ 그 밖의 6자리 → GetReturnMessage(code, "ko"/"en") 문구 표시
```

## 3. DLL 3개

| DLL | 역할 | 우리 앱 |
|---|---|---|
| `AmInterface-RT-X64.dll` | AM 기능 본체 | **AmHelper.exe 가 직접 부른다** |
| `Rathon-CS-Crypt-X64.dll` | 암호화 (본체가 내부에서 씀) | 같은 폴더에 두기만 |
| `AmInterface-JNI-RT-X64.dll` | Java 다리 | **안 쓴다** (Java 가 아니므로) |

자료에 `char *`, `Bool` 같은 C 형식이 섞여 있음 → 매뉴얼에 C 선언도 있었던 것으로 보인다 → 본체 DLL 을 C 로 바로 부를 수 있을 가능성이 높다.

## 4. 구현 방식 (이번에 만든 것)

```
login.js ─[시스템 로그인]─▶ handleAuth.js auth:system-login
                              └ amTrayService.js ─execFile─▶ AmHelper.exe ─LoadLibrary─▶ AmInterface-RT-X64.dll
                              └ authService.loginWithAmToken ─▶ 우리 백엔드(AMTRAY_LOGIN_PATH)
                              └ 메인 창 hookWindowMessage(WM_COPYDATA, WM_USER+env) ◀─ AM-Tray
```

| 파일 | 내용 |
|---|---|
| `src/helpers/windows/amtray/AmHelper.cpp` | DLL 호출 중계 exe. `token` / `show-ui` / `logout` / `message`. 결과는 JSON 한 줄. DLL 이 죽어도 앱은 안 죽음 |
| `src/helpers/windows/amtray/bin/AmHelper.exe` | Mac 에서 mingw 로 빌드한 결과물 (회사 빌드 불필요) |
| `src/helpers/windows/amtray/test/` | 테스트용 가짜 DLL (`FAKE_AM` 환경변수로 결과 바꿈) — 배포 금지 |
| `scripts/amtray-exports.js` | **DLL 확인 — 결론만 짧게**(A/B/C/D + 함수 4개 있음/없음). dumpbin 대신, Node 만 있으면 됨, DLL 을 실행하지 않음 |
| `src/main/services/amTrayService.js` | AmHelper 실행·결과 해석·흉내(MOCK) |
| `src/main/services/authService.js` | `loginWithAmToken` — 백엔드 호출 (요청/응답은 가정) |
| `src/main/ipc/handleAuth.js` | 시스템 로그인 흐름, 윈도우 메시지 받기, 대기 시간 |
| `src/main/services/authConfig.js` | `AMTRAY_*` 설정 (값은 `src/config/app.config.json` 에 넣는다) |
| `src/renderer/scripts/login.js`, `src/locales/*.json` | 안내 문구 |

**안전장치**: `AMTRAY_SYSTEM_ID` 가 비어 있으면(지금 기본) [시스템 로그인] 은 예전처럼 "준비 중" 만 나온다. 이번 반영으로 기존 로그인이 바뀌지 않는다.

### ★ 가정 (확인되면 고칠 곳)
| 가정 | 고칠 곳 |
|---|---|
| DLL 함수: `const char* GetSystemTokenIT(const char*, const char*, const char*)` 등 (`clean/AmInterface.java` 하단) | `AmHelper.cpp` "★ 가정" 블록. wchar_t* 면 설정 `AMTRAY_DLL_WIDE=true` 만 |
| DLL 이 주는 한글 문구는 CP949 | `AmHelper.exe ... --utf8-result` (UTF-8 이면) |
| 함수 이름 대소문자/오타 차이 | 후보를 차례로 찾음. 그래도 다르면 `--fn 이름` |
| AM-Tray 가 **앱 메인 창**으로 메시지를 보냄 | `handleAuth.js` `ensureAmWindowHook` |
| 백엔드 API: `POST {AMTRAY_LOGIN_PATH}` body `{ authzToken }`, 응답은 HMP 로그인과 같은 봉투 | `authService.js` `loginWithAmToken` "★ 요청/응답" |
| `sid` = 시스템 ID 와 같은 값 | 설정 `AMTRAY_SID` |

## 5. 미정·확인 필요

| # | 무엇 | 누구에게 | 문서 |
|---|---|---|---|
| 1 | DLL 함수의 C 형식(문자열 종류, 반환 방식) | AM 담당 / `amtray-exports.js` 결론 | `questions-am.md` Q1 |
| 2 | `systemID` 발급, `sid` 의 정체 | AM 담당 | Q2, Q3 |
| 3 | 윈도우 메시지를 받을 창을 AM-Tray 가 어떻게 찾는지 | AM 담당 | Q4 |
| 4 | 에러코드 표, `GetReturnMessage` 반환형 | AM 담당 | Q5, Q6 |
| 5 | 백엔드 "인가토큰 → 우리 토큰" API | 백엔드 | `request-backend.md` |
| 6 | ValidateToken 응답의 실제 모양(키 대소문자, status 300) | AM 담당 → 백엔드 | Q7 |
| 7 | AM-Tray 로그아웃 알림이 오면 앱도 로그아웃? (녹음 중이면?) | **우리 결정** | — 지금은 로그만 |
| 8 | 앱 시작 시 자동으로 시도? 버튼 눌렀을 때만? | **우리 결정** | — 지금은 버튼만 |

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

### 6-2. AmHelper 단독 (DLL 3개를 `src\helpers\windows\amtray\bin\` 에 복사한 뒤)
```
cd src\helpers\windows\amtray\bin
AmHelper.exe version
AmHelper.exe token --sso-key Dev_CASSO --sid <sid> --system-id <시스템ID>
AmHelper.exe message --code 504011 --locale ko
```
| 결과 | 뜻 |
|---|---|
| `"ok":true,"result":"504011"` 등 | **DLL 호출 성공** (가정한 형식이 맞음) |
| `"ok":true,"result":"긴 문자열"` | 토큰 받음 (AM-Tray 로그인 상태) |
| `"error":"dll_load_failed","winError":126` | 같이 필요한 DLL 없음 (Rathon DLL·VC 런타임) |
| `"error":"dll_load_failed","winError":193` | 32/64비트 불일치 |
| `"error":"function_not_found"` | 함수 이름 다름 → 6-1 결과로 `--fn` |
| `"error":"dll_crashed"` | **C 형식 가정이 틀림** → `--wide` 로 다시, 그래도면 형식 확인 필요 |
| 결과가 깨진 글자 | wchar_t* 일 수 있음 → `--wide` |

### 6-3. 가짜 DLL 로 AmHelper 만 먼저 확인 (진짜 DLL 없이)
```
AmHelper.exe token --dll-dir ..\test\fake-dll --sso-key Dev_CASSO --sid 1 --system-id 1
set FAKE_AM=notlogin   (또는 unavailable / error / crash)
```

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
1. 회사: 6-1 결론(A/B/C/D) + 6-2 결과 + `questions-am.md` 답 받기
2. 백엔드: `request-backend.md` 전달
3. 답이 오면: `AmHelper.cpp` ★ 가정 블록 / `loginWithAmToken` ★ 요청/응답 맞추기 → `AMTRAY_SYSTEM_ID`·`AMTRAY_LOGIN_PATH` 설정 → 실제 로그인 확인
