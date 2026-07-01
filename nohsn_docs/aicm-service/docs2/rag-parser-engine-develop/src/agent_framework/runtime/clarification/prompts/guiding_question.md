유도 질문 (proactive elicitation) 생성 — 단순 "모릅니다" 금지. 옵션·이유·prefix 패턴.

## 입력
- missing_info: 무엇을 모르는지 명확히
- ledger_recent: 최근 명확화 기록 (prefix 부착용)
- persona: {kind, tone, safety}
- threshold_stage: confidence 단계 (verification 0.7~0.85 / guided <0.7)

## 출력 (JSON only)
```json
{
  "question_text": "...",
  "options": ["...", "..."] 또는 null,
  "reason": "...",
  "prefix": "..." 또는 null,
  "kind": "verification" | "guided"
}
```

## 작성 원칙
- **사용자가 답할 수 있는 정보** 만 묻기. 자비스가 자기 자료를 묻지 X (사용자는 자료 모름)
- **옵션 형태** 우선 (자유 응답보다 선택지로 부담 ↓). 옵션 2~3개.
- **이유 명시** ("이 부분 자료가 신·구 혼재라 어느 시점 기준인지 확인 필요" 같은)
- **ledger 와 모순되지 않게 prefix** ("아까 X 라 하셨는데, 다른 각도로 ...")
- 한 발화 ≤ 1 질문. compound 안에서도 통합 1 질문.
- 페르소나 톤 유지

## kind 별 차이
- **verification** (0.7~0.85): "X 로 이해했는데 맞을까요?" — 가정값 노출 + 예/아니오 여지
- **guided** (<0.7): "이 부분이 명확하지 않은데 A/B/C 중 어떤 의미일까요?" 또는 "최근에 ... 자료가 갱신됐는지 알려주시면 더 정확히 답해드릴 수 있어요" — 옵션 또는 자료 부탁

## 금지
- "답변할 수 없습니다" 단독 종료
- 사용자가 모를 정보 (예: 자료 안 사실) 묻기
- 같은 슬롯 반복 질문 (ledger lookup 후 발사)
- 5개 이상 선택지 (사용자 부담)
