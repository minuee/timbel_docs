# 통화 이력 API 확장 요청 (관리자 org-wide + 감지어 건수)

작성: 2026-08-05 / 프론트(asst-web) → 백엔드(asst-service)
관련 화면
- 상담사 통화 이력 : `/advisor-renual/call-history`
- 관리자 통화 이력 : `/advisor-renual/admin/call-history`  ← 이번 요청의 주 대상

---

## 0. 배경 — 왜 두 화면이 다르게 보이는가

같은 "통화 이력" 화면인데 **호출하는 API가 달라서** 관리자 화면에만 값이 비어 있다.

| 항목 | 상담사 화면 `GET /callstat/call-history` | 관리자 화면 `GET /callstat/calls` |
|---|---|---|
| 조회 범위 | `agent_id` **필수** → 본인 콜만 | org-wide (agent_id 선택) |
| 요약 `summary` | ✅ | ❌ |
| 주요 의도 `customer_inquiry`/`intent` | ✅ | ❌ |
| **상담유형 `external_categories[]`** | ✅ | ❌ |
| 키워드 `keywords[]` | ✅ | ❌ |
| **감정 `voc.emotion`** | ✅ | ❌ |
| 정렬 `sort_order` | ❌ | ✅ |
| 상담사 이름 | 불필요(본인) | ❌ (프론트가 상담사 목록 API로 별도 조인 중) |

관리자 화면 코드에는 이미 상담유형 표시 자리가 있으나(`item.category_path`), **응답에 해당 필드가 없어 항상 `-`** 로 나온다.

---

## 1. 요청 A — `GET /callstat/call-history` 를 org-wide 로 확장  ⭐ 우선순위 1

관리자 화면을 이 API로 갈아타게 해주면 **상담유형·감정·키워드·의도가 한 번에 해결**된다.
(`/callstat/calls` 응답을 늘리는 방식은 두 화면이 계속 다른 스키마를 쓰게 되어 비채택)

### 1-1. 요청 파라미터

| 파라미터 | 현재 | 요청 |
|---|---|---|
| `agent_id` | **필수** | **선택** 으로 완화. 미지정 = 전체 상담사 |
| `sort_order` | 없음 | `desc`(기본, 최신) / `asc` 추가 — 현재 `/callstat/calls` 와 동일 규격 |
| `center_id` / `team_id` / `part_id` | 없음 | (선택) 조직 필터. `/callstat/calls` 에 이미 있는 파라미터와 동일 규격이면 됨 |
| `start_date` / `end_date` / `page` / `limit` / `phone_number` / `keyword` / `customer_name` | 있음 | 그대로 |

> ⚠️ 권한: `agent_id` 미지정 호출은 **관리자 권한(SYSTEM/ADMIN/SUPERVISOR/MANAGER)** 에서만 허용해주세요.
> 상담사 토큰으로 생략 호출 시 본인 콜로 강제하거나 403 중 어느 쪽이든 **정책만 명확히** 주시면 프론트가 맞춥니다.

### 1-2. 응답 항목 추가

기존 `CallHistoryListItem` 에 아래 2개만 추가:

```jsonc
{
  "id": "call_5f6effe6_...",
  "call_id": "698592560905",
  "agent_id": "ecp-4",

  // ▼ 추가 요청
  "agent_name": "홍길동",        // 상담사 표시명
  "agent_cti_id": "56356659",    // (선택) 조인 보조용

  // ▼ 기존 그대로
  "consumer_name": "...",
  "consumer_phonenumber": "010...",
  "started_at": "...", "ended_at": "...", "duration_ms": 123456,
  "summary": "...",
  "customer_inquiry": "...", "intent": null,
  "external_categories": ["요금>납부"],
  "keywords": ["환불", "연체"],
  "voc": { "emotion": { "type": "angry", "score": 0.82, "summary": "..." },
           "complaintRisk": {...}, "churnRisk": {...} },
  "direction": null
}
```

