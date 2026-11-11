# AM-Tray 시스템 로그인 — 회사 확인 목록

> 작성: 2026-11-10 · **수정: 2026-11-12** (DLL 을 앱이 koffi 로 직접 부르게 바뀜 → A-1 질문 문장·A-3 창 찾기 보완) · 이전 `questions-am.md`(AM 담당용)·`request-backend.md`(백엔드용)를 합쳐 **아직 남은 것만** 다시 정리
> 근거: 손그림 2장(이 폴더 `1.…jpeg`, `2.…jpeg`), `window-message.md`(AM 명세 옮긴 것), `clean/`(Java 샘플)
> 쓰는 법: 회사에서 **답을 표의 "답" 칸에 적어 온다.** 모르면 비워 둔다.

---

## 0. 오늘(11-10) 해결된 것 — 다시 묻지 않는다

| 이전 질문 | 답 (근거: `window-message.md`) |
|---|---|
| `sid` 가 무엇인가 | **우리가 정하는 세션 이름.** 예) printChaser(운영) / printChaserDev(개발) |
| `systemID` 가 무엇인가 | myAccess 와 협의한 **ACL(시스템 권한명)**. 협의 전에는 AM-Tray 관리자 페이지 "시스템 인가 예외 설정"으로 테스트 가능 |
| 로그인 메시지 | `WM_COPYDATA`, wParam = 30001(운영)/31001(개발), lpData = **사용자 ID(사번) 의 SHA-256** |
| 로그아웃 메시지 | `WM_USER + 30001/31001`, wParam = 같은 값 |
| 에러코드 뜻·대응 | 표 받음 (203030 성공, 504011, 503031~503036, 509090/공백, 500001, 500003) |
| 안내 문구 | 503031~503036, 504011, 509090 문구 받음 (503036 포함) |
| ValidateToken 응답 | `status: 300`, `attr { Result: "Success", USERID }` |
| DLL 반환 방식 | **Bool 반환 = AM-Tray 와 통신 성공 여부**, 결과는 **`lpReturnCode`** 로 확인 |

## 0-1. 우리가 정한 것 (회사에 알릴 필요 없음, 기록용)

| # | 상황 | 결정 |
|---|---|---|
| A | 504011 (AM-Tray 미로그인) | **AM 로그인 창(ShowSSOLoginUI) 띄움** — 지금 구현과 같음 |
| B | 509090 / 공백 (AM-Tray 통신 실패·미설치) | **안내 팝업만** (설치 페이지 이동 안 함) |
| B-2 | 503031~503036 | **코드별 메시지 팝업** (명세 표 기준. Java 샘플의 "503034·503035 = 자체 로그인"보다 우선) |
| C | 로그인 중 다른 사번 메시지(hash 다름) — 특히 녹음 중 | 백엔드에 refreshToken 지원 여부 먼저 확인(아래 B-3) 후 결정 |
| D | AM-Tray 로그아웃 메시지 | **확인 팝업 [로그아웃] / [취소]**. 취소면 로그인 유지 |
| - | `sid` 값 (제안) | 운영 `timbloRecApp` / 개발 `timbloRecAppDev` (내부 이름 규칙) — 바꿔도 됨 |

---

## A. AM 담당자에게

### A-1. ★ cpp 용 DLL 자료 요청 (가장 중요 — 이게 틀리면 호출이 죽는다)
> 이렇게 물으면 된다 (그대로 읽어도 됨):
> "저희 앱은 **Electron(Node.js)** 입니다. C++ 로 개발하는 것은 아니고, Java 는 쓸 수 없어서 **Node.js 에서 본체 DLL(`AmInterface-RT-X64.dll`)의 C 함수를 직접 부르려고** 합니다.
> 그래서 C 함수의 **모양(인자·반환 형식)** 만 정확히 알면 됩니다.
> 명세에 '개발 언어에 따라 cpp, C#, Java dll 을 제공한다'고 되어 있는데, 지금 받은 건 **Java(JNI)용 샘플**뿐입니다.
> 명세에 '**Bool 반환은 통신 성공 여부, 결과는 `lpReturnCode` 로 확인**'이라고 되어 있어서, Java 의 `String GetSystemTokenIT(...)` 와 C 함수 모양이 다를 것 같습니다.
> **cpp 용 DLL 묶음(헤더 .h + 예제 .cpp)** 을 받을 수 있을까요? 반출이 어려우면 헤더의 함수 선언 부분만이라도 부탁드립니다.
> 혹시 Node.js 용 SDK 나 REST 방식이 따로 있으면 그것도 알려 주세요."

> 덧붙여: "혹시 받은 `AmInterface-RT-X64.dll` 이 cpp 용 본체라면, **헤더(.h)나 함수 선언만** 주셔도 됩니다."

