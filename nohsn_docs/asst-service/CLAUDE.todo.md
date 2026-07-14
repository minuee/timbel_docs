# CLAUDE.todo.md — 나중에 실제 적용할 작업

## ☐ 실시간 VOC(감정체크) conversation 전송 방식 개선 — 슬라이딩 윈도우로 전환

> 배경: `/assist-stream` 요청이 올 때마다 그동안의 대화를 **메모리에 전체 누적**해서, CE emotion API의 `conversation`에 **모든 대화**를 실어 보냄(현재 `voc-realtime` 경로).
> 문제: 통화가 길어질수록 메모리/토큰/레이턴시가 계속 커지고, **감정분석 품질도 나빠짐**.

### 왜 전체 누적이 문제인가 (AI 관점)
- 실시간 VOC가 알고 싶은 건 **"지금 이 순간 고객 감정"**인데, 전체를 넣으면 **과거 감정(초반에 화났다 풀린 것)이 현재 판단을 희석** → 뭉뚱그려진 결과.
- 길어질수록 **오래된 맥락이 노이즈**가 되어 최근 1~2턴의 감정 변화(다시 짜증↑)를 놓침 → **감정 변화 감지가 둔해짐**(조기탐지에 치명적).

### 왜 "현재 1턴 / 고객 직전 2턴"도 안 되나
- 너무 짧으면 맥락 부족 — `"네 알겠어요"`가 진심인지 비꼬는 건지 직전 맥락 없이 판단 불가.
- **고객 발화만** 모으면 더 위험: 고객 감정은 보통 **상담사 행동에 대한 반응**이라, 상담사 발화를 빼면 인과가 사라져 LLM이 오판.

### 권장 방향 (적용 시)
1. **슬라이딩 윈도우**: 최근 **6~10 발화**(고객만 2턴 X → 고객 3~4발화 + 사이 상담사 응답 포함, **양쪽 role 유지**)만 전송.
2. **고정 크기 큐(maxlen)로 메모리 보관** → 오래된 건 자동으로 밀려나 **메모리 폭증도 동시 해결**(전체 저장 후 자르기보다 애초에 윈도우만 유지가 깔끔).
3. **통화 극초반**(윈도우보다 짧을 때)은 있는 만큼 그대로 전송.
4. **짧은 윈도우 맥락 보완**: 직전 감정 점수를 상태로 캐싱 → 이번 윈도우 결과와 가중평균(EMA). 윈도우=“지금”, 캐싱=“추세” 담당.
- 윈도우 크기(6~10)는 실제 통화 데이터로 1~2회 튜닝해 적정값 확정.

### 적용 시 손볼 곳 (추정)
- `voc-realtime.service.ts` `handleUtterance`(누적 버퍼/`buildConversation`, 현재 `MAX_BUFFER=40` 슬라이딩 + customer만 누적) — 윈도우 로직 + 양쪽 role 포함으로 변경, 감정 점수 캐싱 상태 추가.
- 적용 전 현재 구조 다시 확인하고 같이 설계할 것.

---

## ☐ 실시간 이전대화 복원에 "문서정보(근거문서)" 추가 — snapshot 조회 API 신설

> 배경: [2026-07-06] 상담 중 페이지 이탈/복귀 시 사라지는 실시간 STT 대화를 복원하는 API `GET /callstat/calls/realtime-by-callid/:call_id/turns` 를 신설했다(발화=turn만 복원). **문서정보(발화별 근거문서)까지 복원하는 건 이번엔 보류** → 필요해지면 아래대로 이어서 진행.
> 이력: `CLAUDE-history.md` #86 참고.

### 문서정보가 어디에 저장돼 있나 (분석 완료)
- **테이블**: `advisor.callstat_assist_snapshot` — 발화별 근거문서/답변 스냅샷. `@Unique(call_id, turn_idx)`, upsert.
  - 컬럼: `id`(uuid), `call_id`(varchar128), `turn_idx`(int4), `customer_query`(text, 매칭보강), `payload`(jsonb), `created_at`.
  - `payload` 구조(jsonb) = `{ hint, answer, sources[], distilled }`.
    - `sources[]` 각 항목: `score, content, ref_num, chunk_id, page_info, document_id, section_title, document_title, source_location`.
    - ⚠️ `source_location`은 **이스케이프된 JSON 문자열**(객체 아님) → 프론트가 `JSON.parse` 한 번 더 해야 `file_path/file_url/page_number` 등 추출.
    - `answer` 본문의 `[1][2]` 각주 ↔ `sources[].ref_num` 매칭(문장별 근거 링크용).
