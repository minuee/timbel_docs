# [요청] 감지 키워드 일괄 등록 API

관리자 설정 화면에서 **엑셀 파일로 감지 키워드를 일괄 등록**하는 기능을 붙이려 합니다.
현재는 단건 `POST /keyword-detects` 뿐이라 90건이면 90번 호출해야 해서, **배열을 한 번에 받는 API** 를 요청드립니다.

프론트에서 엑셀을 파싱해 `{ type, keyword }` 배열로 만들어 보냅니다. (파일이 아니라 JSON 전송)

---

## 요청 스펙

```
POST /aicc/asst-service/keyword-detects/bulk
Content-Type: application/json
```

**Request Body**

```json
{
  "creator_key": "4d763ac5-fec5-4d36-82c0-202d6edb1c37",
  "items": [
    { "type": "forbiddenWord",  "keyword": "무조건 승인됩니다" },
    { "type": "issueWord",      "keyword": "채무불이행" },
    { "type": "profanityWord",  "keyword": "..." }
  ]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `creator_key` | string | 등록자 = 로그인 사용자의 `agent.id` (단건 API 와 동일) |
| `items` | array | 등록할 키워드 목록. 1건 이상 |
| `items[].type` | string | 키워드 분류. 단건 API 의 `type` 과 동일 값 |
| `items[].keyword` | string | 키워드 원문 |

**`type` 허용값** (단건 API 와 동일)

| 값 | 화면 라벨 |
|---|---|
| `forbiddenWord` | 금칙어 |
| `issueWord` | 이슈어 |
| `profanityWord` | 비속어 |
| `emotionWord` | VOC (현재 화면 미노출) |

---

## 처리 규칙 (협의된 내용)

1. **중복은 upsert** — 같은 `type` + `keyword` 가 이미 있으면 갱신, 없으면 생성. 중복 때문에 실패 처리하지 않습니다.
2. **타입별로 그대로 저장** — 한 요청에 여러 `type` 이 섞여 옵니다. 필터링 없이 각 항목의 `type` 대로 저장해주세요.
3. **잘못된 항목은 무시하고 계속 진행** — 아래 경우는 건너뛰고 나머지는 정상 등록해주세요. (전체 롤백 X)
   - `keyword` 가 비었거나 공백뿐인 경우
   - `type` 이 없거나 허용값이 아닌 경우

---

## 응답 스펙

**성공 (200)**

```json
{
  "data": {
    "total": 90,
    "created": 70,
    "updated": 20,
    "ignored": 0
  }
}
```

| 필드 | 설명 |
|---|---|
| `total` | 요청으로 받은 항목 수 |
| `created` | 신규 생성 건수 |
| `updated` | upsert 로 갱신된 건수 |
| `ignored` | 위 3번 규칙으로 건너뛴 건수 |

> 화면에 "90건 중 70건 등록 / 20건 갱신" 처럼 표시할 예정이라 위 4개 카운트가 필요합니다.
> 집계가 부담되면 **최소한 `total` 과 `ignored`** 만이라도 부탁드립니다.

**실패**: 기존 API 들과 동일한 에러 규약을 따르면 됩니다.

---

## 참고

- 한 번에 보내는 최대 건수 제한이 있으면 알려주세요. 프론트에서 나눠 보내겠습니다. (현재 샘플 파일은 90건)
- 배포 전까지는 프론트가 **단건 API 를 반복 호출**하는 방식으로 임시 동작시킵니다.
  배포되면 이 API 로 자동 전환되도록 만들어둘 예정이라, 나온 뒤 알려만 주시면 됩니다.
