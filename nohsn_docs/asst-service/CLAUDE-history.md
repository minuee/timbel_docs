# CLAUDE-history.md

이 파일은 Claude와의 대화 기록을 순차적으로 누적한다. (중요 결정/지식은 `CLAUDE.md`에 별도 정리)

---

## 2026-06-10

### 1. POST /assist-stream 분석 — 프론트 호출 API 맞는지 확인

**질문**: `POST /assist-stream`이 유저 화면에서 프론트가 호출하는 API 주소가 맞는지.

**결론**: 맞음. 프론트가 통화 중 직접 호출하는 SSE 엔드포인트.

- **경로**
  - asst-service 내부: `POST /api/asst/v1/assist-stream` (`@Controller('assist-stream')` + base path `/api/asst/v1`)
  - 게이트웨이 경유(프론트 실제 호출 주소): `POST /aicc/asst-service/assist-stream`
- **성격**
  - 통화 중 **고객 발화당** 프론트→asst-service 요청 (`query` + `conversationHistory` + `callId`)
  - asst-service는 LLM을 직접 호출하지 않고, 외부 RAG(`SEARCH_HOST` `/api/v1/rag/assist-stream`)로 payload 변환 후 **SSE 릴레이** (근거문서 Top5 + 요약 + LLM답변)
  - 응답: `text/event-stream`
- **요청 DTO** (`AssistStreamRequestDto`): `query`(1~1000자, 필수), `conversationHistory?`(speaker: customer/agent + content), `repositoryId?`, `callId?`(로깅용)
- **업스트림 payload 변환** (`buildUpstreamPayload`): `{ query, repository_id(없으면 SEARCH_REPOSITORY_ID 기본값), conversation_history(toRagHistory로 role: user/assistant 변환), distill: false }`
- **발견된 이슈**: `X-Tenant-Id`가 하드코딩(`00000000-0000-0000-0000-000000000000`) + TODO 상태. 토큰 기반 tenantId 연동 미완(`AuthMiddleware → req.tenantId` 연동 필요).
- **관련 파일**: `src/advisor/assist-stream/controllers/assist-stream.controller.ts`, `services/assist-stream.service.ts`, `dto/assist-stream-request.dto.ts`, `services/conversation-history.util.ts`

### 2. 대화 기록 규칙 합의
- 앞으로 모든 대화를 `CLAUDE-history.md`에 순차 기록 (턴마다 또는 필요 시점마다 Claude 판단으로 저장).
- 중요 지식/결정은 사용자가 별도로 `CLAUDE.md`에 요청.

### 3. VOC 실시간 탐지(감정/이탈) 설계 논의 — assist-stream에 연동

**배경**: `POST /assist-stream`이 RAG 문서시스템과 연동돼 대화내용→근거문서를 주고 있음. 여기에 VOC 탐지(고객감정/이탈징후)를 실시간으로 추가하려는데, (1) 매 발화 LLM 호출 시 비용 과다, (2) 같은 API냐 별도냐 고민. VOC 탐지 방식(LLM vs NLP)은 나중 문제, 일단 기존 LLM 사용 전제.

**고민 1 — "필요한 시기에만 전달, 누가 판단?"**
- 결론: **판단 주체는 LLM이 아니라 LLM 앞단의 싼 결정적 게이트**. 게이트 통과 시에만 LLM 호출 → 비용 억제.
- 게이트 후보(조합): ① 키워드/정규식 트리거(해지/환불/책임자/소비자원/욕설 등), ② 스로틀/디바운스(N초·M발화당 1회 상한), ③ 슬라이딩 윈도우(최근 3~5턴 묶음 주기 분석), ④ 상태머신(위험 감지 후 빈도↑, 잠잠하면↓).
- 키워드 게이트+스로틀이면 LLM 호출이 전체 발화의 ~10-20%로 감소.

**고민 2 — 같은 API vs 별도 API**
- 추천: **트리거는 assist-stream 안에 붙이되(데이터 이미 흐름, RAG 릴레이와 병렬 fire-and-forget), 결과 전달은 `SocketGateway` push로 분리**.
  - 이유: 입력(query+conversationHistory)이 이미 들어오니 프론트 중복 전송 불필요. VOC 결과는 RAG 근거문서 패널과 화면 위치 다르고, 상담사+슈퍼바이저 동시 전달 필요할 수 있어 SSE에 섞기보다 Socket push가 적합.
  - 별도 엔드포인트 분리는 "발화 없어도 주기적 분석" 필요해질 때. 지금은 새 발화=분석할 새 정보 시점이라 불필요 → 1단계는 assist-stream 내 트리거+Socket push.
- 저장: 실시간(Track B)은 DB 저장 안 함(ephemeral push). 통화 종료 후 `summarizeCall`에서 최종 verdict만 저장(기존 Track A 분리 유지).

**다음 확인 필요**: 프론트가 VOC 결과를 어떤 패널에서 어떻게 수신 기대하는지(SSE 이벤트 vs Socket 구독). 이게 고민 2 결정을 굳힘.

### 4. 결론 합의 — 단일 API로 2서비스, 프론트는 소켓 구독만 추가
- 백엔드: `POST /assist-stream` 하나가 ① RAG 근거문서(기존 SSE) + ② 게이트 통과 시 VOC 분석→SocketGateway push. 소켓은 이미 양방향 연결 상시 가동 중이라 재사용.
- 프론트: 새 API 없이 소켓으로 오는 VOC 이벤트 구독해서 노출만 추가.
- 구현 주의: (a) VOC 분석은 RAG 릴레이를 막지 않게 fire-and-forget 병렬(.catch로 에러 흡수), (b) push 라우팅 식별값 필요 — 현재 `callId`는 옵셔널(로깅용)이라 push용으론 필수화하거나 토큰에서 agentId/tenantId 해석 필요(X-Tenant-Id 하드코딩 TODO와 동일 라인 작업).

### 5. 게이트 선택 — 키워드 사전은 코드 상수로 시작
- 키워드 트리거는 위험 신호어 정의가 필요하지만 **별도 DB/관리화면 불필요**. 단계: ① 코드 상수 배열(비용0, 5분, 추천 시작점) → ② .env 콤마리스트(배포없이 갱신) → ③ DB+관리API(지금은 오버).
- 키워드만으론 맥락상 위험 누락 → **키워드 OR 스로틀** 조합 권장(키워드 시 즉시 LLM, 없어도 N초마다 1회 안전망).

### 6. 스로틀 타이머 구현 방식 — setInterval 아님, callId별 timestamp 비교
- **핵심**: `POST /assist-stream`은 통화 내내 열린 연결이 아니라 **발화 1건당 1요청**(요청 종료됨). long-lived는 Socket이지 이 API 아님. 따라서 핸들러 안 `setInterval`은 요청 끝나면 죽어 통화 수명을 못 따라감.
- **대신**: 프로세스 메모리에 `Map<callId, lastVocAt>` 두고, 발화 들어올 때마다 "마지막 분석 후 30초 지났나?" 체크. 발화 도착 = 타이머 틱 역할.
  ```ts
  private lastVocAt = new Map<string, number>();
  private shouldRunVoc(callId, query): boolean {
    const now = Date.now(); const last = this.lastVocAt.get(callId) ?? 0;
    if (VOC_KEYWORDS.some(k => query.includes(k))) { this.lastVocAt.set(callId, now); return true; } // 키워드 즉시
    if (now - last >= 30_000) { this.lastVocAt.set(callId, now); return true; } // 최소 30초 간격
    return false;
  }
  ```
- 트레이드오프: "30초마다" 실제 의미 = "최소 30초 간격, 단 새 발화 왔을 때." 무발화(침묵=이탈징후)는 못 잡음 → 필요시 나중에 Socket 쪽 진짜 타이머. cleanup은 통화종료 시 Map 삭제 or TTL/sweep. 멀티 pod면 Map 대신 Redis(현재 단일 인스턴스면 Map 충분).

### 7. 게이트 방식 최종 후보 — 턴 기반(발화 N회마다) 채택 권장
- 발화 1건=1요청이라 **카운터만 올리면 됨**(Date.now 불필요). 턴 기반이 시간 기반보다 더 단순하고 이 요청 모델에 더 적합.
  ```ts
  private vocTurnCount = new Map<string, number>();
  private shouldRunVoc(callId, query): boolean {
    if (VOC_KEYWORDS.some(k => query.includes(k))) { this.vocTurnCount.set(callId, 0); return true; } // 키워드 즉시+리셋
    const n = (this.vocTurnCount.get(callId) ?? 0) + 1;
    if (n >= 3) { this.vocTurnCount.set(callId, 0); return true; } // 3턴마다, 리셋
    this.vocTurnCount.set(callId, n); return false;
  }
  ```
- 턴 vs 시간: 턴=구현 최단순/비용을 발화수로 예측 쉬움, 말 빠른 고객은 짧은 시간 잦은 호출 가능. 시간=시간으로 묶여 안정적, 말 뜸한 고객도 30초 보장.
- **추천**: 시작은 턴 기반(3회)+키워드 즉시. 운영 보며 숫자 조정(2회) 또는 시간 조건 추가. 초반 감정 파악 중요하면 첫 발화 무조건 1회 분석(초기값 튜닝) 고려.

### 8. 게이트 동작 합의 + 컨텍스트(전체 이력 부족) 문제 발견
- **게이트 동작 합의**: 최초 1회 수신 시 분석 + 이후 3턴(고객 기준, 고객-상담사 구분 안 되면 그냥 3턴)마다 LLM 분석. (지금은 키워드 사전 구축 어려우니 턴 기반 위주로 시작)
- **발견된 핵심 문제**: 프론트가 보내는 `POST /assist-stream` payload는 `query`(지금 막 끝난 고객 발화 1건) + `conversationHistory`(직전 2개 메시지, 현재 발화 제외, 둘은 비중복) — **전체 대화가 아님**. RAG 검색용 최소화 설계라 그런 것. VOC(감정/이탈)는 대화 흐름·추세를 봐야 해서 3메시지 창으론 부족.
- **이미 존재하는 누적 저장소 발견**: `advisor.callstat_assist_snapshot` (`call_id`+`turn_idx` unique, `customer_query` text, `payload` jsonb). `AssistSnapshotService.findByCallId(callId)`로 turn 순서대로 전체 고객 발화 조회 가능. 단 저장은 별도 save 엔드포인트(`assist-snapshot.controller`) 경유 — assist-stream.service는 스냅샷 저장 안 함(프론트 드리븐).

**전체 이력 확보 2가지 옵션**
- **옵션 A (인메모리 누적, 추천)**: 턴 카운터용 `Map<callId,...>`에 메시지 배열도 같이 누적. 첫 요청 시 `conversationHistory`+`query`로 시드 → 이후 `query` append. 게이트 통과 시 누적 버퍼 전체를 LLM에. 장점: DB왕복0/의존성0. 단점: 프로세스 로컬(재시작 소실, 멀티 pod 분산) — dev 단일 인스턴스면 무방.
- **옵션 B (스냅샷 테이블 조회)**: 게이트 통과 시 `findByCallId`로 DB에서 누적 발화 읽음. 장점: 영속·멀티pod 안전. 단점: ① `customer_query`만 저장(상담사 턴 없음), ② 스냅샷 save가 분석 시점 전 선행돼야(타이밍 의존), ③ DB왕복.

**상담사 발화 누락 이슈**: assist-stream은 고객 발화마다 트리거 → `query`는 전부 고객 발언. 상담사 답변은 다음 호출 `conversationHistory`에만 잠깐 등장. 감정/이탈은 주로 고객 발화 기반이라 고객 발화만 누적해도 MVP 충분. 상담사 맥락 필요시 옵션 A에서 conversationHistory를 dedup 머지.

**최종 추천**: 옵션 A(인메모리 누적)+고객 발화 위주. 턴 카운터 상태에 메시지 배열만 추가 → 게이트와 컨텍스트를 하나의 per-callId 상태로 동시 해결. 나중에 영속/멀티pod 필요하면 스냅샷 테이블로 승격(자료구조 이미 존재).

### 9. 최종 구현 합의안 (옵션 A 확정)
**`POST /assist-stream` 수신 시:**
1. 기존 RAG 릴레이 그대로(영향 0). VOC는 fire-and-forget 병렬, 실패해도 RAG 응답 안 막음.
2. 별도 VOC 트리거: `Map<callId, { count, buffer }>` 단일 상태로 관리.
   - `buffer`: 발화 누적(옵션 A — 첫 요청 시 conversationHistory+query 시드, 이후 query append)
   - `count`: 턴 카운터 → 최초 1회 + 이후 3턴마다 게이트 통과
3. 게이트 통과 시 누적 buffer 전체를 LLM에 넘겨 VOC(감정/이탈) 추출.
4. 결과 → SocketGateway로 프론트(상담사/슈퍼바이저) push.
- 핵심: count(게이트)+buffer(컨텍스트)가 하나의 per-callId 상태로 묶임.

**남은 미정 2개**:
- callId 라우팅: 소켓 push 대상(callId→상담사/room 매핑)이 소켓 구조에 있는지 확인 필요. → **소켓 구조 분석 예정**
- LLM 호출 방식: 기존 `LlmOrchestratorService` 재사용 + VOC용 프롬프트(감정은 summary 쪽 프롬프트 자산 일부 재활용 가능).

### 10. emotions 테이블 3축 확장 + 소스 반영 (구현 완료)
**방향**: emotion(감정) 단일 → VOC 3축(감정/민원위험/이탈징후)으로 확장. 실시간=3축 추출, 최종 summary=종합평가 프롬프트. 테이블에 3축 저장, 프론트는 필요값만 노출. 사용자가 `migrations/create_emotion_table.sql`을 3축으로 직접 수정함(로컬 테이블은 DROP 후 재생성 방침이라 rename 마이그레이션 불필요).

**스키마 변경**: `advisor.emotions` 컬럼 — `description/icon_type/score` → `sentiment_description/sentiment_type/sentiment_score` 리네임 + `complaint_risk_description`(VARCHAR255)/`complaint_risk_score`(double)/`churn_risk_description`/`churn_risk_score` 추가. (sentiment_type CHECK는 negative/neutral/positive/etc 유지)

**수정 파일**:
- `summary-response.dto.ts`: `RiskAxisDto`(score+summary), `VocAnalysisDto`(emotion+complaintRisk+churnRisk) 신설. `SummaryResponseDto`에 `complaintRisk`/`churnRisk` 추가(기존 `emotion` 유지=하위호환). `EmotionDto`는 그대로(VocAnalysisDto.emotion으로 재사용).
- `emotion.entity.ts`: 컬럼 7개로 확장(위 스키마). `EmotionIconType`/매핑 유지.
- `emotion.service.ts`: `saveEmotion(callstatsId, voc: VocAnalysisDto, token)` — 3축 모두 upsert. `mapEmotionTypeToIconType`(5종→4종 sentiment_type) 유지.
- `summary.service.ts`: `classifyEmotion`→`analyzeVoc`(3축 **종합평가** 프롬프트, gpt-4o-mini), `parseEmotionResponse`→`parseVocResponse`+`parseRiskAxis` 헬퍼. `summarizeCall`은 voc 구조분해 후 result 구성+saveEmotion. public `analyzeEmotion`은 `VocAnalysisDto` 반환.
- `emotion.controller.ts`: `/emotion/analyze` 반환타입 `VocAnalysisDto|Emotion`, Swagger 설명 3축으로.
- `dynamic-database.service.ts`: `runSchemaMigrations` CREATE TABLE 새 3축 스키마로 교체(mechanism ②, IF NOT EXISTS).

**프롬프트 분리 정책**: 현재 `analyzeVoc` 프롬프트 = 통화 종료 후 "종합평가"(전체 대화 기준 최종 판단). 실시간(assist-stream) 조기탐지용 프롬프트는 추후 Track B에서 별도 분기 예정(코드에 주석 명시).

**검증**: `tsc --noEmit` 통과, eslint --fix 후 클린. (사용자가 로컬 emotions 테이블 DROP 후 서버 재시작하면 새 스키마 생성됨 — DataSource 캐시 때문에 풀 재시작 필요)

**다음**: 소켓 구조 분석 → 실시간 Track B(게이트+인메모리 누적+소켓 push) 구현, callId 라우팅 확정.

### 11. 실시간 VOC 영속화 설계 정리 (turn_idx 연결고리)
- **소켓 push는 그대로 유지**(실시간 노출). 추가로 콜이력 사후조회용으로 턴별 VOC를 DB에 저장(최종요약 emotions와 별개).
- 저장소: 기존 `callstat_assist_snapshot`에 컬럼 추가(두 writer 충돌 우려) 대신 **별도 테이블 `callstat_voc` 신설**(서버 단독 writer, 충돌 0, 관심사 분리)로 결정.
- **turn_idx 연결고리 문제**: VOC는 `/assist-stream`(SSE 중, 서버 계산)인데 turn_idx는 `/assist-stream/snapshot`(SSE-done)에서만 들어와 단절. (참고: STT 턴은 Redis Sorted Set `dev:call:{callId}:turn:data`에도 있고 `getPrevSttDataFromRedis(callId)`로 조회 가능 — turn_idx/원문 utterance 보유. 단 이 방향은 보류.)
- **해결**: 프론트가 `/assist-stream` 요청 body에 `turnIdx?: number|null`을 함께 보내기로 함(트리거 발화의 messageData.turn_idx). 이걸로 1:1 매칭.
- **저장 조건(합의)**: `callId && turnIdx != null && VOC LLM 결과 존재` 3조건 모두 충족 시에만 저장. 저장 실패는 기존 프로세스 안 막고 try/catch 로그만(emotions 저장과 동일 패턴).

### 12. 기반 구현 완료 (tsc/lint 0)
- `AssistStreamRequestDto`에 `turnIdx?: number|null`(@IsOptional @IsInt) 추가.
- 신규 엔티티 `CallstatVoc` (`src/advisor/call/entities/callstat-voc.entity.ts`): `id`(uuid PK), `unique(call_id, turn_idx)`, `index(call_id)`, 3축 컬럼(sentiment_type/score/description, complaint_risk_score/description, churn_risk_score/description), created_at. advisor 스키마.
- 4곳 등록: dynamic-database.service.ts(import + dynamic·static 배열), database.config.ts(import+배열). `runSchemaMigrations`에 `CREATE TABLE IF NOT EXISTS advisor.callstat_voc` + 인덱스 추가(멱등).
- **미구현(다음 단계)**: assist-stream 처리 흐름에 게이트(턴 N회/키워드) + VOC 분석(analyzeVoc 재사용) + 소켓 push + callstat_voc 저장 wiring. VOC 입력 소스(인메모리 누적 vs Redis STT)와 소켓 라우팅(callId→상담사/room)은 미확정.

### 13. VOC 입력 소스 = 인메모리 누적으로 확정
- "VOC 입력 소스" = LLM에 먹일 대화 텍스트를 어디서 가져오나. assist-stream payload는 query+직전2개뿐이라 부족 → 더 긴 이력 필요.
- 후보: 인메모리 누적 vs Redis STT(`getPrevSttDataFromRedis`, 원문+speaker+turn_idx 보유). Redis가 객관적으론 더 우수하나, **사용자가 인메모리 누적 선택**(휘발성, 굳이 영속 불필요). Redis "보류"는 정식 결정 아니라 내가 멈춘 것.

### 14. Track B 1단계 구현 완료 — 게이트+누적+분석+저장 (소켓 제외)
- 신규 `VocRealtimeService` (`src/advisor/assist-stream/services/voc-realtime.service.ts`):
  - 상태: `Map<callId, {messages, count}>` (휘발성). 첫 요청 conversationHistory 시드 + 매 요청 query(고객) append. 버퍼 상한 40.
  - 게이트: `(count-1) % TURN_INTERVAL(=3) === 0` → 최초 1회 + 이후 3턴마다.
  - 분석: `summaryService.analyzeEmotion(conversation, token)` 재사용(VocAnalysisDto).
  - 저장: `callId && turnIdx != null` 일 때만 `callstat_voc` upsert(call_id,turn_idx). 실패는 throw 안 하고 warn 로그만. sentiment_type은 `emotionService.mapEmotionTypeToIconType`로 매핑.
- 트리거: `AssistStreamController.assistStream`에서 `void vocRealtimeService.handleUtterance(dto, req.token)` — **fire-and-forget, RAG 릴레이 안 막음**. 실패는 서비스 내부 try/catch 흡수.
- 등록: advisor.module providers에 `VocRealtimeService` 추가. 컨트롤러 spec에 mock 추가.
- 검증: tsc 0, lint 0, 컨트롤러 spec 통과.
- **알려진 한계/TODO**:
  1. 프롬프트 재사용: `analyzeEmotion`은 "종료된 통화 종합평가" 문구 → 실시간 부분대화엔 살짝 안 맞음(1차 구현, 추후 실시간 전용 프롬프트로 분기).
  2. 버퍼 정리: 통화종료 훅 없어 `Map` 엔트리가 누적될 수 있음(`clear(callId)` 메서드만 있고 호출처 없음). 메시지 상한 40으로 엔트리 크기는 제한. 추후 call-end/TTL 정리 필요.
  3. 소켓 push 미구현(다음 단계, callId 라우팅 확정 후 — 사용자가 프론트 확인 후 "생각보다 쉬움").
- **무관한 기존 실패**: `assist-stream.service.spec.ts`의 X-Tenant-Id 테스트(하드코딩 vs undefined 기대) — 내 변경 stash해도 동일하게 깨짐. 별개 TODO.

### 15. 게이트 간격 환경변수화
- `REALTIME_VOC_INTERVAL` 환경변수 추가(사용자가 .env에). `VocRealtimeService`가 ConfigService로 읽어 `turnInterval`로 사용. 누락/형식오류/1미만이면 기본값 3 폴백. 부팅 시 `실시간 VOC 게이트 간격: N턴마다` 로그.

### 16. 실시간 VOC Swagger 테스트 엔드포인트
- 로컬에서 RAG/SSE/소켓 없이 실시간 VOC 로직만 테스트하기 위한 엔드포인트(emotion/analyze 패턴과 동일 취지).
- `POST /assist-stream/voc-test` (`AssistStreamController.vocTest`, tag "AI 상담 보조", `@UseInterceptors(DbCleanupInterceptor)`).
- `VocRealtimeService.handleUtterance` 리팩터: 반환타입 `void`→`VocRealtimeResultDto`(callId/bufferedTurns/gateFired/saved/voc/error), `opts.force`로 게이트 무시 지원. 프로덕션 경로는 `void`로 반환값 무시. `saveVoc`는 boolean 반환.
- 신규 DTO `voc-realtime-test.dto.ts`: `VocRealtimeTestDto`(AssistStreamRequestDto extends + reset/force), `VocRealtimeResultDto`.
- 사용법: ① force=true → 게이트 무시 단발 분석(+callId&turnIdx 있으면 callstat_voc 저장). ② 같은 callId로 반복 호출 → 누적되며 게이트(REALTIME_VOC_INTERVAL턴마다) 발동 확인, reset=true로 버퍼 초기화.
- 컨트롤러 spec: method-level 인터셉터 DI 문제로 `.overrideInterceptor(DbCleanupInterceptor)` 추가. tsc/lint/spec 통과.

### 17. 식별자 분석 — callstats_id vs call_id (서로 다른 컬럼)
- `raw_call.callstats_call`: `id`(PK, "호출통계 ID") + `call_id`(별도 컬럼, "통화 ID").
- **`callstats_id` = callstats_call.id** (emotions PK, summary, callstats_turn.callstats_id가 이걸 참조).
- **`call_id` = callstats_call.call_id** (callstat_voc, callstat_assist_snapshot, assist-stream dto.callId, Redis STT 키. STT 컨트롤러 설명에 "callstats_call.call_id 컬럼값"으로 명시).
- 즉 둘은 다른 식별자. 단계별로 손에 쥘 수 있는 ID가 달라서: call_id는 통화 시작부터 존재(실시간 가용), callstats_id는 통계레코드 PK(통화 후). 설계는 잘못된 게 아님(emotions=통화당1, callstat_voc=통화당N/턴별 의도 맞음).

### 18. emotions ↔ callstat_voc 직접 조인 위해 emotions에 call_id 추가 (옵션 2)
- 목적: 두 테이블을 callstats_call 다리 없이 직접 조인(`emotions.call_id = callstat_voc.call_id`).
- 확인: `summarizeCall`이 `callstatCallRepository.findOne({where:{id:callstats_id}})`로 가져오는 `callstatCall.call_id`가 최종요약 시점에 항상 존재(CallstatCall.call_id는 not-null 컬럼).
- **call_id는 필수 → NOT NULL** (사용자가 SQL 파일에 직접 NOT NULL로 작성, 본인이 관리). 코드 정렬:
  - `emotion.entity.ts`: `call_id: string`(NOT NULL) 추가.
  - `runSchemaMigrations`: emotions CREATE TABLE에 `call_id VARCHAR(128) NOT NULL` + `idx_emotions_call_id` 인덱스.
  - `emotion.service.saveEmotion(callstatsId, voc, token, callId: string)` — **callId 필수**(callstats_id 폴백 제거: 다른 식별자라 오염 방지). `fields.call_id = callId`.
  - `summary.service.summarizeCall`: `callstatCall.call_id` 전달.
  - `/emotion/analyze` 테스트: `AnalyzeEmotionDto.call_id?` 추가. 저장은 `save && callstats_id && call_id` 셋 다 있을 때만, 없으면 분석만.
- SQL 파일(`create_emotion_table.sql`)은 사용자가 직접 수정/관리(에이전트가 건드리지 않음). 실제 반영은 runSchemaMigrations 담당.
- 검증: tsc 0 / lint 0.

### 19. 소켓(실시간 노출) 설계 확정 — 백엔드는 Redis publish만
- 구조: 단일 소켓 + 하나의 `redis-message` 이벤트. 새 소켓 이벤트가 아니라 **새 Redis 채널 + (프론트가) 구독**으로 추가.
- **구독→relay bridge는 이미 가동 중**(STT 자막/통화이벤트/orchestrator가 이미 프론트로 감 = 증거). 프론트가 `POST /redis-monitor/subscribe/{channel}`로 구독, 소켓 서버가 `redis-message`로 범용 relay. → **백엔드는 publish만, relay 코드 안 건드림.**
- 코칭은 고정 채널(`coaching:request`)이라 부팅 시 자동 구독(`coaching-socket.handler`)되지만, VOC는 **상담사별 채널**이라 publish하는 쪽이 cc_cti_id를 알아야 함(per-agent 채널의 본질).
- 채널: `{env}:{vendor_tenant_id}:{cc_cti_id}:call:voc`. env는 **하드코딩 금지** — 프론트 dev/prd와 맞춰야(운영에서 dev로 쏘면 영영 미수신). 백엔드는 `NODE_ENV==='production'?'prd':'dev'`로 도출(별도 env 변수 불필요, .env 수정 안 함).
- payload inner message에 **`agent_id` 필드(값=cc_cti_id)** 필수 — 프론트 전역 파서(useChatMessageParser.ts:119)가 cc_cti_id와 비교, 불일치면 silent drop. `turn_idx`도 포함(턴 매칭).
- **cc_cti_id/tenant 출처 = get_user**: `UserInfoService.getCurrentUser(token)` 응답에 `company.vendor_tenant_id`(예 4609686) + `agent.cc_cti_id`(예 56356659) 들어옴(인터페이스에만 빠져있어 `cc_cti_id?` 추가함). 백엔드 기존 패턴: summary `getCompanyIdFromToken`이 동일하게 getCurrentUser로 `agent.company_id` 추출. **프론트 변경 0.** (주의: 채널 tenant는 `vendor_tenant_id`, summary가 LLM용으로 쓰는 `agent.company_id`와 다른 필드)
- `agent-status-socket.handler`는 Redis 구독이 아니라 직접 socket broadcast 헬퍼(혼동 주의). Redis 구독 핸들러는 `coaching-socket.handler`.

### 20. Track B publish 구현 완료 (tsc/lint 0)
- `VocRealtimeService`에 `RedisService`+`UserInfoService` 주입. `publishVoc()` 추가: getCurrentUser로 vendor_tenant_id+cc_cti_id 해석 → 채널 빌드 → `redisService.publish`. env는 `resolveChannelEnv()`(production→prd, else dev).
- `handleUtterance`: 게이트 통과 시 `publishVoc` + `saveVoc` 둘 다 best-effort 호출. 결과 DTO에 `published` 추가.
- `CurrentUserResponse.agent`에 `cc_cti_id?: string` 추가(user-info.service.ts).
- 테스트: `/assist-stream/voc-test` 응답 `published` + 로그 `실시간 VOC publish: channel=dev:{tenant}:{cti}:call:voc`로 채널/해석 검증 가능.
- **남은 것**: 통화종료 시 인메모리 버퍼 정리 훅(현재 size cap만), 실시간 전용 프롬프트 분기(현재 종합평가 재사용).

### 21. 감정 4종 통일 + 실시간 프롬프트 분기 (tsc/lint 0)
- 배경: 5종(LLM)·4종(DB)·혼재로 헷갈림. 프론트가 4종으로 작업하려 함. → **negative/neutral/positive/etc 4종으로 전면 통일**(etc는 사실상 중립이나 일단 유지). LLM이 4종 직접 출력.
- `EmotionType` 5종→4종(`summary-response.dto.ts`), `EMOTION_TYPES` 상수 추가, EmotionDto.type 설명/enum 갱신.
- **`mapEmotionTypeToIconType` 삭제**(emotion.service) — LLM이 4종 직접 주므로 매핑 불필요. `saveEmotion`/`VocRealtimeService.saveVoc`는 `voc.emotion.type` 그대로 sentiment_type에 저장. voc-realtime에서 안 쓰게 된 `EmotionService` 의존성 제거.
- `parseVocResponse` allowed=4종.
- 결과 통일: 실시간 소켓 payload `emotion.type` / `callstat_voc.sentiment_type` / `emotions.sentiment_type` / SummaryResponse 전부 4종 동일. (payload에 별도 sentiment_type 필드 추가 불필요해짐)
- **프롬프트 분기**: `buildVocPrompt(conversation, mode)` 신설. `analyzeVoc(conversation, tenantId, token, mode)` + public `analyzeEmotion(..., mode='summary')`. summary=통화후 종합평가, realtime=진행중 조기탐지(현 시점 상태). 둘 다 4종 출력. summarizeCall→'summary', VocRealtimeService→'realtime'.
- 주의: 로컬 기존 emotions/callstat_voc 행의 sentiment_type이 옛 값일 수 있음(CHECK는 4종 동일이라 제약 위반 없음). 새 분석부터 4종.

### 22. 실통화 테스트 → 실시간 VOC 한 번도 안 탐 진단 → 이벤트 소스 전환(assist-stream → Redis nlp:complete) (tsc/lint/build/spec 0)

**증상**: 실제 상담사로 전화 테스트. STT 자막은 정상(소켓 중계 OK)인데 우리가 만든 `...:call:voc` publish도, 그 전에 LLM VOC 추출 자체도 **일체 안 됨**. 정책(고객 1번째+이후 3턴마다 LLM)대로면 떠야 할 로그가 0줄.

**근본 원인 — 이벤트 소스를 잘못 붙임**:
- 통화 중 발화는 외부 STT/NLP가 **Redis `{env}:{vendor}:{cc_cti}:call:nlp:complete` 채널**로 발행 → `RedisMonitorService` 구독 → `RedisMonitorController.handleChannelMessage` → `SocketGateway.broadcastToRedisMonitorRoom`로 프론트 중계. asst-service는 이 텍스트를 LLM에 안 넘김(순수 relay).
- 그런데 VOC(`handleUtterance`)는 **`POST /assist-stream` 컨트롤러**에만 붙어 있었음. assist-stream은 RAG 보조용 별도 HTTP라 **매 턴 자동 호출 아님** → 실통화 로그에 assist-stream 진입·RAG 릴레이·VOC 로그 전부 없음 = handleUtterance가 애초에 호출 안 됨.
- 추가 사각지대: `handleUtterance`에 진입 로그 없고, `if(!callId) return`·게이트 미통과가 **무음 스킵**이라 흔적도 안 남음.

