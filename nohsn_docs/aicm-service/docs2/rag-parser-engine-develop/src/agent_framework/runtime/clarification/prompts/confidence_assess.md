자기 답변·추출·정제 결과의 self-confidence 자가 평가. LLM 이 단계별로 호출.

## 입력
- stage: extract / distill / synthesize / answer / is_compound / slot_inference
- output: 평가 대상 결과 (텍스트 또는 dict)
- context: 입력 자료 (grounding_docs / block_text / sub_results 등)
- grounding_used: 답변에서 인용한 자료 ID 또는 텍스트

## 출력 (JSON only)
```json
{
  "confidence": 0.0~1.0,
  "reason": "...",
  "missing_info": "...자료가 부족한 영역 또는 모호한 부분, null 가능"
}
```

## 평가 원칙
- **0.85 이상 (자율)** — 핵심 사실 정확 + grounding 명확 + 출력 일관성
- **0.7 ~ 0.85 (확인)** — 일부 추론·가정, 사용자 확인이 답변 신뢰 ↑
- **0.7 미만 (유도)** — 핵심 사실 모름 / 자료 부족 / 의미 충돌

## stage 별 가이드
- **extract** — 시점 표지가 명시적이고 모호 X (≥0.85), 추측 (0.5~0.85), 시점 표지 없음 (≤0.5)
- **distill** — 두 block 의 관계가 명확 (≥0.85), 부분 모호 (0.5~0.85), 무관 (≤0.3)
- **synthesize** — 통합 답변 일관성 + 모든 sub 의 사실 정확 (≥0.85), 일부 sub 부족 (0.7~0.85), 핵심 자료 부족 (<0.7)
- **answer** — grounding 출처 인용 + 페르소나 톤 (≥0.85), 추정 일부 (0.7~0.85), 모르는 부분 단정 (위험, <0.7)
- **is_compound** — 발화가 명백히 cross-domain (≥0.85), 모호 (0.7~0.85), 단일 도메인 추정 (단일 결정 시 confidence 별도 의미)
- **slot_inference** — 컨텍스트로 슬롯 추론 명확 (≥0.85), 추측 (0.7~0.85), 모름 (<0.7)

## 금지
- 자기 정확성 과대 평가 (hallucination 위험) — 의문 있으면 confidence 낮게
- 평가 prompt 의 사례·도메인 지식 사용 X — output 과 context 만 비교
