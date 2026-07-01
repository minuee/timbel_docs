{% set tr = tool_result or {} %}
{% set items = tr.get('items') or [] %}
{% if not items %}
등록된 보유·관심 종목이 없습니다. "삼성전자 만원에 10주 샀어" 같이 등록해 주세요.
{% else %}
사용자에게 보유·관심 종목 현황을 한국어 존댓말로 정리해 알려주세요. 추천·예측 금지.

## 종목 ({{ items|length }}건)
{% for w in items %}- {{ w.name }} ({{ w.code }}){% if w.qty %} · {{ w.qty }}주 평단 {{ w.avg_cost or '-' }}원{% endif %}{% if w.current_price %} · 현재 {{ w.current_price }}원 ({{ w.change_pct }}%){% endif %}{% if w.pnl is not none %} · 손익 {{ w.pnl }}원 ({{ w.pnl_pct }}%){% endif %}{% if w.monitor_interval_min %} · 모니터 {{ w.monitor_interval_min }}분{% endif %}
{% endfor %}
{% if tr.total_pnl is not none %}
총 평가 {{ tr.total_market_value }}원 · 손익 {{ tr.total_pnl }}원 ({{ tr.total_pnl_pct }}%)
{% endif %}
{% endif %}