**해결책 A안 채택(기존 중계 파이프라인 재사용, 무간섭)**:
- `RedisMonitorController.handleChannelMessage`의 broadcast **직후** 옵저버 통지 한 줄 추가(중계 경로 영향 0).
- 모듈 경계: `RedisMonitorController`=CommonModule, `VocRealtimeService`=AdvisorModule → 직접 주입 시 순환참조. **`@Global` RedisModule의 `RedisMonitorService`(싱글톤)에 옵저버 레지스트리**를 둬서 양쪽이 같은 인스턴스로 디커플링(@nestjs/event-emitter 미설치라 자체 구현).
- **토큰 없는 백그라운드 경로 3대 난점 해결**:
  1. LLM 호출 — `customComplete`는 token 옵셔널, `tenantId`(=X-Tenant-Id)만 필수. `X-Tenant-Id`=company_id임을 확인(getCompanyIdFromToken이 `agent.company_id` 반환) → **nlp 메시지의 `company_id`를 그대로 사용**(토큰 불필요). `SummaryService.analyzeVocByTenant(conversation, tenantId, mode, token?)` 신설(getCompanyIdFromToken 우회).
  2. publish — nlp 채널명에서 `:call:nlp:complete`→`:call:voc` 접미사 교체, `agent_id`=cc_cti_id(채널 3번째 세그먼트). 토큰/userInfo 불필요.
  3. DB 저장 — `DynamicDatabaseService.getConnectionWithoutToken()` 신설(DB_DIRECT_CON=1→정적연결 토큰불필요 / =0→캐시연결만, 없으면 null 스킵). 배포 보강용으로 assist-stream 호출 시 `cacheToken(callId, token)`로 토큰 캐시 → nlp 경로 저장에 재사용.

**speaker 수정**: 기존 `accumulate`가 발화를 무조건 `customer`로 박던 것 → nlp 메시지의 **실제 speaker** 사용. 상담원 발화는 **맥락으로만 누적**, 게이트는 **고객 발화 누적수 기준**(1번째+이후 3턴마다)으로 트리거(상담원-only 발화에 LLM 낭비 방지). 동일 turn 중복(complete 재발행) 방지 키 추가.

**구조 정리**: 프로덕션=`handleNlpComplete(channel, raw)`(nlp 구독), 테스트=`handleUtterance(dto, token, {force})`(`/assist-stream/voc-test` 유지). assist-stream 컨트롤러의 매-턴 `handleUtterance` fire-and-forget 제거(nlp 경로와 이중처리 방지) → `cacheToken`만.

**변경 파일 6개**: `redis-monitor.service.ts`(옵저버 레지스트리), `redis-monitor.controller.ts`(broadcast 후 통지+DI), `voc-realtime.service.ts`(전면 개편), `summary.service.ts`(analyzeVocByTenant), `dynamic-database.service.ts`(getConnectionWithoutToken), `assist-stream.controller.ts`(cacheToken). +spec mock(cacheToken).

**검증**: tsc 0 / eslint 0 / nest build 0 / 관련 spec 통과. 단 **실통화 런타임 검증은 사용자 재시작+통화 필요**(코드 배선만 검증됨).

**A안 caveat(기록)**: nlp:complete 구독은 그 룸에 소켓 구독자(프론트)가 있을 때만 살아있음 → 프론트 미구독 시에도 무조건 돌려야 하면 B안(상시 psubscribe)로 격상. 배포 DB 저장은 캐시 토큰 없으면 스킵(publish·LLM은 정상). 기존 무관 실패(`assist-stream.service.spec.ts` X-Tenant-Id)는 그대로.

**대화기록 규칙 재확인**: 사용자 전역 요청 = 모든 대화를 이 파일에 기록(이번 턴 반영). 커밋은 사용자 지시 전까지 보류.

### 23. voc-test 단독 검증 성공 + publish payload 로그 추가
- 사용자가 `POST /assist-stream/voc-test`(force=true)로 단독 검증: LLM 분석(mode=realtime)→publish(`dev:4609686:56356659:call:voc`, ok=true, 단독이라 수신자 0명)→callstat_voc 저장 모두 정상 확인(DB_DIRECT_CON=1 로컬 정적연결).
- "저장 안 됨" 오인 소지: `callstat_voc`는 `upsert(call_id,turn_idx)`라 **같은 callId+turnIdx 반복 시 같은 행 in-place 갱신**(신규 행 X) + **updated_at 컬럼 없음**(created_at만) → 타임스탬프/건수 변화 없어 미저장처럼 보일 수 있음. 새 행 보려면 turnIdx/callId 변경. (실제론 정상 저장됨, 사용자가 자체 확인 완료)
- **요청 반영**: publish 시 보낸 payload 전체를 로그에 추가. `publishVoc`(test)·`publishVocToChannel`(prod) 둘 다 `payload=${JSON.stringify(payload)}` 꼬리 추가. tsc/lint 0.

### 24. 실통화 프론트 미수신 디버깅 → 게이트 speaker 조건 제거로 해결(끝까지 연결 확인)
- **증상**: 실통화에서 프론트가 voc 미수신.
- **하위 레이어 전부 정상 확인**: 프론트 콘솔 `[chat-sub] 구독+room 참가 완료: dev:4609686:56356659:call:voc`, 백엔드 ACTIVE ROOMS `dev:4609686:56356659:call:voc → 1명`. 채널명 1글자도 안 틀림, Redis 구독자 1명. → 구독/room/채널명 문제 아님.
- **진짜 원인**: 실통화 경로(`handleNlpComplete`)의 게이트가 **고객 발화(isCustomer)에만** 열리도록 돼 있었음. 그런데 STT nlp:complete의 `speaker`가 이 환경에선 (고객 발화까지) `agent`로 오는 등 **고객 라벨이 불안정** → 게이트가 영영 안 열려 **publish 자체가 발생 안 함**(구독자는 있어도 서버가 안 쏘니 받을 게 없음). 사용자가 swagger voc-test에서 본 publish 로그는 force=true 단발 테스트 경로라 별개였음.
- **해결(사용자 제안)**: 게이트에서 **speaker 조건 제거** → 화자 구분 없이 `(totalTurns-1)%interval===0`(발화 1번째 + 이후 N턴마다)로 트리거. speaker는 여전히 buildConversation 맥락엔 포함(LLM이 화자 구분은 봄). `shouldRun(state)`로 시그니처 단순화, handleNlpComplete/handleUtterance 호출부·destructuring 정리(`isCustomer`는 accumulate 내부에서만 사용).
- **진단 로그 추가**: handleNlpComplete에 `실시간 VOC nlp 수신: ... totalTurns, gateOpen` 1줄(무음 스킵 가시화).
- **결과**: 재테스트 → 정상 동작(프론트 수신까지 끝단 연결 확인). 런타임 동작=watch 빌드 통과 의미.
- **남은 메모**: `customerTurns` 필드는 게이트에서 안 쓰게 됐지만 추후 화자별 분석 대비해 누적은 유지. 진단 로그는 운영 전 debug 레벨로 낮추거나 제거 고려.

### 25. GET /summary/data/{callstats_id} 상세조회에 VOC 3축 추가 (tsc/lint 0)
- **요구**: 콜이력 상세조회(`GET /summary/data/:callstats_id` → `getSummaryByCallstatsId` → `findSummaryByCallstatsId`)는 기존에 summary/keywords/external_categories만 반환. 여기에 emotion/complaintRisk/churnRisk 3블록 추가.
- **핵심 분석**: `emotions` 테이블 **PK=callstats_id**(`@PrimaryColumn`). 사용자는 call_id 조인을 예상했으나 **call_id 조인 불필요** — 기존 Summary/CallKeyword/CallCategory처럼 **callstats_id로 직접 find** 하면 됨. (emotions.call_id는 callstat_voc 조인용이지 상세조회용 아님)
- **타입 호환**: 엔티티 `sentiment_type: EmotionIconType` 과 DTO `EmotionDto.type: EmotionType` 둘 다 동일 유니온(negative/neutral/positive/etc) → 캐스팅 불필요.
- **구현**(`summary.service.ts` `findSummaryByCallstatsId`): `Emotion` 레포 추가 → `findOne({where:{callstats_id}})` → 매핑(emotion: sentiment_*, complaintRisk: complaint_risk_*, churnRisk: churn_risk_*). **null 허용**(VOC 이전 통화/저장 실패 시 행 없음 → 3필드 null). 반환타입 확장.
- **컨트롤러**(`summary.controller.ts`): 반환타입에 3필드 추가, `@ApiResponse` schema에 emotion/complaintRisk/churnRisk(nullable) 추가, EmotionDto/RiskAxisDto import.
- **주의**: 이 상세조회 응답 베이스 구조는 `summarizeCall`과 다름(여기엔 counselingTypes 없고 external_categories/Summary 필드 있음). VOC 3블록만 추가한 것. summary spec 없음 → 회귀 없음.

### 26. 관계자 공유용 안내문 작성 + 게이트 설계 2축 정리(코드 변경 없음, 문서/정책)
- **요청**: "고객 VOC 기능 추가 관련 안내" — 정책 위주, 너무 길지 않게. 프로세스 + 주요 이슈(예: 첫 대화 이후 3턴마다).
- **작성한 안내문 골자**(사용자가 조정 예정):
  1. 개요: VOC 3축(고객감정 4종/민원위험/이탈징후), 각 점수0~1+근거 한 문장, 맥락 기반(키워드 단순탐지 아님), 모델 gpt-4o-mini.
  2. 두 트랙: A 실시간(통화 중, 게이트 통과 시 분석→소켓 노출+턴별 저장), B 통화종료후(전체 종합평가→요약 API 응답 포함+통화당 1건 저장).
  3. 핵심 정책: 게이트=첫 발화+이후 3턴마다(REALTIME_VOC_INTERVAL로 무재배포 조정), 트리거는 화자무관 발화수 기준(STT 화자라벨 불안정), 감정 4종 통일.
  4. 저장/조회: 실시간=callstat_voc(턴별), 통화후=emotions(통화당1). 요약 API + 콜이력 상세조회 API 응답에 VOC 포함.
  5. 주요 이슈: LLM 비용→게이트로 빈도제어, 실시간 수신은 프론트가 채널 구독해야, 과거/누락 통화는 조회 시 null, 무발화(침묵)는 미트리거.
- **게이트 구축 방식 5종 정리**(LLM 앞단 결정적 게이트): ①턴기반(채택) ②키워드/정규식 즉시 ③시간 스로틀 ④슬라이딩 윈도우 ⑤적응형 상태머신. 권장 조합=키워드 OR 턴/시간.
- **중요 개념 정리(사용자 질문 "①과 ④ 차이?")**: 게이트는 **2개의 독립 축**이 섞여 있음 —
  - (A) **언제 분석(트리거)**: 턴/시간/키워드/적응형
  - (B) **무엇을 입력(범위)**: 전체 누적 vs 슬라이딩 윈도우(최근 N턴)
  - ①은 (A)축, ④는 (B)축 → 같은 표 비교 부적절, 서로 **조합**되는 별개 선택.
  - **현재 구현 = 트리거: 턴 기반(첫+3턴마다) + 입력: 전체 누적(상한 40턴)**. 슬라이딩 윈도우는 입력을 최근 N턴으로 줄이는 대안(토큰↓·최신민감 vs 초반맥락 놓쳐 오판 가능). 안내문 6번을 (A)/(B) 두 소절로 재구조화 제안(미반영, 사용자 결정 대기).

---

## 2026-06-11

### 27. 실시간 VOC 404 디버깅 → 근본원인 다단계 추적 → 프론트 company payload 폴백으로 해결 (tsc 0)

장시간 디버깅 세션. 실통화에서 실시간 VOC(`handleNlpComplete`)가 LLM 호출 시 **404**. 원인을 한 겹씩 벗겨냄.

**0. analyzeVoc 프롬프트 위치 확인(질문)**: VOC 분석 프롬프트는 외부 등록(promptName)이 아니라 **코드 내장(하드코딩)**. `summary.service.ts buildVocPrompt(conversation, mode)`(인라인 system/user) → `customComplete(messages)`. (요약/키워드는 `complete(promptName)` 외부 등록 방식 — 차이.) `classifyCounselingType`도 하드코딩.

**1. LLM_ORCHESTRATOR_HOST prefix 리팩터**: 코드가 `LLM_ORCHESTRATOR_PREFIX='/api/llm-orchestrator/v1'`를 하드코딩으로 붙이던 것 → **상수 제거**, env에 전체 경로 포함하도록 변경. `.env.development`/`.env.prod` = `https://dev-ecp-llm-orchestrator-service.langsa.ai/api/llm-orchestrator/v1`. (URL 자체는 net 동일 — 404 원인 아니었음.)

**2. 진짜 404 원인 — X-Tenant-Id 값 형식**: 같은 `customComplete`인데 요약(정상)과 실시간(404)의 **유일한 차이 = tenantId**.
  - 요약 경로: `getCompanyIdFromToken` → `currentUser.agent.company_id` = **`company_71900448_...`(회사 UUID)** → 200.
  - 실시간 경로(`voc-realtime.service.ts:171`): `msg.company_id ?? msg.tenant_id` → **`"57"`**(nlp redis 메시지의 숫자 company_id) → 404.
  - **오케스트레이터 직접 테스트로 확정**: `X-Tenant-Id=company_71900448_...` → **201 (토큰 없이도)**, `57`/`60`/`4609686`(vendor_tenant_id) 전부 → **404 `TENANT_NOT_FOUND`**. 응답코드: `{"error":{"code":"TENANT_NOT_FOUND","message":"테넌트(57)가 등록되지 않았습니다"}}`.
  - **결론**: 오케스트레이터는 **회사 UUID(company.id)만** X-Tenant-Id로 받음. **토큰은 불필요**(UUID만 맞으면 201). vendor_tenant_id·숫자 company_id 다 안 됨. 한 줄 수정(`msg.tenant_id` 사용) 불가.

**3. nlp 메시지 ↔ get_user 매핑 분석**:
  - nlp:complete 메시지: `tenant_id="4609686"`(=vendor_tenant_id), `agent_id="56356659"`(=cc_cti_id), `company_id="57"`(숫자), `call_id`.
  - get_user(POC4): `company.id=company_71900448_...`(UUID, 정답), `company.company_id="60"`(숫자), `company.vendor_tenant_id="4609686"`, `agent.cc_cti_id="56356659"`.
  - **중요 함정**: nlp `company_id="57"` ≠ get_user `company.company_id="60"` (같은 테넌트인데 숫자 불일치) → 숫자 company_id는 시스템 간 신뢰 불가 키. 신뢰 키 = vendor_tenant_id / cc_cti_id.
  - UUID는 `getCurrentUser(token)`로만 나옴(토큰 필수). nlp 경로엔 토큰 없음 → 변환 불가가 핵심 난점.

**4. 토큰 출처 추적 → AuthMiddleware exclude 발견(핵심 버그)**:
  - 실시간 경로(Redis 구독)는 토큰 없음 → 유일한 토큰 출처 = `callTokens`(assist-stream 컨트롤러가 `cacheToken(callId, req.token)`으로 채움).
  - 그런데 로그상 `hasToken=false`, `callTokensSize=0` 계속. callId는 일치 확인됨(assist-stream payload `callId=698590897500` == nlp `call_id`).
  - **근본 버그**: `app.module.ts`에서 **`assist-stream`이 AuthMiddleware `.exclude()`** 돼 있음 → `reqWithAuth.token=token`(auth.middleware:120) 미실행 → **`req.token`이 항상 undefined** → `cacheToken(callId, undefined)`는 `if(callId && token)`에서 막혀 **아무것도 저장 안 됨**. (RAG가 잘 됐던 건 RAG가 토큰 대신 placeholder `00000000-...`를 써서 가려졌음.)
  - **수정**: 컨트롤러에서 `x-auth-token` 헤더를 **직접 추출**(미들웨어와 동일 Bearer 정규화) → `cacheToken`에 전달. assist-stream exclude는 유지.

**5. 타이밍 경합 발견(수정 후 재테스트)**: 토큰 추출은 성공(`assist-stream 수신: hasToken=true`)했으나 VOC는 여전히 404. 로그 순서: **nlp:complete 처리(callTokensSize=0)가 먼저 → assist-stream 수신(hasToken=true)이 나중**. 즉 `nlp:complete`(프로세스 내 Redis, 빠름) > `assist-stream`(게이트웨이 경유 HTTP, 느림) 경합. query="안녕하세요"는 발화 종료 시점에 알 수 있어 assist-stream도 사실상 종료 시점 호출 → nlp가 매번 선착. 턴 게이트로 못 피함.

**6. 게이트 조정**: 턴1은 경합으로 토큰 미스 확률 높음 → **턴1 스킵, 턴2부터 발동**(이후 3턴마다). `shouldRun`: `totalTurns>=2 && (totalTurns-2)%interval===0` → 발동 턴 2,5,8,11…

**7. 최종 해결 — 프론트 company payload 폴백(채택)**:
  - 사용자 제안: 오케스트레이터가 토큰 없이 UUID만 있으면 되니, **프론트가 assist-stream payload에 `company`(get_user의 company) 정보를 실어 보냄**. 토큰 경합/미들웨어 전부 우회.
  - **DTO**: `AssistStreamCompanyDto`(id, vendor_tenant_id 필수 / company_id, name 옵션) + `AssistStreamRequestDto.company?`(`@IsOptional @ValidateNested`). **완전 옵션** — 안 보내면 기존 토큰 경로로만 동작(영향 0).
  - **캐시**: `VocRealtimeService.companyUuidByVendor: Map<vendor_tenant_id, company.id(UUID)>` + `cacheCompany(company)`(id&vendor_tenant_id 둘 다 있을 때만 저장). 컨트롤러가 `cacheToken`과 함께 `cacheCompany(dto.company)` 호출. **vendor_tenant_id 키 → callId/타이밍 무관, 프로세스 전역, 통화 끝나도 유지.**
  - **사용**(`handleNlpComplete`): 1순위 토큰 있으면 `analyzeEmotion(token)`(기존), 2순위 토큰 없으면 `msg.tenant_id`로 `companyUuidByVendor`에서 UUID 꺼내 `analyzeVocByTenant(uuid)`(토큰 없이). 둘 다 없으면 스킵.
  - **한계(사소)**: 그 테넌트의 첫 assist-stream 도착 전 nlp 발화는 캐시 미스로 스킵 → 하지만 **첫 도착 이후 모든 통화·턴이 타이밍 무관 해결**(vendor 키라 통화 넘어 유지). 매 통화 첫턴 새던 것과 차원 다름.

**전체 플로우 검증(End-to-End)**: assist-stream(헤더토큰+company) → cacheToken/cacheCompany → STT Redis nlp:complete → RedisMonitor 옵저버 → handleNlpComplete → 게이트(턴2,5..) → 토큰 or company UUID 해석 → analyzeEmotion/analyzeVocByTenant → 오케스트레이터 200 → publishVocToChannel(`:call:voc`) → persistVoc(`callstat_voc`). 다운스트림(CallstatVoc 엔티티 4곳 등록, 테이블 CREATE IF NOT EXISTS, getConnectionWithoutToken 폴백) 모두 정상 확인.

**변경 파일**: `llm-orchestrator.service.ts`(prefix 상수 제거), `.env.development`/`.env.prod`(host 전체경로), `assist-stream-request.dto.ts`(company DTO), `voc-realtime.service.ts`(companyUuidByVendor+cacheCompany, handleNlpComplete 토큰/company 분기), `assist-stream.controller.ts`(헤더 토큰 직접추출 + cacheCompany + Logger).

**검증**: tsc 0. **런타임 재검증은 프론트가 company payload 추가 + 서버 재시작 후 필요**(사용자가 프론트에 전달 예정). 남은 정리: handleNlpComplete의 `[VOC-DEBUG]` 로그는 동작 확인 후 debug 레벨로 낮추거나 제거.

**핵심 교훈(기록)**: 디버깅을 단편적으로 하지 말 것 — 전체 플로우(프론트 payload→미들웨어→토큰→Redis 이벤트→LLM 호출)를 처음부터 끝까지 한 번에 트레이스했으면 ① X-Tenant-Id 형식, ② AuthMiddleware exclude, ③ 타이밍 경합을 더 빨리 묶어 찾았을 것. 오케스트레이터 같은 외부 의존은 **직접 호출(curl)로 입력값별 응답을 먼저 확정**하는 게 추측보다 빠름.

### 28. 프론트 company payload 적용 완료 + 배포 환경변수(IS_REALTIME_VOC_CHECK) 주입 방법 논의 (코드 변경 없음, 정책/지식)

**프론트 작업 완료**: 프론트가 assist-stream payload에 `company`(id, vendor_tenant_id) 추가 + 테스트 완료. → 섹션 27의 company 폴백 경로로 실시간 VOC 정상 동작 확인.

**배경 질문**: `IS_REALTIME_VOC_CHECK=true`일 때만 실시간 VOC를 돌리고 싶은데, 개발은 로컬이고 배포는 젠킨스인데 **서버의 env 구조(env.prod, docker 형식)를 알 수 없음**. 서버 env 파일을 직접 못 고치는 상황에서, 로컬에서 커밋만으로 서버에 반영하는 가장 쉽고 안전한 방법은?

**핵심 발견 — `.env.*` 는 서버에 안 들어간다**:
- `.dockerignore`에 `.env.local/.env.development/.env.test/.env.production` 전부 등재 → `COPY . .` 시 **이미지에 미포함**. 컨테이너 안에 `.env.development` 자체가 없음.
- ConfigModule(`app.module.ts:16-18`)은 `.env.${NODE_ENV}` + `.env`를 읽지만, 그 파일이 이미지에 없으니 결국 **`process.env`(컨테이너 환경변수)만** 사용.
- 즉 **`.env.development` 수정·커밋은 서버 반영 0%.** 서버 config = docker-compose `environment:` 또는 젠킨스/k8s 주입(사용자가 못 건드리는 곳).
- 추가: 레포의 `.env.prod`는 ConfigModule이 찾는 `.env.production`과 이름도 안 맞아 어차피 안 읽힘.

**서버 반영 방법 — 우선순위**:
```
docker-compose environment:  >  Dockerfile ENV  >  코드 기본값(configService default)
   (서버측, 못 건드림)            (커밋 가능 ✅)        (커밋 가능 ✅)
```
- **추천 = Dockerfile `ENV IS_REALTIME_VOC_CHECK=true`**: Dockerfile은 이미지 빌드에 무조건 사용되므로 젠킨스 구조와 무관하게 확실. compose에 같은 변수가 없으면 그대로 먹음(현재 두 compose 모두 이 변수 없음). 나중에 인프라가 compose에서 override 가능.
- `docker-compose.prod.yml`의 `environment:`에 넣는 건 "서버가 그 파일을 실제로 쓴다"는 가정 필요 → 불확실하므로 차선.
- 코드: `configService.get('IS_REALTIME_VOC_CHECK') === 'true'`로 읽고 **없으면 false(기본 OFF, 안전)**. `true`일 때만 nlp 구독 등록(미구현 — 사용자가 배선 보류, 추후).

**docker-compose.dev.yml ↔ .env.development 불일치 점검(사용자 요청)**:
- compose에 **`env_file:` 지시어 없음** → compose는 `.env.development`를 **아예 안 읽음**(두 파일 연결고리 자체가 없음).
- compose `environment:`엔 ~12개만 정의. `USER_HOST`/`LLM_ORCHESTRATOR_HOST`/`SEARCH_HOST`/`REDIS_*`/`DB_DIRECT_CON`/외부호스트들/`IS_REALTIME_VOC_CHECK`/`REALTIME_VOC_INTERVAL` 등 **핵심 변수 대거 누락**. DB값도 placeholder(`dev_user/dev_password/asst_dev`).
- 결론: **이 committed `docker-compose.dev.yml`은 실제 배포본 아닐 가능성 큼**(이대로면 앱 정상 기동 불가). 실제 서버 env는 젠킨스/서버측 다른 경로에서 주입. → **개발서버 구축 시점에 env 주입 방식 확정 후 정리하기로 함**(지금은 로컬 동작 우선).

**문서 기록 위치 이전 시도**: 대화기록을 `minuee_timbel_docs/nohsn_docs/asst-service/`로 옮기려 했으나, 해당 폴더가 macOS 파일권한(EPERM)으로 Claude 도구 접근 불가(`/add-dir` 재추가로도 안 풀림). → 원본(`asst-service/CLAUDE-history.md`) 갱신 후 사용자가 `cp`로 복사하는 방식으로 운용.

### 29. SEARCH_HOST → AICM_HOST 통합 (RAG 답변/문서원본을 새 AICM 서버로 마이그레이션) (tsc 0, 테스트 27 통과) (2026-06-11)

**배경**: 새 AICM 서버(`192.168.101.192`, mock 단계)가 설치됨. 기존 `AICM_HOST`(`https://dev-ecp-aicm-service.langsa.ai`) → `http://192.168.101.192:8173`(nginx 권장, :32012 직접)로 변경. 추가로 기존 `SEARCH_HOST`(`54.116.103.216:5101`)로 하던 RAG 작업도 새 AICM 서버로 **통합**하기로 결정.

**조사 결과(소스 grep)**:
- `AICM_HOST` 사용처 = `knowledge-proxy.controller.ts` 1곳(엔드포인트 5개: search/retrieve_doc·indexes/get_doc_idx·sections/get_section·docs/get_doc·dashboard/popular). 이건 host만 8173로 바꿔 끝 — dashboard/popular 200 확인. 처음 409는 프론트 workspace_id(`019d65ea…`)가 mock 서버에 없어서였고, mock workspace_id(`019bfe5d-d00f-74c9-b6f6-416a9bfa1dc6`)로는 200. **코드 버그 아님, 데이터 이슈**.
- `SEARCH_HOST` 사용처 = 3개 서비스: `assist-stream.service`(`POST /assist-stream`), `search.service`(`POST /stream`), `document.service`(문서원본). 모두 `/api/v1/rag/assist-stream`·`/api/v1/documents/{id}/original` 호출.
- `SEARCH_REPOSITORY_ID` = 위 2 서비스에서 `repository_id` payload로만 사용. AICM `rag_assist`는 `repository_id` 개념이 없고 **`workspace_id`** 사용 → **이 변수 불필요(죽음)**. `SEARCH_DOCUMENT_TYPE_IDS` = 코드에서 env로 **아예 안 읽힘**(완전 dead). → 3개 SEARCH_* env는 그대로 두되 **미사용**(rename 불필요).

**새 AICM 서버 실측 스펙(openapi :32012/openapi.json)**:
- RAG 답변: `POST /api/aicm/v1/search/rag_assist` — body 필수 `workspace_id`,`query` + `enable_distill`(기본 true),`conversation_history` / 헤더 **`X-auth-token` 필수**(mock은 값 미검증, 더미 OK, 헤더 없으면 422). SSE 이벤트 `intent→query_analysis→sources→…→done` 실측.
- 문서원본: `GET /api/aicm/v1/docs/original/{document_id}` — 헤더 `X-auth-token` 필수(없으면 422, dummy면 200 실측).

**코드 변경(6파일)**:
- `assist-stream.service.ts`·`search.service.ts`: host `SEARCH_HOST`→`AICM_HOST`, 경로 →`/api/aicm/v1/search/rag_assist`, payload `repository_id/distill`→**`workspace_id/enable_distill:false`**(기존 동작=distill 미사용 유지), 헤더 `X-Tenant-Id`(하드코딩 0…)→**`X-auth-token: token||'dummy'`**. `stream()`에 `token` 인자 추가.
- `document.service.ts`: host→`AICM_HOST`, 경로 →`/api/aicm/v1/docs/original/{id}`, 헤더→`X-auth-token`. `getOriginal()`에 `token` 인자.
- 컨트롤러 3개: `assist-stream`(이미 헤더서 추출한 `token` 전달, 이 라우트는 AuthMiddleware **제외**라 헤더 직접 추출), `search`(`req.token` 전달, AuthMiddleware 적용), `document`(`@Req()` 추가해 `req.token` 전달).
- DTO 2개(`assist-stream-request`,`search-request`): **`workspace_id`(snake_case) 옵션 추가**(배포 전환기 안전 위해 required 아님 — 사용자 요청). ⚠️ 처음 camelCase(`workspaceId`)로 넣었다가 프론트가 snake_case `workspace_id`로 보내 `forbidNonWhitelisted` 400 발생 → **snake_case로 정정**(프론트·AICM 필드명과 end-to-end 일치). `repositoryId`는 deprecated로 남김.

**테스트**: 영향 spec 갱신(`assist-stream.service.spec`: AICM_HOST/새 payload/URL/X-auth-token, `assist-stream.controller.spec`: mockReq `headers:{}` + 4번째 인자 + VOC mock `cacheCompany` 보강). 27개 전부 통과, tsc 0.

**미해결/주의**:
- 프론트가 `/stream`·`/assist-stream` 호출 시 body에 **`workspaceId`** 실어야 함(없으면 AICM 422). dashboard/popular과 동일 workspace_id 사용.
- mock→실 user-service 전환 시 어드바이저 경로는 더미토큰 거부될 수 있음(실 토큰 필요). `enable_distill`은 현재 false 고정(요약 켜려면 true).
- `/voc-test`(VOC 실시간)는 `REALTIME_VOC_INTERVAL`만 쓰고 RAG relay와 무관 → 이번 변경 **영향 없음**.

### 30. 실시간 VOC 트리거를 상시 Redis 옵저버 → /assist-stream 호출 시로 변경 (tsc 0, 테스트 27 통과) (2026-06-11)

**증상**: 수동 문서검색 `/stream` 호출 중에도 고객 VOC 탐지가 도는 것처럼 보임. 사용자 요구: 실시간 VOC 는 **`/assist-stream`(실시간 발화) 호출 시에만**, `/stream`(수동검색)에선 절대 안 돼야 함.

**원인(코드 확인)**:
- `/stream`(SearchService)은 VOC 코드를 호출하는 곳이 **0곳**(grep 확정) — `/stream` 자체는 VOC 못 돌림.
- 진짜 트리거는 `VocRealtimeService.onModuleInit`이 등록하던 **상시 Redis `nlp:complete` 옵저버**. 앱 기동 시 무조건 등록돼 공용 dev Redis(`dev-ecp-redis.langsa.ai`)의 **모든 통화 발화**를 받아 VOC 분석 → HTTP 경로와 무관하게 백그라운드 상시 동작(그래서 `/stream` 칠 때도 도는 것처럼 보임).
- `IS_REALTIME_VOC_CHECK` 는 **코드 어디서도 안 읽는 죽은 플래그**(env에만 존재) → 사용자가 env에서 제거(주석처리).

**안전성 확인(다른 시스템 영향 없음)**: `RedisMonitorService.registerMessageObserver`는 콜백 배열(`messageObservers`)에 push만 함(채널 구독 신규 안 함). `notifyMessageObservers`가 각 옵저버를 try/catch 격리 호출. **VOC가 이 옵저버의 유일한 등록자**(호출처 1곳)라 떼면 배열만 비고 중계 파이프라인/다른 구독 무관. 코칭 소켓 등 다른 구독은 `redisService.subscribe()` 직접 경로라 별개. → 채널 unsubscribe 0건, 다른 시스템 영향 0.

**변경**:
- `voc-realtime.service.ts`: `OnModuleInit` 인터페이스/`onModuleInit`(옵저버 등록) **제거**. `handleNlpComplete`는 향후 재배선 대비 dead 코드로 남김(주석 명시). `redisMonitorService` 주입은 유지(무해).
- `assist-stream.controller.ts`: 토큰 캐시 직후 `void this.vocRealtimeService.handleUtterance(dto, token)` **fire-and-forget** 추가 → 실시간 발화(=/assist-stream)일 때만 VOC(누적→게이트 REALTIME_VOC_INTERVAL→분석→publish→저장). SSE 응답 안 막음(handleUtterance 내부 예외 격리).
- `/stream`·`/voc-test` 코드 무변경.

