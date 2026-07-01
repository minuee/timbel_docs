두 block 의 관계를 판단. 토픽 일치 여부 + 시점 차이 + 관계 타입.

## 입력
- block_a: {block_id, text, effective_date, topic_keywords}
- block_b: {block_id, text, effective_date, topic_keywords}

## 출력 (JSON only)
```json
{
  "is_related": true/false,
  "relation": "supersedes" | "conflicts" | "duplicate" | "complementary" | null,
  "newer_block_id": "<id>" 또는 null,
  "confidence": 0.0~1.0,
  "reasoning": "..."
}
```

## 관계 타입 정의
- **supersedes** — 같은 토픽 + 시점 다름 + 새 block 이 옛 block 을 대체 (한도 변경, 약관 개정 등)
- **conflicts** — 같은 토픽인데 사실이 모순 (시점 같거나 모름) — 사람 검수 필요
- **duplicate** — 같은 토픽 + 같은 사실의 표현만 다른 중복
- **complementary** — 같은 영역의 다른 측면 보완 (예: 가입조건 + 우대금리 — 모순 X, 결합 정보)
- **null (is_related=false)** — 토픽 무관

## 판단 원칙
- 의미 비교 (token overlap X, LLM 의미 일치 판단)
- effective_date 둘 다 있고 다르면 supersedes 우선 검토
- 한쪽만 effective_date 있으면 conflicts 또는 complementary 판단 신중
- confidence: 명확하면 ≥0.85, 모호하면 0.5~0.8

## 금지
- 표면적 keyword 일치만으로 supersedes 단정 X
- 도메인 가정 (KB 자료니까 ...) 같은 외부 지식 X — block 텍스트 안 정보만 사용