- 엔티티: `src/advisor/call/entities/callstat-assist-snapshot.entity.ts`.

### 저장은 누가/언제 하나 (분석 완료 — 중요)
- 저장 트리거는 **`POST /assist-stream/snapshot`(`AssistSnapshotController`) 하나뿐** → **프론트가 명시적으로 호출**해야 저장됨.
- ⚠️ 실시간 relay(`assist-stream.service.ts`)는 **저장 안 함**(순수 중계). 즉 프론트가 snapshot POST를 안 쐈으면 그 턴은 **DB에 문서정보 없음**(화면엔 인메모리로만 존재).
- → **선행 확인(프론트)**: "통화 중 발화마다 snapshot 저장 POST를 실제로 쏘고 있나?" 이게 YES여야 복원 시 문서정보가 살아난다. (turn=STT는 콜봇/STT 파이프라인이 `raw_call.callstats_turn`에 별도 저장 — snapshot과 저장경로 완전 분리)

### 구현 방향 (조회 로직은 이미 반쯤 있음 → 컨트롤러만 열면 됨)
- **`AssistSnapshotService.findByCallId(callId, token)` 이미 존재**(`src/advisor/assist-stream/services/assist-snapshot.service.ts:32`, `call_id`로 조회 + `turn_idx ASC` 정렬까지 완성). 서비스는 그대로 재사용.
- 할 일: `AssistSnapshotController`(`assist-stream/snapshot`)에 **`@Get()` 추가**해서 `findByCallId` 노출. turns API와 동일 패턴으로:
  - 경로 후보: `GET /callstat/calls/realtime-by-callid/:call_id/snapshots` (turns와 짝 맞추기) 또는 `GET /assist-stream/snapshot?call_id=`.
  - **실시간 화면 호출이므로 turns API처럼 예외 던지지 말고** 통화없음/없음/오류 시 **빈 배열** 반환(try/catch 감싸기). turns는 `advisor.service.ts findTurnsRealtimeByCallNumber` 참고.
  - 응답 형태: 프론트와 합의 필요 — snapshot 통째 배열 vs `{call_id, snapshots:[필요필드]}` 래핑.
- **프론트 매칭 방식 결정 필요**: 복원 시 turns와 snapshots를 각각 조회해 프론트가 `turn_idx`로 조인할지, 아니면 백엔드가 turn+snapshot 합쳐서 한 번에 줄지. (turn_idx는 **0-base** 주의 — turns API에서 확인됨)

### 남은 결정 사항
1. 프론트가 문서정보 복원을 실제로 원하는 시점/화면 (지금은 보류).
2. 통화 중 snapshot 저장이 실제로 돌고 있는지 프론트 확인(위 선행 확인).
3. turns/snapshots 분리 조회 vs 통합 조회 응답 설계.

---

## ☐ 실시간 VOC 감정 "부정감정 완화 penalty" 제거 — 관찰 중 (원복 가능)

> [2026-07-09] `summary.service.ts` `remapEmotionScore()`의 **부정감정 완화 penalty(-0.15)를 완전 제거**함. 배포 후 로그로 정상 반영 확인(`emotion=dissatisfied(0.65)` 그대로 나옴, publish/broadcast 정상).
> 이력: `CLAUDE-history.md` #89 참고.

### 왜 제거했나
- penalty가 `score≥0.6`이면 -0.15 감점 후 `deriveEmotionTypeFromScore`로 type을 재산출 → **dissatisfied(0.65)→0.5→normal 로 강등**.
- 실효: dissatisfied는 CE score 0.75 미만이면 전부 normal, angry도 0.95 미만이면 dissatisfied로 강등. CE가 dissatisfied를 보통 0.6~0.7로 줘서 **거의 100% normal**로 뭉개짐 → 화면에 감정변화가 안 보였음(실시간 배포 문제로 오인).
- `remapEmotionScore`는 realtime·summary **공통** 매핑이라, 실시간 배포값 + DB 저장값 모두 normal로 뭉개져 저장되고 있었음.

### 관찰 포인트 (원복 판단 기준)
- 애초에 penalty를 넣은 이유 = **"부정감정(불만/화남)이 너무 자주 뜬다"** (사용자 확인). 제거했으니 이제 부정감정이 **과도하게 자주** 뜰 수 있음.
- 지켜보다가 "부정감정 노출이 너무 잦다"고 판단되면 → **완전 원복이 아니라 #89 프론트 조언대로** score만 완화하고 type은 CE 원본 유지하는 방식(2안)으로 재설계 권장. (type 강등 부작용 없이 노출 빈도만 낮춤)

