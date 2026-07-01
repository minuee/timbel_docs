{# stock.quote 결과를 한국어 한 줄로 요약. tool_result 가 success=false 면 그 메시지 그대로. #}
{% set tr = tool_result or {} %}
{% if not tr.success %}
{{ tr.summary or "시세 조회 실패" }}
{% else %}
사용자에게 다음 시세를 한국어 존댓말로 한두 줄에 알려주세요. 예측·추천·매수매도 의견 금지.
- 종목: {{ tr.name }} ({{ tr.code }})
- 종가: {{ tr.close }}원 ({{ tr.trade_date }})
- 등락: {{ tr.change }}원 ({{ tr.change_pct }}%)
- 거래량: {{ tr.volume }}
{% endif %}
