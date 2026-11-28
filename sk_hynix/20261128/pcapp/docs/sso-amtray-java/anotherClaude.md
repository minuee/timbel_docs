# Electron 앱 SSO 연동 (WM_COPYDATA) – 검토 정리

## 1. 상황
- 우리 앱 개발 언어: Electron (Node.js). C++로 개발하는 게 아님.
- 목표: Windows 메시지(WM_COPYDATA)로 고객사 SSO 에이전트와 통신해서 SSO 로그인 처리.
- 고객사에서 받은 안내서: Java용. 고객사 반출 금지라 외부 공유 불가.
- 오해가 생긴 이유: Java 안내서를 Electron에서 그대로 쓸 수 없어서 C++ 네이티브 모듈 얘기가 나왔고, 그래서 "C++로 개발하냐"는 질문을 받음.

## 2. 핵심 결론
- 필요한 건 언어가 아니라 통신 규칙. Java든 C++든 결국 같은 Win32 API(FindWindow, SendMessage, WM_COPYDATA)를 부르는 것이라, Java 안내서만 있어도 판단 가능.
- C++ 코드를 직접 짜지 않고 Electron에서 구현할 수 있을 가능성이 높음.
- C++ 안내서가 있으면 구조체 정의가 Win32 그대로라 옮기기 더 쉬움(필수 아님).
- 별도 Java 프로세스를 띄우는 방식은 맞지 않음. 메시지를 Electron 창(HWND)으로 받아야 하므로 중간에 한 번 더 전달해야 해서 오히려 복잡해짐.

## 3. 예상 통신 흐름 (안내서로 확인 필요)
"우리가 에이전트를 찾아야 한다"는 고객사 설명 기준:
1. 우리 앱 → 에이전트
   - FindWindowW(클래스명, 창제목)으로 SSO 에이전트 창 핸들 찾기
   - SendMessageW(에이전트HWND, WM_COPYDATA, 우리HWND, ©DATASTRUCT)로 요청
2. 에이전트 → 우리 앱
   - 에이전트가 wParam으로 받은 우리 HWND에 WM_COPYDATA로 결과(토큰/사용자 정보) 전송
   - 우리 앱이 이 메시지를 받아서 데이터 해석

## 4. Electron 구현 방식 (C++ 빌드 없이)
- 우리 창 핸들: win.getNativeWindowHandle() (Buffer로 HWND 반환)
- 에이전트 창 찾기 / 요청 보내기: koffi(FFI)로 user32.dll의 FindWindowW, SendMessageW 호출
- 응답 받기: win.hookWindowMessage(0x004A, (wParam, lParam) => {...}) (0x004A = WM_COPYDATA)
- 응답 데이터 읽기: lParam은 COPYDATASTRUCT 포인터 → koffi로 dwData, cbData, lpData 읽기

COPYDATASTRUCT 구조:
typedef struct {
  ULONG_PTR dwData; // 메시지 종류 식별값
  DWORD cbData; // 데이터 길이(byte)
  PVOID lpData; // 데이터 포인터
} COPYDATASTRUCT;

참고:
- Electron 창 클래스명은 Chrome_WidgetWin_1로 고정. 에이전트가 우리 창을 클래스명으로 찾는 구조면 문제가 될 수 있음(제목으로 찾거나 HWND를 전달받는 구조면 괜찮음).
- koffi는 미리 빌드된 바이너리를 제공해서 보통 node-gyp / Visual Studio Build Tools 불필요.
- hookWindowMessage, getNativeWindowHandle은 메인 프로세스의 BrowserWindow에서 사용.

## 5. 안내서에서 확인할 항목
(반출 불가이므로 고객사 정책이 허용하는 범위에서 확인. 민감하면 형식만 적어도 됨)
1. 에이전트 창 찾기: FindWindow에 넣는 클래스명 / 창 제목
2. 요청 보내기: dwData 값, 보내는 데이터 내용과 형식, wParam에 무엇을 넣는지
3. 응답 받기: 응답이 우리 HWND로 오는지, 응답 dwData 값
4. 데이터 형식: 문자열 인코딩(UTF-8 / UTF-16 / EUC-KR), 구분자나 JSON 여부, 끝에 NULL 포함 여부
5. 순서와 타이밍: 요청 → 응답 흐름, 타임아웃, 실패 시 처리
6. 기타: 32/64비트 조건, 관리자 권한(UIPI) 필요 여부

## 6. 고객사 답변 초안
개발 언어는 앞서 말씀드린 대로 Electron(Node.js)입니다.
다만 전에 공유해주신 파일이 Java용 안내서라서 Electron에서는 바로 쓸 수 없습니다. 그래서 그 부분만 C++ 네이티브 모듈로 연동하려고 했던 것입니다.
혹시 Node.js(JavaScript)용 SDK나 C/C++용 라이브러리(DLL 등) 문서, 또는 REST API 문서가 있다면 공유 부탁드립니다. 받아보면 방식을 확실히 정할 수 있을 것 같습니다.

## 7. 다음 단계
- 5번 항목 확인 → Electron 메인 프로세스용 예제 코드(koffi + hookWindowMessage) 작성
- 데이터 인코딩과 dwData 값 확인 → 실제 SSO 에이전트로 테스트