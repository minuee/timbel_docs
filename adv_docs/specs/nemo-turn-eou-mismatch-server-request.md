# NeMo ASR turn detector — `ending` / `eou` 불일치 사례 보고

---

## 1. 요청 요약

가이드대로 client 측 turn merge 로직을 구현했으나, 실제 운영 로그에서 **`ending`과 `eou`가 모순되는 케이스**가 빈번하게 발생합니다.

구체적으로:

- `ending = "incomplete"` 또는 `ending = "transformative"` 인데
- `eou >= 0.95` (또는 `eou = 1.0`) 으로 함께 내려오는 경우

가이드 §3.1의 미완 판정 조건은 `ending in (connective, transformative, incomplete) AND eou < 0.8` 입니다. 즉 위 케이스는 client에서 **분리 표시** 됩니다 — 그러나 의미적으로는 다음 turn과 합쳐져야 하는 발화입니다.

**요청 사항**: turn detector가 `incomplete` / `transformative` ending을 부여하는 경우, `eou` 값도 0.8 미만으로 함께 내려주실 수 있는지 검토 부탁드립니다. (또는 가이드 임계값을 조정할 근거 제공 부탁드립니다.)

---

## 2. client 측 구현 확인

`asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts`:

```typescript
const isIncompleteTurn = (turn) => {
  if (!turn) return false;
  const ending = turn.ending ?? "final";
  const eou = turn.eou ?? 1.0;
  return ["connective", "transformative", "incomplete"].includes(ending) && eou < 0.8;
};
```

- `TURN_MERGE_TIMEOUT_MS = 2000`
- `MAX_MERGE_CHAIN = 5`
- 짧은 interjection(≤2자) 분리 처리 포함
- speaker별 buffer 독립 관리

→ **가이드 명세 그대로 구현됨**. client 로직 자체에는 문제 없음.

---

## 3. 정상 동작 케이스 (가이드대로 병합됨)

### Call A — turn 27→28→29 (consultant 발화)

| turn | ending | eou | text |
|---|---|---|---|
| 27 | `connective` | **0.5** | "대출금리로 신용등급에 동의를 하게" |
| 28 | `incomplete` | **0.5** | "1위부터 7회의 0% 8월부터 14일 7.75%" |
| 29 | `final` | 0.95 | "15일부터 29일은 8.1%입니다" |

✅ 27,28의 eou가 0.5라 미완 판정 정상 동작 → 27+28+29 한 버블로 표시됨.

### Call A — turn 1 시작 ~ 25 (대부분 `final`)

이 구간은 모든 turn이 `final eou=0.95` → 별도 병합 없이 1:1 표시. 정상.

### Call B — turn 28→29

| turn | ending | eou | text |
|---|---|---|---|
| 28 | `incomplete` | **0.5** | "주식 매도에 대한 정보는" |
| 29 | `final` | 0.95 | "별도로 잠시만요 잠시만 기다려 주세요" |

✅ 정상 병합.

---

## 4. **문제 케이스: ending과 eou 모순** ⚠️

다음은 **`ending`이 미완 카테고리(incomplete/transformative)**인데 **`eou >= 0.8`** 로 내려와서 client가 미완으로 판정하지 못한 사례입니다. **의미적으로는 다음 turn과 합쳐져야 합니다.**

### Call A (1차 통화)

#### ① turn 14 — `incomplete` eou=**0.95**
```
[nlp:complete] turn=14 ending=incomplete eou=0.95
  "맞죠 아 엔진이 부인이 신용 운전이 최고 대용융자는 공기 연장 조건을
   충족할 경우 60일 단위로 연장이 가능합니다 연장"
[nlp:complete] turn=15 ending=final eou=0.95
  "만기 30일 전부터 만 오일 영업일 오후 4시까지 고객센터 유선 신청 또는
   온라인으로 진행하는 해야 하며 만기일까지 선환되지 않으면 이 일에 자동
   매 반대 매매가 처리됩니다"
```
👉 14의 텍스트가 "...연장"으로 끊긴 후 15에서 연장 신청 방법 이어짐. **합쳐져야 함**. 현재 분리 표시.

#### ② turn 18 — `transformative` eou=**1.0**
```
[nlp:complete] turn=18 ending=transformative eou=1
  "현금상환 오후에 8시부터 오후 5시에 프레온 HTS 온라인 지점 신한대출 및
   0851 현금 상환 또는 모바일은 모바일 업무에 또 다른 대출 현금 상환을
   통해 처리할 수 있습니다 네 더 궁금하신"
[nlp:complete] turn=19 ending=final eou=0.95
  "이상 있으실까요"
```
👉 "더 궁금하신" + "이상 있으실까요" = "더 궁금하신 이상 있으실까요"(=사항 있으실까요). **합쳐져야 함**.

