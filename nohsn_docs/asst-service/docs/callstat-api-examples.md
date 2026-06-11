# Callstat API 사용 예시

## 개요

Callstat API는 통화 통계 데이터를 조회하는 **읽기 전용** 서비스입니다.
`raw_call` 스키마의 4개 테이블(`callstats_call`, `callstats_turn`, `callstats_entity`, `callstats_keyword`)을 참조합니다.

## API 엔드포인트

### 1. 통화 목록 조회 (Pagination 지원)

```bash
GET /api/asst/v1/callstat/calls
Authorization: Bearer {token}

# 기본 조회 (첫 번째 페이지, 10개 항목)
GET /api/asst/v1/callstat/calls

# 페이지네이션
GET /api/asst/v1/callstat/calls?page=2&limit=20

# 통화 방향 필터
GET /api/asst/v1/callstat/calls?direction=inbound

# 날짜 범위 필터
GET /api/asst/v1/callstat/calls?start_date=2025-09-01&end_date=2025-09-30

# 복합 필터
GET /api/asst/v1/callstat/calls?direction=inbound&start_date=2025-09-01&page=1&limit=20
```

**응답 예시:**

```json
{
  "data": [
    {
      "id": "call_001",
      "call_id": "20250923_001",
      "started_at": "2025-09-23T10:00:00Z",
      "ended_at": "2025-09-23T10:05:30Z",
      "duration_ms": 330000,
      "consumer_phonenumber": "010-1234-5678",
      "agent_id": "43930611",
      "extension_number": "1001",
      "direction": "inbound",
      "call_type": "support",
      "created_at": "2025-09-23T10:06:00Z",
      "updated_at": "2025-09-23T10:06:00Z"
    }
  ],
  "total": 150,
  "page": 1,
  "limit": 10,
  "totalPages": 15,
  "hasNext": true,
  "hasPrev": false
}
```

### 2. 통화 상세 조회 (관련 데이터 모두 포함)

```bash
GET /api/asst/v1/callstat/calls/{call_id}
Authorization: Bearer {token}

# 예시
GET /api/asst/v1/callstat/calls/20250923_001
```

**응답 예시:**

```json
{
  "call": {
    "id": "call_001",
    "call_id": "20250923_001",
    "started_at": "2025-09-23T10:00:00Z",
    "ended_at": "2025-09-23T10:05:30Z",
    "duration_ms": 330000,
    "consumer_phonenumber": "010-1234-5678",
    "agent_id": "43930611",
    "extension_number": "1001",
    "direction": "inbound",
    "call_type": "support"
  },
  "turns": [
    {
      "id": "turn_001",
      "callstats_id": "call_001",
      "turn_idx": 1,
      "role": "customer",
      "utterance": "안녕하세요, 문의가 있습니다.",
      "masked_utterance": "안녕하세요, 문의가 있습니다.",
      "started_at": "2025-09-23T10:00:00Z",
      "ended_at": "2025-09-23T10:00:10Z",
      "duration_ms": 10000,
      "intent": {
        "intent": "inquiry",
        "confidence": 0.95
      }
    },
    {
      "id": "turn_002",
      "callstats_id": "call_001",
      "turn_idx": 2,
      "role": "agent",
      "utterance": "네, 안녕하세요. 어떤 도움이 필요하신가요?",
      "masked_utterance": "네, 안녕하세요. 어떤 도움이 필요하신가요?",
      "started_at": "2025-09-23T10:00:11Z",
      "ended_at": "2025-09-23T10:00:20Z",
      "duration_ms": 9000,
      "intent": {
        "intent": "greeting",
        "confidence": 0.98
      }
    }
  ],
  "entities": [
    {
      "id": "entity_001",
      "callstats_id": "call_001",
      "turn_id": "turn_001",
      "turn_idx": 1,
      "slot_type": "phone_number",
      "slot_value": "010-1234-5678"
    },
    {
      "id": "entity_002",
      "callstats_id": "call_001",
      "turn_id": "turn_002",
      "turn_idx": 2,
      "slot_type": "greeting",
      "slot_value": "안녕하세요"
    }
  ],
  "keywords": [
    {
      "id": "keyword_001",
      "callstats_id": "call_001",
      "turn_id": "turn_001",
      "turn_idx": 1,
      "keyword": "문의",
      "freq": 2
    },
    {
      "id": "keyword_002",
      "callstats_id": "call_001",
      "turn_id": "turn_002",
      "turn_idx": 2,
      "keyword": "도움",
      "freq": 1
    }
  ]
}
```