**주의**: 이미 기동된 프로세스엔 **이전 module init 때 등록된 옵저버가 살아있음** → 적용하려면 **서버 풀 재시작 필요**(watch 재컴파일만으론 기존 옵저버 안 빠질 수 있음). 검증: 재시작 후 로그에 "실시간 VOC: nlp:complete 구독 옵저버 등록 완료"가 **안 떠야** 정상. `/assist-stream` 스트리밍 정상 동작 실측 확인.

### 31. 192 개발기(API Gateway 없음) 배포용 환경 전환 — .env.development + docker-compose.dev.yml (2026-06-11)

**배경/방침**: CI/CD 배포 시스템은 일단 미사용, **192 개발기에 git clone 후 Docker 직접 기동**. 외부 노출 포트 정책: 32010번대=인프라, 32020번대~=업무서비스(개발기간 32020~32030, 온프레미스 패키징 때 재정리 예정). **192 개발기엔 API Gateway 미설치**(이태희 수석 미배치, 윤 수석 인계 확인 필요) → 게이트웨이(langsa.ai) 경유하던 outbound 호출을 **각 백엔드 서비스 직접 주소로** 전환.

**연동 서비스 정보(전달받음, 게이트웨이 없음)** — 호스트포트 / timbel_network 내부DNS(:8080):
| 서비스 | 호스트포트 | 내부DNS |
|---|---|---|
| tenant-management-service | 192.168.101.192:32030 (/api/v2) | tenant-management-service:8080 |
| user-service | 192.168.101.192:32031 (/api) | user-service:8080 |
| auth-service | 192.168.101.192:32032 (/api) | auth-service:8080 |
| tenant-mgmt-web | 192.168.101.192:32033 | tenant-mgmt-fe:8080 |
| ecs-api-service | 192.168.101.192:32034 (/api) | ecs_api_service:8080 |

**핵심 분석(Explore 조사) — asst-service가 실제 코드에서 호출하는 활성 외부 env는 6개**:
- USER_HOST(✅user-service), AICM_HOST/SEARCH_HOST(✅이미 192.168.101.192:8173), CE_HOST, LLM_ORCHESTRATOR_HOST, AUDIO_STREAMER_HOST, QA_HOST, REDIS.
- **USER_HOST**: `/api/user/*`,`/api/organization/*`,`/api/configs/get_configs?filters=db_config`(테넌트 db_config=DB 연결 시작점) 붙임 → 받은 user-service base `/api`와 일치.
- **auth-service = 매핑 env 없음**: AuthMiddleware가 토큰 **추출만 하고 외부검증 안 함**("토큰 검증 더 이상 사용 안 함" 주석). `AUTH_SERVICE_API_URL`은 .env.prod에만 있고 코드 **dead**.
- **TENANT_HOST/LLM_HOST/AUDIO_SERVICE_API_URL = dead**(validation.config.ts에만, 코드 미사용). 받은 5개 중 asst-service가 쓰는 건 **user 하나뿐**(tenant/ecs/web 무시).

**사용자 결정**: ① "모름" 호스트(CE/LLM-orchestrator/audio/redis)는 현 .env.development(langsa.ai) **그대로 유지** ② 실행=**192 서버 + timbel_network 내부** ③ DB=**동적연결 DB_DIRECT_CON=0** ④ 외부포트=**32099**.

**변경(코드 0, 설정 2파일)**:
- `.env.development`: `USER_HOST` langsa.ai→**`http://user-service:8080`**(내부DNS, 기존값 주석보존). `DB_DIRECT_CON` 1→**0**. AICM/SEARCH(8173)·CE/LLM-orch/audio/redis(langsa.ai) 유지.
- `docker-compose.dev.yml`: ⚠️기존 compose가 env를 inline으로만 박아 **.env.development 호스트값이 컨테이너에 주입 안 되던 누락** 발견 → **`env_file: .env.development` 추가**, inline DB env(dev_user/asst_dev) 제거. ports `31001`→**`32099:3000`**. networks `asst-network`(bridge)→**`timbel_network`(external)**. ⚠️Dockerfile CMD가 `NODE_ENV=production` 강제 → compose **`command`로 `NODE_ENV=development node dist/src/main` override**(스키마 마이그레이션 로직 정상화).

**미해결/확인필요**: ① `timbel_network` 네트워크 이름 정확 일치 여부(`docker network ls`). ② DB_DIRECT_CON=0이라 user-service가 주는 db_config가 가리키는 DB가 **192망 내부에서 접근**돼야 함(아니면 30s 타임아웃). ③ CE/LLM-orch/audio/redis는 여전히 langsa.ai → 192망에서 그 망 접근 가능해야 동작(불가 시 추후 192 주소로 교체). ④ 실 user-service 전환 시 어드바이저 경로 더미토큰 거부 가능.

### 32. 192 개발기 배포 트러블슈팅 전 과정 — 빌드 성공~테이블 생성까지 (2026-06-11)

#31 설정 이후 실제 192 서버에 git clone→docker 기동하며 막힌 것들을 순서대로 해결. **결과: 배포 완료**(헬스체크 200, redis 연결, DB 직결, advisor 테이블 생성). 도커 가이드 문서 `docs/docker-deploy-guide.md` 신규 작성.

**환경 확정값(192)**:
- 외부포트 **32025** (32020번대만 방화벽 개방, **32099는 막힘** — netstat은 LISTEN인데 외부 접속 불가로 확인). `docker-compose.dev.yml` ports `32099→32025`.
- redis: `redis:7-alpine`이 `192.168.101.192:32014`(호스트포트)로 떠있음. **비TLS** → `.env.development` `REDIS_HOST=192.168.101.192`,`REDIS_PORT=32014`,`REDIS_TLS=false`,`REDIS_PASSWORD=nMzwaa7!U3Z!`(timbel123!는 WRONGPASS였음, redis-cli ping으로 확정).
- DB: 테넌트 DB 미연동이라 **`DB_DIRECT_CON=0→1` 직결**로 전환. postgres `postgres:17` 컨테이너(ID `4c6fda...`)가 `192.168.101.192:32011`. `.env.development` `DB_HOST=192.168.101.192`,`DB_PORT=32011`,`aicc_admin`/`HPr2!txYB!`/`aicc`.
- Dockerfile `FROM node:20-alpine→node:24-alpine`(사용자 요청, 로컬 v24.16.0 일치).
- USER_HOST는 #31대로 `user-service:8080`(내부DNS) 유지.

**겪은 에러→원인→해결(도커 핵심 학습)**:
1. **브라우저 접속 불가(서버 localhost:32099는 200)**: 외부 방화벽이 32099 미개방 → 32025(개방 범위)로 변경.
2. **`ECONNREFUSED 127.0.0.1:5432/32011`**: 직결인데 `DB_HOST=127.0.0.1` → **컨테이너 안 127.0.0.1=자기자신**. host를 `192.168.101.192`로. (port만 32011로 바꾸고 host를 안 바꿔 두 번 반복됨)
3. **redis 연결 타임아웃**: 비TLS redis에 `REDIS_TLS=true` → false로.
4. **commitlint/eslint pre-commit 막힘**: 커밋 메시지 `type:` 형식 필수(`feat`/`chore` 등 13종, `dev` 불가), `socket.gateway.ts` unused `stats` lint(사용자가 로그 주석 해제로 해결).
5. **`relation advisor.notices does not exist`(42P01)**: 스키마 껍데기만 있고 **테이블 없음**.

**테이블 생성 해결(중요)**:
- `synchronize`는 `NODE_ENV==='local'`에서만 켜짐. 배포는 `development`라 OFF → 빈 DB에 핵심 테이블(notices 등) 자동생성 안 됨.
- **함정**: 사용자가 `database.config.ts`의 synchronize를 development로 바꿨으나 무효 → 이 파일은 **never wired up**(실제 연결은 `dynamic-database.service.ts`). 게다가 `'development로'` 한글오타까지.
- **또 함정**: `docker-compose.dev.yml`의 `NODE_ENV`는 `command:` 안 값이 적용(Dockerfile CMD가 production 박음) → environment만 바꾸면 무효.
- **해결책**: 코드 수정 말고 **일회성 `NODE_ENV=local`**(compose의 command+environment 2곳 sed) → 재기동 → synchronize가 전체 테이블 생성 → **development 원복**. (빈 DB라 안전)
- `advisor-schema-ddl.sql`은 **MySQL 문법(`INT(1)`,`ON UPDATE CURRENT_TIMESTAMP`,인라인 COMMENT)+구버전이라 PG에서 사용 불가** — 폐기 권고.

**남은 것**: CE/LLM-orch/audio는 langsa.ai 유지(미배포). 테넌트 DB 준비되면 `DB_DIRECT_CON=1→0`(동적연결)으로 복귀.

### 33. 프론트(asst-web) 192 배포 + 게이트웨이 없는 환경 CORS 활성화 (2026-06-12)

백엔드 배포 후 프론트(asst-web)도 같은 192에 도커 배포하며 막힌 것 해결. **결과: 프론트↔백엔드 연동 완료.**

**프론트 배포 정보**: 외부 주소 `http://192.168.101.192:32026`(컨테이너 내부 webpack-dev-server 32082). 도커 빌드 이슈 2건:
- `yarn install`이 `yarn.lock` 없이 "Resolving packages..." 무한대기 → `package-lock.json`만 있으니 **`npm ci`로 통일**(Dockerfile).
- `npm ci`가 retry 반복 → `.npmrc`가 `@timbel-aicc` 스코프를 **GitHub Packages(npm.pkg.github.com)** 에서 받게 돼있어 폐쇄망/인증 이슈. ⚠️ `.npmrc`에 GitHub PAT(`ghp_...`)가 평문 커밋돼 있음 → 빌드 해결 후 **토큰 revoke 권고**.

**경로 형태 확정**: 게이트웨이가 붙여주던 `/aicc/asst-service/**`(StripPrefix2→PrefixPath `/api/asst/v1`)는 192엔 게이트웨이가 없으므로 **프론트가 직접 `/api/asst/v1/...`** 로 호출해야 함(백엔드 `setGlobalPrefix('/api/asst/v1')`). 즉 프론트 base를 `/aicc/asst-service`→`http://192.168.101.192:32025/api/asst/v1`로 교체. 소켓도 `/api/asst/v1/socket.io` 직접.

**CORS 문제(핵심)**: 프론트(32026)→백엔드(32025) cross-origin인데 CORS 에러. 원인은 `main.ts`가 **CORS를 `NODE_ENV==='local'`에서만 활성화**(주석: "배포는 게이트웨이 globalcors가 단일 처리"). **192엔 게이트웨이가 없어 백엔드·게이트웨이 둘 다 CORS 미제공** → 차단(401도 CORS헤더 없어 CORS로 표시되던 것).
- **해결(코드)**: `main.ts` CORS 조건을 `NODE_ENV===local || !!CORS_ALLOWED_ORIGINS`로 확장, origin은 `CORS_ALLOWED_ORIGINS`(쉼표분리) 우선·없으면 기존 `ALLOWED_ORIGINS_DEV`. `docker-compose.dev.yml` `CORS_ALLOWED_ORIGINS=http://192.168.101.192:32026`(trailing slash 없이 — Origin 헤더와 매칭). **코드변경이라 `--build` 필요.**
- **로컬 무영향 확인**: `.env.local`엔 CORS_ALLOWED_ORIGINS 없음→local은 기존과 동일 동작. compose.dev.yml은 배포전용(로컬 start:dev는 미사용). 기존 게이트웨이 배포도 env 미설정시 기존대로.

**남은 것**: `/proxy/user/get_user` 등 401 발생 시 프론트 인터셉터가 `x-auth-token`/`Authorization`을 싣는지 확인(proxy는 게이트웨이 무관·asst-service 내부기능이라 구조 동일). `.npmrc` GitHub 토큰 revoke.

### 34. CE 프록시 502 → 192 ce-service 직접연결 (2026-06-12)

`/proxy/ce/nlu-catalog/intents/all` **502 Bad Gateway**. asst 프록시가 업스트림 CE에 못 닿은 것.
- **원인**: `CE_HOST`가 아직 `dev-ecp-ce-service.langsa.ai`(langsa.ai) → 192망에서 **timeout**(`curl` 확인). 게이트웨이 없는 192에선 langsa.ai 미접근.
- **발견**: `docker ps`에 **`ce-service:latest`가 `0.0.0.0:32021->8080`** 으로 떠있음(192에 CE 존재).
- **해결**: `.env.development` `CE_HOST`·`CE_API_URL` → **`http://192.168.101.192:32021`**(호스트포트). `.env`만이라 빌드 불필요, 재기동만.
- **검증**: CE 직접 `curl /api/ce/v1/nlu-catalog/intents/all` → **401**(timeout/404 아님 = 연결·경로 OK, 토큰만 필요). ce-proxy 코드는 `Authorization: Bearer ${req.token}`로 올바르게 forward(헤더 일치 — `searchDocuments`만 예외적으로 `X-Auth-token` 사용). 유효 토큰 첨부 시 200 확인.
- **결론**: 401은 전부 **프론트 토큰 첨부** 문제로 수렴(get_user·CE 동일). 백엔드 프록시는 정상.

**남은 langsa.ai 호스트**: `LLM_HOST`/`LLM_ORCHESTRATOR_HOST`/`AUDIO_STREAMER_HOST`도 동일 패턴 예상(192망 timeout) → 해당 기능 쓸 때 192에 서비스 있으면 `docker ps`로 찾아 호스트포트로 교체.

### 35. 로컬 CORS ACAO 중복 해결 — main.ts CORS 조건 정리 (2026-06-12)

로컬(프론트 `localhost:8173` → 게이트웨이 `localhost:8080` 경유)에서 get_user Axios **`ERR_NETWORK`**. 브라우저 콘솔: `Access-Control-Allow-Origin header contains multiple values 'http://localhost:8173, http://localhost:8173'`. curl(브라우저 아님)은 200+정상데이터 → **CORS 확정**.
- **원인**: 게이트웨이(globalcors) + asst-service(`NODE_ENV=local`이라 `enableCors`)가 **둘 다 ACAO 헤더를 붙여 중복**. 브라우저는 ACAO 단일값만 허용. (192는 게이트웨이 없어 asst 단독→문제없었음)
- **해결**: `main.ts` `corsEnabled`를 `NODE_ENV===local || !!CORS_ALLOWED_ORIGINS` → **`!!CORS_ALLOWED_ORIGINS`만**으로 변경. 로컬(.env.local에 CORS_ALLOWED_ORIGINS 없음)→asst CORS off→게이트웨이 단일처리. `npm run start:dev` 재시작으로 적용.
- **192 무영향**: 192는 `NODE_ENV=development`라 원래도 local조건 안 탔고 `CORS_ALLOWED_ORIGINS=...:32026`으로 켜짐 → 변경 전후 동일. (이 main.ts 변경 자체는 다음 192 배포 때 반영, 동작 동일하므로 급하지 않음)
- **교훈**: 게이트웨이 경유 환경은 CORS를 게이트웨이가 단일 처리. 백엔드가 추가로 켜면 ACAO 중복. "백엔드에 CORS 추가"는 중복 악화 — **한쪽만** 켜야 함.

### 36. 콜테스트 양산 redis 의존 / FortiGate VPN — 인프라 대기 (미해결, 2026-06-12)

다음주 192 개발서버 시연(AICC 콜봇+어드바이저)의 **실콜 테스트가 안 되는 상황**. 구조 파악 결과:
- **콜 흐름**: NICE CXone(`cxone.niceincontact.com`) → 양산 STT/NLP → **양산 redis(`dev-ecp-redis.langsa.ai:6379` TLS, AWS)** 로 통화 이벤트 발행 → asst-service가 구독 → 실시간 보조. (테스트 HTML `docs/advisor-call-test.html`은 CXone SDK 테스트용, redis 직접 무관)
- **콜이력 저장은 양산 DB 아님** — 각 환경 자체 DB(로컬=127.0.0.1, 192=32011)에 저장. 로컬이 양산 DB정보 없이 콜테스트 되던 게 증거 → **양산 종속은 redis(통화이벤트) 하나로 좁혀짐**.
- **차단 원인**: ECP-AI(=`*.langsa.ai`) 배포 서비스는 이제 **FortiGate VPN 없이는 외부 접근 불가**로 정책 변경(CE/redis 등 192 timeout의 근본 원인). 로컬은 VPN으로 redis 접속됨(코드·설정 정상 증명). 192는 서버라 클라이언트 VPN 불가 → **인프라가 서버단 경로(사이트-투-사이트/방화벽) 열어야**.
- **요청 사항(콜 인프라 담당자)**: ① 192→`dev-ecp-redis.langsa.ai:6379` 경로 개방(AWS면 192 아웃바운드+AWS SG 인바운드 양쪽), ② 대안: 통화이벤트를 192 redis(32014)로도 발행, ③ 로컬용 macOS FortiClient+프로파일(받은 게 Windows용이라 맥 설치 불가).
- **상태**: 코드/설정 완료, **인프라 경로 개방 대기**. 열리면 즉시 콜테스트 가능.

### 37. 192 개발서버 모니터링 — 브라우저 실시간 로그 뷰어(Dozzle) 도입 (2026-06-12)

192는 도커 배포(게이트웨이 없음)인데, 서버 로그를 매번 SSH 들어가 `docker compose logs -f` 로만 봐야 해 "Swagger처럼 브라우저에서 실시간 로그"를 원함.
- **분석**: 코드엔 이미 모니터링 자산이 있으나 192에서 미가동 — ① OpenTelemetry(`src/tracer.ts`, SigNoz용 OTLP gRPC)는 `OTEL_EXPORTER_OTLP_ENDPOINT` 미설정이라 OFF, ② winston 파일로그(`logs/` 30일 로테이트), ③ health 엔드포인트(`/health/check`, `/health/db-connections`).
- **결정**: SigNoz(Level2)는 ClickHouse 등 무거워 개발기 1대엔 과함 → **Dozzle(컨테이너 1개, 도커소켓 read-only)** 채택. `docker compose logs -f` 를 브라우저로 보는 것 + 검색/멀티컨테이너.
- **구성**: `docker-compose.monitor.yml`(포트 **32027**, asst 배포와 분리된 독립 컨테이너) + `monitor-data/users.yml`(simple auth). 접속 `http://192.168.101.192:32027`, **admin / lena47**.
- **함정·해결**: Dozzle **v10은 sha-256 비번 폐기 → bcrypt 필수**(`fatal: sha256 passwords are no longer supported` → 로그인 무한로딩). `docker run --rm amir20/dozzle generate admin --password lena47 --name admin --email nohsn@timbel.net > monitor-data/users.yml` 로 bcrypt(`$2a$...`) 재생성 후 해결. compose `version` obsolete 속성도 제거.
- **특성**: Dozzle은 도커소켓 기반이라 **asst뿐 아니라 호스트 전체 컨테이너 로그**(postgres/redis/user/ce 등)를 봄 → 서비스간 연관 디버깅에 유리. 단 타 서비스 로그 노출되므로 **인증 필수**, 더 좁히려면 `DOZZLE_FILTER=name=asst-service-dev`.
- **git 인증 트러블슈팅**: 192(Cursor 서버) `git fetch/pull` **401** — Cursor `GIT_ASKPASS`(askpass-main.js)가 만료 자격증명 자동제출(입력창 안 뜸) + GitLab이 PAT 요구. 해결: `git remote set-url origin 'https://oauth2:<PAT>@gitlab.timbel.dev/...'` 후 fetch, 또는 일회성 `GIT_ASKPASS= git fetch 'https://oauth2:<PAT>@...'`. 서버정렬은 pull(충돌) 대신 `git fetch && git reset --hard origin/develop_nohsn`.
- **문서**: `docs/docker-deploy-guide.md` 10번 섹션(Dozzle), 신규 `docs/git-server-sync-guide.md`(git 401/PAT + reset 서버정렬). 커밋 `b71c2ed fix: 모니터링 환경 설정` 등으로 배포 완료.

### 38. wav STT 콜 시뮬레이션 — 소켓 룸 0명 디버깅 (프론트가 엉뚱한 asst 인스턴스 접속) (2026-06-16)

`run_wav_stt.sh`(wav→STT→redis 발화 발행, 양산 redis 의존 우회)로 콜 시뮬레이션 시, 대화 자막·assist-stream RAG는 화면에 뜨는데 로그에 `⚠️ NO CLIENTS IN ROOM: 'dev:4609686:56356659:call:nlp:complete' (0 clients)`. "이전과 다르다, 룸 번호가 안 맞는 것 같다"며 스크립트(`run_wav_stt.sh`)의 `TENANT_ID`/`AGENT_ID`를 계속 수정 중이었음.

**구조(3단 정렬 필요)**: ① asst RedisService가 redis 채널 subscribe → ② 수신 시 채널명과 **글자 그대로 같은** 소켓 룸으로 broadcast(`broadcastToRedisMonitorRoom`, room명=redis 채널명) → ③ 프론트가 `join-room`으로 같은 이름 룸 참여. **소켓 join-room(③)과 redis subscribe(①)는 완전 별개** — 룸에 들어가 있어도 asst가 그 채널 subscribe 안 하면 broadcast 자체가 안 일어남.

**데이터로 하나씩 소거(추측 배제)**:
- `GET /api/asst/v1/redis-monitor/status`(x-auth-token 필요): `subscribedChannels`에 5개 콜채널(events/nlp:complete/nlp:partial/voc/orchestrator:persisted) **전부 구독됨 ✅** → ① 빵꾸 아님. `socketRooms` 5개 전부 `exists:false, clientCount:0` → 룸 이름은 ①과 동일, **이름 불일치 아님**.
- **대화 흐르는 중에도** 같은 curl → 여전히 5개 룸 0명. 근데 화면엔 데이터 나옴 → **화면 자막은 소켓이 아니라 REST(`dev:call:{callId}:turn:data` 정렬셋 폴링)로 그려짐**(스크립트가 그 Lua로 정렬셋 만드는 이유). 소켓 broadcast 경로는 클라 0명.
- 토큰(JWT) 페이로드 = `cId=60, ad=412627, acc=agent40, cd=POC4`. user-service `get_user`(`/api/asst/v1/proxy/user/get_user`)로 실제 식별자 확인 → `company.vendor_tenant_id=4609686 ✅`, `agent.cc_cti_id=56356659 ✅`. **스크립트 id 4609686/56356659는 정확.** (agent UUID `agent_349727fe...`, tenant UUID `tenant_7b72c2eb...` = 스크립트 주석의 그 값) → **id 불일치 아님, 스크립트 손대면 안 됐던 것.**

**결론(범인)**: 스크립트 id 맞음 + asst 구독 다 됨 + 룸 이름 정렬 다 맞음 + 그런데 소켓 룸만 0명 → **프론트 대시보드의 소켓이 데이터 흐르는 asst(124.194.32.36:32025)에 안 붙어 있었음**(다른 asst 인스턴스/주소에 접속). 같은 redis를 여러 asst가 구독하면, 프론트가 붙은 인스턴스만 룸에 클라가 있어 broadcast가 닿고, 안 붙은 인스턴스(우리가 curl한 124)는 같은 nlp 이벤트를 받아도 룸이 비어 "0 clients" 경고. 사용자: "프론트가 잘못 접속해 있는 게 맞다" 확인 → 프론트 접속 주소를 124.194.32.36:32025로 수정 후 재테스트 예정.

**교훈**: ①"0 clients 룸 경고 + 화면엔 데이터" 조합 = 화면은 REST 경로, 소켓은 다른 인스턴스 의심. ②**API와 소켓을 같은 asst 인스턴스로** 붙여야 함(소켓만 딴 데면 같은 증상). ③검증=대화 흐르는 중 `/redis-monitor/status`의 `socketRooms[].clientCount≥1`. ④로그 시각으로 접속 유무만 추론하면 헛다리 — `redis-monitor/status`로 구독·룸·클라수를 한 번에 직접 비교하는 게 정확.

### 39. agent-status 소켓 룸 0명 — 프론트가 join-room 누락 (2026-06-16)

상담 종료 시 `[AgentStatusSocketHandler] ⚠️ Room에 연결된 클라이언트 없음: agent-status (0명)`. 근데 `REALTIME STATS: 1명 연결` + ACTIVE ROOMS엔 coaching/notices/`dev:...:call:*` 룸은 1명씩 있는데 **`agent-status`만 없음**.
- **원인**: 이 소켓 서버는 룸 자동 join이 아니라 **클라가 `join-room` 이벤트를 직접 emit해야** 참여(`socket.gateway.ts:312 handleJoinRoom`). 프론트가 다른 룸엔 join하면서 `agent-status`만 빠뜨림. 서버 broadcast(`broadcastToAgentStatusRoom`)는 정상 — 받는 클라가 0명일 뿐.
- **해결(프론트)**: connect 직후 `socket.emit('join-room', 'agent-status')` + `socket.on('agent-status-update', ...)`. 재연결 시 룸 멤버십 날아가니 `on('connect')` 안에 둘 것. 서버/이벤트명=`agent-status-update`, 룸명=`agent-status`(`agent-status-socket.handler.ts:27,53`). → 프론트 적용 후 `agent-status → 2명` 확인.

### 40. orchestrator:persisted 미수신 + 요약팝업 — run_wav_stt.sh에 라이프사이클 publish 추가 (2026-06-16)

상담 종료 시 프론트가 `...:call:orchestrator:persisted`로 요약팝업을 띄우는데 안 뜸.
- **분석**: `orchestrator:persisted`는 **asst가 publish 안 함 — 오케스트레이터 서비스가 발행**(asst 소스에 publish 0건, `run_wav_stt.sh:199` 주석 근거). asst는 Redis→Socket **가공없이 verbatim 중계**(`redis-monitor.controller.ts:413 handleChannelMessage`). 구독은 정확채널(패턴X), `POST /redis/subscribe/:channel`로 등록. 이 테스트엔 오케스트레이터가 없어 persisted가 영영 안 나감.
- **agent_id 매칭**: 프론트 전역필터가 `agent_id`를 cc_cti_id와 비교. `voc` 채널은 asst가 `agent_id=cc_cti_id`로 **덮어써 발행**(`voc-realtime.service.ts:500,517`)하지만, nlp/events/persisted는 **verbatim**이라 업스트림이 넣은 값 그대로. → persisted가 긴 agent_id면 프론트가 버림.
- **해결(테스트 스크립트 `run_wav_stt.sh`)**: ① 콜시작 시 `call:events`(type=start) publish(프론트 `isInit=false`→"콜 집계 중", 없으면 "상담한 콜이 없습니다"), ② 종료 시 `call:orchestrator:persisted` 직접 publish(오케스트레이터 흉내). agent_id=`${AGENT_ID}`(cc_cti_id), `callstats_id`(=프론트 버튼 활성화 게이트)+`call_id` 포함. 채널 `dev:${TENANT_ID}:${AGENT_ID}:call:orchestrator:persisted`(로그의 룸명과 글자 동일 확인).
- **⚠️ 미해결 연쇄**: 버튼은 켜지지만 누르면 `/summary`가 그 callstats_id로 **DB(raw_call.callstats_call/turn)** 조회 → 테스트는 turn을 Redis에만 넣어 DB행 없음 → 404(45번 참조). asst의 redis 구독 여부는 publish 반환 `수신(구독)자 수`로 확인.

### 41. LLM 오케스트레이터 404 = TENANT_NOT_FOUND + 임시 테넌트 override (2026-06-16)

실시간 VOC가 `LLM Custom Complete 404`. "서버 먹통 같다"고 의심.
- **진단(서버 정상)**: 엔드포인트 직접 curl → 빈body 400, 헤더 넣으면 404 `{"code":"TENANT_NOT_FOUND","message":"테넌트(company_ea847481_...)가 등록되지 않았습니다"}`. **서버·경로 정상, 그 회사UUID가 오케스트레이터에 미등록**이라 404. (`X-Tenant-Id`=company UUID, 설계상 맞는 값 — `voc-realtime.service.ts:82` 주석.) 두 테넌트 직접 검증: `company_ea847481_...`→404, `company_71900448_...`→201(LLM응답 정상). **등록된 건 71900448, ea847481은 미등록**(사용자 기억과 반대).
- **해결(임시, 코드)**: `llm-orchestrator.service.ts` — `complete`/`customComplete`의 `X-Tenant-Id` 세팅 직전 `resolveTenantId()`로 치환. env `LLM_TENANT_OVERRIDE_MAP="원본:대체"`(쉼표 다중쌍), **`NODE_ENV===local||development`에서만** 동작(운영 안전). env 미설정/운영이면 무동작. `.env.5f.development`·`.env.development`에 `company_ea847481_...:company_71900448_...` 추가.
- **배포 함정(핵심)**: 적용 안 됐던 진짜 이유 = `up -d --force-recreate`는 **이미지 재빌드 안 함**. Dockerfile이 `COPY . . && npm run build`로 **dist를 이미지에 굽는** 구조(볼륨마운트X) → `.ts` 변경은 **`--build` 필수**. `docker compose -f docker-compose.dev.5f.yml up -d --build --force-recreate`. 부팅로그 `[임시] LLM 테넌트 오버라이드 활성화`, 호출시 `[임시] LLM 테넌트 치환: ea847481→71900448` 뜨면 성공.

### 42. 실시간 VOC 게이트 제거 — assist-stream 호출마다 무조건 분석 (2026-06-16)

실시간 VOC가 발화 턴 2,5,8…에서만 발동(`shouldRun`: `totalTurns>=2 && (totalTurns-2)%interval===0`, interval=`REALTIME_VOC_INTERVAL` 기본3). 매 호출 분석 원함.
- **구조**: 트리거 진입점은 `POST /assist-stream`→`handleUtterance` 하나뿐. nlp:complete redis 구독경로(`handleNlpComplete`)는 현재 **비활성**(과거 onModuleInit 옵저버 제거됨). `call:events` 종료신호를 VOC로 소비하는 코드는 **없음**(사용자 가정과 다름).
- **해결(코드)**: `assist-stream.controller.ts:77` `handleUtterance(dto, token)` → `{ force: true }` 추가(이미 설계된 게이트 우회 옵션). `shouldRun`은 그대로 둠(nlp경로 재활성 대비). 이 경로는 토큰을 HTTP로 직접 받아 게이트의 "1턴 토큰경합" 사유가 애초에 무관 → 안전. `--build` 필요.

### 43~45. DB 스키마 드리프트 — 바꿔낀 DB가 ORM보다 뒤처져 연쇄 에러 (2026-06-16)