#### ③ turn 39 — `incomplete` eou=**0.95**
```
[nlp:complete] turn=39 ending=incomplete eou=0.95
  "2000원 2주 충전 금액 다 취소하고 NST 매매 수수료는 KRX 매매 수수료보다는
   유관 기관 수수료가 들어가면 시이알이 조금 보관 수수료는 0.00763% 네 기"
[nlp:complete] turn=40 ending=final eou=0.95
  "기관 기관 수수료는 페이퍼 주문 시 0.00185% 중문 시 0.00134%입니다"
```
👉 "네 기" + "기관 기관 수수료는..." 명백한 미완. **합쳐져야 함**.

#### ④ turn 44 — `incomplete` eou=**0.95**
```
[nlp:complete] turn=44 ending=incomplete eou=0.95
  "모바일에서는 모바일 업무는 기타 정보 관리 디지털 위탁 증거금 변경 푸련
   HTS에서는 온라인 지점 고객정보 곰팡이 삼팔 기능 중국인 변경 신청이 있고요
   홈페이지"
[nlp:complete] turn=45 ending=final eou=0.95
  "에서는 트레이딩 주문들 체결 주식계좌 정보 변경 적용 등록을 변경 신청해
   있습니다"
```
👉 "홈페이지" + "에서는 트레이딩..." → "홈페이지에서는 트레이딩...". **합쳐져야 함**.

---

### Call B (2차 통화)

#### ⑤ turn 8 — `incomplete` eou=**0.95**
```
[nlp:complete] turn=8 ending=incomplete eou=0.95
  "네 그 네 고객님 크레온 HTS를 통한 정보 증명서 발급은 수수료 발생하지
   않습니다 아마"
[nlp:complete] turn=9 ending=final eou=0.95
  "고객센터 유성표는 대신증권 시에만 수수리천 원이 부과됩니다"
```
👉 "...아마" + "고객센터..." 한 답변. **합쳐져야 함**.

#### ⑥ turn 12 — `incomplete` eou=**0.95**
```
[nlp:complete] turn=12 ending=incomplete eou=0.95
  "아이가 생각보다 괜찮네요 너 십"
[nlp:complete] turn=13 ending=final eou=1
  "지나고 나서도 더 들고 있으면 만기 연장도 되나요"
```
👉 "너 십" + "지나고..." = "10일 지나고 나서도...". **합쳐져야 함**.

#### ⑦ turn 24 — `connective` eou=**0.95**
```
[nlp:complete] turn=24 ending=connective eou=0.95
  "해당 부위를 가지려면 해당 주식을 결제 기준으로 배당 기준에 다시 재식을
   보유하시면 됩니다 예를 들어"
[nlp:complete] turn=25 ending=final eou=0.95
  "배당 비즈니비 12월 31일이면 12월 31일인데 결제 기준으로 해당 표시에
   대한 주주에게 해당 권리가 주어집니다"
```
👉 "예를 들어" + "12월 31일이면..." 명백한 미완. **합쳐져야 함**.

#### ⑧ turn 31, 32 — `incomplete` eou=**0.95**
```
[nlp:complete] turn=31 ending=incomplete eou=0.95
  "주식 시간의 종가 주문 종가로 주식 매매를 하는 채소로 장계 시간 시 전
   시간 외 종가와 장 종로 후 시간 외 종가 중에 있습니다 장"
[nlp:complete] turn=32 ending=incomplete eou=0.95
  "진단 시간을 좀 가는 오전 8시 30분 남겨 6시 40분 후에 전일 종가로
   청결됩니다 강"
[nlp:complete] turn=33 ending=transformative eou=0.55
  "어려운 시간을 보니까 오후 3시 40분부터 4시 도구 4시까지의 강의평가로
   정해져 있는"
```
👉 30~33이 한 답변(종가 주문 시간 설명)인데 31,32만 eou=0.95라 분리됨. 33은 eou=0.55라 다음 turn과만 합쳐짐.

#### ⑨ turn 52 — `incomplete` eou=**0.95**
```
[nlp:complete] turn=52 ending=incomplete eou=0.95
  "직무관 변경 신청되면은 크레온 모바일에서는 모바일 업무 계좌 정보 관리
   주식 위탁 본체 좀 준비하고 있습니다 해외 은행 HTS에서는 온라인 계정
   고객 정보 08398 적용 작업은 변경 신청이 됩니다 홈페이지"
[nlp:complete] turn=53 ending=final eou=0.95
  "트레이딩 주문 세결 주식 계좌 정보 변경 김경 신청해 주 다른 수수료나
   연체자 등으로는 은행 기술과 발생할 수 있으니 유의하시기 바랍니다"
```
👉 "홈페이지" + "트레이딩..." → "홈페이지 트레이딩..." (실제 메뉴 경로 설명). **합쳐져야 함**.

