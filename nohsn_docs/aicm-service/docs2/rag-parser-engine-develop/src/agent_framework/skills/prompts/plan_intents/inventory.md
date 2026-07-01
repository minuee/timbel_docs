# 카테고리: inventory (재고 조회 — read-only)

본 카테고리는 **재고 확인** 만 다룬다. 재고 *수정*은 후속 PR (admin 권한 + audit log).

## 재고 조회

```
[{1, tool, inventory.check, {
   item_name: "<상품명, 발화 명시 시>",
   sku: "<SKU, 발화 명시 시>",
   item_id: "<문서 UUID, history 에 있을 때>",
   tenant_id: "$personal_tenant_id"
 }}]
```

`item_name` / `sku` / `item_id` 중 *최소 하나*는 채워야 한다. 셋 다 비어 있으면 ask_user_clarify "어떤 상품의 재고를 확인할까요?" 되묻기.

## 응답 패턴

- `status='in_stock'` — "재고 있음 — {상품} · 현재 N개" 안내.
- `status='low'` — "재고 적음 — 곧 품절 가능" + 입고 권유.
- `status='out_of_stock'` — "품절" + (있다면) `restock_eta` 안내 + 입고 알림 신청 권유 (후속 PR).

## 다중 매칭 (disambiguation)

상품명 substring 으로 여러 건 매칭되면 `candidates` 리스트가 반환된다. 답변 LLM 이 후보 echo 하면서 사용자에게 SKU 또는 정확한 상품명을 다시 묻는다.

## 절대 금지

- 재고 수량 변경/입고/출고 도구 호출 X (이번 PR 카탈로그에 존재하지 않음).
- tenant_id 자동 주입 — 사용자에게 묻지 않는다.