`.env.5f.development`의 `DB_DATABASE`를 `company_ea847481_...`로 바꿔 직결(`DB_DIRECT_CON=1`, 124.194.32.36:32011). 이 DB 스키마가 엔티티보다 구버전이라 엔드포인트가 줄줄이 깨짐.
- **43) `coachings/requests/sender/:key` 500**: 테이블 `advisor.coaching_requests`에 엔티티가 선언한 `customer_name`/`sender_name` 컬럼 **없음**. `create_advisor_schema.sql:103` 정의에 그 컬럼 없고, `runSchemaMigrations`는 그 컬럼을 **`coachings`에만** 추가(`coaching_requests`엔 안 함). dev는 synchronize OFF. `findAndCount`가 전체컬럼 SELECT → `column does not exist` → 메서드에 try/catch 없어 500. **수정案**: `runSchemaMigrations`에 `addColumnIfNotExists('coaching_requests','sender_name'/'customer_name')` 2줄(미적용, 보류).
- **44) `assist-stream/snapshot` 500**: 테이블 `advisor.callstat_assist_snapshot` **자체가 없음**. `runSchemaMigrations`가 안 만들고 수동 SQL(`create_callstat_assist_snapshot_table.sql`)로만 생성 — 이 DB엔 미적용 → `relation does not exist`.
- **45) `POST /summary` 404**: 라우트 정상(`@Controller('summary')+@Post()`). 앱이 던지는 `NotFoundException` — `summarizeCall`이 `raw_call.callstats_call`(id)·`callstats_turn`(callstats_id)을 DB조회하는데 그 callstats_id 행이 없음(테스트는 turn을 Redis에만 넣음, `/summary`는 Redis 폴백 없음). 테이블자체 없으면 500이었을테니 **테이블은 있고 행만 없는 것**.
- **공통 원인/방향**: 스키마 반영 3경로(① synchronize=local만, ② runSchemaMigrations=advisor 일부만, ③ 수동 migrations/*.sql) 중 이 DB엔 ③이 덜 적용됨. `migrations/*.sql` 재실행은 `CREATE TABLE IF NOT EXISTS`라 **이미 있는데 컬럼만 빠진 건 못 고침**(이름만 보고 스킵) → 빠진 컬럼은 `ALTER ADD COLUMN`으로. **권장=읽기전용 information_schema로 엔티티↔DB 3-way diff 후 멱등 reconciliation DDL**(보류, 담당자 협의). 사용자 결론: "당장은 두고 나중에 엔티티 문제되면 그때 수정."

### 46. callstat 상세응답에 voc 추가 + raw_call 읽기전용 분석 (2026-06-16)

**(a) `GET /callstat/calls/:id`에 voc 추가(완료)**: 응답 `{call,turns,entities,keywords,snapshots}`에 `voc` 1depth 추가. 소스=`advisor.emotions`. `advisor.service.ts findCallstatDetailById`에서 Emotion 레포를 `callstats_id=call.id`(PK, turns/entities와 동일 기준)로 `findOne`, 없으면 `voc:null`. 매핑: `sentiment_type/score/description`→`emotion.{type,score,summary}`, `complaint_risk_*`→`complaintRisk`, `churn_risk_*`→`churnRisk`(=`VocAnalysisDto`=summary/real-voc 동일구조, null컬럼은 0/''폴백). `callstat.controller.ts` Swagger에 voc(nullable, VocAnalysisDto) 문서화 + `@ApiExtraModels`. 타입체크 통과. `--build` 필요. **주의**: `emotion.type`은 4종 아이콘(negative/neutral/positive/etc)이라 예시의 "angry"(5종)와 다름(테이블 저장값이 아이콘타입). 조회키는 callstats_id(=callstats_call.id) — call_id 기준이 맞으면 키만 교체.
**(b) `raw_call.callstats_call` 사용분석**: asst는 이 테이블 **읽기 전용**(write/DDL 0건) — 통화통계는 외부서비스가 적재, asst는 조회만. 중심=`advisor.service.ts`(findCallstatDetailById 등 callstat 조회들), 집계=`call-stats.service.ts`(QueryBuilder), summary(id조회), todo(consumer_phonenumber 조인). **결론**: raw_call은 asst 비소유 → "DB를 ORM에 맞추기"는 거꾸로, 엔티티를 실제테이블(공통 부분집합)에 맞춰야. `find()/findOne()`은 엔티티 전체컬럼 SELECT라 "엔티티 컬럼 ⊆ 접속DB 컬럼"이어야 안전 — 지금 OK, 다른 raw_call DB(컬럼셋 다름)로 바꾸면 `find()` 엔드포인트 500 위험. 사용자: 문제되면 그때 엔티티 수정.

### 47. 로컬 CORS — get_user (localhost:8173) 차단, .env.local에 CORS_ALLOWED_ORIGINS 추가 (2026-06-16)

로컬 프론트(`localhost:8173`)→로컬 백엔드(`localhost:3000`) `/proxy/user/get_user` CORS 에러.
- **원인**: `start:dev`(NODE_ENV=local)는 `.env.local`→`.env` 로딩. 둘 다 `CORS_ALLOWED_ORIGINS` **없음** → `main.ts:69 corsEnabled=!!CORS_ALLOWED_ORIGINS`가 false → `enableCors` 미호출 → CORS OFF. (main.ts:71-75 `ALLOWED_ORIGINS_DEV` 폴백은 `if(corsEnabled)` 안이라 **죽은 코드**.)
- **해결**: `.env.local`에 `CORS_ALLOWED_ORIGINS=http://localhost:8173,http://localhost:3000,http://127.0.0.1:8173` 추가. `x-auth-token`은 이미 허용헤더(`environment.constant.ts:33`)라 preflight 통과. **로컬 dev 서버 재시작만**(도커 아님, --build 불필요). 35번(게이트웨이 경유시 ACAO 중복)과 달리 여긴 게이트웨이 없는 직결이라 백엔드가 CORS 켜는 게 맞음.

---

## 2026-06-17

### 48. VOC 고객감정 — 3종 → 5종 확장 (emotion_prompt.md 기준) (tsc/lint 0)

**요구**: VOC 3축 중 **감정(emotion) 1축만** `docs/emotion_prompt.md`의 5종 기준으로 교체. 민원위험/이탈징후 2축은 그대로. **DB 컬럼 구조 변경 없음.** 단 sentiment_type 값은 치환 없이 LLM 5종 영문을 **그대로 저장**.

**핵심 합의(이해 정정 2회)**:
- (1차 오해) 5종→3종 치환 저장 ❌. (정정) **치환 없이 5종 영문 그대로 저장.**
- 기존 `negative/neutral/positive`는 **이미 저장된 데이터 호환용 레거시**라 남김. 앞으로는 5종만 저장.
- 결과적으로 `sentiment_type` 가질 수 있는 값 = 레거시 3종 + 신규 5종 = **8종**(사용자 결정: `etc` 제거).
- 발견: `sentiment_type` 에 **CHECK 제약**(`emotions`/`callstat_voc` 둘 다, `IN ('negative','neutral','positive','etc')`)이 실제로 있음 → 5종 그대로 저장하려면 CHECK 확장 불가피(컬럼 구조 변경은 아님).

**확정값**:
- 신규 5종 영문키: `angry`(화남) / `dissatisfied`(불만) / `normal`(일반) / `satisfied`(만족) / `thanks`(감사). (일반은 기존 neutral과 키 충돌 피해 `normal`)
- CHECK 8종: 레거시 3종(negative/neutral/positive) + 신규 5종. etc 제거.
- 매핑/치환 함수 **신설 안 함**(저장부 emotion.service.ts:27, persistVoc, 이력조회 summary.service.ts:1004 모두 이미 값 그대로 통과 — 섹션 21에서 매핑 삭제됨).

**변경 파일(코드 4개)**:
- `emotion.entity.ts`: `EmotionIconType`/`EMOTION_ICON_TYPES` 8종으로(레거시3+신규5, etc 제거).
- `summary-response.dto.ts`: `EmotionType`/`EMOTION_TYPES` 8종, **`NEW_EMOTION_TYPES`(신규 5종) 신설**, `EmotionDto` 설명 5종 기준+레거시 안내로 갱신.
- `summary.service.ts`: `buildVocPrompt` 감정 정의를 emotion_prompt.md 5종(정의/판단신호/우선순위 angry>dissatisfied>satisfied>thanks>normal/감사 과대검출 주의)으로 교체, JSON 예시 type=`angry`. `parseVocResponse` allowed=`NEW_EMOTION_TYPES`(신규 5종만 통과, 레거시는 LLM이 출력 안 함). `analyzeVoc` fallback emotion.type `neutral`→`normal`.
- `dynamic-database.service.ts` `runSchemaMigrations`: 두 CREATE TABLE의 CHECK를 8종으로+DEFAULT `neutral`→`normal`. 기존 배포 DB용 **멱등 ALTER**(DROP CONSTRAINT IF EXISTS `{table}_sentiment_type_check` → ADD, 인라인 자동 제약명) 추가, 테이블별 개별 try/catch 격리. ⚠️기존 데이터에 `etc` 행이 있으면 ADD CONSTRAINT 실패(그 테이블만 스킵) — etc 없다는 전제.

**안 건드린 것**: `migrations/*.sql`(사용자 관리 영역, 섹션 18 규칙). 실제 반영은 runSchemaMigrations 담당. → 일관성 위해 사용자가 `create_emotion_table.sql`/`create_callstat_voc_table.sql`의 CHECK도 8종으로 갱신 권장(기록용).

**프론트 전달 문서 작성**: `docs/voc-emotion-5type-frontend.md` — 5종 표/레거시 3종 fallback 처리/값 받는 위치(소켓 voc 채널, /summary, /summary/data, /callstat/calls)/체크리스트. complaintRisk·churnRisk 무변경 명시.

**비대칭(인지된 한계)**: 실시간/요약 응답은 5종, 콜이력 상세조회는 과거건이면 레거시 3종이 나옴(DB 미변경이라 불가피). 프론트가 8종 모두 매핑.

**검증**: tsc 0, eslint 0, etc 잔존참조 0. **런타임 검증(실통화/재시작 후 5종 출력+CHECK 확장 적용)은 사용자 재시작 필요**(코드/스키마 배선만 검증).

### 49. 실시간 소켓 emotion payload 구조 확인(프론트 질문) + emotion score 설계 논의 → 미반영 결정

**프론트 질문**: 실시간 voc 소켓 payload 의 emotion 에 `type` 외 `sentiment_type` 필드가 따로 오는지.
- **확인 결과(코드+git)**: 소켓 payload 는 `emotion: voc.emotion` = `{ type, score, summary }` **하나뿐, `sentiment_type` 필드 없음**(과거에도 추가된 적 없음 — `voc-realtime.service.ts` payload 블록 `:516-523`/`:568-575`). `sentiment_type` 은 DB 저장(`callstat_voc` upsert `:472`)에만 등장. 프론트가 쓰던 `emotion.type` 이 곧 그 값이고, 별도 `sentiment_type` 은 없음. 이번 변경으로 그 `type` 값만 3종→5종으로 바뀜(구조 동일).
- **답변**: `emotion.type` 한 필드로 내려감. 5종(angry/dissatisfied/normal/satisfied/thanks)으로 바뀐 것뿐.

**emotion score 설계 논의(결론: 미반영)**:
- 현재 3축 score 는 모두 **LLM 이 직접 책정**, 백엔드는 `Math.max(0,Math.min(1,x))` 클램프만(구간→type 변환 로직 없음. type/score 독립).
- complaint/churn 은 "0 없음~1 매우높음(위험)"으로 의미 명확하나 emotion.score 는 의미 정의가 느슨(LLM 자율 "강도").
- 논의: emotion.score 를 위험도 방향(높을수록 위험)으로 통일 + 유형별 구간(thanks 0~0.2 … angry 0.8~1.0) + 구간내 미세조정안까지 검토. 미세조정은 "위험 방향"이어야 함을 확인(긍정유형은 강할수록 0쪽, 부정유형은 강할수록 1쪽 — 단순 "강도 위쪽"은 thanks/satisfied 에서 거꾸로).
- **사용자 최종 결정: 프롬프트에 score 구간/미세조정 규칙 넣지 않음.** emotion.score 는 기존대로 LLM 자율(0~1) 유지. 이번 작업은 **5종 감정 변경만으로 확정**(섹션 48 상태 그대로, 추가 코드 변경 없음).

### 50. POST /summary·이력조회 404 — callstats_id 가 call_id 로 와도 동작하게 fallback (tsc/lint 0)

**증상**: `POST /summary` 404 `통화 통계를 찾을 수 없습니다: test-call-id-...`. "어제는 됐는데 갑자기".
- **원인(데이터)**: `raw_call.callstats_call` 은 `id`(PK, 예 `call_07ddaf31_...`) 와 `call_id`(예 `test-call-id-...`) 가 **별도 컬럼**(섹션 17). `summarizeCall` 은 `where:{id:callstats_id}` 로 **id(PK)** 를 찾는데, 프론트가 **call_id 값**을 callstats_id 로 보냄 → id 로는 미존재 → 404. (어제는 프론트가 id 를 보냈거나 데이터가 달랐던 것. 코드는 git diff 상 무변경 — 5종 작업은 조회 로직 안 건드림.)
- **함정**: fallback 만으로 부족 — `summarizeCall` 의 turn 조회(`callstats_turn.callstats_id`)·emotions 저장도 파라미터 callstats_id 를 그대로 써서, call_id 로 callstatCall 을 찾아도 turn 에서 또 0건. **이후 조회/저장을 모두 실제 PK(callstatCall.id) 기준으로** 통일해야 함.

**수정(3곳, 동일 패턴 — id 로 찾고 없으면 call_id 로 fallback → 실제 PK 로 후속 조회)**:
- `summary.service.ts summarizeCall`(`POST /summary`): callstatCall = id||call_id 조회, `resolvedCallstatsId = callstatCall.id` 도입 → turn 조회·`saveEmotion` 모두 resolvedCallstatsId.
- `summary.service.ts findSummaryByCallstatsId`(`GET /summary/data/:id`): CallstatCall 레포 추가, 동일 fallback → summary/call_categories/call_keywords/emotions 4개 조회 모두 resolvedCallstatsId.
- `advisor.service.ts findCallstatDetailById`(`GET /callstat/calls/:id`): `call` 을 id||call_id 로 fallback(이후 로직은 이미 call.id 기준이라 자동 일관).

**효과**: 프론트가 id(PK) 든 call_id 든 셋 다 200. 내부 조회/저장은 항상 callstats_call.id 기준이라 turn/emotions 매칭 일관(emotions PK 도 진짜 id 로 저장).

**확인된 정상 동작**: 보여준 emotions 행들은 전부 created_at=06-16(어제) 라 sentiment_type 이 레거시(neutral/negative) — 옛 코드 산물, 정상. 오늘 재시작 후 새 통화부터 5종 저장. (LLM 실패 fallback 행은 'neutral 0.0' → 이제 'normal').

**검증**: tsc 0, eslint 0. **런타임은 사용자 재빌드(124 도커 `--build`)/재시작 후 확인 필요.**

### 51. (시연 트러블슈팅) fallback OR 강화 + emotions 미저장 진짜 원인 = STT 의 callstats_turn 미적재 (tsc 0)

오전 11시 시연 직전 디버깅. "최근 통화 emotions 저장 안 됨 / GET /summary/data 404" 증상을 한 겹씩 벗김.

**오해 → 진짜 원인 추적 순서**:
1. (오해) emotions CHECK 4종이 5종을 막는 줄 → **DDL 확인 결과 이미 8종**(ALTER 정상 적용됨, thanks 포함). CHECK 무관.
2. (오해) saveEmotion 코드 문제 → 코드 정상(call_id/sentiment_type 다 채움).
3. (진짜) `POST /summary` 가 `통화 턴 데이터가 없습니다` 404 → emotions 저장 **이전 단계(callstat_turn 조회)** 에서 막힘. `callstat_voc`(실시간)는 turn 안 써서 정상 → 둘의 차이가 단서였음.
4. **근본 원인**: `raw_call.callstats_turn` 에 그 통화의 대화 턴이 **아예 없음**. asst 는 이 테이블 **읽기 전용**(grep 결과 save/insert/upsert 0건, find 만) — 적재는 **외부 STT/콜인프라** 몫. 그날 **STT 담당자의 데이터 적재 로직 오류**로 callstats_turn 이 안 쌓여서, asst 가 요약할 대화가 없어 404 → emotions 도 못 생김. **asst 코드(요약/VOC/이번 수정) 전부 정상.**
   - 관계: `callstats_turn`(원천 대화) → POST /summary 가 읽어 LLM 분석 → `emotions`(결과). 직접 FK 아님, `callstats_id`(=callstats_call.id) 공유로 연결. turn 없으면 emotions 없음.

**이번에 한 코드 보강(50번 이어서, OR 강화)**:
- `summary.service.ts summarizeCall`: turn 조회를 `idCandidates`(요청값 + callstatCall.id + callstatCall.call_id, dedupe) **OR 조회**로. saveEmotion 은 `resolvedCallstatsId`(=callstatCall.id) 로 통일.
- `summary.service.ts findSummaryByCallstatsId`: `whereAny`(같은 후보 OR)로 summary/category/keyword/emotions 4개 조회.
- `advisor.service.ts findCallstatDetailById`: call 을 id||call_id fallback.
- **OR 안전성**: where 후보를 늘리는 것이라 **기존 id 조회는 1순위 그대로 처리(회귀 없음, superset)**. id·call_id 둘 다 통화당 유니크라 다른 통화 오염 불가.

**상태**: 시연은 turn 있는 과거 통화(call_xxx)로 정상 진행. **로컬 작업분(48~51) 아직 서버 미배포** — 시연은 기존 서버 코드로 돌아 무관했음. 사용자가 **로컬에서 회귀 테스트(특히 진짜 id 호출이 기존과 동일한지) 후 문제없으면 그대로 유지** 예정. 커밋/배포는 추후.

### 52. 응답 시간 UTC→KST 전역 변환 인터셉터 (tsc/lint 0)

**문제**: 프론트에 노출되는 시간(특히 DB 조회 제공 시간)이 **UTC 기준이라 9시간 빠르게** 보임. DB 시간 컬럼이 대부분 `timestamptz`(UTC 저장) → TypeORM Date → JSON 직렬화 시 `...Z`(UTC ISO)로 나감. `main.ts`에 응답 직렬화 인터셉터가 없었고(ValidationPipe만), 코드의 `toISOString()`은 전부 로그·소켓용이라 HTTP 응답 본문 변환은 부재.

**결정(사용자 확정)**: 프론트 무수정 → **백엔드 글로벌 응답 인터셉터**로 일괄 변환. 포맷 **A = ISO 8601 + `+09:00` 오프셋**(`2026-06-17T10:30:00.000+09:00`). 표준이라 프론트가 그대로 표시해도, Date 로 재파싱해도 안전.

**구현**:
- 신규 `src/common/interceptors/timezone.interceptor.ts` (`TimezoneInterceptor`): 응답 본문 재귀 순회하며 `Date` → KST ISO(+09:00) 치환(절대시각 유지, 표기만 KST). 순환참조 WeakSet 방어.
- `main.ts`: `app.useGlobalInterceptors(new TimezoneInterceptor())` (useGlobalPipes 직후).

**한계(기록)**:
- 엔티티 `Date` 필드만 변환됨(TypeORM 이 Date 로 읽는 timestamptz 등). **raw 쿼리(QueryBuilder `getRawMany`)가 시간을 문자열로 반환하면 변환 안 됨**(call-stats 통계 등 — 필요 시 별도 처리).
- **SSE/소켓 등 `@Res()` 직접 응답엔 미적용**(HTTP 응답 본문 한정). 소켓 payload 시간은 별도.
- timestamp(타임존 없음) 컬럼(config/group)도 Date 로 읽히면 동일 변환되나, 저장 자체가 tz 없는 값이라 의미는 주의.

**검증**: tsc 0, eslint 0. 런타임은 재시작 후 GET 응답의 created_at/updated_at 이 `+09:00` 로 나오는지 확인 필요.

### 53. 시간 KST 노출 — 2차 보강(문자열 ISO 변환 + TZ=UTC) → 완전 해결 (tsc/lint 0, 런타임 검증 완료)

52의 인터셉터(Date 만 변환)로는 대부분 페이지가 그대로 UTC 노출. 실제 응답값 확인하며 두 겹을 추가로 잡음.

**관찰된 실제 응답값**:
- `created_at`: `"2026-06-17T15:11:04.718+09:00"`(정상) ← `timestamptz` 가 **문자열**로 직렬화돼 옴(`...+00:00`). Date 가 아니라 인터셉터가 못 잡고 있었음.
- `started_at`/`ended_at`: `"...06:10:48.634+09:00"`(9시간 부족, 오류) ← `callstat_call` 의 이 두 컬럼만 **`timestamp`(타임존 없음)**.

**원인 2겹**:
1. DB 시간이 `Date` 가 아니라 **타임존 명시된 ISO 문자열**(`+00:00`/`Z`)로 응답에 옴 → 52 인터셉터(Date instanceof)가 우회됨.
2. `started_at`/`ended_at` 은 `timestamp(no tz)` 라, node-postgres 가 **서버 로컬 TZ(KST)로 파싱** → 절대시각이 9시간 어긋남(읽는 순간 틀어짐, 인터셉터 +9 로는 복구 불가, 게다가 서버 TZ 마다 어긋남이 달라짐).

**해결(2곳, 둘 다 한 군데씩)**:
- `timezone.interceptor.ts`: `Date` 뿐 아니라 **타임존이 명시된 ISO 문자열**(`/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$/`)도 KST(+09:00)로 변환. 오프셋 없는 문자열·UUID·일반텍스트는 매칭 안 돼 안전(node 로 케이스 실증).
- `main.ts`: `process.env.TZ = 'UTC'` 한 줄 → `timestamp(no tz)` 를 UTC 로 일관 파싱 → started_at 절대시각 정상화 → 인터셉터가 정확한 KST 로. `timestamptz` 는 절대시각이라 영향 0.

**엔티티 타입 분류(참고)**: `timestamptz` = 콜 created_at/updated_at, bookmark/todo/intent-feedback/callstat-voc/keyword/snapshot. `timestamp(no tz)` = **callstat_call.started_at/ended_at**, config/group/agent/notice/favorite/keyword-detect 의 created_at/updated_at.

**검증 완료(런타임)**: 재시작 후 `started_at 06:10 → 15:10`, `ended_at → 15:13`, `created_at 15:11` 전부 같은 시간대로 정상. 사용자 확인 완료.

**배포 시 권장**: 도커 환경엔 `docker-compose`/`Dockerfile` 에도 `TZ=UTC` 를 넣어두면 환경 무관하게 확실(main.ts 런타임 설정의 안전망). formatDateTime(콜이력 목록 일부 경로)을 타는 화면이 있으면 그건 오프셋 없는 문자열이라 별도 정리 필요(현재 미발생).

## 2026-06-19

### 54. 5f 서버 STT 미수신 — Redis 연결 하루 뒤 죽음(redisConnected:false) → 무한 재연결+자가 헬스체크로 근본수정 (tsc 0, 런타임 복구 확인)

**증상**: 5f 서버에서 상담전화 시작부터 STT 메시지가 프론트로 **아예 안 옴**. "아침부터 갑자기". 코드 변경 없었고(테스트 완료 상태), 5f redis 는 원래부터 `dev-ecp-redis.langsa.ai`.

**진단 과정(데이터로 좁힘)**:
1. redis-cli 로 `dev-ecp-redis.langsa.ai`(TLS) ping → PONG. 직접 PSUBSCRIBE 후 실제 통화 걸어보니 `dev:{vendor}:{cti}:call:nlp:partial/complete`, `call:events` 가 **redis 까지 정상 도착**. → redis·publisher(STT) 정상, 채널명 규칙도 코드 기대값과 일치(채널 변경 아님).
2. `GET /redis-monitor/status` → **`redisConnected:false`** 인데 monitoredChannels/subscribedChannels 에 STT 채널 다 있고 socketRooms 에 프론트 3명 join 됨. = 구독 등록·소켓룸·프론트 다 정상, **asst 의 redis 소켓 연결만 죽음**. health/check 는 ok(프로세스는 살아있음).

**근본 원인(왜 5f 만, 왜 하루 뒤)**:
- `dev-ecp-redis.langsa.ai` → CNAME → `timbel-dev-callbot-pub-nlb-...elb.ap-northeast-2.amazonaws.com` (AWS **public NLB**, 3.37.104.111 / 52.78.5.55).
- AWS NLB 특성: **idle timeout 약 350초 + 끊을 때 FIN/RST 없이 silent drop** → 클라이언트는 half-open(죽은 줄 모름).
- AWS 프로덕션은 통화 24시간 상시라 연결이 idle 될 틈이 없어 안 끊김. 5f 는 테스트라 통화 뜸 → 밤사이 긴 idle → NLB 가 조용히 끊음 → asst half-open.
- 게다가 코드가 **재연결 10회 초과 시 Error 반환=영구 포기**(`redis.service.ts` reconnectStrategy) + `redis-monitor.service.ts` health check 가 끊김 감지해도 실제 `reconnect()` 미호출(주석만) + `startHealthCheck()` 호출처도 없음 → 한 번 죽으면 자력 복구 불가. 다음 통화의 `POST /redis-monitor/subscribe/{ch}` 가 `ensureRedisConnected→reconnect` 를 우연히 트리거할 때까지 죽어있음(분석 중 그 경로로 한 번 살아남).

**해결(근본수정, 사용자 확정 후)** — 파일 3곳:
- `redis.service.ts` ① reconnectStrategy(client/subscriber 둘 다) **10회 포기 제거 → 무한 재연결**(로그는 초기10회+이후10회마다). ② **자가 헬스체크 추가**: `onModuleInit→startHealthCheck()`, 주기마다 client/subscriber **PING+5초 타임아웃**으로 half-open 감지(`isOpen=false` 또는 PING 무응답 → `reconnect()`). PING 이 keepalive 도 겸해 NLB idle 예방. `disconnect()` 에 타이머 clear. 기존 `reconnect()` 의 구독 자동복구 로직 재사용.
- `redis.config.ts` health_check_interval 기본 **30000→180000(180초)**. 이 값이 node-redis pingInterval + 자가 헬스체크 주기 공통 제어. (주기는 사용자가 180초 선택 — NLB 350초보다 짧게. `REDIS_HEALTH_CHECK_INTERVAL` 로 override 가능)

**효과**: 통화 없는 새벽에 NLB 가 끊어도 최대 180초+α 안에 asst 가 자력 감지·재연결·구독복구. 도커 재가동(임시방편) 불필요해짐. tsc --noEmit 0. (배포: develop 커밋 후 5f 1회 재시작 필요. 확인: status 가 시간 지나도 redisConnected:true 유지 + 로그 `🩺 Redis 자가 헬스체크 시작`.)

### 55. assist-stream 1~2초 지연 — 백엔드 결백, AICM rag_assist 검색시간이 범인 (구간분해 로그로 실측 확정, tsc/lint 0)

**증상**: 프론트(로컬 npm run dev → 빠름 / 배포 도커 asst-web-dev 32026 → 느림)에서 assist-stream 첫 sources 도착까지 1~2초. 프론트는 "백엔드가 AICM 호출 *전* 단계에서 1~2초 먹는다"고 주장. A/B 둘 다 백엔드는 동일(asst-service 도커 32025).

**진단 단계(추측 배제, 측정으로 확정)**:
1. 코드 확인: `assist-stream.service.ts` 는 **얇은 SSE 릴레이** — `${AICM_HOST}/api/aicm/v1/search/rag_assist`(124.194.32.36:8173) 로 fetch 후 청크를 `res.write` 로 그대로 중계만. sources/intent/search/distill/generate stages 는 전부 AICM 이 생성(asst 는 통과). SSE 헤더도 모범(X-Accel-Buffering:no, flushHeaders). VOC(`handleUtterance`)는 `void` fire-and-forget(컨트롤러에서 stream 전 호출). AuthMiddleware 는 assist-stream `exclude`(app.module) → 미들웨어 외부호출 없음.
2. `docker stats`: asst-service-dev **CPU ~0%(피크 7%)**, MEM 109MB/62.5GB, limit 없음 → **사양/경합/CPU바운드 전부 기각**. 1~2초가 CPU 작업이면 스파이크가 떴어야 함.
3. 핵심 통찰: 백엔드 동일 → `inToFetch`(백엔드 내부시간)는 A/B 물리적으로 동일해야 함. 프론트 측정값은 네트워크 경로가 섞여 **오염**됨 → 백엔드 자기 시계 로그만이 네트워크 무관·일괄적 진실.
4. 측정 사각지대 발견: 기존 latency 로그 시작점(`tIn`)이 stream() 진입이라 그 *전*의 VOC 동기구간이 안 잡힘 → **컨트롤러 진입 시각(t0) 추가 측정** 필요.

**수정(측정 보강 + 방어)** — 파일 3곳, 동작/응답 영향 0:
- `assist-stream.controller.ts`: 진입 시각 `t0=Date.now()` 측정해 `stream(...,t0)` 전달. VOC 호출을 `setImmediate(()=>void handleUtterance(...))` 로 **다음 틱 분리**(동기구간이 fetch 출발을 못 막게).
- `assist-stream.service.ts`: `stream()` 에 `tController?` 인자 추가, latency 로그에 `controllerToStreamMs`(수신→stream진입) + `totalMs` 추가. (기존 inToFetch/fetchToHeaders/headersToFirstChunk 유지)
- `.env.5f.development`: `ASSIST_STREAM_LATENCY_LOG=1`.

**실측 결과(배포 후 통화)** — `[assist-stream-latency]`:
- `controllerToStreamMs` **0~2ms**, `inToFetchMs` **0~1ms** → **asst 백엔드는 요청받고 1ms 안에 AICM 호출. 완전 결백.** ("AICM 호출 전 1~2초" 가설 기각)
- `fetchToHeadersMs` 13~62ms(AICM 연결 정상)
- `headersToFirstChunkMs` **≈1000ms**(948~1019, query별 544~1019 변동, 통화 직후 짧은query는 7~8ms) → **여기가 범인 = AICM `rag_assist` 의 intent+벡터검색+리랭킹 시간**
- `totalMs` ≈ 첫 sources까지 1초

**결론**: asst-service 는 1~2ms 로 결백(더 최적화할 것 없음). assist-stream 1초는 **AICM/RAG 서비스(8173) `rag_assist` 의 첫 sources 생성시간** — 단축은 AICM/RAG 팀의 검색 최적화 영역. 프론트 체감 1~2초 = AICM 1초 + 배포환경(B) 네트워크 경로. query별 출렁임도 AICM 검색시간 변동. (참고: 브라우저 Timing 의 Content Download 7s 는 SSE 라 "스트림 전체 열린시간=LLM generate 완료까지"이지 다운로드 지연 아님 — TTFB 14ms 가 증거.)

**후속 (같은 날)**:
- **프론트 전달용 `event: asst-latency` SSE 이벤트 추가** (`assist-stream.service.ts`, 첫 sources 직전 1회, `ASSIST_STREAM_LATENCY_LOG=1` 게이트). data: receivedAt(KST)/backendMs/aicmConnectMs/aicmSearchMs/totalMs. 프론트가 받아 "백엔드 vs AICM" 분해 표시 가능. 기존 sources/generate/done 이벤트 무영향, 플래그 off 시 미전송(즉시 원복 가능). 프론트팀 작업 완료, 배포는 사용자가 진행. tsc/lint 0.
- **보고서 작성**: `docs/assist-stream-latency-report.md` (한 줄 결론 → 구간정의 + Flow/KST타임라인 → 실측예시 → 통계 → 조치 → 모니터링 → 원본로그 부록). 관련자 공유용.
- **재측정 회차들**: 16:49 KST 회차는 AICM 검색 1.8~1.9초 스파이크(부하), 17:11~13 회차는 ~1초로 회복 → AICM 부하 변동 재확인. 백엔드는 모든 회차 0~2ms.
- **★ 미구현(메모리에 기록)**: 현재 측정은 "첫 조각(sources)까지=~1초"만. **스트림 완료(done)까지 = 답변생성(generate) 포함 AICM 전체시간(체감 ~9초)** 측정은 미구현. 추가하면 "AICM 느림"이 9초로 부각됨. (SSE라 AICM이 결과를 조각으로 전송: 첫조각 sources=1초, 마지막조각 done=~9초, 둘 다 순수 AICM 시간). 메모리 `assist-stream-latency` 참조.

### 56. 신규 AWS 서버 배포 — DB 자동마이그레이션 트리거 시점 확인 + timestamp 9시간 오차 근본수정(tz-init) (tsc/lint 0, 런타임 검증)
- **DB 반영 질문**: 새 서버 배포 후 추가 컬럼/테이블(coachings 3컬럼, emotions/callstat_voc 테이블)이 반영됐는지 불안 → 코드로 흐름 확정.
  - `runSchemaMigrations`(dynamic-database.service.ts:448)는 **부팅 시 안 돔**. 부팅 시점 DB작업은 `database-init.service.ts`의 `CREATE SCHEMA IF NOT EXISTS advisor` **단 하나**(스키마 폴더만).
  - 테이블/컬럼 생성은 **첫 연결 생성 시점**(`getConnection`:189 / `getStaticConnection`:351)에만. `AuthMiddleware`(:127)가 토큰 든 아무 요청이나 통과시키면 그때 첫 연결 생성→마이그레이션 실행→전부 멱등 생성. 즉 **"배포"가 아니라 "배포 후 첫 인증요청"이 트리거.**
  - 멱등(IF NOT EXISTS/addColumnIfNotExists) → 두번째 연결부터 스킵. `getConnection` 실패해도 미들웨어가 요청 통과시키고 console.error만(:130) → 연결 실패 시 마이그레이션 아예 안 돌고 조용히 넘어감.
  - **결과: 사용자 토큰 API 호출하니 정상 생성 확인됨.**
- **timestamp 9시간 오차 (DB 읽은 시각이 KST로 9h 어긋남)**:
  - 원인: `process.env.TZ='UTC'`가 `main.ts:29`(모든 import 뒤)에 있어 ① 실행 타이밍 늦음 ② 젠킨스 빌드캐시로 옛 dist(그 줄 없음)가 떠 있을 수 있음. compose `TZ=UTC`(docker-compose.dev.yml:21)는 **타팀 젠킨스 스크립트(수정·조회 불가)**라 보장 안 됨.
  - pg `setTypeParser` 미설정(grep 0건) → timestamp(no-tz) 파싱이 프로세스 TZ에만 의존. timestamp 컬럼(callstat_call.started_at/ended_at, 다수 @CreateDateColumn)과 timestamptz 혼재.
  - **수정(확정 후)**: `src/tz-init.ts` 신규(`process.env.TZ='UTC'` 한 줄) + `main.ts` 맨 첫 import `import '@app/tz-init'`로 **모든 import보다 먼저** 실행. 기존 늦은 할당 제거.
  - 효과: 모든 timestamp 컬럼 일괄 해결(컬럼별 작업 0), compose env 무관, **코드 변경이라 젠킨스 빌드캐시 자동 무효화→옛 dist 문제 동시 해결**. timestamptz는 무영향.
  - 검증: build/lint 0, dist/src/main.js 3번째 줄 `require("./tz-init")`(tracer보다 먼저), 런타임 `getTimezoneOffset()=0`(UTC) 확인. **develop 푸시→젠킨스 재빌드·배포 시 적용**(커밋은 사용자 확인 대기).

### 57. assist-stream vs stream 응답지연 재분석 + 프론트 협업 (2026-06-22, 코드수정 없음·분석만)
- **발단**: 집에서 작성한 `docs/backend-assist-stream-refactoring.md`(2주전 소스 기반) 검증 요청. 현재 소스와 대조.
- **문서 vs 현재 소스 차이**:
  - **distill 가설 무효화**: 문서는 "assist-stream만 `distill:false`, stream은 키없음→RAG기본값". 현재는 **둘 다 `enable_distill:false` 명시**(assist-stream.service.ts:54, search.service.ts:62) → distill은 두 API 속도차 변수에서 완전 제외. (필드명도 `distill`아닌 `enable_distill`)
  - **호출경로 변경**: 문서 `${SEARCH_HOST}/api/v1/rag/assist-stream` → 현재 **둘 다 `${AICM_HOST}/api/aicm/v1/search/rag_assist`** 동일.
  - **stream도 conversationHistory 받음**: search-request.dto.ts:40 + toRagHistory() 호출(:63), assist-stream과 동일 가공(화자당 3턴컷). util 공유.
  - SSE 릴레이는 두 API 글자단위 동일(res.write(decoder.decode)) — 문서대로.
  - 문서엔 없던 추가분: VOC 실시간분석, asst-latency SSE이벤트, assist-snapshot, company/turnIdx DTO필드.
  - 사소버그: service.ts:20 주석은 `ASST_STREAM_LATENCY_LOG`인데 실제 읽는건 `ASSIST_STREAM_LATENCY_LOG`(:30). 켤땐 후자.
- **VOC가 assist-stream 응답 막는지 재검증 → 안 막음 확정**: controller가 `setImmediate(()=>void handleUtterance())`로 다음틱 분리 → `await stream()`의 fetch가 먼저 출발. handleUtterance 내부 무거운작업(analyzeEmotion→LLM, persistVoc→DB, publish→redis) 전부 await I/O라 이벤트루프 양보. stream()은 순수 RAG프록시라 DB/redis/LLM 안 써서 자원경합 없음. 동기구간(accumulate/buildConversation)은 버퍼40턴 상한이라 ms미만. 단 ① `force:true`로 발화마다 LLM 도는 비용, ② assist-stream엔 DbCleanupInterceptor 없어 VOC의 DB연결 정리주체 불명확(누수 잠재리스크) — 속도와 별개 점검권장.
- **프론트 실측 데이터(minimal body)**:
  - asst-latency(첫 sources까지): API접수 0.00s · 연결 0.06s · 검색 1.08s = **합 1.14s** (우리서버 몫 0~0.06s)
  - done.stages(답변완성까지): 의도 1.06s · 검색 1.00s · 선별(distill) 0.00s · **생성(generate) 1.76s** = **약 3.8s**
- **핵심 결론**:
  - done의 stages/token_usage/distill은 **asst-service가 아니라 RAG(AICM)가 생성**하는 값. asst-service는 가공없이 통과만(grep으로 생성코드 0건 확인). skip/채우기/generate분해는 모두 RAG 영역 → RAG 담당자 확인사항.
  - **백엔드 무죄**(0~0.06s). 지연 2.7~3.8초는 전부 RAG 처리시간, **generate 1.76s가 최대 단일구간**.
  - distill 0.00s는 우리가 false 보내서 정상.
- **"한꺼번에 vs 타이핑" 증상**(stream은 타이핑처럼, assist-stream은 한꺼번에 펑):
  - asst-service는 두 API 모두 버퍼링없이 즉시 릴레이 → 백엔드가 만드는 차이 아님.
  - 후보 (A)프론트가 done까지 모아 렌더 / (B)RAG가 토큰 한덩어리 전송.
  - **프론트 회신: (A) 배제** — 프론트는 per-token 즉시렌더(throttle/debounce 없음), stream도 동일로직. 단 토큰프레임이 네트워크에서 묶여 도착하면 1회 read로 합쳐져 "한꺼번에" 보일 수 있음 = (B) 가능성.
- **★ 미완 액션(다음)**: asst-service reader 루프에 **청크 도착 시각+바이트 로그** 추가(ASSIST_STREAM_LATENCY_LOG 게이트). write가 시간차로 여러번→RAG 점진전송(프론트 정상) / 마지막 한덩어리→(B) RAG 전송방식 확정. stream에도 같이 넣어 나란히 비교. RAG 처리시간 단축은 통제밖이라 오늘은 여기까지 합의.

### 58. assist-stream 속도개선 결론 + distill 토글 시도→전면 원복 (2026-06-22, 최종 소스 변경 없음)
- **프론트 실측(minimal body, done.stages)**: 의도 1.06s·검색 1.00s·선별 0·생성 1.76s ≈ 3.8s. asst-latency: 접수 0.00·연결 0.06·검색 1.08 = 1.14s(첫 sources). → **백엔드 몫 0~0.06s(무죄), 지연=RAG. done.stages/token_usage/distill 은 RAG(AICM) 생성값, asst-service는 통과만**(grep 0건 재확인).
- **"한꺼번에 vs 타이핑" 증상**: asst-service는 버퍼링없이 즉시 릴레이 → 백엔드가 만드는 차이 아님. 프론트 회신=프론트는 per-token 즉시렌더(throttle 없음)라 (A)프론트 배제. SSE 이벤트 순서 `intent→query_analysis→sources→distilled(옵션)→token×N→done`.
- **속도 비교 실측(curl, dev AICM 124.194.32.36:8173)**:
  - `internal/document`(무인증, 검색만) **0.24s**
  - `rag_assist`(검색+AI요약, SSE) **3.5~3.9s** → 차이 ≈ **generate(AI요약) 비용**. 검색 자체는 빠름.
- **distill on/off 실측 비교(같은 query, rag_distill.txt vs rag_distill_false.txt)**:
  - false: distilled 이벤트 **없음**, 전체 3882ms (stages intent848/search252/**distill0**/generate3625)
  - true: distilled **옴**(`{selected_refs, summary, rationale, latency_ms}`), 전체 4481ms (distill 664 추가, **generate 동일 ~3.6s**)
  - → **distill 켜면 +0.6초 느려짐(generate는 그대로). distilled 는 프론트 1차요약/참고문서 조기렌더용 데이터지 속도개선 아님.** 테스트 query("삼성코리아 펀드")가 매칭문서 없어 distilled.summary 빈 값이라 이점 미입증.