#### ⑩ turn 75 — `incomplete` eou=**0.95**
```
[nlp:complete] turn=75 ending=incomplete eou=0.95
  "인터넷 주식 거래는 현지 통화로 기준으로 하므로 한전이 필요하면 이득
   주식 워낙 중문 서비스를 이용할 경우 직접 환전하지 않아도 됩니다 현장판은"
[nlp:complete] turn=77 ending=final eou=0.95
  "시간은 이번 달러가 오전 9시부터 2일 오후 2시까지 좀 기타 통화는 9시부터
   5분 2시까지입니다"
```
👉 "현장판은" + "시간은..." → "현장판은 시간은...". **합쳐져야 함**.

---

## 5. 패턴 요약

문제 케이스의 공통 패턴:

1. **마지막 토큰이 명사/조사로 끝남** ("홈페이지", "현장판은", "예를 들어", "기")
2. 그러나 `eou`는 0.95 이상으로 매우 높게 평가됨
3. ending은 정확히 `incomplete` / `transformative` 로 마킹됨

즉, **ending 분류는 정확한데 EOU 점수가 의미와 어긋남**.

### 통계 (이 두 통화 합산)

| 패턴 | 건수 |
|---|---|
| ending=incomplete & eou≥0.8 (이상치) | 9건 |
| ending=transformative & eou≥0.8 (이상치) | 1건 |
| ending=connective & eou≥0.8 (이상치) | 1건 |
| 정상 (ending=미완 & eou<0.8) | 4건 |

**비정상 케이스가 정상의 약 2.7배**. 운영 환경에서 미완 turn의 다수가 client merge에서 누락되고 있습니다.

---

## 6. 검토 요청

다음 중 어느 쪽이 가능한지 의견 부탁드립니다:

### (A) 서버 측 turn detector 보정 — 권장
- `ending = incomplete | transformative` 이면 `eou < 0.8` 보장
- 또는 두 카테고리에 대해 eou 계산 로직을 분리해서 더 보수적으로 평가

### (B) 가이드 임계값 조정
- 가이드 §3.1을 다음과 같이 변경:
  - `ending in (incomplete, transformative)` → eou 무시, 무조건 미완 취급
  - `ending = connective` → 기존대로 `eou < 0.8` 적용
- 이 경우 false positive(합치면 안 되는데 합쳐지는 케이스) 가능성 분석 필요

### (C) 다른 안

서버 측에서 검토 가능한 안이 있다면 공유 부탁드립니다.

---

## 7. client 측 임시 우회 적용 (2026-05-11)

서버 측 turn detector 보정 검토가 진행되는 동안 client 측에서 가이드 §3.1 조건을 임시로 완화했습니다.

**변경 전**:
```ts
return ["connective", "transformative", "incomplete"].includes(ending) && eou < 0.8;
```

**변경 후**:
```ts
return ["connective", "transformative", "incomplete"].includes(ending);
```

즉 미완 카테고리(`connective` / `transformative` / `incomplete`) ending이면 **`eou` 값과 무관하게 무조건 미완으로 처리**해 다음 turn과 병합합니다.

- 적용 파일: `asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts:88-93`
- 적용 일자: 2026-05-11
- **원복 조건**: 서버 측 ASR turn detector가 미완 카테고리 ending에 대해 `eou < 0.8`을 일관되게 부여하도록 보정되는 시점

### 유지되는 안전망

eou 조건만 풀고 가이드 §3.2의 나머지 안전 규칙은 그대로 유지됩니다:

- 짧은 interjection(≤2자) 분리 규칙 → "네/아/음" 같은 backchannel은 합쳐지지 않음
- `MAX_MERGE_CHAIN = 5` → 최대 5개 미완 turn까지만 chain, 초과 시 강제 flush
- `TURN_MERGE_TIMEOUT_MS = 2000` → 2초 내 다음 turn 없으면 buffer 단독 표시
- speaker별 buffer 독립 → 화자가 바뀌면 자동 분리

### 운영 모니터링 필요

본 보고서에서 식별한 별도 이슈(분류 자체 오류 의심)도 함께 추적 부탁드립니다:

- **turn B-69**: 긴 안내 발화인데 `ending=interjection`으로 분류됨 — interjection 카테고리 분류 정확도 점검 필요
- **turn B-75 ↔ B-76 순서 역전**: 서버 emit 순서 또는 message ordering 검토 필요

서버 측 보정이 완료되면 client 코드를 가이드 §3.1 원안으로 원복할 예정입니다.

---

## 8. 참고 자료

- 전체 로그 원본: `nemo-turn-eou-mismatch-logs-20260511.md` (동일 디렉토리)
- 가이드 문서: `CLIENT_NEMO_TURN_MERGE_GUIDE.md` (2026-05-07)
- client 구현: `asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts:88-93`
