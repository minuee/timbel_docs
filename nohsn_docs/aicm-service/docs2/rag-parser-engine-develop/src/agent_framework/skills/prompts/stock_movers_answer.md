{% set tr = tool_result or {} %}
{% if not tr.success %}
{{ tr.summary or "시장 동향 조회 실패" }}
{% else %}
사용자에게 한국어 존댓말로 시장 동향을 정리해 알려주세요. 추천·예측 금지.

## {{ tr.trade_date }} {{ tr.market }} 시장 동향

### 급등주 top {{ tr.gainers|length }}
{% for s in tr.gainers %}- {{ s.name }} ({{ s.code }}) {{ s.close }}원 (+{{ s.change_pct }}%, 거래량 {{ s.volume }})
{% endfor %}

### 급락주 top {{ tr.losers|length }}
{% for s in tr.losers %}- {{ s.name }} ({{ s.code }}) {{ s.close }}원 ({{ s.change_pct }}%, 거래량 {{ s.volume }})
{% endfor %}

### 거래량 top {{ tr.volume|length }}
{% for s in tr.volume %}- {{ s.name }} ({{ s.code }}) {{ s.close }}원 ({{ s.change_pct }}%, 거래량 {{ s.volume }})
{% endfor %}
{% endif %}