- **시도→원복**: assist-stream 에 `ASSIST_STREAM_ENABLE_DISTILL` env 토글 추가(enable_distill=플래그) + .env.development=true 넣었다가, "속도개선과 무관·오히려 +0.6초"로 판단 → **assist-stream.service.ts·.env.development 전부 원복**(git diff로 service.ts 원본 동일 확인). distill 미사용(enable_distill:false) 기존 상태 유지.
- **★ 최종 결론**:
  1. **백엔드는 응답속도 못 줄임** — 병목은 RAG generate(~3.6s), asst-service 오버헤드 0~0.06s. RAG/LLM(모델·출력길이·스트리밍) 최적화는 AICM 담당 영역.
  2. **채택된 해법(프론트)**: distill 무관하게 **sources 오면 문서 먼저 노출(~1초) + done에서 AI요약 노출** → 체감개선. (옵션: token을 done 대기말고 올 때마다 타이핑 렌더하면 요약이 더 일찍 차오름)
- **(별개) AWS 새 고객서버 /stream 403 "조회 가능한 분류가 없습니다"**: AICM `PermissionEnforcer`가 그 토큰 계정(agent)의 **할당 분류 0개**로 판정(문서 `docs/callbot_advisor_api.md` §1). `rag_assist`만 권한체크, `internal/document`(무인증)는 통과 → 같은 workspace에서 검색은 되는데 rag_assist만 403. **우리 코드 무관, AICM 권한세팅(계정↔분류 매핑) 영역**. 로컬/dev는 정상, AWS만 발생(권한데이터 미세팅 추정).

### 59. assist-stream 속도개선 — generate 병목 재확인 + 캐싱 방향 합의(미완, 내일 이어서) (2026-06-22)
- **사용자 의도**: assist-stream이 RAG 호출이 느리다 → "검색문서 요약(distill)"이 느린 줄 알고 수정하려 함. 검토 결과 인식 교정:
  1. 코드는 **이미 `enable_distill:false`**(`assist-stream.service.ts:54`) — distill 안 탐.
  2. done.stages 재비교: distill은 켜도 664ms뿐, **진짜 병목은 `generate` 3625ms(전체의 93%)**. → 사용자도 generate가 범인임 인정.
- **RAG 담당자 제약**: **LLM 모델 변경 불가**(담당자 회신). 모델 `gemma-4-31B`, completion 115토큰에 3625ms(토큰당 ~31ms).
- **핵심 합의(중요)**: RAG가 **이미 token 스트리밍**(rag_distill_false.txt: token 이벤트 320개) + asst 릴레이도 버퍼링 없음 → **백엔드 최적**. 그러나 **상담사는 "요약 전체"가 필요** → TTFT(첫 글자) 개선은 **무의미**, 실질 대기 = `generate` 완료(마지막 글자 송신) + 프론트 렌더 시간. 사용자 표현: "끝까지 다 넘겨준 시간 + 프론트가 추가로 그리는 시간".
- **결론: generate 절대시간은 우리 코드로 못 줄임**(RAG가 답변 생성하는 순수 LLM 시간, 모델·프롬프트·GPU 영역인데 막힘). asst-service가 RAG 안 건드리고 쓸 카드 2개:
  1. **캐싱(우리 영역, 1순위)**: `workspace_id` + 정규화 `query` 키로 완성답변 저장 → 반복/FAQ 질문은 RAG 호출 자체 스킵, generate 3.6초 통째 제거. 단 질문 반복률에 효과 갈림.
  2. **프론트 렌더링 시간 분리 측정**: "다 받고도 프론트가 더 그리는 시간"이 실측 안 됨. 토큰마다 마크다운 통째 재렌더면 느려지는 흔한 케이스 → 측정해서 프론트팀에 근거 제공.
- **★ 미완(내일 이어서 결정)**:
  1. 사용자가 원래 하려던 수정이 캐싱인지 다른 접근인지 확인.
  2. 실제 상담 질문 **반복률**(캐싱 효과 좌우).
  3. 프론트가 답변을 **토큰마다 다시 그리는 구조**인지 확인.
  → 위 답에 따라 [캐싱 / 측정부터 / 프론트 이관] 방향 확정.

### 60. VOC 테이블(emotions/callstat_voc) 고객 AWS 생성 실패 — 마이그레이션 견고화 (2026-06-23)
- **증상**: `/summary` 의 VOC 테이블(`advisor.emotions`, `advisor.callstat_voc`)이 로컬/사내개발은 정상인데 **고객 AWS(Jenkins 배포)에서만 생성 안 됨**. (코드는 origin/develop·develop_nohsn 동일, 4개 엔티티 등록도 모두 정상)
- **질문2(기존 summary 저장 영향 여부) → 영향 없음 확인**:
  - 요약 본 저장 `saveSummaryData`(summary/keyword/category)는 emotions/callstat_voc 를 아예 안 건드림 → 무관.
  - VOC 저장 `saveEmotion` 은 `summarizeCall` 148~161 에서 try/catch → 실패해도 요약 응답 정상.
  - VOC 조회는 핫픽스 `16bdb0c`(getSummaryData 1052~, findByCallstatsId)로 try/catch → 500 안 나고 emotion=null/404. → **VOC 깨져도 summary 안전.**
- **질문1(생성 실패 원인)**: `runSchemaMigrations`(dynamic-database.service.ts:448~)가 연결 시마다 raw SQL로 생성하나 전체 try/catch라 실패해도 경고만. 로컬/dev OK·고객만 실패 = 환경차. 유력순: ①앱 DB유저 advisor 스키마 CREATE 권한 없음(permission denied) ②advisor 스키마 미존재(마이그레이션에 CREATE SCHEMA 없었음) ③gen_random_uuid() 미지원(callstat_voc만, PG13미만/pgcrypto). + 구조문제: emotions→callstat_voc→CHECK 가 한 try라 앞 실패가 뒤 막음.
- **조치(전체 견고화, 사용자 로그접근 어려워 방어적으로)**: dynamic-database.service.ts `runSchemaMigrations` 수정
  ① `CREATE SCHEMA IF NOT EXISTS advisor` 선행 추가 ② `CREATE EXTENSION IF NOT EXISTS pgcrypto` 시도(PG13미만 대비) ③ emotions / callstat_voc 각각 독립 try/catch 로 격리 ④ 실패 시 원인 힌트 포함 명확 로그(permission/schema/gen_random_uuid). tsc 통과.
- **남은 확인**: 다음 배포 후 고객서버 로그의 `[마이그레이션] ... 실패` 메시지로 진짜 원인 확정. 만약 `permission denied` 면 코드로 못 풀고 **고객 DBA가 앱유저에 advisor CREATE 권한 부여 or 테이블 선생성(migrations/*.sql)** 필요.

### 61. VOC 테이블 미생성 원인 = 테넌트 DB 권한(CREATE 없음) 확정 + 진단로그 보강 (2026-06-23)
- **흐름**: 고객서버(ArgoCD/k8s) emotions/callstat_voc 미생성 디버깅. 배포구조부터 확인됨 — Jenkins(`docker build --no-cache`→harbor push, 여기까진 이미지만) → ArgoCD `app set image=:v142` + `app sync`(aicc ns) 롤아웃. 초기 404는 롤아웃 Progressing 과도기였고, 새 코드(persistEmotion) 정상 배포 확인.
- **진단 로그 보강**(dynamic-database.service.ts runSchemaMigrations): ①진입 `[마이그레이션] 시작: user/db` ②`advisor 스키마 권한 CREATE/USAGE`(has_schema_privilege) ③emotions/④callstat_voc 생성 성공로그 ⑤최종 `to_regclass` 존재확인 `emotions=O/X`. (query 제네릭으로 lint 통과)
- **★ 원인 확정(로그)**: `[마이그레이션] 시작` 정상 → 근데 `permission denied for database`(CREATE SCHEMA), `permission denied for schema advisor`(CREATE TABLE), `permission denied to create extension pgcrypto` → `emotions=X, callstat_voc=X`. 즉 **테넌트 접속계정(user=db=company_xxx)은 advisor 기존테이블 읽기/쓰기만 되고 CREATE 권한 없음**. 기존 테이블은 프로비저닝 시 마스터계정이 미리 생성한 것; 신규 테이블은 앱이 자동생성 불가. 로컬/사내개발은 권한 있어 정상이었던 것.
- **해결방향(코드 불가, DBA 영역)**: ①프로비저닝 DDL스크립트(사내개발DB 기준)에 두 테이블 추가(영구) ②DBA가 기존 테넌트 DB에 수동 CREATE+GRANT ③앱계정에 GRANT CREATE ON SCHEMA advisor(자동생성 작동, 보안상 비권장). summary 조회는 try/catch로 emotion=null 정상응답 중이라 서비스 안 죽음.
- **현재 상태**: 사용자가 권한 정책 체크 중. DDL은 이미 있음(사내개발 기준). 권한 결정되면 마무리.

### 62. 실시간 VOC 미노출 원인=채널 prefix prd↔dev 불일치 → dev 고정으로 해결 (2026-06-23)
- **emotions/callstat_voc 권한**: DBA가 수동 테이블 생성(+GRANT)으로 해결. POST /emotion/data 200, assist-stream voc-test saved=true 로 테이블/저장 확인.
- **★ 실시간 VOC 화면 미노출 진짜 원인**: `publishVoc` 채널 prefix가 `NODE_ENV==='production'→'prd'` 였는데, 이 시스템의 다른 소켓채널(nlp:complete/events/orchestrator)은 NODE_ENV 무관 **전부 `dev`**. 프론트도 `dev:4609686:56356659:call:voc` 구독. → 우리 VOC만 `prd:` 로 튀어 **채널 불일치 → 프론트 미수신**. (publish 는 ok=true 라 백엔드만 보면 정상으로 착각)
- **시도→실패**: ①`VOC_CHANNEL_ENV ?? NODE_ENV fallback` + `.env.development=dev` → 고객서버(k8s, NODE_ENV=production)는 `.env.development` 안 읽힘(.dockerignore 제외 + production 이라 미로드[[env-load-priority]]) → 여전히 prd.
- **★ 최종(채택)**: voc-realtime.service.ts ~565 `const env = process.env.VOC_CHANNEL_ENV ?? 'dev'` — **NODE_ENV 의존 제거, 기본 dev**(다른 채널과 일관). 코드배포만으로 해결(chart.git 미접근 우회). voc-test 로그 `channel=dev:...` 확인. 커밋 56b9eab/8189237/cb2cff9.
- **CLI 단독 테스트**: `POST /assist-stream/voc-test` (force:true, reset:true) → 응답 published/saved + 로그 channel prefix 확인. 단 published:true 는 dev/prd 무관(채널명은 로그로만 판별).
- **남음**: 실제 통화에서 프론트 화면 실시간 VOC 노출 최종확인.

### 63. asst-latency SSE 이벤트 게이트 제거 — AWS 5단계 모달 누락 해결 (2026-06-23)
- **증상(프론트 보고)**: AWS 고객사만 AICM 응답속도 상세모달이 5단계(API접수/AICM연결/AICM검색/결과전송/생성)로 안 펼쳐지고 단일막대 폴백. 로컬/사내dev는 정상. `done.stages`는 AWS도 정상수신 → **`asst-latency` 이벤트만 누락**.
- **원인**: asst-latency 전송이 `if(this.latencyLog)` 게이트(env `ASSIST_STREAM_LATENCY_LOG===1`) 안에 있었음. 이 env가 레포 어느 .env에도 없음 → 배포 configmap 주입값이라 AWS엔 미설정 → 그 환경만 누락.
- **조치**: `assist-stream.service.ts` 게이트 제거 — `asst-latency`는 **환경변수 무관 항상 전송**, 콘솔 구조화로그(`[assist-stream-latency]`)만 env 게이트 유지. tsc 통과. 커밋·배포는 사용자.

### 64. assist-stream-new 신규 엔드포인트 — RAG 검색만 + 답변은 LLM Orchestrator(gpt-4o-mini) (2026-06-23)
- **목적**: assist-stream 병목 = RAG 내부 sLLM(gemma)의 `generate`(0.5~10s 편차, [[항목59]]). 이걸 우회 — RAG는 검색까지만, 답변생성은 우리가 제어하는 orchestrator로.
- **검색소스 검토(curl은 사용자가 실행 [[external-curl-user-runs]])**: 프론트는 `rag_assist`의 `event:sources` 포맷에 의존. `internal/document`(청크+score 유사하나 chunk_id·source_location.file_url 부족 → 프론트 문서활용 제한), `retrieve_doc`(문서 전체 덤프, score/chunk 없음 → 부적합). → **rag_assist 그대로 호출 후 sources까지만 받고 generate(token) 끊기** 채택(프론트 무수정·포맷 100% 일치).
- **구현(신규 2파일)**: `controllers/assist-stream-new.controller.ts`(`POST /assist-stream-new`), `services/assist-stream-new.service.ts`. advisor.module 등록 + app.module AuthMiddleware exclude 추가. 기존 assist-stream/search 무수정.
  - 흐름: rag_assist 호출 → SSE파싱(intent/query_analysis/sources 릴레이) → sources 직후 `reader.cancel()+abort` → sources content + conversationHistory 를 `customComplete(openai/gpt-4o-mini, serviceName:'adv')` 로 답변생성 → `event:token`(통짜 1회)+`done`(stages:{search,generate}, latency_ms, source) 릴레이. **비스트리밍 1단계**.
  - tenantId: `dto.company?.id` 우선(빈번호출 user-service 왕복 회피), 없으면 token→`UserInfoService.getCurrentUser().agent.company_id`.
  - `asst-latency` 이벤트도 추가(항목63과 동일 포맷, 항상 전송).
  - 요청 바디 = 기존 `AssistStreamRequestDto` 동일 → **프론트는 URL만 `/assist-stream`→`/assist-stream-new` 변경**.
- **실측(테스트환경 상이 → 기존과 직접비교 부적합)**: search593+gen1026=1620ms / 552+1259=1814ms / 914+**8968**=9884ms(generate 편차 큼). 비스트리밍이라 "수초 빈화면→통짜 출력" 체감 답답.
- **★ 미완(나중에, 사용자 보류)**: ①`done`에 `completion_tokens`/`tps` 추가(generate 9초 원인=출력길이 확인 + TPS 실측) ②프롬프트 개선(`max_tokens`+간결화 + **STT 유사발음 교정** 의도 반영: 부정확 발화를 문서 정확용어로 이해/정정) ③2단계 SSE 스트리밍(체감속도). **커밋 안 함(사용자가 직접)**.
- **TPS 메모**: TPS=Tokens Per Second=`completion_tokens ÷ generate초`. 기존 RAG샘플 ~31.7tok/s(gemma). 고객사 제출용 가공데이터(평균응답 1.5s/min1.0/max2.5 → 평균 ~89tok/s) 별도 제공.

## 2026-06-24

### 65. callstat_voc 조회 API 추가 (call_id 기준, turn_idx asc 전체컬럼) (2026-06-24)
- **목적**: 실시간 저장된 VOC(advisor.callstat_voc)를 콜 이력에서 사후조회. 엔티티/4스팟 등록은 이미 완료돼 있었음.
- **엔드포인트**: `GET /callstat/calls/by-call-id/:call_id/voc` (기존 by-call-id/:call_id/turns·/stt 패턴과 일관). callstats_call 조인 없이 **callstat_voc.call_id 직접 매칭**(call_id=varchar128, raw call id). turn_idx ASC, 전체컬럼 그대로. 데이터 없으면 빈배열 `[]`(404 아님).
- **변경 2파일**: `advisor.service.ts` `findVocByCallId()` + CallstatVoc import / `callstat.controller.ts` 엔드포인트 + import. build 통과.
- **프론트 전달**: base path 포함 `GET /api/asst/v1/callstat/calls/by-call-id/{call_id}/voc`, call_id 그대로 param. 리턴 필드명세 전달(sentiment_*/complaint_risk_*/churn_risk_* score는 0~1 nullable, description nullable → null 가드).

### 66. 배포 env 주입 구조 규명 + ArgoCD 요청 가이드 문서화 (2026-06-24)
- **발단**: 신규 env `CE_API_KEY`/`CE_API_LLM_URL` 가 배포에 미적용. 고객사=k8s+ArgoCD(접속만 가능).
- **★ 규명**: 배포 Pod env는 `.env.development` 가 아니라 **k8s Deployment가 주입**. 근거 — `.dockerignore`가 `.env.*` 제외(이미지 미포함) + ConfigModule이 파일없으면 process.env 사용 + 코드레포에 k8s manifest 없음. → **`.env.development` 수정은 배포에 무효**.
- **Deployment env 구조(Live Manifest 확인)**: `containers[].env` 직접나열(envFrom 안씀). 평문=`value:`(REDIS_HOST 등), 비밀=`valueFrom.secretKeyRef`→Secret `asst-service-secret-v147`. 그 Secret은 **CSI SecretProviderClass `asst-service-spc-v147`**(secrets-store.csi.k8s.io, /mnt/secrets, SA secrets-sa)가 외부저장소에서 채움. value/valueFrom은 택일(값은 Secret/외부저장소에만, Deployment엔 주소만).
- **GitOps 소스(App DETAILS→SOURCE)**: `gitlab.timbel.dev/apps/devops/langsa/chart` path `ecp/chart/apps`, 계층형 values 5개(뒤가 앞 덮음). asst-service는 `values/aicc/asst-service/base-values.yaml`(공통)·`dev-values.yaml`(dev전용). Secret/SPC/이미지 전부 `-v{BUILD_NO}` → CI 템플릿 자동생성 → **Argo UI Live Manifest 직접 EDIT 금지**(sync/빌드 덮어씀). 사용자 차트레포 접근권한 없음 → DevOps 요청 필요.
- **금지방법**: ①.dockerignore에서 .env 빼서 이미지에 굽기(비밀 노출, .env.development 이미 git커밋됨) ②Argo Live EDIT(임시). ✅정석=차트 values 수정→MR→Sync.
- **산출물**: `docs/argocd-request.md` 생성(구조·금지방법·절차·DevOps 요청문 템플릿). 메모 [[deploy-architecture]] 에 env 주입방식 추가.

### 67. CE env 미주입 임시 하드코딩 fallback (담당자 부재, 추후 원복) (2026-06-24)
- **상황**: 요청은 넣었으나 DevOps 담당 부재중. CE_API_KEY/CE_API_LLM_URL 없으면 CE 연동 동작불가 → 임시로 소스에 기본값 박고 나중에 env 주입되면 재배포 원복.
- **읽는 곳**: `summary.service.ts` 2곳뿐(633 CE_API_LLM_URL, 693 CE_API_KEY). emotion.controller는 doc스트링만.
- **발견**: CE_API_LLM_URL은 이미 `CE_EMOTION_FALLBACK_URL`로 fallback 존재(사실상 하드코딩됨). **진짜 빠진건 CE_API_KEY**(키없으면 x-api-key 헤더 자체 미부착→인증실패).
- **조치**: 임시상수 2개(`CE_API_LLM_URL_FALLBACK`/`CE_API_KEY_FALLBACK`, `[임시/TODO 원복]` 주석) 추가 + `configService.get(key, 기본값)` 2번째인자로 적용. env 주입시 env우선, 없으면 fallback. build 통과. 사용자 커밋·배포 완료, 테스트 진행중.
- **★ 원복 체크리스트**: env 차트반영·재배포되면 → 상수2개 삭제 + get() 기본값인자 제거(`get<string>('CE_API_KEY')`로) + 재배포. `CE_API_KEY_FALLBACK` grep으로 위치추적 가능.

### 68. LLM Orchestrator 호스트 마이그레이션(langsa 삭제 대비) + CE 하드코딩 원복 + LLM 문서화 (2026-06-24)
- **배경**: 인프라가 langsa 도메인(`dev-ecp-llm-orchestrator-service.langsa.ai`) 다음주 삭제 예정. "langsa는 게이트웨이 통해서만 접근" 안내. asst-service가 LLM_ORCHESTRATOR_HOST로 쓰는 중(요약/키워드/상담유형/자동todo).
- **영향범위 규명**: LlmOrchestratorService 사용처 = summary(요약/키워드/상담유형), todo(자동생성). assist-stream-new는 사용자가 다른걸로 교체. 감정/VOC는 orchestrator 아님(기본 CE, `VOC_ANALYZER=llm`일 때만 orchestrator).
- **인프라 회신**: 5층=langsa 도메인 / AWS내부=`http://llm-orchestrator-service-svc.aicc` / 게이트웨이외부=`https://ecpad.etaas.co.kr/aicc/llm-orchestrator-service` (k8s내부는 http 주의).
- **배치 정리**: `.env.development`(내부DNS세트)=내부DNS, `.env.5f/.192`(5층,클러스터밖)=게이트웨이주소. 내부 DNS는 5층서 resolve 불가. AWS배포 env는 차트가 결정(인프라가 이미 적용)이라 .env 수정은 배포 무효 — 사용자가 .env.development=AWS세트라고 정정.
- **경로 prefix**: 내부직접접근은 `/api/llm-orchestrator/v1` 유지 필요(게이트웨이 없어 prefix 안붙음). 게이트웨이 외부주소는 `/api`·끝슬래시 빼는게 맞음(게이트웨이가 prefix 부여). asst-service 자신의 `/api/asst/v1` 와 동일 패턴.
- **★ 직접 검증(사용자 명시 요청으로 curl 실행)**: `POST https://ecpad.etaas.co.kr/aicc/llm-orchestrator-service/llm/custom/complete` (X-Tenant-Id=company_71900448.., X-Service-Name=adv, Bearer) → **HTTP 201 success:true, gpt-4o-mini 실제응답, latency 964ms**. 게이트웨이 주소 정상 확정. `.env.5f.development` 끝슬래시 제거 + (테스트용)VOC_ANALYZER=llm 추가.
- **혼동정리**: emotion/analyze 는 orchestrator 아니라 CE를 탐(VOC_ANALYZER 기본 ce). analyzeVocViaOrchestrator는 등록프롬프트 없이 코드내장프롬프트로 /llm/custom/complete 직접호출. orchestrator 실패해도 200+중립fallback이라 응답내용 봐야함.
- **CE 하드코딩 원복**: 인프라가 차트에 CE_API_KEY/CE_API_LLM_URL 주입완료 → summary.service.ts 임시 하드코딩 상수2개 + get() 기본값 제거(원위치 `get('CE_API_KEY')`). build 통과, 잔여 0. 메모 ce-env-temp-hardcode 삭제. (.env.5f/.192 의 CE_API_KEY는 5층 도커용이라 유지)
- **문서화**: `docs/advisor-summary-llm.md`(요약/자동todo API 명세), `docs/advisor-llm-orchestartor.md`(LLM 호출경로·호스트·등록프롬프트·상담유형 전문/스키마). 프롬프트는 요약/키워드/자동todo=Orchestrator 등록(레포에 없음, 이름만), 상담유형=코드 하드코딩(분류체계 목록까지)·customComplete(provider/model만, temp/maxTokens 미지정). 키워드 system/user 2개=ChatCompletion 표준(system=역할규칙고정, user=대화데이터).
- **callstat_voc 조회 API**(항목65) 도 이 세션 작업: `GET /callstat/calls/by-call-id/:call_id/voc`, call_id 직접매칭, turn_idx ASC, 전체컬럼.