### 원복 방법 (그대로 되돌릴 경우 — `summary.service.ts`)
1. 상수 2개 복구 (constructor 위):
   ```ts
   private static readonly NEGATIVE_EMOTION_PENALTY_THRESHOLD = 0.6;
   private static readonly NEGATIVE_EMOTION_PENALTY = 0.15;
   ```
2. `remapEmotionScore()`의 score 계산부(`const score` 라인)를 되돌리고 감점 블록 복구:
   ```ts
   let score = Math.round(clamped * 100) / 100;
   if (score >= SummaryService.NEGATIVE_EMOTION_PENALTY_THRESHOLD) {
     score =
       Math.round((score - SummaryService.NEGATIVE_EMOTION_PENALTY) * 100) / 100;
   }
   return { type: this.deriveEmotionTypeFromScore(score), score };
   ```
3. ⚠️ 원복 시 감정 강등 부작용도 같이 돌아옴 — 위 "관찰 포인트"의 2안(score만 완화)을 우선 검토할 것.

---

## ☐ 감지어(금칙어/비속어/이슈어) 실시간 탐지 — 사전(CRUD)만 있고 매칭 엔진은 전무

> [2026-07-09 분석] 관리자가 등록한 감지어를 assist-stream 대화에서 실시간 감지하는 기능. **등록/관리는 구축돼 있으나, 발화를 감지어와 대조하는 매칭 프로세스는 전혀 없음.** (현황 파악만, 미착수)

### ✅ 있는 것 — 감지어 등록/관리 (CRUD 완비)
- **모듈**: `src/advisor/keyword-detect/` (controller/service/entity/dto)
- **테이블**: `advisor.keyword_detects` — 감지어 1개당 로우 1개.
  - 컬럼: `id`(varchar100 PK), `keyword`(varchar255, 감지단어), `type`(varchar50, **금칙어/비속어/이슈어 구분값**), `creator_key`(varchar50, 등록자), `create_at`/`update_at`.
  - 3그룹은 별도 테이블 아니라 **`type` 컬럼 값으로 구분**.
- **REST 엔드포인트** `/keyword-detects`: 등록(POST) / 목록·페이지네이션(GET) / 등록자별(GET creator/:key) / **타입별(GET type/:type)** / 검색(GET search=등록목록 ILIKE) / 단건·수정·삭제(GET/PATCH/DELETE :id).
- 테넌트별 DB 저장(토큰 기반 getRepository).

### ❌ 없는 것 — 실시간 매칭(탐지) 로직
- `assist-stream.service` / `voc-realtime.service` **어디서도 `KeywordDetect`를 참조 안 함**. 코드 내 KeywordDetect 사용처는 모듈 등록 + 엔티티 배열 3곳(인프라 등록)뿐.
- 발화 텍스트를 등록 감지어와 대조하는 코드 없음 → 감지 이벤트/저장/소켓 push도 없음.
- `searchKeywordDetects`는 관리화면용 목록검색(keyword ILIKE)이지 대화 매칭 아님.

### 붙일 자리 & 성능 (분석)
- **자리**: `voc-realtime.service.ts` `handleUtterance` 옆. 이미 발화가 이 경로로 흐름 → VOC 감정분석 옆에 감지어 매칭을 얹으면 됨.
- **성능 걱정 거의 없음**: 감지어 매칭은 VOC(외부 LLM, 수초)와 달리 **인메모리 문자열 매칭(발화당 <1ms)**. 게이트 불필요.
  - 진짜 부하지점 = **발화마다 감지어 DB 조회** → **테넌트별 감지어 목록 메모리 캐시**(TTL 30~60초, 또는 등록/수정 시 무효화)로 해결.
  - VOC가 쓰는 **`setImmediate` fire-and-forget** 패턴 그대로 → SSE relay(문서검색 응답) 안 막음. 감지 결과는 VOC와 같은 소켓 채널 패턴으로 push.

### 결정 필요 (구축 착수 시)
1. **매칭 방식**: 단순 포함(includes) vs 형태소/정규식 — 오탐 처리("개"가 "개나리"에 걸림) 정책.
2. **감지 후 동작**: 소켓 push만 / DB 저장도 / 관리자 알림도.
3. **저장 위치**: `callstat_voc` 확장(VOC와 통합 저장 — 사용자 선호) vs 신규 테이블.
- VOC 통합: 사용자가 "voc 개선해서 감지어도 같이 체크·저장" 방향 선호. callstat_voc에 감지어 hit(단어/타입) 컬럼 얹는 것 검토.

