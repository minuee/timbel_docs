{% set tr = tool_result or {} %}
{% if tr.success %}
{{ tr.summary }}
{% else %}
{{ tr.summary or tr.error or "등록 실패" }}
{% endif %}
