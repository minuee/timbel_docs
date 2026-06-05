# NeMo ASR Turn EOU 불일치 — 서버 팀 검토 요청

> **TL;DR** — 서버가 `ending=incomplete/transformative/connective` (미완 신호)와 `eou ≥ 0.8` (완결 신호)을 **동시에** 보내는 모순 케이스가 빈번합니다. 가이드 §3.1 조건이 동작하지 못해, mid-word/조사 단위로 끊긴 발화가 별도 메시지로 분리 표시됩니다.

| | |
|---|---|
| **Date** | 2026-05-11 |
| **From** | client (asst-web) |
| **To** | NeMo ASR / turn detector 서버 팀 |
| **첨부** | [원본 로그](./turn-eou-mismatch-raw-log.md) · [가이드](./CLIENT_NEMO_TURN_MERGE_GUIDE.md) |
| **샘플** | Call 1 (47 turn) + Call 2 (77 turn) = 총 124 turn |

---

## 1. 문제 한 줄

`ending` 분류기와 `eou` 추정기가 서로 모순된 값을 동시에 송신합니다.

```
가이드 §3.1:  ending ∈ {connective, transformative, incomplete}  AND  eou < 0.8  →  미완
관측:        ending = incomplete       AND  eou = 0.95
            ending = transformative   AND  eou = 1.0
```

`ending`은 "이 발화 안 끝났다"고 말하고, `eou`는 "끝났다 신뢰도 95%"라고 말합니다.

---

## 2. 영향 (정량)

| 카테고리 | 전체 turn | eou < 0.8 (정상 미완) | **eou ≥ 0.8 (모순)** |
|---|---:|---:|---:|
| `incomplete` | 11 | 3 | **8** |
| `transformative` | 3 | 2 | **1** |
| `connective` | 5 | 4 | **1** |
| **합계** | **19** | 9 | **10 (53%)** |

> **미완 ending의 절반 이상이 `eou ≥ 0.8` 모순 케이스.** 가이드가 의도대로 동작하지 못합니다.

---

## 3. 핵심 증거 — mid-word / 조사 split

단어 중간 또는 조사에서 끊긴 명백한 미완 케이스. `eou ≥ 0.8` 책정이 부적절하다는 가장 강한 증거입니다.

| # | Call | turn | payload | 끊긴 꼬리 | 다음 turn 시작 | 합쳤을 때 의미 |
|---|:---:|:---:|---|---|---|---|
| 1 | 1 | 39 | `incomplete eou=0.95` | `…네 기` | `기관 수수료는…` | `네 기관 / 기관 수수료는` (mid-word 반복) |
| 2 | 1 | 44 | `incomplete eou=0.95` | `…홈페이지` | `에서는 트레이딩…` | `홈페이지에서는` (조사 split) |
| 3 | 2 | 12 | `incomplete eou=0.95` | `…너 십` | `지나고 나서도…` | `십일 지나고 나서도` (mid-word) |
| 4 | 2 | 52 | `incomplete eou=0.95` | `…홈페이지` | `트레이딩 주문…` | `홈페이지에서는…` (조사 split) |
| 5 | 2 | 75 | `incomplete eou=0.95` | `…현장판은` | `시간은 이번 달러가…` | 조사 `-은`으로 끊김 |
| 6 | 1 | 14 | `incomplete eou=0.95` | `…연장` | `만기 30일 전부터…` | 연장 신청 안내가 둘로 쪼개짐 |
| 7 | 1 | 18 | `transformative eou=1.0` | `…더 궁금하신` | `이상 있으실까요` | `더 궁금하신 이상 있으실까요` |
| 8 | 2 | 24 | `connective eou=0.95` | `…예를 들어` | `배당 ... 12월 31일이면` | `예를 들어 배당…` |
| 9 | 2 | 8 | `incomplete eou=0.95` | `…아마` | `고객센터 유성표는…` | 부사 끊김 |
| 10 | 2 | 31 | `incomplete eou=0.95` | `…있습니다 장` | `진단 시간을…` | `장 진단` 또는 `장중` |

> **3, 1, 2번**(`…너 십 / 지나고`, `…네 기 / 기관`, `…홈페이지 / 에서는`)이 가장 강한 증거 — 단어 한가운데서 EOU=0.95가 책정됨.

---

## 4. 부수 이슈

### 4.1 긴 본문에 `ending=interjection`

가이드 §3.2는 `interjection`을 짧은 backchannel("네/예/응")로 전제하지만, **130자 절차 설명 본문**에 `interjection`이 붙어 있음.

> **Call 2, turn 69** — `ending=interjection eou=0.95`
> `"신한 계좌 설정 밑에 있는 PC TTS 홈페이지 크레온 모바일에서 각각 가능하신데 신용대출은 신용대출 약정샵 중도사의 신용약정 등록 해지되었고 ..."`

### 4.2 완결 의문문에 `ending=incomplete`

한국어 의문 종결어미(`-나요`, `-까요`)로 끝나는 **완결 질문**에 `incomplete` 부여. 가이드대로 처리하면 다음 turn(별개 질문)과 잘못 병합됨.

> **Call 1, turn 37** — `ending=incomplete eou=0.5`
> `"현재 크레온에서 거래할 수 있는 구간은 어디인가요"` ← 완결된 질문임

### 4.3 turn 순서 역전 (별개 이슈)

Call 2에서 도착 순서가 `... 74 → 76 → 75 → 77 ...`로 역전. `turn_idx` 단조 증가가 깨짐 — transport ordering / worker race 의심.

---

## 5. 검토 옵션

| 안 | 변경 위치 | 변경 내용 | 장점 | 단점 |
|---|---|---|---|---|
| **A** | EOU 추정기 | ending이 미완 계열이면 EOU 가중치 보정 → `eou < 0.8` 보장 | 두 신호 정합성 회복 (근본 해결) | 모델 재학습 비용 |
| **B** | Ending 분류기 | EOU 높으면 `ending = final`로 보정 | 단순 | mid-word split이 final로 보여 client가 발견 불가 |
| **C** | Client 가이드 | `incomplete/transformative`는 EOU 무시하고 무조건 미완 | client 단독 변경 가능 | EOU 신호 의미 변질, 가이드 개정 필요 |
| **D** | Ending 분류기 | 한국어 종결어미(`-나요`, `-까요`, `-입니다` 등)로 끝나면 final로 보정 | §4.2 해결 | §3 mid-word split은 미해결 |

> **client 측 권장**: **A + D 조합** — EOU 추정기 보정으로 근본 원인 해결 + 종결어미 휴리스틱으로 §4.2 보완.

---

## 부록 — 환경

- **Client 구현**: [`useChatMessageParser.ts:88-93`](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts#L88-L93)

  ```ts
  const isIncompleteTurn = (turn) => {
    const ending = turn.ending ?? "final";
    const eou = turn.eou ?? 1.0;
    return ["connective", "transformative", "incomplete"].includes(ending) && eou < 0.8;
  };
  ```

- **Client 설정**: `TURN_MERGE_TIMEOUT_MS = 2000`, `MAX_MERGE_CHAIN = 5`
- **채널**: `dev:4609686:56356659:call:nlp:complete`
- **에이전트**: `56356659`
- **원본 로그**: [`turn-eou-mismatch-raw-log.md`](./turn-eou-mismatch-raw-log.md)
