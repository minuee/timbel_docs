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