**왜 cpp 용인가** (물어보면 이렇게 설명)
| 자료 | 우리 앱에서 쓰려면 | 판단 |
|---|---|---|
| Java 용 (지금 받은 것) | 앱에 Java(JVM)를 따로 넣어야 함 — 설치 파일 커지고 복잡 | ❌ |
| C# 용 | C# 중계 exe 를 새로 만들어야 하고 PC 에 .NET 필요 | △ cpp 를 못 받을 때 대안 |
| **cpp 용** | 앱(Electron/Node.js)이 **koffi 로 본체 DLL 을 바로 부름** — C++ 로 개발하는 게 아니고, 헤더는 **함수 모양(인자·반환)** 만 보려는 것 | ✅ |
- "C++ 로 개발하냐"고 물으면: **아니요, Electron(Node.js)입니다.** C 형식 DLL 은 Node.js 에서 바로 부를 수 있어서, 함수 선언(헤더)만 있으면 됩니다.
- 받은 DLL 중 `AmInterface-RT-X64.dll` 이 본체, `AmInterface-JNI-RT-X64.dll` 은 Java 가 본체를 부르는 다리로 보인다 → **새 DLL 이 아니라 본체의 함수 모양(헤더)만 있어도 될 가능성이 크다.**
- **헤더를 못 받아도 시험은 할 수 있다**: `node scripts\amtray-koffi-test.js token ...` 를 `--signature string` / `bool_out` 두 가지로 돌려 어느 쪽이 맞는지 본다(`update_20261112.md` 확인 표 3번). 다만 추측이라 헤더로 확정하는 게 안전하다.
- C# 용 DLL 은 Node.js 에서 바로 부를 수 없다(C# 중계 exe 가 따로 필요) → cpp(C) 용이 가장 좋다.

참고 — 지금 가진 자료: Java 선언(`xTokens.java`, `clean/AmInterface.java`)과 Java 샘플(`am-tray.java`)뿐. **C 선언·lpReturnCode 가 들어간 함수 모양은 받은 자료에 없다** → 묻는 게 당연함.

| 확인할 것 | 답 |
|---|---|
| 함수 선언 그대로 (예: `BOOL GetSystemTokenIT(char* ssoKey, char* sid, char* systemID, char* lpToken, char* lpReturnCode)` ?) | |
| **인가토큰은 어느 인자로 오나** (lpReturnCode 와 따로? 같이?) | |
| 버퍼 크기는 우리가 정하나 (토큰 최대 길이, 크기 인자 있나) | |
| 문자열 형식: `char*`(ANSI/CP949 / UTF-8) vs `wchar_t*` | |
| `ShowSSOLoginUI` / `SSOLogout` / `GetReturnMessage` 선언 (철자 `ShowSSOLoginUI` 맞나) | |
| 초기화·종료 함수(Init/Release)를 먼저 불러야 하나 | |
| 명세의 "**SetSystemToken** API" 는 GetSystemTokenIT 의 오타인가, 다른 함수인가 | |

### A-2. 에러코드 — 표 받은 뒤 남은 것
| 확인할 것 | 답 |
|---|---|
| (확인만) 503034·503035 를 Java 샘플은 "자체 로그인", 명세 표는 "메시지 팝업" — **명세 표 기준으로 팝업 처리할 예정**인데 맞나 | |
| 500001(DLL 로드 실패) / 500003(DLL API 통신 실패) 은 누가 주는 값인가 — DLL 을 못 불러오면 DLL 이 코드를 줄 수 없어 보임. JNI 다리(또는 cpp 래퍼)가 만드는 값인가, 우리가 직접 판단하라는 뜻인가 | |
| 500001 / 500003 안내 문구 (자체 로그인으로 넘기기 전 한 줄 안내할지) | |
| "공백" 은 lpReturnCode 가 빈 문자열이라는 뜻인가, Bool=false 일 때인가 | |
| 안내 문구를 `GetReturnMessage(code, locale)` 로 받아야 하나, 표 문구를 앱에 넣어도 되나 / 영어 문구 | |

### A-3. 윈도우 메시지
| 확인할 것 | 답 |
|---|---|
| **어느 창으로 보내나** (창 제목·클래스 지정? 등록 함수? `ShowSSOLoginUI` 를 부른 프로세스?) | |
| 창을 **클래스 이름**으로 찾는 방식인가 — Electron 창의 클래스 이름은 `Chrome_WidgetWin_1` 로 **고정이라 바꿀 수 없다**(다른 Electron 앱·크롬과 같음). 창 **제목**으로 찾거나 창 핸들(HWND)을 넘겨받는 방식이면 문제없음 | |
| SHA-256 결과 형식: 32바이트 바이너리 / 64자 hex(대문자? 소문자?) / 끝에 NULL 포함? | |
| 해시 대상: 사번 그대로인가 (앞뒤 0·대소문자·접두어 없이) | |
| 앱을 켰을 때 AM-Tray 가 **이미 로그인 상태**면 메시지가 오나, 우리가 먼저 GetSystemTokenIT 를 불러야 하나 | |
| 그림 1 ④ "시스템 확인": 우리 앱이 **등록**돼 있어야 메시지를 보내나, **실행 중**이면 보내나 | |
| 다른 사용자로 바꿔 로그인했을 때도 같은 로그인 메시지가 오나 (그림 1 ⑤ "사용자 변경 로그인 시") | |

