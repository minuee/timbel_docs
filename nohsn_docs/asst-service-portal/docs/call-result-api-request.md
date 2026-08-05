# 통화 결과(완료/이관/콜백/중도종료/실패) 신규 설계

작성: 2026-08-05 / 프론트(asst-web) ↔ 백엔드(asst-service)
관련 화면
- 상담사 통화 이력 : `/advisor-renual/call-history`
- 관리자 통화 이력 : `/advisor-renual/admin/call-history`
- 콜 이력 상세 모달 (수동 수정 입력 지점)

> **LLM 판정은 이번 범위에서 제외한다.**
> `/summary` 호출 시 백엔드가 대화록 발화 유무만 보고 값을 저장하고, 나머지는 상담사가 수정한다.

---

## 1. 배경 — 값도 컬럼도 없음

통화이력 카드 시안에는 `완료 / 이관 / 콜백` 배지가 있으나, **목록·상세 API 어디에도 해당 필드가 없고 DB 컬럼도 없다.**
프론트는 양쪽 화면에서 자리만 잡아둔 상태다.

| 위치 | 현재 상태 |
|---|---|
| 상담사 툴바 `call-history/index.vue:66` | `ECPSelect disabled` / `전체 결과 (미구현)` / options 빈 배열 |
| 상담사 카드 1행 `:95` | `통화결과 · 미구현` 텍스트 |
| 관리자 툴바 `admin/call-history/index.vue:57` | 동일 |
| 관리자 카드 1행 `:94` | 동일 |

인입유형(`direction`)은 컬럼이 이미 있고 값만 안 실리는 상태였으나, 통화 결과는 **컬럼 자체가 없어** 신규 설계가 필요하다.
또한 `direction` 적재는 `raw_call.callstats_call` 담당 영역이라 asst-service 작업이 아니었다 → **본 설계는 그 의존을 피하는 것이 목표**다(§3).

---

## 2. 값 정의 (5종)

| 코드값 | 라벨 | 정의 | 채우는 주체 |
|---|---|---|---|
| `COMPLETE` | 완료 | 상담 목적을 달성하고 정상 종료 | **자동(기본값)** + 수동 |
| `ABORTED` | 중도종료 | 연결은 됐으나 상담 완결 전 끊김 | **자동** + 수동 |
| `TRANSFER` | 이관 | 타 상담사·부서로 넘김 | 상담사 수동 |
| `CALLBACK` | 콜백 | 재통화를 약속하고 종료 | 상담사 수동 |
| `FAILED` | 실패 | **끝까지 진행했으나 문의를 해결하지 못함** | 상담사 수동 |
| `null` | (미지정) | 요약 미실행 / 기능 배포 이전 콜 / 상담사가 비움 | — |

### 2-1. `FAILED` 는 "연결 실패"가 아님

연결 자체가 실패한 콜은 **callstats 에 행이 남지 않아** 통화이력에 뜨지 않는다.
따라서 `FAILED` 를 **"연결·대화는 됐으나 미해결로 끝난 콜"** 로 정의한다(미해결율 지표로 활용 가능).

### 2-2. 자동 판정 규칙

`/summary` 시점에 대화록 턴(`role`, `utterance`)의 **고객 발화 유무만** 본다.

```
고객 발화 턴 수 == 0   →  ABORTED
그 외                  →  COMPLETE
```

- `TRANSFER` / `CALLBACK` / `FAILED` 는 의미 판단이 필요해 자동으로 채우지 않는다 → **상담사가 수정**
- 자동 판정은 항상 둘 중 하나를 반환하므로 **`null` 이 나오지 않는다**
  (`null` 은 요약이 아예 실행되지 않은 콜, 기능 배포 이전 콜, 상담사가 의도적으로 비운 콜에만 남는다)

### 2-3. 값이 겹칠 때 우선순위 (수동 입력 안내용)

```
TRANSFER > CALLBACK > ABORTED > FAILED > COMPLETE
```

예) 해결하지 못해 타 부서로 이관한 콜 → `TRANSFER`.
이관·콜백은 **일어난 사실**이고 완료·실패는 **해석**이므로 사실을 우선한다.

---

## 3. 테이블 — 신규 테이블 (기존 `callstats` 무수정)

`callstats` 컬럼 추가 방식은 **적재 담당 영역(raw_call)** 을 건드려 타 팀 일정에 묶인다.
별도 테이블이면 **asst-service 단독으로 완결**되고, 기존 콜은 행이 없어 `LEFT JOIN` 시 자연히 `null` 이 된다.

```sql
advisor.callstat_call_result
  callstats_id   PK, FK → callstats(id)   -- 예: call_5f6effe6_...
  call_id        (참고용, INDEX)           -- 예: 698592560905
  result_code    NULL 허용
                 COMPLETE | TRANSFER | CALLBACK | ABORTED | FAILED
  source         AUTO | MANUAL
  updated_by     user_key                  -- MANUAL 일 때만
  updated_at
  created_at
  INDEX (result_code)                      -- 목록 필터용
```

`runSchemaMigrations()` 에 멱등 등록.

### 3-1. PK 는 `callstats_id`

