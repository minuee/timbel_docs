{% set tr = tool_result or {} %}
{% if tr.success %}
종목이 삭제되었습니다.
{% else %}
{{ tr.error or "삭제 실패" }}
{% endif %}
