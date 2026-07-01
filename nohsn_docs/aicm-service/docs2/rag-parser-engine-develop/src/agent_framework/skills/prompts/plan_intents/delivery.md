# 카테고리: delivery (배송 추적 — 추상 layer)

본 카테고리는 **송장 기반 배송 조회** 만 다룬다. 실 carrier API (스마트택배/CJ대한통운/한진/우체국) 호출은 후속 PR.

## 배송 조회

```
[{1, tool, delivery.track, {
   tracking_number: "<송장번호 — 공백·하이픈 그대로 OK, 도구가 정규화>",
   carrier: "<택배사 코드, 발화 명시 시 (cj/hanjin/lotte/koreapost/sweettracker)>",
   tenant_id: "$personal_tenant_id"
 }}]
```

송장번호 없이 호출 X — 발화에 송장번호가 없으면 ask_user_clarify "송장번호를 알려 주세요." 되묻기.

## 응답 패턴

- `status='pending'` — "배송 준비 중".
- `status='picked_up'` — "택배사 인수 완료".
- `status='in_transit'` — "운송 중" + (있다면) ETA 안내.
- `status='out_for_delivery'` — "배송 출발 — 곧 도착 예정".
- `status='delivered'` — "배송 완료".
- `status='failed'` — "배송 실패 — 재발송 또는 문의 필요".
- `status='unknown'` — 내부 캐시 미스. 후속 PR 의 carrier webhook 활성화 시 외부 조회로 보강된다고 안내.

## 다중 매칭

동일 송장번호가 여러 carrier 에 등록된 경우 (드물게 발생), 도구는 `last_updated` 가 가장 최근인 row 를 우선 반환한다. carrier 가 발화에 명시되어 있으면 그 carrier 만 매칭.

## 절대 금지

- 배송 status 수정 도구 호출 X.
- carrier API 외부 호출 X (이번 PR 추상 layer 범위).
