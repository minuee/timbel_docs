# 감지어 탐지 이력 API (프론트엔드 전달용)

감지어가 통화 발화에서 탐지된 이력을 조회하는 API 2개입니다.
경로는 모두 `/aicc/asst-service` 기준이며, 인증은 기존 API와 동일합니다.

---

## 1. 이력 리스트

```
GET /aicc/asst-service/keyword-detect-logs
```

### 파라미터 (전부 선택)

| 이름 | 타입 | 설명 |
|---|---|---|
| `page` | number | 페이지 번호 (1부터). 기본 `1` |
| `limit` | number | 페이지당 건수. 기본 `10` |
| `keyword` | string | 검색어. 감지된 키워드에 부분일치 (대소문자 무시) |
| `type` | string | `forbiddenWord` / `profanityWord` / `issueWord` |
| `agent_id` | string | 상담사 (예: `ecp-4`) |
| `from` | string | 기간 시작. ISO8601 |
| `to` | string | 기간 종료. ISO8601 |
| `call_id` | string | 특정 통화만 |
| `speaker` | string | `customer` / `agent` |
| `agent_cti_id` | string | CTI ID로 직접 지정할 때 |

- 필터는 전부 AND로 걸립니다.
- 정렬은 **감지 최신순 고정**입니다.
- URL에 `+09:00`을 쓸 때 `+` 는 `%2B` 로 인코딩해야 합니다. (안 하면 공백으로 해석됨)

### 호출 예시

```
/aicc/asst-service/keyword-detect-logs?page=1&limit=20&type=forbiddenWord&agent_id=ecp-4&from=2026-08-01T00:00:00%2B09:00&to=2026-08-31T23:59:59%2B09:00
```

### 응답

```json
{
  "data": [
    {
      "id": "kwdlog_9f2a...",
      "call_id": "698592356973",
      "turn_idx": 3,
      "keyword": "원금 보장",
      "type": "forbiddenWord",
      "speaker": "agent",
      "agent_id": "ecp-4",
      "agent_name": "홍길순",
      "detected_at": "2026-08-04T10:23:11.482Z"
    }
  ],
  "total": 137,
  "page": 1,
  "limit": 20,
  "totalPages": 7,
  "hasNext": true,
  "hasPrev": false
}
```

`agent_cti_id`, `keyword_id`, `content_hash`, `create_at` 도 함께 오지만 화면에 쓸 일은 없습니다.

빈 결과는 `data: []`, `total: 0` 으로 옵니다. `agent_id` 로 필터했는데 해당 상담사가 없어도
에러가 아니라 빈 목록입니다.

---

## 2. 통계

```
GET /aicc/asst-service/keyword-detect-logs/stats
```

파라미터는 **1번과 동일**합니다 (`page` / `limit` 만 무시).
목록 화면의 필터를 그대로 넘기면 그 조건의 집계가 나옵니다.

### 응답

```json
{
  "total": 137,
  "byType": [
    { "type": "forbiddenWord", "count": 82 },
    { "type": "profanityWord", "count": 41 },
    { "type": "issueWord", "count": 14 }
  ],
  "byAgent": [
    {
      "agent_cti_id": "56356659",
      "agent_id": "ecp-4",
      "agent_name": "홍길순",
      "count": 53
    }
  ],
  "topKeywords": [
    { "keyword": "원금 보장", "type": "forbiddenWord", "count": 22 }
  ]
}
```

- `topKeywords` 는 상위 20건만 옵니다.
- `byType`, `byAgent` 는 전부 옵니다.

---

## 알아두실 것

- **`turn_idx`** 는 고객 발화만 값이 있고 상담사 발화는 `null` 입니다.
  상담사 발화는 대화 히스토리로 들어와 턴 번호가 없습니다.
- **`agent_id` / `agent_name`** 은 저장된 값이 아니라 조회 시점에 상담사 정보를 붙인 것입니다.
  아직 동기화되지 않은 CTI ID면 `null` 로 옵니다. 화면에서 `null` 처리를 해두세요.
- **같은 키워드라도 발화가 다르면 별도 행**입니다.
  고객이 한 통화에서 "도용"을 세 번 말하면 3건입니다. (같은 발화가 반복 전달되는 것은 서버에서 걸러집니다)
- **`keyword`** 필드를 화면에 쓰세요. 감지 당시 값이 그대로 저장돼 있어, 관리자가 나중에 사전에서
  키워드를 수정하거나 지워도 이력은 그대로 남습니다. (`keyword_id` 는 `null` 이 될 수 있습니다)
- **`emotionWord`(VOC)** 는 탐지 대상이 아니라 이력에 나오지 않습니다. 필터 드롭다운에서 제외해주세요.
- **발화 원문은 내려가지 않습니다.** `call_id` + `turn_idx` 로 통화 상세와 연결하는 구조입니다.
- 인증 토큰이 없으면 `404` 로 `인증 토큰이 필요합니다` 가 떨어집니다.

---

상세 필드는 Swagger 에서도 확인할 수 있습니다.