---

### 진행 메모
- [2026-06-26] 테스트 엔드포인트 4개(`PostCall-LLM`) 신설 완료, ①②③ 스웨거 테스트 정상. ④는 CE 재배포 대기 중.
- emotion(VOC)도 CE path가 `/ai-apps/advisor-emotion/runs`로 변경됨(이미 운영 흐름 반영).
- [2026-06-26] 실시간 VOC conversation 누적 방식 개선안(슬라이딩 윈도우) todo 등록 — 아직 미적용, 의견 단계.
- [2026-07-02] ①②③④ 운영 흐름 CE 전환 완료(오케스트레이터 다운 대응). 공용 `CeLlmClientService` 신설, 전 축 fail-soft, `POSTCALL_ANALYZER` 롤백 스위치. 테스트·배포는 사용자.
- [2026-07-06] 실시간 이전대화 복원 turns API 신설(`realtime-by-callid/:call_id/turns`). 문서정보(snapshot) 복원은 보류 → todo 등록(위 "실시간 이전대화 복원에 문서정보 추가"). `findByCallId` 이미 있어 컨트롤러 GET만 추가하면 됨.
- [2026-07-09] 실시간 VOC 감정 penalty(-0.15) 제거 → 배포 확인(dissatisfied 정상 표시). 원복 가능성 있어 todo 등록(위 "부정감정 완화 penalty 제거 — 관찰 중"). 원복 시 완전복구보다 score만 완화(type 유지) 2안 권장. + rag-assist intent 로그(`[민누이로그분석]` 문서검색/일상대화 최종판정) 추가.
- [2026-07-09] 감지어(금칙어/비속어/이슈어) 실시간 탐지 현황 분석 → todo 등록(위 "감지어 실시간 탐지"). 등록 CRUD(`advisor.keyword_detects`)는 완비, 실시간 매칭 엔진은 전무. 붙일 자리=voc-realtime handleUtterance, 성능 OK(캐시+비동기).
- [2026-07-09] **LLM Orchestrator(`LlmOrchestratorService`) 코드 완전 제거**(2단계). 배경: dev(5f)에서 orchestrator가 죽어 실시간 VOC가 500 에러 → 이미 전 기능 CE 전환 완료(2026-07-02)라 orchestrator는 **아무도 안 타는 롤백 코드/미사용 컨트롤러만** 남아있던 상태였음.
  - **1단계(요약/할일 로직)**: `summary.service.ts`·`todo.service.ts`에서 orchestrator 경로 삭제 — `*ViaOrchestrator`(요약/키워드/상담유형/VOC/할일), `useOrchestratorForPostcall`, VOC 게이트, orchestrator 전용 헬퍼(`parseVocResponse`/`parseRiskAxis`/`buildVocPrompt`/`parseCounselingTypeResponse`). 게이트 4개는 **CE 직행**으로 단순화. `POSTCALL_ANALYZER`/`VOC_ANALYZER` 스위치 코드도 제거.
  - **2단계(서비스 완전 삭제)**: 미사용 `assist-stream-new`(controller+service) 삭제, `common/services/llm-orchestrator.service.ts` 삭제, `advisor.module.ts` 등록(import/controllers/providers/exports) + `app.module.ts` AuthMiddleware 제외경로에서 제거.
  - **안전성**: 실행 경로 변화 0 — orchestrator는 env가 이미 `ce`라 호출 안 되던 죽은 코드. `npm run build` 통과, 코드 내 orchestrator 참조 0. DTO(`LlmSummarizeContentDto`/`LlmKeywordContentDto`)는 `summary/dto` 소속이라 삭제와 무관.
  - **⚠️ 트레이드오프**: orchestrator **롤백 스위치가 사라짐** → 요약/키워드/상담유형/VOC/할일은 이제 **CE 단일 경로**. CE 장애 시 각 경로는 fail-soft(빈 결과/fallback 마크다운)로만 방어되고 orchestrator로 되돌릴 수는 없음(CE 안정성이 전제). 되살리려면 git 복원.
  - **env**: `LLM_ORCHESTRATOR_HOST`는 **존치**(코드가 안 읽어 무해, 사용자 요청).
  - **롤백**: 커밋 전이면 `git checkout -- <파일>` / 삭제파일 `git checkout HEAD -- <path>`, 커밋 후면 해당 2커밋 `git revert`.
