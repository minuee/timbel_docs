# 서버단 인가토큰 검증 API (원본: window-message.md 아래쪽)

> **백엔드가 부르는 API.** PC앱은 직접 부르지 않는다(인가토큰을 우리 백엔드로 보낼 뿐).

| 항목 | 값 |
|---|---|
| URL (개발) | `https://samlamdev.skhynix.com/tray/api/ValidateToken` |
| URL (운영) | `https://samlam.skhynix.com/tray/api/ValidateToken` |
| Method | `POST` |
| Content-Type | `application/json; charset=UTF-8` |

## 요청
```json
{ "systemID": "<시스템 ID>", "authzToken": "<PC앱이 받은 인가토큰>" }
```
- [정리] 서버 샘플은 키를 `"SystemID"`(대문자 S)로 넣는다. 명세는 `systemID`. [?] 어느 쪽인지 확인

## 응답
```json
{ "status": 300, "attr": { "RESULTID": "SUCCESS", "USERID": "<인증 사용자 ID>" } }
```
| attr.RESULTID | 뜻 |
|---|---|
| `SUCCESS` | 성공 — `USERID` 사용 |
| `SYSTEMID_INVALID` | 시스템 아이디 검증 실패 |
| `TOKEN_INVALID` | 유효하지 않은 인가토큰 |
| 그 밖 | 통신 실패로 처리 |

- [?] 원본 명세는 `Result : "Success"`, 샘플 코드는 `RESULTID` / `"SUCCES"`(오타로 봄). 실제 키·값 대소문자 확인
- [?] `status : 300` — HTTP 상태코드인지 본문 값인지, 정말 300 인지
- [?] `USERID` 가 사번인지 AD 계정인지
- 샘플은 응답이 `204 No Content` 면 "잘못된 요청"으로 처리
