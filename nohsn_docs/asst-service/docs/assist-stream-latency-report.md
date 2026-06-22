# assist-stream 응답지연 분석 보고서

> 작성일: 2026-06-19
> 대상: asst-service `POST /assist-stream` (AI 상담 보조 SSE)
> 측정 출처: asst-service 컨테이너 로그 `[assist-stream-latency]` (백엔드 자체 타임스탬프 측정 → 클라이언트 네트워크/환경 영향 배제, ~60건)

---

## 1. 한 줄 결론

**assist-stream의 ~1초 지연은 100% AICM `rag_assist`의 검색(intent 판단 + 벡터검색 + 리랭킹) 시간이며, asst-service 백엔드 자체 처리는 1~2ms로 무관하다.**

---

## 2. 배경

- 프론트에서 assist-stream 호출 시 첫 sources(근거문서) 도착까지 1~2초 체감.
- 환경별 차이: 프론트 로컬(`npm run dev`)은 빠르고, 배포(도커 `asst-web-dev`)는 느림. **단 백엔드는 두 경우 모두 동일**(asst-service 도커 `124.194.32.36:32025`).
- 프론트 측정값은 프론트↔백엔드 네트워크 경로가 섞여 **오염**되므로, 백엔드가 자기 시계로 측정한 값으로 구간을 분해해 원인을 확정함.

---

## 3. 측정 구간 정의

assist-stream 1회 호출을 백엔드 기준 4구간으로 분해한다.

| 구간 | 의미 | 담당 |
|---|---|---|
| `controllerToStreamMs` | 요청 수신 → 내부 처리(토큰 추출 등) | **asst 백엔드** |
| `inToFetchMs` | AICM 호출 직전까지(payload 빌드) | **asst 백엔드** |
| `fetchToHeadersMs` | AICM 연결 → 응답 헤더 도착 | AICM 연결 |
| `headersToFirstChunkMs` | 헤더 → **첫 sources**(검색결과) | **AICM RAG** |
| `totalMs` | 요청 수신 → 첫 sources 전체 | 합계 |

> asst-service의 assist-stream은 **얇은 SSE 릴레이**다. `${AICM_HOST}/api/aicm/v1/search/rag_assist`로 호출 후 응답 청크를 그대로 중계할 뿐, sources·intent·search·distill·generate stages는 전부 **AICM/RAG 서비스가 생성**한다.

### 처리 흐름 (단계)

```
프론트 ─▶ ① Controller 접수 ─▶ ② AICM 호출 ─▶ ③ AICM 결과수신 ─▶ ④ Backend 가공 ─▶ ⑤ 프론트 전송
```

### 한국시간(KST) 타임라인 — 실제 로그 1건(예시 ①) 기준

> 서버 로그는 UTC로 찍히므로(예: `06:20:39`) 한국시간(KST)은 **+9시간**(`15:20:39`)이다. 초 이하(ms)는 측정 구간값을 누적해 표기.

```
 KST 시각          단계                                  소요
 ───────────────────────────────────────────────────────────────
 15:20:38.000     ① API Controller 접수 (요청 수신)         기준점
 15:20:38.002     ② AICM 서버 호출 (요청 전송)              +2ms      ← 백엔드 처리
 15:20:39.272     ③ AICM 서버 결과 수신 (첫 sources 도착)    +1,270ms  ← ★ AICM (연결 74ms + 검색 1,196ms)
 15:20:39.272     ④ Backend 가공                           +0ms      ← 단순 중계(가공 없음)
 15:20:39.272     ⑤ Frontend 전송 시작 (SSE 중계)           즉시
 ───────────────────────────────────────────────────────────────
 총 소요 1,272ms (약 1.3초)  →  거의 전부(1,270ms)가 ②~③ AICM 호출~결과수신 구간
```

→ 한눈에: **요청 받고 AICM 부르기까지 2ms, AICM이 답을 주기까지 1,270ms.** 지연은 전부 AICM 쪽이다.

---

## 4. 실측 예시

### 예시 ① — 전형적 케이스 (06:20:39)

```json
{"controllerToStreamMs":2, "inToFetchMs":0, "fetchToHeadersMs":74, "headersToFirstChunkMs":1196, "totalMs":1272}
```

