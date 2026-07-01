block 텍스트에서 시점/버전 표지를 식별. 도메인 무관 (KB/의료/교육/식당 모두 동일 패턴).

## 입력
- block_text (헤딩 + 본문)

## 출력 (JSON only)
```json
{
  "effective_date": "YYYY-MM-DD" 또는 null,
  "version_label": "v.3" / "1차 개정" / null,
  "topic_keywords": ["..."],
  "confidence": 0.0~1.0,
  "reasoning": "..."
}
```

## 판단 원칙
- "이 시점 이후 적용", "이 일자에 개정", "기준일", "발효일" → effective_date
- "v.N", "N차 개정", "Rev.N", "버전 N" → version_label
- 표현·구두점·공백·년도 표기 변이 (2026.02.04 / 2026-02-04 / 26.2.4 / 2026년 2월 4일) 모두 같은 의미로 일반화
- topic_keywords: 이 block 의 핵심 토픽 명사 3~6개 (LLM 의 의미 비교용)
- confidence: 시점 표지가 명시적이고 모호함 없으면 ≥0.85, 추측이면 0.5~0.8, 시점 표지 없으면 < 0.5
- 시점 표지 자체가 없으면 effective_date=null + confidence 낮음 (정상 케이스 — block 의 절차 설명 등)

## 금지
- token overlap 식의 단순 매칭 X
- "최근/요즘" 같은 상대적 시점은 effective_date null (모호함)
- block 안 다른 주체의 발효일 (예: 직원 입사일) X
