# 작업 내역 (2026-06-09)

오늘 수정/생성한 소스 리스트. 미커밋·미배포 상태(로컬 워킹트리).

## 🆕 신규 생성

| 파일 | 내용 |
|---|---|
| `src/advisor/emotion/entities/emotion.entity.ts` | Emotion 엔티티 (icon_type, score, description) |
| `src/advisor/emotion/services/emotion.service.ts` | 감정 저장/조회 + icon_type 매핑 |
| `src/advisor/emotion/controllers/emotion.controller.ts` | 조회 GET + 분석 테스트 POST |
| `src/advisor/emotion/dto/analyze-emotion.dto.ts` | 감정 분석 테스트용 DTO |
| `migrations/create_emotion_table.sql` | emotions 테이블 생성 SQL (이력용) |

## ✏️ 수정 — 감정 분석 기능

| 파일 | 변경 내용 |
|---|---|
| `src/advisor/summary/services/summary.service.ts` | EmotionService 주입, summarizeCall에 감정 자동저장, `analyzeEmotion()` 추가 |
| `src/advisor/advisor.module.ts` | EmotionController/EmotionService 등록 |
| `src/common/services/dynamic-database.service.ts` | Emotion 엔티티 등록(동적/정적), emotions 테이블 마이그레이션(CREATE, score 포함) |
| `src/config/database.config.ts` | Emotion 엔티티 등록 |

> 참고: `summary-response.dto.ts`(EmotionDto)는 어제 작업분. 오늘은 직접 수정 안 함(그대로 사용).

## ✏️ 수정 — proxy 버그 수정

| 파일 | 변경 내용 |
|---|---|
| `src/common/proxy/knowledge-proxy.controller.ts` | `@ApiBearerAuth` 추가 + 경로 `/api/` → `/api/aicm/v1/` (5개) |
| `src/common/proxy/audio-proxy.controller.ts` | `@ApiBearerAuth('bearer')` 추가 |
| `src/common/proxy/ce-proxy.controller.ts` | `@ApiBearerAuth('bearer')` 추가 |
| `src/common/proxy/qa-proxy.controller.ts` | `@ApiBearerAuth('bearer')` 추가 |
| `src/common/proxy/user-proxy.controller.ts` | `@ApiBearerAuth('bearer')` 추가 |

## ✏️ 수정 — 설정/문서

| 파일 | 변경 내용 |
|---|---|
| `.env.development` | `LLM_ORCHESTRATOR_HOST` 수정 (⚠️ `LLM_HOST`는 아직 죽은 주소 `dev-aicc` — 수정 필요) |
| `CLAUDE.md` | 문서 보강 (DB/마이그레이션/배포/감정분석/proxy 등) |

## ⚠️ 내가 안 건드린 변경 (커밋 전 확인 필요)

| 파일 | 비고 |
|---|---|
| `src/advisor/notice/controllers/notice.controller.ts` | 이번 작업과 무관 — 다른 작업분이 섞인 듯, 의도 확인 |
| `package-lock.json`, `yarn.lock` | 의존성 락파일 — 오늘 의도 변경 아님, 확인 |

## 📌 내일 체크리스트

1. **미커밋·미배포** — 위 변경 전부 로컬에만 있음. develop 배포해야 반영.
2. **`LLM_HOST` 죽은 주소 수정** (`dev-aicc.langsa.ai` → 올바른 호스트). ORCHESTRATOR만 고쳤음.
3. **notice.controller.ts 변경 의도 확인** 후 커밋 포함 여부 결정.
4. **감정/이슈 분석 고도화 미결정 사항** (CLAUDE.md `OPEN DECISIONS`):
   - 민원/이탈 실시간 분석 부착 위치: A) assist-stream.service 직접 vs B) 외부 RAG 위임
   - 저장 구조: emotions 확장 vs `call_risk_analysis` 신규 테이블
   - 모델: gpt-4o-mini vs 상위
5. **409(workspace 없음)는 코드 문제 아님** — 유효한 workspace_id로 호출하면 200.

## 커밋 단위 제안

- ① 감정분석 기능 (emotion 도메인 + summary/module/db config)
- ② proxy 버그 수정 (proxy 컨트롤러 6개 + 경로)
- ③ env/문서 (.env.development, CLAUDE.md)
