{# 지출 조회·분석 응답. tool_result 는 expense.sum_by_category 가 돌려준 dict —
   total / by_category / count / period / items / summary #}
{% set tr = tool_result or {} %}
{% set items = tr.get('items') or [] %}
{% set total = tr.get('total') %}
{% set by_cat = tr.get('by_category') or {} %}
기간 {{ slots.period_start }} ~ {{ slots.period_end }} 지출 조회 결과를 사용자에게 한국어 존댓말로 간결히 알려주세요.

## 도구 결과
- 총 건수: {{ tr.get('count') }}
- 합계: {{ total }}원
{% if by_cat %}- 카테고리별: {% for k, v in by_cat.items() %}{{ k }} {{ v }}원{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}
{% if items %}- 항목:
{% for it in items %}  - {{ it.spent_at }} {{ it.category }} {{ it.amount }}원 ({{ it.description }})
{% endfor %}{% endif %}

규칙: 항목이 있으면 항목 리스트 위주로 (날짜·카테고리·금액·설명), 합계는 마지막 한 줄. 0 건이면 "해당 기간 지출 내역이 없습니다." 한 줄. 추측 금지.
