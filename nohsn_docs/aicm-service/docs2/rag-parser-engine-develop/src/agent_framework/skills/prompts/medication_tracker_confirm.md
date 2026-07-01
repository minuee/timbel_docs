복용 알람 등록 결과를 사용자에게 알립니다.

## 톤앤매너
- 존댓말. 이모지 X. 코드블록 X.
- 한두 문장으로 간결히.

## 도구 결과 (LLM 직접 참조)

- success: {{ tool_result.success if tool_result and tool_result.success is defined else "(없음)" }}
- duplicate: {% if tool_result and tool_result.duplicate %}true{% else %}false{% endif %}
- next_at: {{ tool_result.next_at if tool_result and tool_result.next_at else "(없음)" }}
- recurrence: {{ tool_result.recurrence if tool_result and tool_result.recurrence else "(없음)" }}
- summary: {{ tool_result.summary if tool_result and tool_result.summary else "" }}

## 분기

위 *duplicate=true* 면 → "이미 동일 알람이 등록되어 있습니다." 톤.

위 *success=true* 이고 duplicate=false 면 → 등록 안내 + 다음 발사 시각 명시:
- 매일 (daily): "{{slots.medication_name}} 알람을 매일 {{slots.time}}에 등록했습니다. 다음 발사: {{ tool_result.next_at }}."
- 매주 (weekly): "{{slots.medication_name}} 알람을 매주 {{slots.weekday}} {{slots.time}}에 등록했습니다."
- 격일/N일 (every_n_days): "{{slots.medication_name}} 알람을 {{slots.every_n}}일마다 {{slots.time}}에 등록했습니다."

위 *success=false* 면 → 실패 사유 안내 + 사용자에게 다시 시도 권유.

마지막에 한 문장 — 알람 일시정지/해제 방법 안내 ("나중에 멈추려면 '혈압약 알람 멈춰 줘' 라고 말씀해 주세요.").
