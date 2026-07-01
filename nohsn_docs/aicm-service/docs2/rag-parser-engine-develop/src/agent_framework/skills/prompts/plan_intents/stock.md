# 카테고리: stock (주식 가격 / 등록 / 모니터링 / 분석)

## 시세 조회

"삼성전자 현재가", "삼성전자 주식 얼마야" →

```
[{1, tool, stock.quote, {code_or_name: "삼성전자"}}]
```

종목명 → code 변환 ("삼성전자" → "005930") 은 도구 내부에서 처리. plan 은 발화 그대로 넘김.

## 보유 주식 등록 (신규 또는 동일 종목 정보 업데이트)

"삼성전자 216500원에 53주 샀어" →

```
[{1, tool, stock.add_watch, {
   code_or_name: "삼성전자",
   qty: 53,
   avg_cost: 216500,
   tenant_id: "$personal_tenant_id"
 }}]
```

* 인자 키: `qty` (보유 수량 정수), `avg_cost` (평단가 정수, 원 단위).
* `match_qty` / `match_avg_cost` 같은 *match_* prefix 키는 stock.update_watch 의
  *기존 row 매칭* 조건 — add_watch 에선 사용 X.
* 같은 종목이 이미 있으면 add_watch 가 자동 dedup-by-code 후 *비-None 필드만*
  merge (새 값으로 덮어씀). 신규 row 생성 X.

## 보유 수량 변경 (직전 등록 후 단순 update)

"수량이 530주야" / "그 주식을 530주로 변경" → stock.update_watch.
이 도구는 같은 종목의 기존 row 를 찾아 update — 새 row 생성 X.

```
[{1, tool, stock.update_watch, {
   code_or_name: "삼성전자",
   qty: 530,
   tenant_id: "$personal_tenant_id"
 }}]
```

* `qty` / `avg_cost` 가 변경 *대상 값* (새로 설정할 값).
* `match_qty` / `match_avg_cost` 는 *기존 row* 매칭 조건 (옵션). 보통 종목명만으로
  매칭 충분하므로 match_* 생략. id 명시되면 id 우선.

직전 turn 에서 등록한 종목명을 history 에서 추출.

## 거래 의향 (매수/매도) — 실 주문 미지원, 관심 등록으로 대체 (D71)

"카카오 20만원치 매수해줘" / "삼성전자 사자" / "엔비디아 50만원 담아" /
"테슬라 들어가자" / "NVDA 한 주 사자" / "카카오 절반 팔자" 같은 거래 의향은
*시스템에 실주문 도구가 없으므로* `stock.add_watch` 로 관심 종목 등록.

```
"카카오 20만원치 매수" → [{1, tool, stock.add_watch, {
   code_or_name: "카카오",
   note: "매수 의향 20만원치",
   tenant_id: "$personal_tenant_id"
 }}]
```

* note 에 사용자 발화 핵심 (매수/매도 의향 + 금액·수량) 보존.
* 응답 본문은 "주문은 미지원이라 관심 종목 등록 — 목표가/손절가 알림 설정할까요?" 안내.
* 매도/팔자 발화도 동일 도구. note='매도 의향' 으로 차별.
* unsupported 응답 절대 X — *관심 등록* 대안 항상 제시.
* 네거티브 가드 (stock 아님): '사자 사진/사자성어' (동물·고사), '단톡방
  들어가자' (채팅방), '비트코인 담아' (코인·미지원). LLM 분류기가 이미 거름.

## 가격 모니터링 알람

"삼성전자 23만원 되면 알려줘" →

```
[{1, tool, stock.add_watch, {
   code_or_name: "삼성전자",
   alert_high: 230000,
   tenant_id: "$personal_tenant_id"
 }}]
```

내림 방향 ("21만원으로 떨어지면") → alert_low.

## 시장 동향 / 추천 종목

"오늘 상승률 높은 종목" / "급등주" → stock.market_movers.
"내일 삼성전자 전망" / "이 종목 어때?" → stock.analyze + multi-source 보강 (info_lookup 카테고리로 escalate 가능).

## 결제 / 거래 관련 일반 정보

"주식 매매 수수료", "T+2 결제" 같은 *정보 조회* → info_lookup 카테고리로 라우팅 (이 카테고리에서 처리 X).




## 시세 조회 슬롯 정규화 / 별칭 강제 규칙

stock.quote 의 `code_or_name` 에는 사용자의 전체 문장을 넣지 말고 **단일 종목 식별자만** 넣는다.
가격/시세/주가/현재가/장전가 같은 요청어, 공백, 조사, 보조 설명은 제거한다.

* 사용자가 6자리 한국 종목코드를 함께 말하면 종목명보다 **6자리 코드 우선**:
  * "삼성전자 005930 시세" → `{code_or_name: "005930"}`
  * "005930 현재가" → `{code_or_name: "005930"}`
* 자주 쓰는 국내 별칭은 정식 코드로 정규화:
  * "삼성전자" → `{code_or_name: "005930"}`
  * "네이버", "NAVER", "naver" → `{code_or_name: "035420"}`
  * "카카오" → `{code_or_name: "035720"}`
  * "SK하이닉스", "에스케이하이닉스" → `{code_or_name: "000660"}`
* 해외 주식 시세/장전가 요청은 한국 6자리 코드를 요구하지 말고 티커를 추출해 그대로 stock.quote 로 조회:
  * "테슬라 주가" / "TSLA" → `{code_or_name: "TSLA"}`
  * "애플 장전가" / "AAPL" → `{code_or_name: "AAPL"}`
  * "엔비디아 티커 NVDA 시세" → `{code_or_name: "NVDA"}`

예시:
```
"삼성전자 005930 시세" → [{1, tool, stock.quote, {code_or_name: "005930"}}]
"네이버 주가" → [{1, tool, stock.quote, {code_or_name: "035420"}}]
"테슬라 주가 지금 얼마야?" → [{1, tool, stock.quote, {code_or_name: "TSLA"}}]
"애플 장전가 확인해줘" → [{1, tool, stock.quote, {code_or_name: "AAPL"}}]
"엔비디아 티커 NVDA 시세" → [{1, tool, stock.quote, {code_or_name: "NVDA"}}]
```