### 3. 개별 데이터 조회 API

#### 턴 목록만 조회

```bash
GET /api/asst/v1/callstat/calls/{call_id}/turns
```

#### 엔티티 목록만 조회

```bash
GET /api/asst/v1/callstat/calls/{call_id}/entities
```

#### 키워드 목록만 조회

```bash
GET /api/asst/v1/callstat/calls/{call_id}/keywords
```

## 필터링 옵션

### 사용 가능한 필터:

| 파라미터     | 설명             | 예시                  |
| ------------ | ---------------- | --------------------- |
| `page`       | 페이지 번호      | `1`                   |
| `limit`      | 페이지당 항목 수 | `20`                  |
| `direction`  | 통화 방향        | `inbound`, `outbound` |
| `start_date` | 시작 날짜        | `2025-09-01`          |
| `end_date`   | 종료 날짜        | `2025-09-30`          |

### 복합 필터 예시:

```bash
# 특정 Agent의 9월 인바운드 통화만 조회
GET /callstat/calls?agent_id=43930611&direction=inbound&start_date=2025-09-01&end_date=2025-09-30

# 지원 요청 통화의 최근 50건 조회
GET /callstat/calls?call_type=support&limit=50

# 특정 기간의 아웃바운드 통화 2페이지
GET /callstat/calls?direction=outbound&start_date=2025-09-15&page=2&limit=25
```

## 데이터 구조

### CallstatCall (메인 통화 정보)

- **id**: 호출 통계 ID
- **call_id**: 통화 ID (실제 통화 식별자)
- **started_at/ended_at**: 통화 시작/종료 시간
- **duration_ms**: 통화 지속 시간 (밀리초)
- **consumer_phonenumber**: 고객 전화번호
- **agent_id**: Agent ID
- **extension_number**: 내선 번호
- **direction**: 통화 방향 (inbound/outbound)
- **call_type**: 통화 유형

### CallstatTurn (턴별 발화 정보)

- **turn_idx**: 턴 순서
- **role**: 역할 (customer/agent)
- **utterance**: 실제 발화 내용
- **masked_utterance**: 마스킹된 발화 내용
- **intent**: 의도 분석 결과 (JSON)

### CallstatEntity (슬롯 정보)

- **slot_type**: 슬롯 유형 (phone_number, name 등)
- **slot_value**: 슬롯 값

### CallstatKeyword (키워드 정보)

- **keyword**: 추출된 키워드
- **freq**: 빈도수

## 사용 사례

### 1. Agent 성과 분석

```bash
# 특정 Agent의 월간 통화 통계
GET /callstat/calls?agent_id=43930611&start_date=2025-09-01&end_date=2025-09-30
```

### 2. 통화 상세 분석

```bash
# 특정 통화의 전체 분석 데이터
GET /callstat/calls/20250923_001
```

### 3. 키워드 분석

```bash
# 특정 통화의 키워드만 추출
GET /callstat/calls/20250923_001/keywords
```

### 4. 대화 플로우 분석

```bash
# 특정 통화의 턴별 대화 내용
GET /callstat/calls/20250923_001/turns
```

## 주의사항

- **읽기 전용**: 모든 API는 조회만 가능합니다
- **인증 필수**: Bearer token 인증이 필요합니다
- **동적 DB**: 토큰에 따라 적절한 데이터베이스에 연결됩니다
- **스키마**: `call` 스키마의 테이블들을 참조합니다