`keyword_detect_logs` 가 `call_id`(CTI 계열 숫자)를 키로 잡은 탓에 콜 하나의 감지 내역을 조회할 수 없어,
별도 요청서(`call-history-admin-api-request.md` §2-3)로 `callstats_id` 필터 추가를 요청한 상태다. 같은 문제를 반복하지 않기 위한 결정이다.

1. `/summary` 가 받는 키가 `callstats_id` (프론트가 넘기는 유일한 키)
2. 통화이력 목록 **행의 `id` 가 곧 `callstats_id`** → `LEFT JOIN` 이 바로 붙는다
3. 상세 모달 URL `/callstat/calls/{X}` 의 `{X}` 도 `callstats_id`
4. `call_id` 는 유일성·재사용 보장이 불확실해 PK 로 부적합

`call_id` 는 CTI 대조·디버깅용 참고 컬럼으로 함께 저장한다(`/summary` 시점에 둘 다 있어 비용 없음).

### 3-2. `result_code` 를 nullable 로 두는 이유

"미지정으로 되돌리기"를 **행 삭제**로 처리하면 다음 요약이 `AUTO` 로 행을 되살려 버린다.
따라서 값을 비우는 것은 **행 유지 + `result_code = null`** 로 처리한다.

---

## 4. ⭐ 핵심 규칙 — `source = MANUAL` 이면 자동 갱신 금지

`/summary` 는 자동(통화 종료 후) + 수동(상담사 버튼) 양쪽에서 호출되어 **여러 번 실행될 수 있다.**

| 기존 행 | 재요약 시 |
|---|---|
| 없음 | `AUTO` 로 insert |
| `source = AUTO` | **덮어씀** |
| `source = MANUAL` | **건너뜀** |

### ⚠️ 잠금 판단은 `source` 만 본다 (`result_code` 아님)

```
result_code = null  AND  source = MANUAL   →  "상담사가 의도적으로 비웠다"
```

이 행도 **자동 갱신 대상이 아니다.** `result_code IS NULL` 을 "값 없음 = 채워도 됨"으로 처리하면
상담사가 지운 값을 다음 요약이 되살려, §3-2 에서 nullable 로 만든 의미가 사라진다.

---

## 5. 작업 항목

### 5-1. 테이블 신설
`advisor.callstat_call_result` — `runSchemaMigrations()` 멱등 등록 (§3)

### 5-2. `summarizeCall()` 종료 시 upsert
- §2-2 규칙으로 `result_code` 계산(`ABORTED` 또는 `COMPLETE`) → `source = AUTO` 로 upsert
- 기존 행이 `source = MANUAL` 이면 **스킵** (§4)

### 5-3. `PATCH .../result` — 수동 수정
```
PATCH /aicc/asst-service/callstat/calls/{id}/result
body: { "result_code": "CALLBACK" }   // null 허용 = 미지정으로 되돌리기
→ upsert, source = MANUAL, updated_by = 요청자 user_key
```
- `{id}` 로 **`call_id` 가 들어오는 경우 `callstats_id` 로 정규화** (`/summary` 의 기존 fallback 과 동일 — `summary.service.ts:126`)
- 엔드포인트 경로 형태는 백엔드 컨벤션에 맞춰 조정 가능

### 5-4. 목록 API — `LEFT JOIN` + 필터
`GET /callstat/call-history` (양쪽 화면이 사용)

응답 아이템에 추가:
```jsonc
{
  "id": "call_5f6effe6_...",
  "call_result": "ABORTED",          // 없으면 null
  "call_result_source": "AUTO"       // AUTO | MANUAL | null
}
```

필터 파라미터:

| 파라미터 | 값 | 비고 |
|---|---|---|
| `call_result` | `COMPLETE`/`TRANSFER`/`CALLBACK`/`ABORTED`/`FAILED` | 미지정 = 전체 |

---

## 6. 권한 — 1차는 관리자도 조회만

관리자 통화이력에서는 **표시·필터만 하고 수정은 제공하지 않는다.**

- 상담사가 본인 콜을 고칠 수 있어 당장 막히는 시나리오가 없다
- `updated_by` 컬럼을 1차에 넣어두므로 나중에 붙이는 비용은 늘지 않는다

→ **`PATCH` 는 본인 콜만 허용**으로 시작. 정책은 백엔드 의견에 맞춘다.

---

## 7. 프론트 작업 (스펙 확정 후)

- 카드 배지 — 5종 라벨·색상, `null` 은 `-`
- `call_result_source` 로 표기 구분: `AUTO` = 점선·연한색 / `MANUAL` = 실선
- 툴바 "전체 결과" 셀렉트 활성화 (양쪽 화면)
- 콜 이력 상세 모달에 수정 UI + `PATCH` 연동
- 관리자 화면은 표시·필터만

---

## 8. 남은 확인

- [ ] 테이블·컬럼명 사내 컨벤션 확인
- [ ] `PATCH` 엔드포인트 경로 형태
- [ ] **기존 콜 소급 처리** — 배포 이전 콜을 배치로 채울지, `null` 로 둘지
- [ ] `PATCH` 권한 정책 (본인 콜만 / 관리자 허용)
