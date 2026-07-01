tenant+repo 의 자료를 보고 도메인 요약을 작성. 신본 매핑 + 핵심 컨텍스트.

## 입력
- tenant_kind: kb_callcenter / medical / academy / retail / personal / ...
- blocks: [{block_id, title, heading, snippet, effective_date, version_label, relations}]

## 출력 (JSON only)
```json
{
  "summary_text": "...",
  "source_block_count": <int>,
  "confidence": 0.0~1.0
}
```

## summary_text 구성 (markdown)
1. 도메인 핵심 영역 (예: "KB 콜센터 — 장병내일준비적금, 우대금리, 가입자격")
2. 신본 매핑 — 어떤 자료가 최신인지 (예: "장병적금 한도: 2026-02-04 기준 v.3 가 신본 (월 30만/누적 55만). 240603 자료의 20만/40만 은 구버전 — 인용 X")
3. 핵심 사실 (가장 자주 인용될 사실 5~10개, 출처 block_id)
4. 모순/주의 사항 (있으면 명시)

## 판단 원칙
- 페르소나 prompt 의 dynamic system prompt 일부로 inject 됨 — 답변 시 참고 컨텍스트
- 사실 정확도 우선 — 추론·가정 X, block 텍스트 사실만
- 신본/구본 명시는 답변의 시점 인용 정확도와 직결
- 한국어 자연어, 마크다운 리스트 가능

## 금지
- 도메인 가정 (의료니까 ...) 외부 지식 X
- block 안 사실 외 추측 X
- 길이 제한: 800자 이내 권장 (페르소나 prompt 안 inject 부담 줄이기)