### 69. AWS 통화일시(started_at/ended_at) +9 어긋남 — KST저장 no-tz를 UTC+Z로 환산 (2026-06-24)
- **증상**: AWS 배포 화면(대시보드 최근콜·콜이력 리스트)에서 통화일시가 정확히 **+9시간** 어긋남(15:27 통화 → 화면 00:27). 로컬/5층은 정상.
- **★ 진짜 원인**: `started_at`/`ended_at`은 `raw_call.callstats_call`의 **`timestamp`(no-tz)** 컬럼인데 **AWS DB는 KST 벽시계로 저장**(예 "15:27"), **로컬/5f DB는 UTC(-9h)로 저장**. 프론트는 보정 안 하고 `new Date(raw).toLocaleString("ko-KR")` 만 함 → **타임존(Z) 없는 값은 깨짐**. `created_at`(timestamptz)은 UTC절대시각이라 `...Z`로 나가 정상이었음.
- **삽질 경로(교훈)**: ① process TZ(tz-init/`docker-compose TZ=UTC`/ArgoCD `TZ=UTC`)는 **무관**(formatDateTime이 벽시계 라운드트립이라 TZ 독립). ② TimezoneInterceptor(+9) 삭제·main.ts 등록제거 → 효과 없었음(화면이 그 응답경로를 안 씀). ③ by-call-id 목록을 formatDateTime→평문으로 바꿔도 평문은 Z가 없어 프론트가 또 +9. **결정타는 "화면이 실제 호출하는 엔드포인트를 못 짚은 것"** — 대시보드/콜이력 리스트는 `GET /callstat/agent-summary`(`CallStatsService.getCallStatsByAgentAndDate`, getRawMany→`row.started_at as Date` 그대로)를 씀. 거기가 진짜 수정처였음.
- **★ 해결**: started_at/ended_at(KST 벽시계)을 **`created_at`과 동일한 UTC ISO(...Z)** 로 환산. 헬퍼 `toUtcIso(date)` = 저장된 벽시계를 `+09:00`로 해석 → `new Date(...).toISOString()` → `...Z`. (TZ 독립, AWS=KST저장 기준. 5f=UTC저장이라 5f엔 안 맞지만 테스트데이터라 무시)
- **수정 파일**: ① `advisor.service.ts` — `toUtcIso` 추가, started_at/ended_at 6군데(일반목록/by-call-id목록/상세-by-id call+turns/상세-by-callnumber call+turns) 적용. ② **`call-stats.service.ts`(agent-summary)** — `toUtcIso` 추가, `row.started_at/ended_at` 적용 ← **실제 화면 수정처**. created_at/updated_at(timestamptz)은 raw `...Z` 유지(정상).
- **부수**: `TimezoneInterceptor` 파일 삭제 + main.ts 등록/import 제거(되돌릴 필요 없음, created_at류는 raw Z로도 정상). `tz-init.ts` import는 사용자가 main.ts에서 제거(무영향). 검증: agent-summary curl에서 `started_at: "2026-06-24T06:27:26.000Z"`(=15:27 KST) 확인.
- **남은 것(주의)**: turn raw 반환 엔드포인트(`/callstat/calls/:id/turns`, `findTurnsByCallId/ByCallNumber`, entities/keywords 등)는 started_at을 raw로 내보내 +9 가능 — 그 화면 쓰면 동일 패턴(toUtcIso)으로 추가수정 필요.

### 70. 실시간 VOC 디버깅 로그 추가 + LLM Orchestrator ENOTFOUND(env 로드 함정) (2026-06-25)
- **요청 2건**: ① VOC가 LLM에 보내는 대화 구조 재확인 ② "첫 대화인데 감정점수 크게 나옴" 디버깅용 상세로그 추가.
- **① 구조 확인**: assist-stream 경로 `VocRealtimeService.handleUtterance`(voc-realtime.service.ts:258)는 **누적분 전부 + 현재발화**를 보냄(마지막 1개 아님). 첫호출만 `conversationHistory`로 시드(:269) → `dto.query`를 **무조건 'customer'로** 누적(:282) → `buildConversation`(전체 join '\n', :411) → `analyzeEmotion`→CE emotion API `{conversation}`(summary.service.ts:712). MAX_BUFFER=40. **점수는 코드가 안 만들고 CE 응답을 clamp(0,1)만**(mapCeEmotionResponse:749, toScore:587) → 첫발화 고점수면 CE 프롬프트/스케일 문제 or stale버퍼(states맵 프로세스잔존, assist-stream경로엔 clear 안불림).
- **② 로그 추가**(handleUtterance, 분석 로직 무수정): 진입상태(firstContact/seededHistoryCount/totalTurns/customerTurns/force/query100자) + LLM전송(lines/chars/head) + 결과3축(emotion/complaint/churn). PII 최소화로 head는 100자(사용자 선택 B)→후에 500자로 늘림. 필터태그 **`[민누이로그분석]`** 전체 prepend(grep용). **임시 디버깅 로그 — 원인 다 잡으면 제거 예정(놔두기로 함, grep `민누이로그분석`으로 추적).**
- **head 잘림 착시**: `chars=68`인데 head가 짧아보임 = 100자제한 아님. `conversation`이 `join('\n')`이라 **개행이 로그를 다음줄로 밀어** 잘려보인 것. → `.replace(/\n/g,' | ')` 한줄화로 해결. lines=3/5턴은 정상(assist-stream 호출수≠STT턴수, agent발화 미누적·customer만 쌓임 → 감정 부정편향 가능 단서).
- **★ LLM Orchestrator 503 "연결할 수 없습니다"**: Request `…/aicc/asst-service/summary` → 503. 코드상 503=`error.request`만(연결단계 실패), 502=`error.response`(경로/4xx) (llm-orchestrator.service.ts:197-210). **경로404 아니라 DNS/연결 문제로 확정.**
- **★ 진짜원인 = env 로드 우선순위 함정([[env-load-priority]])**: 로그 스택 `getaddrinfo ENOTFOUND dev-ecp-llm-orchestrator-service.langsa.ai` → 실제 호출호스트가 **`.env`의 langsa값**(.env:19), 사용자가 `.env.development`에 박은 `http://llm-orchestrator-service-svc.aicc`(:25)가 **안 먹음**. 이유: **`.env`가 최우선 로드**(NODE_ENV별 `.env.{env}` 우선 안되는 배포구성). langsa는 이 클러스터(aicc)서 resolve 불가라 ENOTFOUND. → **`.env` 직접 수정으로 해결, 잘 됨.** 교훈: 이 배포 LLM_ORCHESTRATOR_HOST 등 바꿀 땐 `.env.development` 아니라 **`.env`**를 고쳐야 함.

### 71. VOC emotion score 재정렬 — CE 최초순서 → 위험 단조순서 변환 (2026-06-26)
- **배경**: VOC 3축(emotion/complaintRisk/churnRisk)을 프론트가 평균내 **종합위험지수** 산출. 그런데 emotion 5단계가 `normal-thanks-satisfied-dissatisfied-angry`(최초순서)면 score축이 **비단조**(satisfied(만족,0.5)가 normal(중립,0.1)보다 위험 높게 평균됨) → 평균 왜곡. 핵심 발견: **종합위험지수 평균계산은 백엔드에 없고 프론트가 함**, CE도 종합지수 안 줌(우리는 3축 전달자).
- **설계 결론(논의 끝)**: ① emotionType **신뢰**(LLM이 angry라 했으면 그 감정 맞다고 봄), 그 type 구간 안에서 강도로 score. ② 5단계를 **위험 단조 순서** `thanks<satisfied<normal<dissatisfied<angry`(thanks=0.0~ … angry=0.8~1.0)로 재배치하면 프론트 평균이 정상화. ③ 백엔드 변환은 **균등 0.2폭**으로 단순하게(비균등 가중치는 실데이터로 튜닝, 지금 매직넘버 금지). normal 베이스라인(0.5)이 위험에 떠있는 우려는 **프론트 평균 정책**에서 풀 일(레이어 분리).
- **★ CE 실제 입력 확정**(CE담당자 회신): CE가 최초순서 절대값으로 보냄 — normal `0.0~0.19` / thanks `0.2~0.39` / satisfied `0.4~0.59` / dissatisfied `0.6~0.79` / angry `0.8~1.0` (+ emotionType). 즉 우리가 받는 score는 "type내 강도 0~1"이 아니라 **5구간 절대값**.
- **★ 구현**(`summary.service.ts`): `remapEmotionScore(rawType, rawScore)` 추가 — **emotionType 신뢰 + 구간 내 강도(상대위치) 보존**으로 새 구간 재배치. 테이블 `ORDER{type:{ceLower, lo, hi}}`: thanks(0.2→0.0~0.19) satisfied(0.4→0.2~0.39) normal(0.0→0.4~0.59) dissatisfied(0.6→0.6~0.79) angry(0.8→0.8~1.0) — hi에 0.01갭 미러링해 경계 비겹침. 식 `shifted=lo+(ceScore-ceLower)` → 새구간 clamp → 소수2자리. **폴백: type이 5종 아니거나 score 숫자불가면 normal/0.5**(`parseScoreOrNull`로 0과 구분). `mapCeEmotionResponse`가 이 변환 사용(emotionScore의 `toScore` 직접호출 대체). complaintRisk/churnRisk는 단조축이라 무수정.
- **적용범위**: `analyzeVocByCeApi` 경유라 realtime(통화중 handleUtterance)·summary(통화후) **양쪽 자동 적용**. 검증: normal0.1→0.5 / thanks0.3→0.1 / angry0.9→0.9 / 구간벗어난 angry0.5→clamp0.8 / weird·"abc"→normal0.5. tsc 통과.
- **CE팀 당부**: score는 해당 emotionType 안에서의 강도로 일관되게 줘야 변환 정확(프롬프트 수정중). 재시작 필요(코드변경).

### 72. PostCall-LLM — 상담사후처리 4개 LLM을 독립 테스트 엔드포인트로 신설 (시작) (2026-06-26)
- **목표**: summary API가 내부에서 개별호출하는 LLM 4종을 emotion `analyze` 패턴처럼 **conversation 직접입력 → 호출 → 결과반환** 독립 엔드포인트로 신설. **기존 흐름(`summarizeCall`/`autoCreateTodos`)은 무수정**, 스웨거에서 호출만으로 테스트 가능하게.
- **대상 4종**(현 호출방식): ① 할일자동생성 `todo.service.ts:436 callLlmAutoCreateTodos` complete `adv-auto-create-todos` ② 내용요약 `summary.service.ts:236 callLlmSummarize` complete `adv-conversations-summarize`(4필드→마크다운조립) ③ 키워드 `:291 callLlmKeywords` complete `adv-conversations-summarize-keyword`(count) ④ 상담유형 `:340 classifyCounselingType` **customComplete openai/gpt-4o-mini + 인라인 systemPrompt(~120줄 카탈로그) + JSON파싱**. 1·2·3는 오케스트레이터 등록프롬프트, 4만 코드하드코딩.
- **호출구조 확인**: 전부 개별 axios.post(배치 없음). summary 1콜=Promise.all로 요약·키워드·상담유형(+VOC) 동시발사, 할일은 별도 API. 프론트→asst 2API / asst→LLM 4~5개 개별호출.
- **패턴 레퍼런스**: `emotion.controller.ts` `@ApiTags('VOC-LLM')` `analyze`/`analyze/ce-raw` — conversation body 받아 LLM/CE 직접호출, DbCleanupInterceptor, @ApiBearerAuth('bearer').
- **확정**: 스웨거 그룹명 **`PostCall-LLM`**(상담사후처리). request body/endpoint/return은 사용자가 4개 순차 제공 예정. **첫번째 입력 대기중.**

- **① 할일자동생성 구현 완료 + 스웨거 테스트 OK**: 신규 모듈 `src/advisor/postcall/`(기존 summary/todo 무수정). `dto/ce-todolist-test.dto.ts`(conversation·maxLength:number·includeSimple:string) / `services/postcall-llm.service.ts`(`runTodolistRawByCe` — emotion `analyzeVocRawByCe` 패턴 복제: base=`CE_API_LLM_URL` 공유 path=`/ai-apps/advisor-todolist/runs` fallback full, 헤더 x-api-key+Authorization+X-Tenant-Id, getCompanyIdFromToken 복제) / `controllers/postcall-llm.controller.ts`(`@ApiTags('PostCall-LLM')` `POST /postcall/todolist`). advisor.module 3곳 등록. **CE 응답 원본 그대로 노출**(split 안함 — 실제 서비스 교체 시점에 `|` split). 응답 `{output:{todos:"a|b|c"},outcome:"success"}`. 함정: 서비스 파일 상단 주석에 `ai-apps/*/runs` 쓰면 `*/`가 블록주석 조기종료 → "하위 runs"로 회피. tsc 통과. 나머지 3개(요약/키워드/상담유형) 같은 모듈에 path만 바꿔 추가 예정.

- **②③④ + emotion path 변경 완료(스웨거 테스트 OK)**: 모두 같은 `PostCall-LLM` 모듈에 추가. service에 CE 호출 공통메서드 `postToCe<T>(path, fallbackUrl, body, token, label)` 추출(헤더 x-api-key+Auth+X-Tenant-Id, 502변환, conversation 80자 로그) — todolist도 이걸 쓰게 리팩토링.
  - ② **내용요약** `POST /postcall/summary` path `/ai-apps/advisor-summary/runs`, body `{conversation}`(공용 `CeConversationDto`), 응답 `output.{customerInquiry,handlingResult,followUp,notes}`+outcome.
  - ③ **키워드** `POST /postcall/keywords` path `/ai-apps/advisor-keywords/runs`, body `{conversation,count:number}`(`CeKeywordsTestDto`), 응답 `output.keywords`=파이프문자열.
  - ④ **상담유형** `POST /postcall/category` path `/ai-apps/advisor-category/runs`, body `{conversation, categories}`(`CeCategoryTestDto`) — **categories=파이프구분 후보카탈로그를 클라가 넘김**(기존 코드 하드코딩 카탈로그를 외부화), 응답 `output.{id:"1|2|3", categoryPath:"A>B>C|..."}`+outcome.
  - 전부 **CE 원본 그대로 노출**(파이프 split 안함 — 실서비스 교체 시 적용). 기존 summary/todo 흐름 무수정.
  - **기존 emotion(VOC) CE path 변경**: `/ai-apps/emotion/runs` → `/ai-apps/advisor-emotion/runs` (summary.service 동작상수 2곳 CE_EMOTION_PATH/FALLBACK + 주석 7곳 일괄). 적용에 서버 재시작 필요.
  - 최종 PostCall-LLM 4개(todolist/summary/keywords/category) 전부 tsc 통과 + 스웨거 테스트 정상.

- **④ category request body 수정 + 파이프 응답 배경**: 처음에 잘못 만들어 body에 `categories`(후보 카탈로그)를 넣었으나 **제거** — 올바른 구조는 body `{conversation}`만 보내면 CE가 **자체 프롬프트의 카탈로그**로 분류. 전용 `CeCategoryTestDto` 삭제하고 `CeConversationDto` 재사용. service `runCategoryRawByCe(conversation, token)` body `{conversation}`만.
  - **현 구조 정리**: 기존 운영 `classifyCounselingType`은 카탈로그+분류규칙+응답형식(**배열** `[{id,categoryPath}]`)을 전부 **asst-service 코드 systemPrompt(:347~471)에 하드코딩** → LLM오케스트레이터(customComplete). 새 CE `advisor-category`는 동일 카탈로그가 **CE 쪽 프롬프트로 이동**(우리 눈엔 안 보임, 우리는 conversation만 전송). "하드코딩 위치만 우리→CE 이동", 둘 다 하드코딩.
  - **★ 응답형식 차이(중요)**: CE 개발자가 배열을 못 줘서 사용자가 **파이프 문자열로 타협** — `output.{id:"1|2|3", categoryPath:"A>B>C|D>E>F|..."}`. 실서비스 교체 시 **id·categoryPath 각각 `|` split 후 같은 index끼리 zip**해서 기존 배열 `[{id,categoryPath}]`로 복원 필요(todos/keywords는 단일필드 split, category만 2필드 split+zip). 지금 테스트 4개는 전부 **원본 그대로**(변환 없음), split·zip은 실서비스 교체 시점에 일괄 적용 예정.

### 73. PostCall-LLM 4종 신설 + VOC 실시간 "화남 오표시" 원인규명(프론트 채널 필터) (2026-06-26)
- **PostCall-LLM 4종 신설**(`src/advisor/postcall/`, 기존 summary/todo 무수정): CE service `/ai-apps/advisor-*/runs` 직접호출 테스트 엔드포인트. 그룹명 `PostCall-LLM`(상담사후처리). emotion `analyze/ce-raw` 패턴 복제, 전부 **CE 원본 그대로 반환**(split 안함).
  - ① `POST /postcall/todolist` (advisor-todolist, body conversation+maxLength+includeSimple, 응답 output.todos 파이프) ② `POST /postcall/summary` (advisor-summary, body conversation, output 4필드) ③ `POST /postcall/keywords` (advisor-keywords, body conversation+count, output.keywords 파이프) ④ `POST /postcall/category` (advisor-category, body **conversation만** — categories는 CE 프롬프트 자체보유, output.{id,categoryPath} 파이프).
  - service 공통부 `postToCe<T>()`. 스웨거 summary에 CE path 노출(목록 가시성), description에 full URL. 실서비스 교체 가이드는 `CLAUDE.todo.md` 참조.
  - **emotion(VOC) CE path 변경**: `/ai-apps/emotion/runs` → `/ai-apps/advisor-emotion/runs`(summary.service 상수2+주석 일괄).
- **★ VOC 실시간 "프론트에 화남(0.85) 표시" 원인규명 (코드수정 없음, 진단만)**:
  - **증상**: ce-raw 직접호출은 normal(0.1)인데 프론트 실시간 화면엔 angry/0.85.
  - **경로 확인**: 프론트 실시간 = `handleNlpComplete`(Redis nlp:complete 구독)가 프로덕션 경로(voc-realtime.service.ts:255 주석). `handleUtterance`는 테스트/단발(voc-test). head500 conversation 로그는 handleUtterance(305)에만 있어 실경로엔 안 찍힘.
  - **점수차 원인**: ce-raw=CE원본(remap 없음), 실시간=`remapEmotionScore`(오늘아침 작업) 거침. normal은 0.4~0.59로 재배치돼 **normal/0.1 → normal/0.5**. 단조축(complaint/churn)은 toScore(clamp)만. → ce-raw vs 실시간 점수 다른 건 **의도된 설계**(버그 아님).
  - **0.85의 진짜 정체**: type이 **angry**. remap/프론트 아니라 **CE가 실제 angry 판정**. 원인=해당 call_id 버퍼에 부정발화 누적("어쩌라고/왜 손실이 커요" 등 40턴, 전부 customer·2배중복). 누적분 전체를 CE로 보내(buildConversation) angry 나옴.
  - **★★ 핵심 버그(프론트 해결)**: publish 채널이 **상담사(cc_cti_id) 단위**(`dev:{vendor_tenant_id}:{cc_cti_id}:call:voc`)라 call_id 없음. 4개 화면(로컬/개발/양산/관리자)을 같은 계정으로 열어 각각 call_id 생성→4콜이 같은 채널로 publish→모든 화면이 8메시지(4콜×2턴) 다 수신, 남의 콜(화난 콜)까지 표시. **payload엔 call_id 있음** → 프론트가 `payload.call_id===내call_id` 필터로 해결(채널 cc_cti_id 단위 유지). 백엔드 무수정.
- **남은 개선(미적용, todo)**: 실시간 VOC 버퍼 누적→슬라이딩 윈도우(최근 6~10발화, agent발화 포함, 중복제거, 통화종료 clear). `CLAUDE.todo.md` 등록됨. 커밋은 사용자가 직접.

### 74. VOC 실시간 중복 publish 근본 해결 — 메모리+Redis 2단 dedupe (2026-06-26)
- **증상**: 같은 (call_id, turn_idx)에 대해 VOC 결과가 프론트에 여러 번 노출. 값이 **다른** 중복(emotion 0.65/0.6 등)이라 = 각각 별도로 CE API를 호출한 결과.
- **원인 (2겹)**:
  1. **같은 서버 내 중복**: `handleUtterance`(assist-stream POST)가 turnKey 없이 누적 → 4화면이 같은 call_id+turn_idx로 4번 호출하면 4번 다 분석/publish. (`handleNlpComplete`는 turnKey 있었으나 `turn_idx:speaker:내용길이`라 누적길이 변하면 매번 통과 = 느슨)
  2. **서버 간 중복(진짜 근본)**: **개발/양산 2대 서버가 같은 Redis 공유**. 각 서버는 자기 메모리(`states` Map)로만 dedupe → 서로의 처리를 모름 → 같은 (call_id, turn_idx)를 2대가 각각 분석+publish → 같은 voc 채널이라 프론트가 다 받음. 메모리 가드는 1프로세스 한정이라 원천적으로 못 막음.
- **해결 (2단 가드, `voc-realtime.service.ts`)**:
  1. **메모리 가드**: 두 경로(`handleUtterance`/`handleNlpComplete`) 중복키를 **`call_id:turn_idx`로 통일** → 같은 `state.processedKeys` 공유해 한 경로가 처리하면 다른 경로도 스킵. `accumulate`가 duplicate면 **CE 호출 전에 return**(분석/publish 모두 차단, 비용 절약).
  2. **Redis 가드(분산)**: `acquireVocLock(callId, turnIdx)` 신설 — 분석 직전 `SET voc:dedupe:{call_id}:{turn_idx} NX EX 60`. 여러 서버가 같은 Redis에 원자적으로 1대만 통과. 실패 시 `분산 중복 스킵(Redis)` 로그 후 return. Redis 장애 시 통과(가용성 우선). `redisService.getClient()`(node-redis v4) 사용.
- **전제**: dedupe 키가 call_id+turn_idx라 **같은 통화=같은 call_id**여야 작동. (call_id가 화면마다 다르면 다른 통화로 인식 → 그건 call_id 발급 쪽 문제, Redis로 못 막음.)
- **검증**: 개발/양산 2대 + 동일 Redis에서 **1건만** publish 확인 ✅. 두 서버 다 재시작 필요.
- **별개 잔존(참고)**: 값이 **완전 동일한** 중복이 뜬다면 그건 서버 중복이 아니라 **소켓 2개 연결**(voc 룸 2명) = 프론트 소켓 문제. 프론트 call_id 필터(이미 적용)는 "남의 콜"만 막고 같은 콜 중복수신은 못 막음.
- **남은 개선(todo)**: 버퍼 누적→슬라이딩 윈도우(긴 통화 누적 시 화남 편향). 커밋은 사용자가 직접.

### 75. Redis 한 대 공유 → 채널 env prefix(dev/localDev) 분리 + VOC 락 키 환경분리 (2026-06-29)
- **배경/근본원인**: Redis **1대**를 local/사내개발(5f)/AWS개발 **3환경이 같은 계정**으로 공유. 채널명이 `{env}:{vendor_tenant_id}:{cc_cti_id}:call:{...}` 인데 env=`dev` 고정 + 같은 계정이라 **3환경 채널이 완전히 동일** → 교차 수신/중복. Redis Pub/Sub은 DB index와 무관(전역)이라 `REDIS_DB`로도 격리 안 됨. Redis 인스턴스 분리가 안 되니 **채널 prefix로 논리 분리**(차선).
- **5개 채널 발행자별 제어권**:
  - **voc** → **asst가 발행**(`publishVoc`, voc-realtime.service.ts:~668) → `VOC_CHANNEL_ENV ?? 'dev'`. 우리가 제어. 실시간 프로덕션 경로 `publishVocToChannel`은 nlp 채널명에서 prefix **자동 상속**(설계상 정석).
  - **nlp:complete/partial, events** → **STT 서버 발행**. STT가 **`dev` 고정 배포만 가능**(변경 불가). → 그대로 `dev` 공유. asst는 **중계(relay)만** 하고 처리 안 함(`registerMessageObserver` 정의만 있고 **호출 0건**, `handleNlpComplete` 미사용) → dev 공유돼도 **무해**(읽기 전용).
  - **orchestrator:persisted** → **callbot 발행** → localDev로 전환 완료.
  - **4개 채널은 백엔드 코드 변경 없음**: redis-monitor 구독은 프론트가 채널명 통째로 넘김(`@Param('channel')`) → asst는 prefix를 **만드는 게 아니라 따라감**. prefix 결정자 = 프론트(구독) + 외부 발행자.
