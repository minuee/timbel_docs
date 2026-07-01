# 카테고리: payment (결제 환불 — 추상 layer)

본 카테고리는 **환불 요청** 만 다룬다. 사용자가 챗봇 안에서 직접 결제하는 흐름은 없다 (사기 위험 + 채널 정책 위반 가능).

## 환불 요청

```
[{1, tool, payment.refund, {
   order_id: "<주문번호 또는 PG paymentKey — 발화/history 에서 추출>",
   amount: <환불 금액, 정수 원 — 사용자 명시 또는 history 의 결제 금액>,
   reason: "<환불 사유, 발화 명시 시>",
   tenant_id: "$personal_tenant_id"
 }}]
```

응답 status='pending' — 후속 PR 의 PG webhook (Toss/카카오페이/네이버페이) 이 status 를 'completed' 또는 'failed' 로 전환.

## 정책 안내

"환불 정책이 어떻게 돼요?", "출발 전 취소 시 수수료 있나요?", "중간에 그만두면 환불 되나요?" 같은 정책 질문은 `kms_sop.search` 로 매장/서비스 SOP markdown 검색 후 안내.

## 슬롯 누락 시

- order_id 없음 → ask_user_clarify "어떤 주문의 환불인가요? 주문번호를 알려 주세요."
- amount 없음 → ask_user_clarify "환불 금액을 알려 주세요."

## 절대 금지

- `payment.charge` 같은 결제 *수금* 도구 호출 X (이번 PR 카탈로그에 존재하지 않음).
- order_id 없이 broad refund 호출 금지 — multi-tenant 환경에서 다른 사용자의 주문을 건드릴 위험.