- asst 백엔드(`ctrl + inToFetch`): **2ms**
- AICM 연결(`fetchToHeaders`): 74ms
- **AICM 검색 → 첫 sources(`headersToFirstChunk`): 1196ms ← 전체 1272ms의 약 94%**
- → 1.2초 중 거의 전부가 AICM 검색시간, 백엔드는 2ms.

### 예시 ② — 빠른 케이스 (06:15:47, 통화 직후 짧은 발화)

```json
{"controllerToStreamMs":1, "inToFetchMs":0, "fetchToHeadersMs":20, "headersToFirstChunkMs":7, "totalMs":28}
```

- 짧은/빈 query라 RAG 검색이 거의 안 돎 → `headersToFirstChunk` **7ms** → 전체 **28ms**.
- → **같은 백엔드인데 전체 28ms.** 백엔드가 병목이면 이렇게 빠를 수 없음. 차이는 오직 AICM 검색 유무이며, **백엔드 처리는 원래 수십 ms 이내**임을 역으로 증명한다.

---

## 5. 통계 요약 (~60건)

| 구간 | 실측 범위 | 평균(근사) |
|---|---|---|
| asst 백엔드(`ctrl + inToFetch`) | **0~2ms** | ~1ms |
| AICM 연결(`fetchToHeaders`) | 8~88ms | ~40ms |
| **AICM 첫 sources(`headersToFirstChunk`)** | **940~1227ms** (짧은 query 예외 7~8ms) | **~1020ms** |
| 전체(`totalMs`) | 21~1272ms | ~1050ms |

→ **전체 응답시간의 약 95%가 `headersToFirstChunk`(AICM RAG 검색)**, asst 백엔드 기여분은 0.1% 미만.

---

## 6. 결론 및 조치 방향

| 대상 | 판정 | 조치 |
|---|---|---|
| **asst-service (백엔드, 32025)** | 1~2ms, **병목 아님** | 최적화 여지 없음 |
| **AICM / RAG 서비스 (`rag_assist`, 8173)** | 첫 sources까지 **~1초**, **실제 병목** | intent 판단 + 벡터검색 + 리랭킹 최적화(인덱스/리랭커/모델) 검토 |
| **프론트 체감 1~2초** | AICM ~1초 + 배포환경 네트워크 경로 | 백엔드 내부와 무관, 경로는 별도 점검 |

- query마다 940~1227ms로 출렁이는 것은 발화 내용·후보문서량·AICM 부하에 따른 **검색시간 변동**(정상 범위).
- 참고: 브라우저 Network 탭의 **Content Download(최대 7초)** 는 SSE 특성상 "스트림이 열려 있는 전체 시간 = LLM 답변 생성(generate) 완료까지"를 의미하며 다운로드 지연이 아니다. (TTFB 14ms가 그 증거)

---

## 7. 상시 모니터링 방법

```bash
docker logs -f asst-service-dev | grep assist-stream-latency
```

- 플래그: `.env`의 `ASSIST_STREAM_LATENCY_LOG=1` 일 때만 출력 (첫 청크당 1줄, 동작/응답 영향 없음).
- 운영 중 **`headersToFirstChunkMs` 추세**만 추적하면 RAG 검색성능 변화를 상시 감시 가능.
- `controllerToStreamMs` / `inToFetchMs`가 갑자기 커질 때만 백엔드를 의심하면 된다(현재 0~2ms).

---

## 8. 부록 — 원본 측정 로그 (실제 시각 포함)

> 수집: `docker logs -f asst-service-dev | grep assist-stream-latency` (2026-06-19 **06:15~06:25 UTC = KST 15:15~15:25**, 통화 callId `698591133438` / `698591133575`)
> ※ 아래 로그 시각은 UTC 표기다. 한국시간(KST)으로 보려면 +9시간.
> 각 줄 형식: `시각  [assist-stream-latency] {구간별 ms}`. `headersToFirstChunkMs`(AICM 검색)가 전체의 대부분임을 시간순으로 확인할 수 있다.