- **최종 채널 정책(혼용)**: STT발(nlp/events)=`dev`, asst/callbot발(voc/persisted)=`localDev`. 프론트가 채널별 prefix 섞어서 구독. 한 콜이 두 prefix에 걸치지만 의도된 절충(STT가 dev 고정이라).
- **★ 핵심 버그 — VOC 분산 락 키에 env 없음** (`acquireVocLock`, voc-realtime.service.ts:~418): 키가 `voc:dedupe:{callId}:{turnIdx}`라 **3환경이 같은 락 경쟁** → 턴마다 **먼저 잡은 1환경만** voc 계산·발행하고 나머진 스킵. AWS가 대부분 턴 선점→`dev:voc` 발행→local(localDev 구독)은 못 봄 → **"5턴 넘는데 localDev 1건만 옴"** 증상. (이 락은 원래 *같은 환경 멀티 pod* 중복방지용 #74인데, 한 Redis에 3환경 붙으니 환경 간에도 과 dedupe)
  - **수정**: 키에 env prefix 추가 → `const env = process.env.VOC_CHANNEL_ENV ?? 'dev'; key = voc:dedupe:${env}:${callId}:${turnIdx}`. 환경별 락 독립 → 각 환경이 게이트 턴마다 자기 prefix로 독립 발행(채널 prefix와 락 scope 일치). 검증: `localDev:...:call:voc` 게이트 턴마다 정상 발행 ✅. **락 키 바뀌어 서버 완전 재시작 필요.**
- **env 값 현황**: `VOC_CHANNEL_ENV` — `.env`/`.env.development`(AWS) 없음→기본 dev, `.env.local`/`.env.5f.development` `localDev`. `??`라 미설정만 폴백(빈문자열은 미폴백, 필요시 `|| 'dev'`로 강화 가능).
- **VOC 게이트(참고, 버그 아님)**: `shouldRun` = `totalTurns>=2 && (totalTurns-2)%interval===0`. `REALTIME_VOC_INTERVAL=3`(현재) → 턴 2,5,8,11. 매 턴 원하면 `=1`(턴 2,3,4…; 턴1은 `>=2`라 불가, 코드수정 필요). 카운트 기준=asst 누적 발화수(assist-stream 호출 시작 시점부터).
- **미적용(보류)**: coaching_agent_*/agent-status/notices는 env prefix 없어 여전히 공유되나 **영향 작아 보류**(같은 계정 본인 중복 정도, payload 필터됨). 거슬리면 동일 방식으로 prefix 적용 가능(asst publish+subscribe 둘 다 제어 → 외부 의존 없음). 커밋은 사용자가 직접.

### 76. 상담코칭 실시간 알림 — 코칭 생성 이벤트를 프론트 표준 채널 포맷(redis-message + env prefix)으로 발행 (2026-06-30)
- **요청(프론트 클로)**: 관리자가 코칭 전송 → DB 저장 API(`createCoaching`)가 asst로 옴 → 받는 상담사 소켓 채널로 "코칭 생성" 이벤트 publish 요청. **목적은 단순 — 프론트의 "실시간 미확인 코칭 카운트" 갱신 트리거**(이벤트 받으면 목록만 재조회, 화면 리로드 X). 백엔드는 **트리거만 쏘고 카운트 값은 안 실음**(프론트 재조회).
- **기존 인프라 이미 존재(로직 동작, 포맷만 불일치)**: `createCoaching`(`coaching.service.ts:123`) → `publishCoaching`(Redis `coaching:message`) → `CoachingSocketHandler.handleCoachingMessage`(구독) → Socket.IO emit. `coaching_request`(코칭 요청)는 별개 경로(무수정).
- **receiver_key 정체 확정(프론트 회신)**: `receiver_key = agent.id`(내부 user_key)이며, 소켓 전역필터에 쓰는 **`cc_cti_id`(CTI id)와 다른 별도 필드**. 매핑은 **프론트가** 담당(프론트가 agent 객체에 id·cc_cti_id 다 보유 → 자기 `agent.id`로 코칭 채널 구독). 백엔드는 **receiver_key 기준 room으로 발행만**.
- **포맷 불일치 2건 → 프론트 표준 패턴(`redis-message`)으로 교체**:
  - **채널(room)**: 기존 `coaching_{receiver_key}` → **`${env}:${tenantId}:${receiver_key}:coaching`** (프론트 `getRedisKey(tenantId, agent.id, 'coaching')`와 동일, getRedisKey가 내부에서 env prepend).
  - **이벤트명/payload**: 기존 이벤트명 `coaching`+raw payload → **이벤트명 `redis-message`** + 래퍼 `{ channel, message, timestamp }`, **`message.type='coaching_created'`**로 식별(`broadcastToRedisMonitorRoom`(socket.gateway.ts:561)이 쓰는 바로 그 패턴). message에 receiver_key/sender_key/coaching_id/call_id/coaching_request_id/is_important/priority_type/created_at 포함.
- **★ env prefix 함정(핵심, 프론트 클로가 먼저 지적 → 검증됨)**: 처음엔 prefix 없이 `{tenantId}:{agent.id}:coaching`으로 만들었으나, **이 시스템 채널은 전부 `{env}:` prefix로 시작**(VOC=`dev:{tenantId}:{ccCtiId}:call:voc`, voc-realtime.service.ts:597). prefix 빠지면 프론트 구독채널과 안 맞아 **수신 0**. → 코칭도 **VOC와 동일 소스 `process.env.VOC_CHANNEL_ENV ?? 'dev'`** 사용하도록 수정(모든 채널 prefix 일치, NODE_ENV 의존 금지). #75에서 "보류"했던 coaching env prefix를 이번에 적용한 셈.
- **★ env 값(프론트 공유용, #75 기록 재확인)**: `VOC_CHANNEL_ENV` — **AWS개발(`.env`/`.env.development`)=미설정→기본 `dev`**, **로컬/사내개발(`.env.local`/`.env.5f.development`)=`localDev`**. 즉 코칭 채널 prefix도 환경에 따라 `dev`/`localDev`로 갈림 → 프론트도 환경별로 동일하게 맞춰야 함.
- **tenant_id 확보**: `DynamicDatabaseService.getTenantId(token?)` 신설(내부 `tenantConfigService.getTenantConfig` 재사용; **DB_DIRECT_CON=1(로컬)·조회실패 시 undefined**, throw 안 함 → 코칭 생성 안 깨짐). `createCoaching`이 호출해 `publishCoaching(coaching, tenantId)`로 전달, `CoachingMessage.tenant_id` 필드로 핸들러까지 운반. tenant 없으면 핸들러가 tenant 세그먼트만 생략(env prefix는 유지).
- **수정 파일 6개**: `coaching.constants.ts`(상수), `dynamic-database.service.ts`(getTenantId), `coaching.types.ts`(tenant_id 필드), `coaching-redis.service.ts`(tenantId 인자), `coaching.service.ts`(getTenantId 호출·전달), `coaching-socket.handler.ts`(handleCoachingMessage 채널/이벤트 교체). tsc+eslint 통과.
- **미검증(프론트 최종확인 권장)**: 프론트 `getRedisKey` **실제 출력 채널 문자열 1개**로 100% 검증 — ① env prefix 값(환경별 `dev`/`localDev`, VOC_CHANNEL_ENV 따름) ② 구분자 `:`·마지막 세그먼트 `coaching` ③ `tenantId`/`agent.id` 순서. 일치하면 그대로 배포. 배포 `develop`, 커밋은 사용자가 직접.
- **※ 정정**: 이 #76은 tenant 세그먼트로 `tenant_id`(company UUID)를 썼으나, 실배포 테스트에서 채널 불일치로 **틀린 것으로 판명** → #77에서 `vendor_tenant_id`로 정정함.

### 77. 코칭 실시간 알림 실배포 디버깅 + 미확인 코칭 카운트 전용 API 신설 (2026-06-30)
배포(개발실서버 `ecpad.etaas.co.kr`) 후 "상담사쪽 코칭 알림 안 옴 / 미확인 카운트 0" 증상을 단계별로 추적해 근본 2건을 잡고, 미확인 카운트 전용 API를 신설.

- **① 채널 tenant 세그먼트 = `vendor_tenant_id`여야 함 (★#76 정정)**:
  - #76은 채널을 `${env}:${tenant_id}:${receiver_key}:coaching`로 만들었는데, 실로그상 `tenant_id=company_71900448_1b8a_4ab1_96b3_9f2c1de46740`(company UUID)였음.
  - **프론트가 실제 구독하는 채널은 `dev:4609686:agent_...:coaching`** — tenant 자리가 **`4609686`(vendor_tenant_id)**. VOC 채널(`dev:{vendor_tenant_id}:{cc_cti_id}:call:voc`)도 동일 식별자. 즉 모든 실시간 채널은 tenant_id가 아니라 **vendor_tenant_id**를 씀.
  - `TenantConfigResponseDto`엔 vendor_tenant_id가 **없음**(tenant_id만). vendor_tenant_id는 **`UserInfoService.getCurrentUser(token).company.vendor_tenant_id`**에서만 얻어짐(VOC가 쓰는 방식, voc-realtime.service.ts:653).
  - **수정**: `getTenantId` 경로 폐기 → `CoachingService`에 `UserInfoService` 주입(같은 advisor.module provider라 DI OK), `createCoaching`에서 `getCurrentUser(token).company.vendor_tenant_id` 조회(try/catch, 실패 시 undefined·코칭 생성 무영향). `CoachingMessage.tenant_id`→`vendor_tenant_id` 필드 rename, `publishCoaching(coaching, vendorTenantId)`, 핸들러 채널 `${env}:${vendor_tenant_id}:${receiver_key}:coaching`. vendor_tenant_id는 회사 단위라 sender(관리자)·receiver(상담사) 동일.
  - **검증 로그**: `📡 [코칭] 전송: channel=dev:4609686:agent_0c814a0e_...:coaching, event=redis-message, type=coaching_created (1명 연결)` → `✅ 전송 완료 → 1명`. **백엔드 실시간 emit 정상 동작 확인.** (`getTenantId`는 dead code로 남음, 무해.)
- **② 미확인 카운트 0의 진짜 원인 = 키 불일치(데이터)**: 백엔드 조회 로직은 정상이었음. 
  - `GET /coachings/receiver/{key}`(`findCoachingsByReceiver`): `where {receiver_key, ...buildFilter}` + `findAndCount` → `{data,total,...}`. is_read 파싱도 정상(QueryCoaching(Request)Dto `@Transform` 'true'/'false'→boolean). favorite 2개(`favorite-coaching/user`, `favorite-coaching-requests/user`)는 즐겨찾기(북마크)라 미확인 무관. requests/sender는 발신자 관점이라 무관. **미확인 소스는 `coachings/receiver` 하나뿐.**
  - **실제 증상**: 프론트는 `receiver/agent_349727fe_...`로 조회 → `total:0`. 그런데 코칭 48건은 전부 `receiver_key=agent_0c814a0e_...`로 저장됨(개발실 DB GET 결과로 확인). → **코칭 받은 키(0c814a0e) ≠ 프론트 조회 agent.id(349727fe)**. 실시간도 같은 이유(채널이 0c814a0e라 349727fe 상담사 화면은 미수신).
  - **미해결(내일)**: 이 두 키가 같은 상담사인지 확인 → 같으면 "관리자 코칭 전송 시 넣는 receiver_key" vs "상담사 화면 agent.id"를 일치시켜야(키 정렬). 백엔드 코드 버그 아님(양쪽 다 프론트가 보낸 값 그대로 저장/조회).
- **③ 미확인 코칭 카운트 전용 API 신설** (사용자 핵심 요구 — 처음부터 없던 것):
  - `GET /coachings/receiver/:receiverKey/unread-count` → `{ receiver_key, unread }`. 컨트롤러에서 `receiver/:receiverKey`보다 **위에 등록**(라우트 가로채기 방지). `getUnreadCountByReceiver` 서비스 메서드(QueryBuilder `getCount`).
  - **is_read 타입 함정 대응**: 개발실 응답에서 `is_read`가 **boolean이 아닌 문자열 `"false"`** 로 내려옴(엔티티는 `@Column boolean`인데 실 DB 컬럼이 varchar로 생성된 정황). 카운트가 타입/표현에 안 흔들리도록 **`LOWER(c.is_read::text) IN ('false','f')`** 로 비교(boolean false→'false', varchar 'false'/'f', 대문자 'FALSE' 모두 미확인 카운트). 사용자 요청대로 "boolean과 'false' 모두 포함".
  - 검증: `0c814a0e` 키로 `unread-count` → 정상 동작 확인(사용자 "잘되네"). tsc+eslint 통과.
- **미해결/후속(내일 이어서)**:
  1. **키 매칭**(0c814a0e vs 349727fe) — 같은 상담사인지 + 관리자 전송 receiver_key ↔ 상담사 agent.id 정렬.
  2. **is_read 컬럼 타입** — 실 DB가 varchar 의심. 정규화(boolean 마이그레이션) 또는 엔티티 transformer로 응답 boolean화 검토. (현재 unread-count는 ::text로 우회 중이나, 목록 API의 `?is_read=false` 필터는 varchar 컬럼이면 깨질 수 있음 → 점검 필요.)
  3. **coaching created_at 타임존**(별개, 보류): `timestamp`(no tz)+서버 TZ=UTC라 KST 벽시계가 `...Z`(UTC)로 라벨링돼 나감 → 프론트 표시 어긋남. 해결책 A(백엔드 `+09:00` 직렬화) / B(프론트 Z 무시) 중 택. started_at 선례와 동일 패턴.
  - 상세 프로세스/구조는 `docs/advisor-coaching-process.md`에 정리(내일 작업 기준 문서). 커밋은 사용자가 직접.

### 78. 코칭요청(관리자 수신) 대칭화 — 미확인 카운트 API 신설 + 실시간 발행 표준 통일 (2026-06-30)
#76·#77에서 **코칭(상담사 수신)** 쪽만 신표준으로 작업됐고 **코칭요청(coaching_request, 관리자 수신)** 쪽은 옛 패턴 그대로 + 미확인 카운트 API 없음 → **비대칭** 상태였음. 관리자 상단 메뉴의 미확인 코칭요청 배지 실시간 갱신을 위해 코칭요청 쪽을 코칭과 **완전 대칭**으로 맞춤. (프론트 요구: ①관리자/상담사 미확인 카운트 실시간 노출 ②코칭요청 토스트+API적립 ③관리자쪽 무리로드 갱신 미구축 ④상담사/관리자별 카운트 API 정합성.)

- **분석 — 두 흐름 비대칭 확정**: 코칭(`coachings`, 상담사) = `redis-message`+`${env}:${vendor_tenant_id}:${receiver_key}:coaching`+unread-count API ✅ / 코칭요청(`coaching_requests`, 관리자) = 옛 room `coaching_{receiver_key}`+이벤트 `coaching_request`+raw payload, vendor_tenant_id 없음, unread-count 없음 ❌. `handleCoachingRequestMessage`가 #76 작업 전 옛 코드 그대로였음.
- **작업 1 — 코칭요청 미확인 카운트 API 신설**: `GET /coachings/requests/receiver/:receiverKey/unread-count` → `{receiver_key, unread}`. 서비스 `getUnreadCountRequestByReceiver`(코칭쪽 `getUnreadCountByReceiver` 복제, 테이블만 `CoachingRequest`). is_read 타입 함정 동일 대응 `LOWER(c.is_read::text) IN ('false','f')`. 컨트롤러에서 `requests/receiver/:receiverKey`(목록)보다 **위에 등록**(라우트 가로채기 방지).
- **작업 2 — 코칭요청 실시간 발행 표준 통일(코칭과 대칭)**:
  - 채널: 옛 `coaching_{receiver_key}` → **`${env}:${vendor_tenant_id}:${receiver_key}:coaching_request`** (접미사만 `coaching_request`로 코칭과 분리 — 사용자 확정: 접미사 분리안).
  - 이벤트: 옛 `coaching_request`+raw payload → **`redis-message`** + 래퍼 `{channel, message, timestamp}`, **`message.type='coaching_request_created'`**. message에 receiver_key/sender_key/**coaching_request_id**/call_id/is_important/priority_type/created_at.
  - 발행부: `createCoachingRequest`에서 `UserInfoService.getCurrentUser(token).company.vendor_tenant_id` 조회(try/catch 무시, 실패 시 코칭요청 생성 무영향 — 코칭과 동일 패턴) → `publishCoachingRequest(savedRequest, vendorTenantId)`.
- **수정 파일 6개**: `coaching.constants.ts`(`COACHING_REQUEST_CHANNEL_TYPE='coaching_request'`/`COACHING_REQUEST_CREATED_MESSAGE_TYPE='coaching_request_created'`), `coaching.types.ts`(`CoachingRequestMessage.vendor_tenant_id?`), `coaching-redis.service.ts`(`publishCoachingRequest` vendorTenantId 인자), `coaching.service.ts`(createCoachingRequest vendor_tenant_id 조회·전달 + getUnreadCountRequestByReceiver), `coaching.controller.ts`(unread-count 라우트), `coaching-socket.handler.ts`(handleCoachingRequestMessage 채널/이벤트 교체, import에서 SOCKET_COACHING_EVENTS 제거·REQUEST 상수 추가). tsc+eslint 통과.
- **읽음처리는 신규 작업 없음(기존 API 그대로)**: 관리자=코칭요청 읽음처리 = **기존 `PATCH /coachings/requests/:id/read`**(`markCoachingRequestAsRead`, `coaching_requests` 테이블). 단건만 지원(일괄은 요청 시 추가). 읽음 후 unread-count 재조회로 배지 갱신.
- **프론트 전달 정리(대칭표)**: 상담사=코칭(`coachings`,우측 LNB,`:coaching`,`coaching_created`,`/coachings/receiver/{id}/unread-count`,`PATCH /coachings/{id}/read`) ↔ 관리자=코칭요청(`coaching_requests`,상단 메뉴,`:coaching_request`,`coaching_request_created`,`/coachings/requests/receiver/{id}/unread-count`,`PATCH /coachings/requests/{id}/read`). 백엔드는 트리거만 발행(카운트 값 미포함→프론트 재조회). 생성 API만 호출하면 실시간 자동 발행.
- **백엔드 작업 완료 — 남은 건 프론트 + 조건부 백엔드**:
  1. **키 매칭(공통, #77 ②와 동일)**: `receiver_key` ↔ 화면 `agent.id` 일치해야 unread/실시간 둘 다 동작(불일치 시 `unread:0`+미수신). 결과 따라 백엔드 키 정규화 추가 가능성.
  2. **vendor_tenant_id 출처**: 프론트 user 정보 `company.vendor_tenant_id`(예 4609686), 채널 일치 필수.
  3. **배포 반영**: 재배포(이미지 재빌드+롤아웃) 전엔 신규 API/채널 미노출. 커밋·배포는 사용자가 직접.

### 79. VOC 감정 — 불만/화남 과다 노출 완화 (score>=0.6에만 -0.15 감점) (2026-06-30)
"실시간 VOC에서 불만/화남이 너무 빈번하게 노출된다"는 요청. 분석 결과 노출 빈도는 전적으로 CE가 보내는 emotionType에 의해 결정됨(우리 서비스는 그대로 신뢰해 위험 단조 score로 재배치만 함). 부정쪽만 보수적으로 완화하도록 remap 출력 score에 감점 적용.

- **구조 파악**: CE `emotionType`(thanks/satisfied/normal/dissatisfied/angry)+`emotionScore` → `remapEmotionScore`(summary.service.ts)가 **타입을 신뢰**해 위험 단조 구간으로 재배치(thanks 0~0.19 / satisfied 0.2~0.39 / **normal 0.4~0.59 / dissatisfied 0.6~0.79 / angry 0.8~1.0**). 프론트는 이 score를 0.6(불만)·0.8(화남) 컷으로 버킷팅(사용자 "0.5 normal, 0.6↑ 불만"과 일치).
- **핵심 진단**: normal 타입은 0.59에서 clamp돼 절대 0.6을 못 넘음 → 불만/화남 표시 = CE가 dissatisfied/angry로 분류한 것. 밴드 숫자만 넓히면 프론트 컷(0.6 고정)과 type-score 정합 깨짐 → **유일한 백엔드 레버 = 부정 score 감점(약한 건 normal로 강등)**.
- **빼기는 CE raw가 아니라 최종 remap된 출력 score에 적용해야 효과**: CE raw에 빼면 remap이 타입으로 재버킷팅해 효과 미미. (사용자에게 이 전제 설명·합의.)
- **결정(사용자)**: A안=「score>=0.6일 때만 감점」(normal/긍정 무손상) + 감점폭 **0.15**. (초기 제안 0.1 → 사용자가 0.15로 상향. "둘 다"(post-call+실시간) 적용.)
- **구현**: `remapEmotionScore` 최종 score 산출 직후 — `if (score >= 0.6) score -= 0.15`, 이후 `deriveEmotionTypeFromScore(score)`로 **type 재산출**(경계 넘으면 type도 강등, type-score 정합 유지). 상수 `NEGATIVE_EMOTION_PENALTY_THRESHOLD=0.6`/`NEGATIVE_EMOTION_PENALTY=0.15` 신설. `remapEmotionScore`는 post-call 요약·실시간 VOC 공용이라 둘 다 자동 반영. DB 저장값(sentiment_type/score)도 감점 정합값.
- **실효 효과**: 불만 0.60~0.74→normal, 0.75~0.79→불만 유지 / 화남 0.80~0.94→불만, 0.95~1.0→화남 유지. **불만 컷 0.6→0.75, 화남 컷 0.8→0.95.** normal·긍정(<0.6) 원본 그대로.
- **수정 파일 1개**: `src/advisor/summary/services/summary.service.ts`. tsc+eslint 통과.
- **남은 것**: 재배포 후 사용자 실측 테스트(감점폭 0.15 적정성 확인 — 과하면 0.1로, 부족하면 상향 등 상수만 조정). 커밋·배포는 사용자가 직접.

### 80. 실시간 VOC 누적 끌어올림 완화 — 분석 입력을 최근 4개 발화로 제한 (2026-06-30)
#79(emotion -0.15 감점) 배포 후에도 "emotion 점수가 계속 높다"는 후속. 원인 추적 중 두 가지 규명 + 사용자 직감(누적대화) 채택해 입력 윈도우 도입.

- **진단① VOC_ANALYZER 경로 분기**: `.env.5f.development`에 `VOC_ANALYZER=llm` → 5층은 **LLM 경로(analyzeVocViaOrchestrator)** 를 타는데 이건 `remapEmotionScore`(=#79 감점)를 **안 거침**. AWS 개발기(.env.development)는 미설정→기본 `ce`→감점 적용. **5층에서 테스트했으면 #79가 0% 적용**된 것. (로그로 판별: `VOC 분석 완료(CE)` = ce경로/감점됨 vs `VOC 분석 LLM 응답` = llm경로/미적용.)
- **진단② 누적 끌어올림(사용자 직감, 채택)**: 실시간 VOC는 매 분석 턴마다 `buildConversation(state.messages)`로 **누적 버퍼 전체(최대 MAX_BUFFER=40)** 를 LLM/CE에 통째로 넘김 → 초반 화난 발화 1건이 이후 모든 턴 점수를 계속 끌어올림(후반 진정돼도 안 내려감).
- **결정(사용자)**: assist-stream(`toRagHistory`: 화자별 최근 3턴)처럼 분석 입력을 단기 윈도우로 제한. 크기=**최근 4개 단순컷(slice(-4), 화자 구분 없음)**, **상수 고정**(env 미사용).
- **구현**: 상수 `MAX_ANALYSIS_MESSAGES=4` 신설. 분석 입력 생성 2곳(nlp:complete 경로 ~223, handleUtterance 경로 ~340) 모두 `buildConversation(state.messages.slice(-4))`로 변경. 메모리 버퍼(MAX_BUFFER=40)·accumulate·post-call 요약(summarizeCall, 전체 대화 유지)은 **무수정**. 진단 로그를 `lines=4/12(누적)`로 보강(실입력/누적 가시화).
- **효과/범위**: 초반 화난 발화가 윈도우 밖으로 밀리면 점수에서 빠짐 → 누적 끌어올림 해소. **CE·LLM 경로 무관 적용**(5층 llm에서도 동작) → #79 감점(CE 전용)과 독립적으로 보완. emotion뿐 아니라 민원·이탈도 같은 입력이라 3축 다 "최근 기준"으로 단기화(실시간 조기경보엔 자연스러움).
- **수정 파일 1개**: `src/advisor/assist-stream/services/voc-realtime.service.ts`. tsc+eslint 통과.
- **남은 것/내일**: 재배포 후 실측 — ① 어느 환경/경로(ce·llm)에서 보는지 로그로 먼저 확정 ② 윈도우 4개로 점수 추세 개선되는지 ③ 부족하면 윈도우 크기(상수)·#79 감점폭 같이 조정. 5층에서 #79까지 먹이려면 `VOC_ANALYZER=ce` 전환 또는 LLM 경로에도 감점 추가 필요. 커밋·배포는 사용자가 직접.

### 81. 코칭 시간 표시 어긋남 — created_at/updated_at KST→UTC(...Z) 보정 (2026-07-01)
관리자/상담사 코칭 모달의 코칭 리스트 시간이 어긋나던 문제. 실측: 작업 시각 10:18(KST)인데 API가 `created_at:"2026-07-01T10:18:25.333Z"`로 응답 → 프론트 `new Date().toLocaleString('ko-KR')`가 +9 더해 어긋남.
- **원인**: `coachings/coaching_requests`의 `created_at`은 `@CreateDateColumn`을 **DB `now()`**(세션 TZ=KST)가 채워 `timestamp`(no tz) 컬럼에 **KST 벽시계**로 저장됨. 앱(node-postgres, 프로세스 TZ=UTC)이 이를 그대로 UTC로 읽어 `...Z`로 **잘못 라벨링**. DTO엔 created_at 없고 전역 ValidationPipe(whitelist)라 클라 주입 불가 → 값 출처는 DB뿐. `started_at`(raw_call) 선례와 **완전 동일 케이스**.
- **수정(코칭 전용, 다른 도메인 무수정)**: `CoachingService`에 `toUtcIso`(call-stats/advisor.service 선례 복제: KST 벽시계를 `+09:00`으로 해석 → `toISOString`) + `normalizeDates`(created_at/updated_at in-place 보정) 추가. 모든 코칭 출력 지점에 적용 — 생성 2곳(**Redis 발행 직전**에 보정해 실시간 토스트도 동일 교정), findByCallId, 목록 4개, update/mark 4개.
- **효과**: `10:18Z`(오출력) → `01:18Z`(진짜 UTC) → 프론트 +9 → 07-01 10:18(KST) 정확. 수정 파일 1개 `coaching.service.ts`, tsc+eslint 통과.
- **별개 발견(사용자: A안 미사용 결정으로 보류)**: `src/tz-init.ts`(`process.env.TZ='UTC'`)가 **어디서도 import 안 됨**(main.ts엔 주석만). 현재 컨테이너 기본 UTC라 마스킹 중이나, 컨테이너 TZ가 KST면 콜목록 started_at이 +9 어긋날 잠재버그. 커밋·배포는 사용자가 직접.

### 82. 실시간 VOC 토큰 만료 무력화 — 유저 토큰 의존 제거(payload 우선/토큰 폴백) + db_config 연결문자열 캐시 (2026-07-02)
전날(07-01 14:19:38 KST) 상담원 access 토큰(20분) 만료 후 **실시간 VOC 감정변화 미표시 + 통화종료 후 summary 401** 사고. 대화(STT)는 토큰무관이라 정상, VOC/summary만 무증상 정지(try-catch 격리 부작용). 분석문서 `docs/IIWAKE.md` 기반으로 근본 대응. (SSO refresh API는 정책상 미구현 → 우리 쪽은 "토큰 만료와 무관하게 동작"만 목표.)

- **인증 구조 코드 확정(블랙홀 해소)**: `AuthMiddleware`는 **토큰 검증 안 함**(라우팅 재료로만 사용, "토큰 검증 생략"). 토큰 목적지는 **오직 `USER_HOST`**(`get_configs?filters=db_config`=`TenantConfigService`, `get_user`=`UserInfoService`). 코드 전체에 **SSO/OIDC/keycloak/auth-service 참조 0개**. → 어제 401은 asst가 아니라 **user-service(USER_HOST)가 만료토큰 거부**한 것. SSO(발급자)와 user-service(소비자·401 주체)는 **다른 시스템**. user-service의 토큰 검증 방식(자체 JWKS vs IdP introspect)은 우리 레포로는 확인 불가(=블랙홀 경계).
- **어제 사고 지점 = `/assist-stream`→`handleUtterance`의 토큰 의존 3다리(전부 만료 시 사망)**: ①LLM `analyzeEmotion`→`getCompanyIdFromToken`→`getCurrentUser(token)` ②publish `publishVoc`→`getCurrentUser(token)`(vendor_tenant_id+cc_cti_id) ③DB `persistVoc`→`getRepository(token)`→`getTenantConfig(token)`. **화면 멈춤 직접 원인은 ②**(getCurrentUser 401→publish 스킵). (`/assist-stream`은 AuthMiddleware exclude라 미들웨어發 401은 없음.)
- **해결 원칙(합의)**: VOC는 유저 신원 불필요·테넌트 정보만 필요 → **payload 값 있으면 토큰 안 씀 / 없으면 기존 토큰 경로 폴백**(하위호환·전부 예외격리).
- **프론트 협조(완료)**: `POST /assist-stream` body에 `company.id`/`company.vendor_tenant_id`(기존 전송중) + **`cc_cti_id` top-level 신규 추가**(company 밖, 값 없으면 필드 생략). company.id는 실시간 화면 진입 시 get_user로 store 채워 통화중 항상 존재.
- **구현(수정 4파일, tsc+eslint 통과)**:
  - `assist-stream-request.dto.ts`: `cc_cti_id?: string` top-level 옵셔널 추가.
  - `voc-realtime.service.ts`: **①** `dto.company.id` 있으면 `analyzeVocByTenant(conv, company.id, 'realtime', token)`(토큰 0), 없으면 `analyzeEmotion` 폴백. **②** `publishVoc`가 `dto.company.vendor_tenant_id`+`dto.cc_cti_id` 우선, 둘 중 하나라도 없을 때만 `getCurrentUser(token)` 폴백. **③** `persistVoc(...,vendorTenantId)` 추가 + 신설 `resolveVocRepository`(토큰 유효→토큰경로 / throw·부재→`getConnectionByVendor(vendor)` 캐시 재접속 / 최종 로컬 정적연결). `handleUtterance` 첫부에 **prime**: `cacheConnString(token, vendor_tenant_id)` fire-and-forget. nlp 경로도 `msg.tenant_id` 전달(현재 미사용이나 정합).
  - `dynamic-database.service.ts`: `vendorMeta: Map<vendor_tenant_id,{tenantId,connString}>` 신설. `cacheConnString`(토큰 유효 시 db_config 1회 캐시, 로컬/중복/토큰없음 self-guard, best-effort) + `getConnectionByVendor`(살아있는 커넥션 재사용→없으면 캐시 연결문자열로 토큰없이 재생성+runSchemaMigrations). 엔티티 배열 **`DYNAMIC_ENTITIES` 상수 추출**(getConnection+재접속 경로 공유, 옵션빌더 `buildDynamicDataSource`로 통합해 중복 제거). **핵심: db_config(연결문자열)는 만료 안 됨** → 토큰 유효할 때 캐시하면 만료 후 재접속 가능. 키를 vendor_tenant_id로 두는 이유=connections Map 키(tenant_id)는 payload에 없음(두 API 출처 상이).
  - `assist-stream-new.controller.ts`/`.service.ts`: **미사용(NOT IN USE)** 상단 주석(프론트 미호출, 실트래픽은 `/assist-stream`, 인증 이슈 검토 제외).
- **결과**: ①②③ 전부 토큰 만료 무관 → 어제 사고 구조적 재발 불가. **로컬/배포 전 서버 풀재시작 필요**(dynamic-database 캐시 DataSource 갱신).
- **남은 것**: ① `hasCompany`/`vendor_tenant_id` 로그로 payload 항상 오는지 실측(false여도 토큰 폴백으로 안전동작하나 그 통화는 만료 취약) ② `voc-test`로 토큰없이 저장/publish 검증 ③ summary 등 **유저 권한판정 필요 엔드포인트는 별개**(refresh/BFF 논의 대상, 이번 범위 아님). 커밋·배포는 사용자가 직접.

### 83. 통화 종료 후 summary/summary-data 토큰 만료 무력화 — payload company 우선/토큰 폴백 (2026-07-02)
#82(실시간 VOC)에 이어, **통화 종료 시 프론트가 보내는 `/summary`(createSummary)·`/summary/data`(saveSummaryData)도 VOC/DB 때문에 토큰에 동일 의존** — 프론트가 먼저 이 상황을 확인 요청. 어제 사고의 "통화종료 후 summary 401"이 바로 이 경로였고, #82에선 "유저 권한판정 필요"라며 범위 밖으로 뒀으나 재검토 결과 summary는 실제 권한판정 안 함(테넌트ID+DB커넥션만 필요) → 실시간과 동일하게 payload 우회 가능.
- **진단(토큰 3의존)**: `summarizeCall`(summary.service.ts) — ① raw_call 읽기 `getRepository(CallstatCall/Turn, token)` ② tenantId `getCompanyIdFromToken(token)`→`getCurrentUser`(=어제 401 지점) ③ `analyzeVoc`(②의 tenantId) ④ `saveEmotion(...,token)` DB쓰기. `createOrUpdateSummary`(/summary/data) — VOC 없음, `getRepository` x3(Summary/CallCategory/CallKeyword) DB커넥션만.
- **프론트 계약(완료·동시배포)**: 두 엔드포인트 body에 `company:{ id, company_id, vendor_tenant_id, name }` 추가. 실시간 `AssistStreamCompanyDto`와 동일(`company.id`=회사UUID=X-Tenant-Id, `vendor_tenant_id`=DB연결 캐시키). 값 없으면 필드 생략→토큰 폴백.
- **⚠️ 400 함정**: 전역 ValidationPipe `forbidNonWhitelisted:true`라 DTO에 `company` 없으면 프론트가 보내는 순간 summary 전면 400 → **프론트·백 동시배포 필수**(사용자가 둘 다 배포하므로 OK).
- **DB 우회 원리**: `vendor_tenant_id→연결문자열(vendorMeta)` 캐시는 **통화 중 실시간 VOC(#82 cacheConnString)가 이미 채워둠** → 통화 끝나고 만료토큰 summary 와도 `getConnectionByVendor(vendor)`로 토큰 없이 재접속. 실시간 미경유 통화는 짧아 그 시점 토큰 유효→토큰 경로 동작.
- **구현(수정 6파일, tsc+eslint+build 통과)**:
  - `summary-company.dto.ts`(신규): `SummaryCompanyDto{ id, vendor_tenant_id, company_id?, name? }` — 실시간 DTO 복제.
  - `summary-request.dto.ts`/`summary-create.dto.ts`: `company?: SummaryCompanyDto` 옵셔널 추가(@ValidateNested/@Type).
  - `advisor.service.ts`: **`getRepositoryResilient(entity, token, vendorTenantId?)` 신설** — #82 `resolveVocRepository` 패턴 공용화(토큰 유효→토큰경로 / 만료·throw→`getConnectionByVendor` / 로컬 `getConnectionWithoutToken` / 최종 기존에러 재현). voc-realtime의 중복 로직을 AdvisorService로 승격.
  - `summary.service.ts`: `summarizeCall` — tenantId=`company?.id ?? getCompanyIdFromToken(token)`, raw_call repo 2개 resilient화, `saveEmotion`에 vendor 전달. `createOrUpdateSummary` — repo 3개 resilient화. 로그에 `hasCompany`/`vendor` 보강.
  - `emotion.service.ts`: `saveEmotion`/`persistEmotion`에 `vendorTenantId?` 추가, repo를 `getRepositoryResilient`로(VOC 실제 저장 보장).
- **원칙**: payload 있으면 토큰 안 씀 / 없으면 기존 토큰 폴백(전부 하위호환). **배포 후 서버 풀재시작 필요**(#82와 동일, 캐시 DataSource 갱신).
- **연계 산출물(대신증권 소명)**: 관련부서 요청으로 어제 감정분석 장애 소명문서 작성 → `docs/대신증권_감정분석_장애_소명.md`(IIWAKE.md 기반, 인프라 비판 제거·존댓말 소명체, 원인→영향→조치①②완료/③협의제안→재발방지 + 비개발자용 [간단 요약]). #82=실시간 감정미표시, #83=요약401에 각각 1:1 대응해 "조치 완료"로 묶음.
- **남은 것**: ① 실측 — 긴 통화(토큰 만료) 후 summary에서 VOC 3축 응답·emotions 저장·/summary/data 저장 정상인지, 로그 `hasCompany`/`vendor`로 payload 도착 확인 ② 소명문서 ①·② "조치 완료" 표기는 실배포 상태 맞춰 사용자가 확정(미배포면 "배포 예정"으로) ③ 유저 권한판정 진짜 필요한 엔드포인트의 refresh/BFF는 여전히 별개 논의. 커밋·배포는 사용자가 직접.

### 84. 세션 만료 사전 알림 — assist-stream SSE `event: auth-expiry` (2026-07-02)
사용자 아이디어: access 토큰 20분으로 짧으니 만료 전에 프론트에 미리 알리자. #82/#83이 "감정·요약은 토큰 없어도 됨"(면역)이라면, 이건 "상담원이 만료를 인지"하게 하는 보완(세션 자체 연장은 refresh/BFF 영역이라 별개).
- **정책 확정(사용자)**: 현재 **silent refresh 없음(정책상 미구현)** → **알림 전용**(자동갱신 아님, 프론트가 재로그인/저장 안내). 신호는 **남은시간+플래그 같이**. 임계값 **5분(300초)**. 전송 방식은 **"5분 이하면 발화마다 계속"**(사용자가 "한 번만"보다 선호) — 근거: stateless(서버가 callId별 '이미 보냄' 상태 안 들어도 됨=누수無), 유실 이벤트 자가복구, 중복표시는 프론트 dedupe(결합도↓).
- **주입 지점**: `assist-stream.service.ts` `stream()`의 `flushHeaders()` 직후(기존 `event: asst-latency` 커스텀 이벤트 옆). `res`는 그 요청 1건의 응답스트림이라 **broadcast 아님 — 요청 보낸 그 상담원한테만 1:1**(token도 그 요청 헤더에서 뽑은 본인 것 → exp도 본인 것). VOC publish(Redis→소켓 1:N)와 명확히 구분됨(사용자 질문으로 확인).
- **구현(수정 2파일, tsc+eslint+build 통과)**:
  - `src/common/utils/jwt.utils.ts`(신규): `getTokenExpiry(token)` — **서명검증 없이 payload.exp만 base64url 디코드**(안내용 힌트, 인증판정 사용금지 명시). README에만 있고 실파일 없던 jwt.utils 신설.
  - `assist-stream.service.ts`: 상수 `AUTH_EXPIRY_WARN_SEC=300` + `writeAuthExpiryEvent(res, token)` — exp 읽어 `expiresInSec=exp-now`, **>300이면 미전송**, ≤300이면 `event: auth-expiry\ndata:{ expiresInSec, expiresAt(KST+09:00), warn:true, thresholdSec:300 }` 전송. 이미 만료면 expiresInSec 음수(프론트가 만료 구분). 전부 try/catch 격리(알림 실패가 스트림 무영향).
- **프론트 전달(규격만 만들어 사용자가 전달)**: `event: auth-expiry` 구독 → warn/expiresInSec로 상담원 안내(배너/토스트), 배너 중복은 프론트 dedupe. 미대응이어도 무해(모르는 이벤트 무시). **배포 순서 무관**(백엔드 먼저 배포해도 프론트 미붙음=무해). 백엔드 배포는 사용자 몫(Claude는 프론트팀 연락 채널 없음—규격만 산출).
- **남은 것**: ① 배포 후 실측 — 만료 5분 전 통화에서 `event: auth-expiry` 수신 + 로그 `[AUTH-EXPIRY]` 확인 ② 프론트 리스너 배선(사용자 전달) ③ 근본(1h20m 상한 넘기기)은 여전히 refresh/BFF. 커밋·배포는 사용자가 직접.

### 85. 대신증권 토큰만료 장애 소명문서 + refresh 발견으로 근본해결 확정 (2026-07-02)
#82~84(어제 07-01 14:19:38 KST 상담원 토큰만료로 실시간 감정분석·통화후 요약 먹통) 건을 **대신증권(고객)에 소명**하라는 요청. 소명문서 작성 → 진단 심화 → **프론트가 refresh API 발견·근본해결까지** 하루에 마무리. 문서 `docs/대신증권_감정분석_장애_소명.md`.
- **소명문서 톤(핵심)**: 내부 분석문서 `docs/IIWAKE.md`와 달리 **고객용 존댓말 소명체, 인프라 비판 제거**. 비개발자 대상. 구조=1.개요 2.원인 3.영향 4.조치 5.재발방지 + 부록(로그근거) + [간단요약](사용자 직접 편집 영역). **6장(향후 협의)은 "보안정책 충돌 확인 요청"이 괜히 부스럼이라 사용자가 삭제**.
- **로그 근거자료(부록) — `docs/error-log-20260701.md`(60184줄, UTC 타임스탬프) 분석**: agent41(sub=1232) 토큰 exp **14:19:38 KST**(=IIWAKE 사건시각 일치) 디코드 확인 + 만료 후 **14:23:02까지 204초·104건** 만료토큰 계속 전송(전부 401). 만료 직후 로그: `VocRealtimeService 실시간 VOC 처리 실패(무시): Failed to get current user: Unauthorized` / `TenantConfigService·DynamicDatabaseService 401` / 인증서버 원문 `토큰 인증 실패: 401: token 만료`. **로그가 인과사슬 전부 증명**. 토큰값·IP 마스킹, UTC→KST 환산 표기. (14:24:38 등장 새 토큰은 refresh 아니라 **테스트 재로그인**이라 근거서 제외 — 사용자 정정.)
- **원인 진화(3단계)**: ⓐ초기 "재발급 없음(정책)" → ⓑ"통화중 화면전환 없어 갱신 미트리거(추정)" → ⓒ**프론트 확정**: 재발급이 **axios 응답 인터셉터(401+code:107)에만 반응형**으로 존재, **assist-stream은 SSE라 raw fetch 필수 → 인터셉터 못 탐** → 통화중 발화만 도는 구간엔 갱신계기 0 → 만료. (SSE 통신구조가 자동갱신 흐름과 분리된 **기술적 특성** — 소명문서/메일은 "누락"이 아닌 이 톤으로 프레이밍해 책임감 완화.)
- **refresh API 발견(판 뒤집힘)**: 사용자가 `POST https://ecplab-gw.etaas.co.kr/auth/refresh {refreshToken}` 발견. 응답 디코드로 **완전 롤링 확인** — 호출 시 accessToken(+20분)·refreshToken(+65분)·displaySessionExpiredAt(+60분) 전부 리셋, 새 refresh exp가 옛것보다 뒤로 밀림. **활동 중 무한 연장 가능**. 담당자 회신 "수정한 것 없음"=**어제도 있었음**(신규 아님). → "silent refresh 없다"는 #84 전제가 깨짐. **asst-service 코드 변경 0**(토큰관리는 프론트+게이트웨이 소관).
- **프론트 최종 구현(2축, 확정)**: **A. 선제 타이머** — sessionStorage(VITE_COOKIE_USE_AT=false) 토큰 읽어 **만료 ~3분 전 주기 refresh**(모든 요청이 매번 저장소서 토큰 재읽기라 저장소만 갱신되면 다음 발화부터 새 토큰 자동적용, assist-stream 코드 무수정). **B. auth-expiry 세션칩** — 우리 #84 이벤트 구독해 헤더에 "세션정보" 칩(주황/빨강+툴팁) 표시(안전망). → **우리 #84가 버려진 게 아니라 "2차 안전망"으로 실역할 부여됨**. 백엔드 #84 필드(`auth-expiry`/`expiresInSec`/`expiresAt`/`thresholdSec`)가 프론트 `AuthExpiryEvent`와 **계약 일치 확인 → 백엔드 무변경**.
- **배포**: 백엔드 배포 완료(#82~84), 프론트 배포 중. 소명문서 ①②③ 전부 **조치 완료**로 확정. 커버 이메일도 작성(발송 완료).
- **교훈/메모**: ① 고객 소명문서엔 dev 특수케이스(로컬 dev토큰 exp 2083 불멸) 제외 — AWS 실환경 기준만. ② "적용예정 vs 조치완료" 등 상태표기는 실배포 맞춰 사용자가 확정. ③ 문서에 "세부기술 요청시 제공" 같은 상투구도 고객이 부스럼 느낄 수 있음(단 무해). ④ **외부 curl(/auth/refresh 등)은 사용자가 직접 실행**, Claude는 오프라인 디코드·명령작성만.

### 86. 실시간 이전대화 조회 API 신규 + 문서정보(assist-snapshot) 저장/조회 구조 파악 (2026-07-06)
프론트 요청: 상담 통화 중 페이지 이탈/뒤로가기 후 복귀하면 실시간 STT 대화가 인메모리라 화면에서 사라짐 → "이전대화 불러오기"용으로 저장된 turn 조회 API 필요. 제안 `GET /aicc/asst-service/turns?call_id=`.
- **테이블 관계 재확인(사용자 분석 검증)**: `raw_call.callstats_call.id`(PK) = 다른 테이블들이 참조하는 `callstats_id`(1:N). `callstats_call.call_id`는 외부에서 전달받은 통화ID로 id와 1:1이지만 조인키 아님. `callstats_turn.callstats_id` = `callstats_call.id`. 코드 근거: `call-stats.service.ts:66` `ck.callstats_id = call.id`, `:155` `call.id = s.callstats_id`. **turn_idx는 0부터 시작**(프론트 명세는 "1부터"라 되어있어 불일치 — 프론트에 전달 필요).
- **기존 유사 API 존재**: `GET /callstat/calls/by-call-id/:call_id/turns`(findTurnsByCallNumber)가 거의 동일. 차이 딱 2가지 → ① 응답이 `CallstatTurn` 엔티티 통째(프론트는 `{call_id,turns:[6필드]}` 래핑) ② call 못 찾으면 **404 throw**(프론트는 실시간 화면이라 빈배열 원함). 결론: **기존은 손 안 대고**(다른 소비자 영향 방지) 내부 조회로직만 재활용해 신규 생성.
- **구현(수정 2파일, tsc 통과)**:
  - 경로 확정(사용자 지정): **`GET /callstat/calls/realtime-by-callid/:call_id/turns`**(게이트웨이 `/aicc/asst-service/callstat/calls/realtime-by-callid/{call_id}/turns`). 프론트 제안 `/turns` 대신 명시적 경로로.
  - `advisor.service.ts`: `findTurnsRealtimeByCallNumber(callId, token)` 신설 — call_id로 CallstatCall 찾고 없으면 `{call_id, turns:[]}`, 있으면 `callstats_id=call.id`로 turn 조회(turn_idx ASC) 후 6필드(callstats_id/turn_idx/role/utterance/masked_utterance/created_at) 매핑. **전체를 try/catch로 감싸 통화없음/턴없음/오류 전부 예외 없이 빈배열**(실시간 화면 보호).
  - `callstat.controller.ts`: 엔드포인트 + Swagger 스키마 추가.
  - 프론트 전달: 변경된 endpoint 통보 + turn_idx 0-base 주의.
- **문서정보 조회 질문 조사(사용자 질문: 상담종료 후 대화이력에 메시지별 "문서정보"가 노출됨 → DB저장한다는 뜻, 조회 API 있나?)**:
  - **저장처 = `advisor.callstat_assist_snapshot`** 테이블. assist-stream이 실시간 relay하는 "근거문서 Top5 + hint + distilled + answer"를 turn별로 저장. 컬럼: id(uuid PK), call_id(varchar128), turn_idx(int4), customer_query(text, 매칭보강), payload(jsonb=sources/hint/distilled/answer), created_at. `@Unique(call_id, turn_idx)` upsert.
  - **저장 API**: `POST /assist-stream/snapshot`(AssistSnapshotController, upsert) — GET 조회 전용 엔드포인트는 **없음**.
  - **조회 경로**: 문서정보만 뽑는 독립 GET은 없고, `GET /callstat/calls/:id` 통화상세 응답의 **`snapshots` 배열**로 포함됨(advisor.service.ts:423, `call.call_id`로 조회 turn_idx ASC). 즉 프론트가 대화이력 화면에서 문서정보 보는 건 이 상세 API의 snapshots로 추정.
  - **남은 것**: 이번 realtime turns와 짝으로, 문서정보도 call_id 단독으로 빈배열-안전 조회하는 전용 GET이 필요한지는 프론트 확인 후 결정(현재는 상세 API에 묶여있음). 커밋·배포는 사용자가 직접.

### 87. todos 테이블 기한(due_date) 컬럼 추가 + 등록/수정 API 반영 (2026-07-08)
프론트 요청: 할일(todo)에 "기한 적용"(언제까지 처리) 기능 → 우선 컬럼 1개로 충분. 요구=일자까지만(시각 불필요).
- **컬럼 확정**: 처음 `due_at timestamptz` 제안했다가, 요구가 "일자까지만"이라 **`due_date date NULL`로 교체**. 이 코드베이스는 timestamptz +9 타임존 어긋남 이력(started_at)이 있어 날짜전용은 `date`가 정석·안전. (사용자가 준 CREATE TABLE 스키마 기준, 사용자가 직접 ALTER 실행: `DROP COLUMN due_at; ADD COLUMN due_date date NULL`.)
- **동작 확정(사용자 결정)**: ① 자동등록(auto-create)엔 기한 미적용 → 항상 null(나중 보완) ② 수정(PUT)은 **전달된 때만 반영**(미전달=기존값 유지, 명시적 null=기한 해제) — 기존 title/state의 "요청 필드만 업데이트" 패턴과 동일. state만 바꿀 때 기한 안 날아가게.
- **⚠️ 핵심 함정**: 로컬 `NODE_ENV=local`은 synchronize=true라 **엔티티에 없는 컬럼을 DROP**함 → 수동 ALTER만 하고 엔티티에 안 넣으면 다음 접속에 컬럼 삭제됨. 그래서 엔티티 추가 필수.
- **구현(6파일, tsc+eslint 통과)**:
  - `todo/entities/todo.entity.ts`: `@Column({type:'date', nullable:true}) due_date: string|null` 추가(TypeORM date는 JS에서 'YYYY-MM-DD' 문자열).
  - `todo/dto/create-todo.dto.ts`: `due_date?` 선택 필드, `@Matches(/^\d{4}-\d{2}-\d{2}$/)` 검증.
  - `todo/dto/update-todo.dto.ts`: `due_date?: string|null`(null 허용=해제), 동일 검증.
  - `todo/services/todo.service.ts`: createTodo에 `due_date: dto.due_date ?? null`; updateTodo에 `if (dto.due_date !== undefined) todo.due_date = dto.due_date`.
  - `todo/controllers/todo.controller.ts`: GET 목록 Swagger 응답 스키마에 due_date(date, nullable) 노출.
  - `common/services/dynamic-database.service.ts` runSchemaMigrations: `addColumnIfNotExists(advisor, todos, due_date, 'DATE NULL')` — develop 배포 시 **전 테넌트 DB 자동반영**(사용자 수동 ALTER는 한 DB만 적용됐을 것이므로).
- **배포 반영**: 로컬은 서버 완전 재시작 필요(커넥션 캐시). dev는 develop 배포로 마이그레이션 자동. 자동등록 손 안 댐. 커밋·배포는 사용자 직접.
- **남은 것**: 프론트 전달용 규격 정리(별도 산출). auto-create 기한 보완은 추후.

### 88. todos 조회에 call_id 조인 추가 + memos 핀 고정(is_pinned) 기능 신규 (2026-07-08)
#87(todos due_date)에 이어 프론트 요청 2건.
- **① todos 조회에 call_id 추가**: `GET /todos` 응답에 `callstats_id`만 있고 `call_id` 없었음. `advisor.todos`엔 call_id 컬럼 자체가 없고 `raw_call.callstats_call.call_id`에 있음(관계: todos.callstats_id = callstats_call.id). 이미 전화번호(consumer_phonenumber) 때문에 CallstatCall을 **left join** 중이라 select+매핑만 추가. 매칭 통화 없으면 `call_id: null`(특수케이스 대응, left join이라 todo는 안 사라짐). 수정: `todo.service.ts` getTodos(addSelect `callstat.call_id` + 매핑 `?? null` + 리턴타입에 `call_id?: string|null`), `todo.controller.ts`(리턴타입+Swagger 스키마). CallstatCall 엔티티에 call_id는 varchar로 존재 확인.
- **② memos 핀 고정 기능**: 프론트에 메모 핀 기능 있는데 저장 안 됨. 백엔드에 핀 컬럼 전무(is_pinned grep 0건). **주의**: memos의 `bookmark_id`는 핀 아님 — 메모↔북마크(스크립트/지식) 연결 링크(nullable). 이번 건과 무관하게 그대로 둠(사용자 지시).
  - **결정(사용자)**: 타입=`is_pinned BOOLEAN NOT NULL DEFAULT false`(코드베이스는 플래그를 int로 쓰지만 사용자가 boolean 명시). 정렬 적용처=`findMemosByUserKey`(`GET /memos/user/:userKey`, 프론트 메모목록 화면이 쓰는 API로 확인). 업데이트 API=**기존 `PATCH /memos/:id` 재사용**(신규 엔드포인트 X, updateMemo가 Object.assign이라 DTO에 필드만 추가하면 동작).
  - 구현(4파일, tsc+eslint 통과): `memo.entity.ts`(is_pinned boolean default false), `dto/update-memo.dto.ts`(`is_pinned?` @IsBoolean @IsOptional), `memo.service.ts` findMemosByUserKey 정렬 `{ is_pinned:'DESC', create_at:'DESC' }`(핀 1순위·최신 2순위), `dynamic-database.service.ts` runSchemaMigrations에 `addColumnIfNotExists(advisor, memos, is_pinned, 'BOOLEAN NOT NULL DEFAULT false')`.
  - 참고: memos 조회 메서드가 5개(user/group/all/bookmark/그룹내부)라 정렬은 **화면이 쓰는 user별에만** 넣음(엉뚱한 데 넣으면 화면 안 고쳐짐).
- **DB 반영**: 로컬 수동 `ALTER TABLE advisor.memos ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT false;` + 서버 완전재시작(캐시). dev는 develop 배포로 마이그레이션 자동. todos call_id는 컬럼추가 아니라 조인이라 DB작업 없음.
- **프론트 전달**: todos 조회 응답에 call_id 추가(없으면 null) / 메모 핀 = `PATCH /memos/:id {is_pinned:true|false}`, 목록은 `GET /memos/user/:userKey`가 핀 우선 정렬해서 내려줌.
- **상태**: 사용자가 배포 후 테스트 예정. 커밋·배포는 사용자 직접.

### 89. 실시간 VOC 감정이 화면에 안 뜨는 문제 → 원인은 "전달"이 아니라 "감정 매핑 penalty" (2026-07-09)
증상: "assist-stream VOC가 실시간 배포가 잘 안 됨(부분 손실). 근데 상담후 테이블엔 저장 잘 됨." → 배포/전달 문제로 의심.
- **전달 경로 조사(무혐의 판명)**: publishVoc → Redis PUBLISH `{env}:{vendor}:{cc_cti}:call:voc` → asst self-subscribe → RedisMonitorController.handleChannelMessage → SocketGateway.broadcastToRedisMonitorRoom → 프론트 room. 로그로 정상턴(turn1) 확인: `발행완료(수신자:1명)` + `BROADCAST (1 clients)` + `ok=true`. **전달은 완벽.** pod 1개(멀티인스턴스 아님), 프론트는 로그인 시 room 상주. (구조 특이점: VOC만 코칭/nlp과 달리 "턴당 단발 publish, 무재전송"이라 진짜 손실 시 티남 — 이번 건 아님)
- **진짜 원인(로그 turn3에서 발견)**: CE emotion API 원문 `emotionType:"dissatisfied", emotionScore:0.65` 인데 최종 `emotion=normal(0.5)`로 뭉개짐. summary 텍스트는 "불만족 표출"로 맞게 들어가는데 type/score만 틀림 = 파싱 아니라 **매핑 버그**.
  - 범인: `summary.service.ts` `remapEmotionScore()`의 **부정감정 완화 penalty**(THRESHOLD=0.6, PENALTY=0.15). score≥0.6이면 −0.15 감점 후 `deriveEmotionTypeFromScore`로 type 재산출 → dissatisfied 0.65 → 0.5 → **normal로 강등**. dissatisfied는 CE score 0.75 미만 전부 normal, angry도 0.95 미만이면 dissatisfied로 강등. CE가 dissatisfied를 보통 0.6~0.7로 줘서 **거의 100% normal**로 나감 → 화면에 감정변화 안 보임.
  - ⚠️ `remapEmotionScore`는 realtime·summary **공통** 매핑 → 실시간 배포값 + **DB 저장값도 normal로 뭉개져 저장**되고 있었음(사용자가 "저장 잘 됨"이라 한 값이 실은 normal).
- **수정(사용자 확정: penalty 완전 제거)**: 사용자가 "부정감정이 너무 자주 나와서 의도적으로 눌렀던 것" 확인해줌. 그래도 type 강등 부작용이 근본문제라 **완전 제거** 결정.
  - `NEGATIVE_EMOTION_PENALTY_THRESHOLD`/`NEGATIVE_EMOTION_PENALTY` 상수 2개 삭제 + remapEmotionScore 감점 블록 삭제(`let score`→`const`). clamp가 구간 보장하므로 `deriveEmotionTypeFromScore(score)`는 CE 원본 type과 항상 일치. tsc --noEmit 통과, 잔여 참조 0.
  - 결과: dissatisfied(0.65)→dissatisfied, angry(0.85)→angry, normal 유지. 과거 저장분은 소급 안 됨(새 통화부터 정상).
- **프론트 조언(감정변화 시각화)**: type 전환 강조 / score·3축 종합위험지수 실시간 그래프 / 통화중 최고치 배지(단발손실 대비 겸함). 필요시 종합위험지수를 백엔드 payload에 선계산해 넣는 것도 옵션(미결).
- **상태**: 사용자가 배포(develop) 후 통화 테스트 예정. 커밋·배포는 사용자 직접.

### 90. dev(5f)에서 LLM Orchestrator가 계속 호출됨 → 원인은 "배포 미반영", 결론은 orchestrator 코드 완전 제거 (2026-07-09)
증상: 5f 개발기 로그에 `LLM Custom Complete 요청` + `호출 실패 500`이 계속 뜸. "orchestrator는 안 쓰기로 했는데 왜 호출되냐"가 출발점.
- **호출부 특정**: `customComplete` 실호출 3곳(summary 상담유형·VOC, assist-stream-new) + `complete` 3곳(summary 요약/키워드, todo). 요약/키워드/상담유형/VOC/할일은 **전부 CE 대체 경로가 있고 orchestrator는 env 스위치(`POSTCALL_ANALYZER`/`VOC_ANALYZER`) 롤백용**, assist-stream-new는 미사용(NOT IN USE) 컨트롤러.
- **범인 추적(핵심)**:
  1. 에러 스택이 `VocRealtimeService.handleUtterance → SummaryService.analyzeVocViaOrchestrator`(게이트 안 거치고 직접 호출) → **실시간 VOC** 경로인데 현재 소스와 다름(현재 소스는 `analyzeVocByTenant → analyzeVoc` 게이트 경유).
  2. `.env.5f.development`의 `VOC_ANALYZER=ce`로 바꿔도 계속 500 → **배포된 `dist`가 게이트 생기기 전 옛 빌드**라는 증거.
  3. 도커는 `--build --force-recreate`까지 했는데도 옛 로그 → 진짜 원인은 **배포 서버 로컬(`/dataset/aicc/asst-service`)이 origin과 divergent라 `git pull`이 막혀** 소스·env가 옛 상태로 남아 그걸 빌드한 것. 도커 캐시가 아니었음.
  4. 해결: `git fetch origin && git reset --hard origin/develop_nohsn`(5f는 `develop_nohsn` 브랜치 배포)로 소스 강제 정렬 후 재빌드. `b1f1326`에 `VOC_ANALYZER=ce` 이미 포함돼 있어 정렬만으로 CE 확정.
- **결정(사용자): orchestrator 코드 아예 제거**(env `ce`로 봉인만으론 불안 → 롤백 스위치째 삭제). 2커밋 단계로:
  - **1단계**: `summary.service.ts`·`todo.service.ts`에서 `*ViaOrchestrator`(요약/키워드/상담유형/VOC/할일) + `useOrchestratorForPostcall` + VOC 게이트 + orchestrator 전용 헬퍼(`parseVocResponse`/`parseRiskAxis`/`buildVocPrompt`/`parseCounselingTypeResponse`) 삭제, 게이트 4개 **CE 직행**. `LlmOrchestratorService`·`ConfigService`(todo) 주입 제거.
  - **2단계**: 미사용 `assist-stream-new`(controller+service) 삭제, `common/services/llm-orchestrator.service.ts` 삭제, `advisor.module.ts` 등록(import/controllers/providers/exports) + `app.module.ts` AuthMiddleware 제외경로 정리.
- **안전성**: 실행 경로 변화 0(orchestrator는 env가 이미 ce라 죽은 코드였음), `npm run build` 2회 통과, 코드 내 orchestrator 참조 0. DTO(`Llm*ContentDto`)는 `summary/dto` 소속이라 무관. ⚠️ 트레이드오프=orchestrator 롤백 스위치 소멸(요약/VOC 등 CE 단일경로, 단 각 경로 fail-soft). `LLM_ORCHESTRATOR_HOST` env는 존치(무해, 사용자 요청). 롤백은 git.
- **메모리화**: 5f는 `develop_nohsn` 배포 + 배포서버 divergent로 pull 막히면 옛 소스 빌드됨(→ reset --hard) 함정을 memory에 기록.
- **상태**: 코드 수정·빌드검증까지 완료. 커밋(2분할)·배포·재빌드는 사용자 직접. 배포 후 `CE emotion API VOC 3축 분석 시작`/`상담유형 분류 완료(CE)` 로그로 확인.

### 91. 프론트 상담화면 리뉴얼 문의 2건 → ② direction/call_type 미적재(우리 소관 아님) + ③ 통화이력 목록용 신규 API + summary 4필드 컬럼화 (2026-07-13)
프론트 문의: ② `GET /callstat/agent-summary` 의 `direction`/`call_type` 이 26건 전부 null, ③ 목록에 의도/상담유형/감정이 없음(상세엔 있음).
- **② 결론: asst-service 무관, 적재 측 문제.** 두 필드는 `raw_call.callstats_call` 컬럼(`direction` varchar(8), `call_type` **jsonb**인데 엔티티 타입은 string — 값 들어오면 손봐야 함). asst-service는 `call.*` 로 읽어 그대로 내려줄 뿐 **INSERT/UPDATE 코드가 아예 없음**(read-only). 값 스펙 힌트는 목록 필터 DTO의 `@IsIn(['I','O'])` (I=인바운드/O=아웃바운드)뿐 → 콜 적재 담당자 확정 필요. 사용자 판단: **미구현으로 남겨둠**.
- **③ 신규 엔드포인트 `GET /callstat/call-history`** (기존 agent-summary는 무손상 유지, 요청 파라미터 동일). 내부적으로 `getCallStatsByAgentAndDate()` 재호출 후 페이지 call id 로 일괄 조인(N+1 없음):
  - `categories`: `advisor.call_categories` + `ce.external_categories` → `[{external_categories_id, category_path}]`
  - `voc`: `advisor.emotions` 3축(emotion/complaintRisk/churnRisk) — **상세 API와 구조 동일**(프론트 컴포넌트 재사용). 구버전 스키마 테넌트 대비 try/catch로 격리(실패 시 voc=null, 목록 500 방지)
  - `intent`: `raw_call.callstats_turn.intent` 원본. **콜 대표 의도 컬럼이 없고 적재도 안 됨 → 당분간 항상 null**, 가공 없이 자리만 유지(적재 시작되면 자동 반영)
- **summary 4필드 컬럼화 (핵심 설계 변경)**: `POST /summary` 는 LLM 4개(내용요약/키워드/상담유형/VOC)를 호출하는데, 내용요약 결과 4필드(`customerInquiry/handlingResult/followUp/notes`)를 `buildSummaryMarkdown()` 으로 **합쳐서 리턴만 하고 버리고 있었음**. 저장은 별개 요청(`POST /summary/data`)이라 서버가 원본을 못 갖는 구조.
  - **프론트 확인 결과**: `/summary` 200 → **자동으로 `/summary/data` 즉시 호출**(상담사 개입 없음) + 수동 저장 N회. **요약 텍스트는 사람이 편집 안 함(편집되는 건 상담유형뿐)** → 목록 카드에 LLM 원본 표시 OK.
  - **결론(파싱·프론트 작업 0)**: `advisor.summary` 에 `customer_inquiry/handling_result/follow_up/notes` (**TEXT NULL**) 추가하고, **`POST /summary` 시점에 LLM 원본 4필드를 upsert**(VOC/emotions 저장하는 자리, 동일 fail-soft). 이후 `/summary/data` 저장은 summary 마크다운·키워드·상담유형만 덮어써서 4컬럼은 원본 유지.
  - `callLlmSummarize()` 가 `{markdown, content}` 를 리턴하도록 변경 + `saveSummaryContent()` 신설. 마이그레이션은 `runSchemaMigrations` 의 `addColumnIfNotExists` 4개(전 테넌트 자동, RDS 접근 불필요).
  - **조회 폴백**: `call-history` 는 컬럼값 우선, null이면(컬럼 도입 전 과거 요약) `summary` 마크다운의 `**1. 고객 문의**` 섹션을 정규식 파싱 → **기존 데이터도 즉시 표시**. 목록 카드 "의도" = `customer_inquiry`.
  - **컬럼 타입 논의**: 사용자가 VARCHAR(100) 제안 → PG는 varchar/text 저장공간·성능 동일하고 **초과 시 truncate 아니라 에러**(=4필드 조용히 저장 실패), 게다가 `addColumnIfNotExists` 는 **add-only라 나중에 길이 확장 불가**(전 테넌트 수동 ALTER 필요) → **TEXT 확정**.
- **수동 선반영 SQL**(사용자 요청, 파일로는 안 남김): `ALTER TABLE advisor.summary ADD COLUMN IF NOT EXISTS customer_inquiry TEXT NULL;` (handling_result / follow_up / notes 동일).
- **상태**: 코드 수정 + tsc/eslint 통과. 커밋·배포는 사용자 직접. 배포 후 `[마이그레이션] 시작` 로그 + 신규 요약 1건 → `call-history` 의 `customer_inquiry` 채워지는지 확인 예정. (향후 과제: 오라클 백엔드 신규 구축 시 TEXT/TIMESTAMPTZ/jsonb 등 타입 매핑 재정의 필요)

### 92. 실시간 VOC가 상담사/관리자에게 간헐적으로 안 옴 → 원인 100% 프론트(소켓 재연결 시 룸 재조인 누락), 백엔드 무결 (2026-07-14)
증상: 관리자(최대 4명 상담사 동시 모니터링)와 상담사에게 **VOC(감정/민원/이탈)만** 간헐적으로 안 옴. STT·코칭·공지·상담사상태는 정상. "관리자로 로그인 후 시간이 지나면 안 오다가 **새로고침하면 옴**".
- **초기 오진(기록용, 전부 틀렸음)**: ① "관리자용 공유 경로가 없다" → 틀림(관리자도 상담사별 voc 룸을 직접 구독 중). ② redis-monitor 참조카운트 부재로 서로 강제 퇴장 → 프론트가 unsubscribe를 **아예 호출 안 함**(스웨거 전용)이라 무관. ③ 채널 prefix(`VOC_CHANNEL_ENV`) 불일치 → 코칭 룸도 같은 env를 쓰는데 코칭은 정상이므로 배제. ④ 멀티 pod + socket.io redis adapter 부재 → 미검증. **교훈: 로그부터 봤어야 했다.**
- **로그로 확정**(`aicc-asst-service-deploy-57c6d556f5-4hftw`, 24:13~24:34, 21분):
  - 발행 채널 `dev:4609686:56356659:call:voc`(32건) == 프론트 join 룸(30건). **채널명·발행 타이밍·브로드캐스트 전부 정상.**
  - `BROADCAST START` 인원수: **STT 룸 3~4명 vs VOC 룸 2~3명 — 항상 정확히 1명 적음.**
  - 소켓별 join 룸 대조: 재연결 소켓(`3_TW` 끊김 24:17:48 → 2초 뒤 `2kPJ` 접속)이 6개 룸(coaching/notices/agent-status/events/persisted/nlp:complete)은 재조인했는데 **`call:voc`+`call:nlp:partial` 2개만 정확히 누락**.
- **진짜 원인(둘 다 프론트, 프론트팀 인정·수정 완료)**:
  1. `useChatSocket.ts:40` **`once("connect")`** — voc/nlp:partial 조인이 `once`라 **브라우저당 평생 1회만** 실행. 나머지 룸은 `on("connect")`이라 재연결마다 복구됨 → 재연결 시 VOC 룸만 영구 이탈. 새로고침하면 낫는 이유가 이것. → `on("connect")`로 수정.
  2. `useChatMessageParser.ts:316` **`currentCallId` 굳음** — `call:start`를 놓치면 이전 콜 id가 남아 새 콜 VOC를 전부 stale로 drop. → 수정 완료.
- **끊김 자체의 원인은 미제(정직하게 미확정)**: disconnect 8건 전부 `transport close`, **`ping timeout` 0건**, 소켓 수명 12초~21분으로 제각각 → LB idle timeout 패턴 아님(`pingInterval:25s`라 idle도 안 됨). 서버엔 disconnect 코드 0줄, 프론트도 로그아웃 때만 disconnect. Redis는 **무관**(브라우저↔서버 구간 vs 서버↔Redis 구간은 별개 연결). 결론: 끊김을 0으로 만드는 건 불가능하므로 **고칠 것은 "재연결 후 복구"**.
- **백엔드 확인 사실**: `client.join()`은 `@SubscribeMessage('join-room')` 한 곳뿐(`socket.gateway.ts:302`). `handleConnection()`에 **룸 복구 로직 없음** → 재연결 시 소켓 id가 새로 발급되어 룸 멤버십 전부 소멸. **"재조인은 클라이언트 몫"이 현재 계약.**
- **상태**: 프론트 2건 수정 완료, 배포 후 검증 예정. **검증법**: `grep "BROADCAST START: Room" | grep -E "call:voc|call:nlp:complete"` → **VOC 룸 인원수 == STT 룸 인원수**면 해결.
- **미해결 숙제(이번 원인 아님, 실재하는 버그)**:
  1. `voc-realtime.service.ts:81` **`FALLBACK_CC_CTI_ID='56356659'` 하드코딩** — cc_cti_id 못 구하면 모든 통화 VOC가 저 상담사 1명 채널로 발행. 주석에도 "제거 대상". 현재는 프론트가 항상 보내줘서 잠복.
  2. **redis-monitor 구독에 참조 카운트 없음** — `DELETE /redis-monitor/unsubscribe-all` 한 번이면 그 pod에 붙은 **전원의 모든 채널**이 죽음(`deleteRedisMonitorRoom`이 룸의 전 클라이언트를 강제 leave + Redis 구독 해제). 프론트가 안 불러서 잠복.
  3. **재연결 시 서버 룸 자동 복구**(handshake query로 채널목록 수신 → `handleConnection`에서 자동 join) — 프론트 실수에 면역이 되는 안전망. 프론트팀 합의: **프론트 배포 결과 확인 후 논의**.
