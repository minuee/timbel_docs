{% set summaries = slots["_fanout_summaries"] %}
{% if summaries and summaries|length > 1 %}
다음 지출 {{ summaries|length }}건을 기록했습니다. 사용자에게 항목별 한 줄로 확인해 주세요.
{% for s in summaries %}- {{ s }}
{% endfor %}
{% else %}
지출이 기록되었습니다. 사용자에게 한 줄로 확인해 주세요.
- 금액: {{ slots.amount }}원
- 카테고리: {{ slots.category }}
{% if slots.memo %}- 메모: {{ slots.memo }}{% endif %}
{% if slots.spent_at %}- 날짜: {{ slots.spent_at }}{% endif %}
{% endif %}
