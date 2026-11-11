# AM-Tray 연동 자료 — 정리본

> 원본(손으로 옮겨 적은 것)은 상위 폴더 그대로 둔다. 이 폴더는 **오타를 고치고 역할별로 다시 나눈** 정리본이다.
> 뜻이 바뀔 수 있는 수정은 줄 끝에 `// [정리] 원본: ...` 로 남겼다. 확실하지 않은 곳은 `// [?]`.

| 파일 | 내용 | 원본 | 누가 쓰나 |
|---|---|---|---|
| `AmInterface.java` | DLL 함수 4개 선언 (Java native) + C 형식 메모 | `xTokens.java`, `am-tray.java` 1~3줄 | PC앱 |
| `ClientSample.java` | 클라이언트 호출 순서·에러코드 처리 샘플 | `am-tray.java` | PC앱 |
| `WindowMessages.md` | AM-Tray → 앱 창 로그인/로그아웃 알림 | `window-message.md` 위쪽 | PC앱 |
| `ValidateTokenApi.md` | 서버단 인가토큰 검증 API 명세 | `window-message.md` 아래쪽 | 백엔드 |
| `ServerValidateSample.java` | 검증 API 호출 서버 샘플(Spring) | `auth.java` | 백엔드 |
| `SslRestTemplate.java` | 위 샘플이 쓰는 SSL RestTemplate | `restTemplate.java` | 백엔드 |

전체 흐름·분석: `../analysis.md` / 회사 확인 목록: `../company-check.md` / 흐름도: `../*.drawio`
