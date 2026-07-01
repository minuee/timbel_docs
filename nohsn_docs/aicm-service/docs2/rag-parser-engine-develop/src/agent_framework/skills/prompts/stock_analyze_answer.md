{% set tr = tool_result or {} %}
{% if not tr.success %}
{{ tr.summary or "분석 실패" }}
{% else %}
{% set q = tr.quote or {} %}
{% set ind = tr.indicators or {} %}
{% set news = tr.news_sentiment or {} %}
{% set disc = tr.disclosures or [] %}
사용자에게 다음 정보를 한국어 존댓말로 정리해 알려주세요. 절대 규칙:
- 매수·매도 권고 금지
- "사야 한다 / 팔아야 한다 / 좋다 / 나쁘다" 평가 금지
- 사실·신호만 진술
- 답변 마지막 줄에 면책 그대로: "{{ tr.disclaimer }}"

## 시세
- 종목: {{ tr.name }} ({{ tr.code }})
- {{ q.summary }}

## 기술적 신호
{% for s in (ind.signals or []) %}- {{ s }}
{% endfor %}

{% if news.available %}
## 뉴스 톤 (최근 5건)
- 평균 점수 {{ news.score }} → {{ news.tone }}
- positive {{ news.counts.positive }} · negative {{ news.counts.negative }} · neutral {{ news.counts.neutral }}
{% endif %}

{% if disc %}
## 최근 공시 ({{ disc|length }}건, 14일)
{% for d in disc[:5] %}- {{ d.date }} {{ d.title }}
{% endfor %}
{% endif %}

응답 형식: 시세 한 줄 → 신호 bullet 3-5개 → 뉴스/공시가 있으면 추가 → 마지막에 면책 한 줄. 추측·예측·"앞으로 어떨 것" 같은 단정 금지.
{% endif %}