### A-4. 기타
| 확인할 것 | 답 |
|---|---|
| `ssoKey` 실제 값 ("API 명세서에 표기한 값을 고정") — `Dev_CASSO` / `Prod_CASSO` 맞나 | |
| `ShowSSOLoginUI` 는 창만 띄우고 바로 돌아오나, 로그인 끝날 때까지 기다리나 | |
| DLL 배포: 설치 폴더에 3개 같이 두면 되나, VC++ 재배포 패키지 필요한가, DLL 버전 바뀌면 알려 주나 | |
| 테스트용 **시스템 인가 예외 설정** 신청 방법 (우리 systemID 로) | |

---

## B. 백엔드에게 (새 API 요청)

PC앱은 DLL 에서 **인가토큰(authzToken)** 만 받는다. 사용자가 누구인지는 서버가 SSO 에 검증해야 알 수 있다.
→ **"인가토큰 → 우리 토큰" API 를 새로 만들어 주셔야 한다.**

```
PC앱 ──① POST {새 API} { authzToken } ──▶ 백엔드
                                        ② POST https://samlam(dev).skhynix.com/tray/api/ValidateToken
                                           { systemID, authzToken } → status 300, attr.Result == "Success", attr.USERID
                                        ③ USERID(사번)로 사용자 확인 → accessToken / refreshToken 발급
PC앱 ◀──④ { httpCode, message, data: { empno, tokens: { accessToken, refreshToken } } }
```

### B-1. 요청하는 API (제안 — 경로·이름은 편하신 대로, 확정되면 요청·응답 예시를 그대로 주세요)
| 항목 | 제안 |
|---|---|
| 경로 | `POST /api/auth/sso/amtray` (사번 로그인 `/api/auth/sso/hmp` 와 같은 서버) |
| 요청 | `{ "authzToken": "<인가토큰>" }` — **앱은 사번을 보내지 않는다** |
| 성공 | HMP 로그인과 같은 봉투 `{ httpCode: 200, message, data: { empno, tokens: { accessToken, refreshToken } } }` |
| 약관 미동의 | 404 / 422 (HMP 와 같게) |
| 토큰 검증 실패 | 401 + message |
| 시스템 ID 오류 / SSO 통신 실패 | 500 계열 + message |

### B-2. SSO 검증 API (AM 명세)
| 항목 | 값 |
|---|---|
| URL | 개발 `https://samlamdev.skhynix.com/tray/api/ValidateToken` / 운영 `https://samlam.skhynix.com/tray/api/ValidateToken` |
| 요청 | POST JSON `{ "systemID": "...", "authzToken": "..." }` |
| 응답 | `{ "status": 300, "attr": { "Result": "Success", "USERID": "..." } }` |
| 샘플 | `clean/ServerValidateSample.java`, `clean/SslRestTemplate.java` — ⚠️ SSL 검증을 끈 채 호출함. 운영은 사내 CA truststore 권장 |

### B-3. 확인할 것
| 확인할 것 | 답 |
|---|---|
| **refreshToken 도 발급되나** (녹음 중 끊기지 않게 silent refresh 필요 — 결정 C 와 연결) | |
| 새 API 경로·요청·응답 예시, 일정 | |
| `USERID` 는 사번인가 AD 계정인가 (AD 면 사번 조회 필요) | |
| 실패 시 `Result` 값 종류 (이전 샘플: SYSTEMID_INVALID / TOKEN_INVALID) | |
| 백엔드 서버 → samlam(dev/운영) 방화벽 | |
| **ValidateToken 성공일 때만** 토큰 발급 (앱이 보낸 값을 믿지 않음) | |

---

## C. myAccess / 담당 부서
| 확인할 것 | 답 |
|---|---|
| 우리 앱 `systemID`(ACL 시스템 권한명) 협의·발급 — 개발/운영 값 | |
| 앱과 백엔드가 **같은 systemID** 를 쓴다 (앱: DLL 호출, 백엔드: 검증) | |

---

## D. 회사 PC 에서 직접 확인 (DLL 받은 뒤)
`analysis.md` 6장 그대로. 결과만 적어 온다.
| 확인 | 결과 |
|---|---|
| `node scripts\amtray-exports.js C:\DLL폴더` 결론 (A/B/C/D) + 함수 4개 있음/없음 | |
| `node scripts\amtray-koffi-test.js token ...` 결과 한 줄 (아무 출력 없이 끝나면 A-1 선언이 다르다는 뜻 → `--signature bool_out` 로도 한 번) | |