**`agent_name` 이 필요한 이유**: 지금 관리자 화면은 `GET /agents/assignable` 로 상담사 목록을 따로 받아
`agent_id ↔ cc_cti_id` 로 이름을 조인한다. 그런데 실데이터에 **cc_cti_id 가 중복(agent40·agent41=56356659)
되거나 비어 있는 계정**이 있어 이름이 "알 수 없음"으로 빠지는 콜이 생긴다. 응답에 이름이 실리면 이 조인 자체가 사라진다.

### 1-3. 프론트 영향

- 관리자 화면이 `/callstat/calls` → `/callstat/call-history` 로 전환
- 상담사 화면과 카드 렌더 로직 공용화 (상담유형·키워드·의도·감정 표시가 동일 코드)
- 상담사 목록 조인 제거

---

## 2. 요청 B — 콜별 감지어 건수  ⭐ 우선순위 2 (상담사·관리자 **양쪽 공통**)

현재 두 화면 모두 감지어 자리에 `감지어 · 미구현` 으로 표기 중이다.
**콜 단위로 감지 건수를 집계할 수단이 아예 없다.**

### 2-1. 1안 (권장) — 통화 이력 응답에 포함

```jsonc
{
  "id": "call_5f6effe6_...",
  "detect_count": 3,
  "detects": [
    { "type": "forbiddenWord", "count": 1 },
    { "type": "issueWord",     "count": 2 }
  ]
}
```

- 목록 1회 호출로 끝나 추가 왕복이 없음
- `type` 값은 기존 `/keyword-detect-logs` 와 동일 (`forbiddenWord` / `profanityWord` / `issueWord`)

### 2-2. 2안 — 벌크 집계 엔드포인트 신설

```
GET /keyword-detect-logs/counts?callstats_ids=call_a,call_b,call_c
→ [ { "callstats_id": "call_a", "count": 3,
      "byType": [ { "type": "forbiddenWord", "count": 1 } ] } ]
```

목록 한 페이지(20건) 로드 후 1회 호출. 1안이 어려울 때의 대안.

### 2-3. 부수 요청 — `GET /keyword-detect-logs` 에 `callstats_id` 필터 추가

현재 이력 조회는 `call_id`(CTI 계열 숫자, 예 `698592560905`)로만 좁힐 수 있다.
화면이 다루는 키는 콜통계 행 id(`call_5f6effe6_...`)라서 **특정 통화의 감지 내역을 직접 조회할 수 없다.**
상세 모달에서 "이 통화에서 걸린 감지어" 를 보여주려면 이 필터가 필요하다.

---

## 3. 참고 — 이미 알고 있는 미적재 필드 (이번 요청 아님)

아래는 응답에 필드는 있으나 값이 항상 `null` 이라 화면에 `· 미구현` 으로 표기 중.
적재 계획이 잡히면 별도로 알려주세요.

| 필드 | 화면 표기 | 현재 |
|---|---|---|
| `direction` | 인입유형 I/B · O/B | 항상 null (콜 적재 시 미기록) |
| 통화 결과(완료·이관·콜백) | 통화결과 | 응답 필드 자체 없음 |
| `intent` | 주요 의도 폴백 | 항상 null (`customer_inquiry` 로 대체 표시 중) |

---

## 4. 요약 (백엔드 체크리스트)

- [ ] `GET /callstat/call-history` — `agent_id` 필수 → 선택
- [ ] `GET /callstat/call-history` — `sort_order` 지원
- [ ] `GET /callstat/call-history` — 응답에 `agent_name` (+ 가능하면 `agent_cti_id`)
- [ ] (선택) `GET /callstat/call-history` — `center_id`/`team_id`/`part_id` 필터
- [ ] `agent_id` 미지정 호출의 권한 정책 확정
- [ ] 콜별 감지어 건수 — 1안(응답 포함) 또는 2안(벌크 집계) 중 택1
- [ ] `GET /keyword-detect-logs` — `callstats_id` 필터 추가
