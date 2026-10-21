# 회의록 처리 상태 조회 API

회의록(콘텐츠)의 **처리 상태**(`Content.transcribeStatus`)만 가볍게 조회하는 API. 업로드/전사/요약 진행 상황을 폴링하거나 완료 여부를 확인할 때 사용한다.

> 대상: timblo-mobile 개발자.
> 상세 조회(`GET /contents/:id`)는 전사·요약·북마크·메모까지 전부 로드해 무겁지만, 이 API는 **Content 1행의 상태 컬럼만** 반환해 폴링에 적합하다.

---

## 공통

- **인증**: 기존과 동일한 timblo 토큰 헤더 — `Authorization: Bearer <token>` (필수).
- **베이스 URL / 게이트웨이**: 기존 API가 쓰는 host/prefix 규칙 그대로(아래 경로는 master-api 내부 라우트 기준).
- **응답 봉투**: `{ "message": string, "httpCode": number, "data": object }` (이하 예시는 `data`만 표기).
- **권한**: 해당 회의록의 **뷰어 이상**(조회 권한이 있는 사용자).

---

## 엔드포인트

### GET `/contents/:contentId/status`

- Path
  - `contentId` (필수): 회의록 ID
- Request body: 없음

- Response `data`:
```json
{
  "contentId": "e893e192-abc5-43ae-a9dd-55bf10804a21",
  "transcribeStatus": "DONE"
}
```

---

## `transcribeStatus` 값

파이프라인 진행 단계를 나타내는 문자열. **완료/실패(종료 상태)만 확인하면 되는 경우** `DONE` / `ERROR`만 보면 된다.

| 값 | 의미 | 종류 |
|---|---|---|
| `WAITING` | 대기(업로드 직후/처리 대기) | 진행 중 |
| `RUNNING` | 전사(STT) 진행 중 | 진행 중 |
| `STT_DONE` | 전사 완료, 요약 대기/진행 | 진행 중 |
| `SUMMARY_DONE` | 요약 완료(후처리 진행) | 진행 중 |
| `RE_SUMMARY_RUNNING` | 재요약 진행 중 | 진행 중 |
| `TEXT_SPLIT_DONE` | (텍스트 업로드) 분할 완료 | 진행 중 |
| `DONE` | **처리 완료** | ✅ 종료 |
| `ERROR` | **처리 실패** | ⛔ 종료 |
| `CANCEL` | 취소됨 | ⛔ 종료 |

> `transcribeStatus`는 `VARCHAR(50)` 자유 문자열이라 파이프라인/엔진에 따라 값이 추가될 수 있다. 클라이언트는 **`DONE`/`ERROR`(및 `CANCEL`)를 종료 상태로 처리**하고 그 외는 "진행 중"으로 취급하는 것을 권장한다.

---

## 에러

| httpCode | 상황 |
|---|---|
| `1000` | `contentId` 누락 또는 존재하지 않는 회의록(`content not found`) |
| 권한 오류 | 뷰어 미만(조회 권한 없음) |

---

## 호출 예시

```bash
curl -H "Authorization: Bearer <token>" \
  https://<host>/api/contents/e893e192-abc5-43ae-a9dd-55bf10804a21/status
# → { "message":"Success", "httpCode":200,
#     "data": { "contentId":"e893e192-...", "transcribeStatus":"DONE" } }
```

## 폴링 가이드

- 업로드 후 상태를 주기적으로 조회하다가 `DONE`이면 상세 조회, `ERROR`/`CANCEL`이면 실패 처리.
- 권장 간격: 2~5초(과도한 폴링 자제). 종료 상태 도달 시 폴링 중단.
- 실시간 통지가 필요하면 기존 SSE(콘텐츠 변경 알림)도 함께 활용 가능.
