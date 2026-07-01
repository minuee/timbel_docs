사용자가 답변하려는 슬롯/토픽이 ledger 의 기존 항목과 의미적으로 일치하는지 LLM 비교.

## 입력
- new_intent: {slot_name, topic, entities, missing_info}
- ledger_history: [{turn_idx, asked, answered, applied_skill, applied_slot, confidence}]
- ledger_slots: {skill_name: {slot_name: {value, source_turn, confidence}}}
- ledger_topics: [{turn_idx, topic, entities, persona_state}]

## 출력 (JSON only)
```json
{
  "matched": true/false,
  "matched_record_type": "history" | "slot" | "topic" | null,
  "matched_record_idx": <int> 또는 null,
  "matched_value": "..." 또는 null,
  "similarity_reason": "..."
}
```

## 판단 원칙
- 의미 비교 (token overlap X). 같은 슬롯 다른 표현도 일치 인정.
- 사용자가 직전에 답한 시간/장소/주제 등을 다시 묻는 케이스 즉시 hit
- 다른 각도 (예 "어제 일정" vs "이번 주 일정") 는 unmatched
- ledger 가 비었으면 matched=false

## 금지
- 비슷한 단어 1개 만으로 matched=true 단정
- ledger 외부 추측 (도메인 지식) X