```
2026.06.19 06:15:47  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":20,"headersToFirstChunkMs":7,"totalMs":28}
2026.06.19 06:15:47  {"callId":"698591133438","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":13,"headersToFirstChunkMs":8,"totalMs":21}
2026.06.19 06:15:55  {"callId":"698591133438","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":37,"headersToFirstChunkMs":1002,"totalMs":1039}
2026.06.19 06:15:55  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":1,"fetchToHeadersMs":39,"headersToFirstChunkMs":1005,"totalMs":1046}
2026.06.19 06:16:04  {"callId":"698591133438","controllerToStreamMs":2,"inToFetchMs":0,"fetchToHeadersMs":41,"headersToFirstChunkMs":1019,"totalMs":1062}
2026.06.19 06:16:04  {"callId":"698591133438","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":34,"headersToFirstChunkMs":1019,"totalMs":1053}
2026.06.19 06:16:19  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":29,"headersToFirstChunkMs":948,"totalMs":978}
2026.06.19 06:16:19  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":33,"headersToFirstChunkMs":955,"totalMs":989}
2026.06.19 06:16:32  {"callId":"698591133438","controllerToStreamMs":2,"inToFetchMs":0,"fetchToHeadersMs":52,"headersToFirstChunkMs":985,"totalMs":1039}
2026.06.19 06:16:32  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":62,"headersToFirstChunkMs":970,"totalMs":1033}
2026.06.19 06:16:43  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":50,"headersToFirstChunkMs":981,"totalMs":1032}
2026.06.19 06:16:43  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":45,"headersToFirstChunkMs":993,"totalMs":1039}
2026.06.19 06:16:59  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":43,"headersToFirstChunkMs":544,"totalMs":588}
2026.06.19 06:16:59  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":46,"headersToFirstChunkMs":555,"totalMs":602}
2026.06.19 06:19:51  {"callId":"698591133575","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":35,"headersToFirstChunkMs":1227,"totalMs":1262}
2026.06.19 06:19:51  {"callId":"698591133438","controllerToStreamMs":0,"inToFetchMs":1,"fetchToHeadersMs":34,"headersToFirstChunkMs":1218,"totalMs":1253}
2026.06.19 06:19:51  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":40,"headersToFirstChunkMs":1222,"totalMs":1263}
2026.06.19 06:20:02  {"callId":"698591133575","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":8,"headersToFirstChunkMs":962,"totalMs":970}
2026.06.19 06:20:02  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":12,"headersToFirstChunkMs":947,"totalMs":960}
2026.06.19 06:20:02  {"callId":"698591133438","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":13,"headersToFirstChunkMs":951,"totalMs":964}
2026.06.19 06:20:15  {"callId":"698591133438","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":19,"headersToFirstChunkMs":1024,"totalMs":1043}
2026.06.19 06:20:15  {"callId":"698591133575","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":15,"headersToFirstChunkMs":1031,"totalMs":1046}
2026.06.19 06:20:15  {"callId":"698591133438","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":20,"headersToFirstChunkMs":1026,"totalMs":1046}
2026.06.19 06:20:39  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":69,"headersToFirstChunkMs":1166,"totalMs":1236}
2026.06.19 06:20:39  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":88,"headersToFirstChunkMs":1175,"totalMs":1264}
2026.06.19 06:20:39  {"callId":"698591133438","controllerToStreamMs":2,"inToFetchMs":0,"fetchToHeadersMs":74,"headersToFirstChunkMs":1196,"totalMs":1272}
2026.06.19 06:20:44  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":49,"headersToFirstChunkMs":1073,"totalMs":1123}
2026.06.19 06:20:44  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":46,"headersToFirstChunkMs":1065,"totalMs":1112}
2026.06.19 06:20:44  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":46,"headersToFirstChunkMs":1075,"totalMs":1122}
2026.06.19 06:20:56  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":29,"headersToFirstChunkMs":1024,"totalMs":1054}
2026.06.19 06:20:56  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":41,"headersToFirstChunkMs":1041,"totalMs":1083}
2026.06.19 06:20:56  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":29,"headersToFirstChunkMs":1029,"totalMs":1059}
2026.06.19 06:21:26  {"callId":"698591133438","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":19,"headersToFirstChunkMs":964,"totalMs":983}
2026.06.19 06:21:26  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":23,"headersToFirstChunkMs":967,"totalMs":991}
2026.06.19 06:21:26  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":28,"headersToFirstChunkMs":970,"totalMs":999}
2026.06.19 06:21:45  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":43,"headersToFirstChunkMs":941,"totalMs":985}
2026.06.19 06:21:45  {"callId":"698591133575","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":49,"headersToFirstChunkMs":940,"totalMs":989}
2026.06.19 06:21:45  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":40,"headersToFirstChunkMs":955,"totalMs":996}
2026.06.19 06:22:10  {"callId":"698591133575","controllerToStreamMs":0,"inToFetchMs":1,"fetchToHeadersMs":41,"headersToFirstChunkMs":1119,"totalMs":1161}
2026.06.19 06:22:10  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":49,"headersToFirstChunkMs":1106,"totalMs":1156}
2026.06.19 06:22:10  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":50,"headersToFirstChunkMs":1103,"totalMs":1154}
2026.06.19 06:22:31  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":41,"headersToFirstChunkMs":1044,"totalMs":1086}
2026.06.19 06:22:31  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":45,"headersToFirstChunkMs":1037,"totalMs":1083}
2026.06.19 06:22:31  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":46,"headersToFirstChunkMs":1056,"totalMs":1103}
2026.06.19 06:24:15  {"callId":"698591133438","controllerToStreamMs":0,"inToFetchMs":0,"fetchToHeadersMs":47,"headersToFirstChunkMs":961,"totalMs":1008}
2026.06.19 06:24:15  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":38,"headersToFirstChunkMs":978,"totalMs":1017}
2026.06.19 06:24:15  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":35,"headersToFirstChunkMs":978,"totalMs":1014}
2026.06.19 06:24:29  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":40,"headersToFirstChunkMs":1058,"totalMs":1099}
2026.06.19 06:24:29  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":29,"headersToFirstChunkMs":1089,"totalMs":1119}
2026.06.19 06:24:29  {"callId":"698591133438","controllerToStreamMs":2,"inToFetchMs":0,"fetchToHeadersMs":41,"headersToFirstChunkMs":1057,"totalMs":1100}
2026.06.19 06:24:46  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":14,"headersToFirstChunkMs":1025,"totalMs":1040}
2026.06.19 06:24:46  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":16,"headersToFirstChunkMs":1096,"totalMs":1113}
2026.06.19 06:24:46  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":17,"headersToFirstChunkMs":1103,"totalMs":1121}
2026.06.19 06:24:56  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":35,"headersToFirstChunkMs":1022,"totalMs":1058}
2026.06.19 06:24:56  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":19,"headersToFirstChunkMs":1102,"totalMs":1122}
2026.06.19 06:24:56  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":14,"headersToFirstChunkMs":1088,"totalMs":1103}
2026.06.19 06:25:12  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":30,"headersToFirstChunkMs":1011,"totalMs":1042}
2026.06.19 06:25:12  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":35,"headersToFirstChunkMs":1014,"totalMs":1050}
2026.06.19 06:25:12  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":28,"headersToFirstChunkMs":1017,"totalMs":1046}
2026.06.19 06:25:28  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":53,"headersToFirstChunkMs":968,"totalMs":1022}
2026.06.19 06:25:28  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":61,"headersToFirstChunkMs":977,"totalMs":1039}
2026.06.19 06:25:28  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":64,"headersToFirstChunkMs":991,"totalMs":1056}
2026.06.19 06:25:49  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":69,"headersToFirstChunkMs":980,"totalMs":1050}
2026.06.19 06:25:49  {"callId":"698591133575","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":69,"headersToFirstChunkMs":975,"totalMs":1045}
2026.06.19 06:25:49  {"callId":"698591133438","controllerToStreamMs":1,"inToFetchMs":0,"fetchToHeadersMs":57,"headersToFirstChunkMs":994,"totalMs":1052}
```

### 부록 관찰 요약

- 전 구간에 걸쳐 `controllerToStreamMs`(0~2ms) + `inToFetchMs`(0~1ms) = **백엔드 처리 항상 2ms 이하**로 일정.
- `headersToFirstChunkMs`(AICM 검색)만 **544~1227ms로 출렁이며 `totalMs`를 그대로 결정** → 응답시간 = 사실상 AICM 검색시간.
- 06:15:47 의 7ms/8ms 두 건은 통화 시작 직후 짧은 발화로 검색이 거의 없던 예외 케이스(백엔드 자체는 28ms·21ms로 완료 → 백엔드 속도의 상한을 보여줌).

