"""Admin demo 계정 본인 personal_tenant 풍부 시드 — 30 docs 운영 가이드.

배경:
    `demo-admin@kms-plus.io` 는 5 개 조직 personal_tenant 에 admin 멤버십을
    가지고 있지만, 본인 personal_tenant 자체에는 0 docs / 0 repo 였다.
    chat 진입 시 활성 tenant 가 admin 본인 tenant → RAG 0 hits.

이 스크립트는 admin 의 personal_tenant 에 다음을 시드한다:
    repo "platform-admin"  → 15 docs (플랫폼 운영, 보안, 배포 등)
    repo "operations"      → 15 docs (운영 절차, demo 시연, 로드맵 등)

`seed_by='seed_admin_inventory'` 마커로 식별. 인덱싱은
`index_demo_docs.py` 가 이 마커도 함께 픽업하도록 마커 리스트에 추가됨.

실행:
    docker exec -e PYTHONPATH=/app kms-api \
        python scripts/seed/admin_inventory.py --execute --reindex

옵션:
    --dry-run   기본. 변경 없이 plan 출력.
    --execute   실제 INSERT.
    --reseed    기존 seed_admin_inventory documents 제거 후 재시드.
    --reindex   document INSERT 후 index_demo_docs.py --execute --reindex
                자동 호출 (chunks/embedding 까지).

idempotent:
    (repository_id, title) 기준 — 같은 doc 재시도 시 skip.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

ADMIN_EMAIL = "demo-admin@kms-plus.io"
SEED_MARK = "seed_admin_inventory"


# ── Doc bodies ────────────────────────────────────────────────────────


DOC_PLATFORM_OVERVIEW = """[AICM 플랫폼 운영 가이드]

1. 개요
- AICM (AI Knowledge & Conversation Management) 은 자연어로 동작하는 지식·업무 통합 플랫폼.
- 주 모듈: Document, Agent, Chat, Skill, Search/RAG, Tenant.
- 멀티테넌트 — 모든 데이터는 tenant_id 로 격리. cross-tenant 조회는 membership + 명시적 컨텍스트 필요.

2. 일반 운영 원칙
- 사용자/상담사 시점에서 정확도 > 속도. 단, 채팅 첫 응답 ack 는 < 300ms.
- 모든 응답에 출처(citation) 노출. 출처 없는 LLM hallucination 차단.
- 운영자는 매일 audit log + intent 분포를 확인.

3. 모듈별 책임
- Document: 업로드/파싱/블록화/색인. PDF·MD·DOCX·HWPX·이미지·표 LLM 해석 포함.
- Agent: persona 기반 LLM 캡슐. allowed_skills, allowed_repos 로 권한 제어.
- Skill: state machine + slot + tool 조합. YAML v1 스키마.
- Search/RAG: BGE-M3 dense + ES BM25 keyword + reranker(BGE-reranker-v2-m3).
- Tenant: workspace 단위. personal/organizational, membership role(viewer/editor/admin/owner).

4. 핵심 SLA
- intent 분류: < 200ms (rule + LLM gate)
- search dense+keyword+rerank: < 1.5s (top_k=10)
- chat 응답 첫 토큰: < 1s, 완성: < 8s 평균
"""


DOC_SKILLS_YAML = """[Skills YAML 작성 패턴 v1.1]

1. 스킬은 LLM 의 동적 system prompt 캡슐
- name, description, intent_keywords, persona, tools, slots, state_machine 으로 구성.
- description 은 LLM 매칭에 직접 쓰임 — 자연스러운 의도 문장.

2. 권장 패턴
- 한 스킬 = 한 가지 책임. 복합 의도는 orchestrator 가 분기.
- slot fill 은 명시 vs 추론 분리. 사용자 명시값 우선.
- tool 호출 결과는 항상 ledger 에 기록 → 추적성.

3. 금기 사항
- 키워드 리스트로 intent 분기 X. LLM 의 의도 추론 위임.
- 사례 yaml (case enumeration) 만들지 말 것. 패턴 코어 우선.
- 군대식 어휘 (발사/발화) 금지. 송출/푸시/emit 사용.

4. 검증 체크리스트
- 단발 정확도 외에 multi-turn (참조해소, slot 보존, capability 질문) 회귀 케이스 포함.
- 에러 상황 (tool 실패, slot missing) 분기 명시.
"""


DOC_AGENT_KEYS = """[외부 에이전트 발급 절차]

1. 신청
- /api/v1/agents 로 POST → name, description, persona, allowed_skills, allowed_repos.
- tenant owner 또는 admin 만 발급 가능.

2. API 키 발급
- agent 생성 후 /api/v1/agents/{id}/keys 로 키 발급. prefix + secret 분리.
- secret 은 1회만 표시. 분실 시 재발급.

3. 외부 호출
- 헤더: X-Agent-Key, X-Tenant-ID. body 는 user message + optional session_id.
- 외부 endpoint: /api/v1/external/agents/chat (rate limit per_min).

4. 회수/만료
- agent.is_active=false 로 즉시 비활성. 키 단위 revoke 도 가능.
- 30일 미사용 키는 자동 경고 → 90일 미사용 시 자동 만료.
"""


DOC_RAG_TUNING = """[RAG 튜닝 가이드]

1. 임베딩 모델
- BGE-M3 (multilingual, dense+sparse 동시). RTX 5090 GPU.
- chunk size: 단락 단위 (200~500자). 너무 짧으면 컨텍스트 손실, 길면 retrieval drift.

2. 검색 단계
- dense (Qdrant) top_k=20 → keyword (ES) top_k=20 → union → reranker top_k=10.
- reranker: BGE-reranker-v2-m3. score < 0.3 컷오프.

3. Intent gate
- /search /rag/* 진입 시 LLM 분류기 병렬 전처리. 일상대화는 SKIP.

4. 튜닝 다이얼
- top_k: 답변 정확도 vs 컨텍스트 노이즈. 일반 5~10, 정확도 우선 시 20+.
- chunk overlap: 0~100자. 표·코드 블록은 overlap 0 권장.
- reranker score 임계: 0.2 (관대) ~ 0.5 (엄격).
"""


DOC_INTENT_CLASSIFIER = """[Intent Classifier 추가 방법]

1. 새 intent 정의
- intents/ 디렉토리에 yaml 추가 → name, description, examples (3~5개).
- examples 는 변형 표현 포함 (존댓말/반말/오타/축약).

2. 분류기 등록
- src/intent/classifier.py 의 INTENT_REGISTRY 에 추가.
- LLM prompt 에 intent 목록 자동 노출 (코드 변경 X).

3. 회귀 테스트
- tests/intent/test_classifier.py 에 케이스 추가. 정확도 95%+ 유지.
- 경계 케이스 (둘 다 가능한 표현) 명시 prompt 한 줄로 해결.

4. 모니터링
- 운영 후 intent 분포 logs 확인. 잘못 분류된 케이스 → prompt 보강.
"""


DOC_TENANT_ISOLATION = """[Tenant 격리 · membership 관리]

1. 격리 원칙
- 모든 documents/blocks/chunks/agents 는 tenant_id 로 strict scoped.
- Qdrant collection 도 tenant_slug 별로 분리 (kms_<slug>_blocks).
- ES index 도 분리 (block_<slug>).

2. Membership
- accounts.personal_tenant_id 는 본인 소유 tenant.
- tenant_memberships 로 cross-tenant 권한. role: viewer/editor/admin/owner.
- JWT 의 tenant_id 가 활성 컨텍스트. X-Tenant-ID 헤더로 switch 가능.

3. 위험
- 동일 도메인 다른 고객사 (예: 크레온/타증권사) 문서가 한 tenant 에 섞이면 컨텍스트 mismatch.
- 2번째 고객사 문서 들어오기 전 분리 구조 확정 필수.

4. Admin 본인 tenant
- demo-admin@kms-plus.io 본인 tenant 는 platform-admin 운영 자료만 보유.
- 조직 자료는 cross-tenant membership 통한 workspace 전환으로 접근.
"""


DOC_DEMO_SEEDING = """[Demo 계정 시드 절차]

1. 13 demo 계정 생성
- scripts/seed/per_account_demo.py — 계정 + personal tenant + repo + 3 docs.

2. 데이터 확장
- scripts/seed/per_account_expand.py — 계정당 8~12 docs 추가.
- seed_by='seed_per_account_expand_v2' 마커.

3. 인덱싱
- scripts/seed/index_demo_docs.py --execute — chunks + embeddings.
- ADDITIONAL_SEED_MARKS 에 새 마커 추가하면 함께 색인.

4. Admin
- scripts/seed/admin_demo.py — admin 계정 생성 + 5 조직 cross-membership.
- scripts/seed/admin_inventory.py — admin 본인 tenant 30 docs.

5. 검증
- 각 계정 로그인 → /tenants 확인 → /rag/retrieve 으로 자기 tenant 자료 응답 확인.
"""


DOC_DEPLOY_CHECKLIST = """[프로덕션 배포 체크리스트]

1. 사전 점검
- DB migration alembic upgrade head — 신규 revision 적용.
- Qdrant collection 존재 확인 — tenant_slug 별.
- ES index template 적용.

2. 서비스 기동 순서 (GPU 자원 경합 방지)
- vLLM healthy → reranker → worker → api → frontend.
- 역전 시 OOM. nginx 업로드 100MB 제한 함께 확인.

3. 배포 후 smoke
- /health 200 응답.
- /auth/v2/login 로그인 → /chat/sessions/new → /chat/message stream.
- /search 한국어 쿼리 — top_k 응답 ms 단위.

4. 롤백
- 직전 image tag 복귀. DB migration 은 명시 down 만 (자동 X).
- 데이터 손실 위험 시 백업 복구 절차 (별도 doc).
"""


DOC_BACKUP_RESTORE = """[백업 / 복구 절차]

1. 일별 백업 (자동)
- Postgres pg_dump → S3 (kms-backups/postgres/<YYYY-MM-DD>.sql.gz). 보존 30일.
- Qdrant snapshot → S3 (kms-backups/qdrant/). collection 단위.
- Elasticsearch snapshot repo → S3.

2. 주간 백업
- 전체 docker volume tarball — 별도 S3 bucket. 보존 12주.

3. 복구 시나리오
- 실수 삭제 (단일 tenant) → Postgres point-in-time + Qdrant collection 재색인.
- 전체 복구 → Postgres 복원 → Qdrant snapshot import → ES restore → vLLM 재기동.

4. 검증
- 복구 후 즉시 /health 와 /search smoke.
- 데이터 정합성 확인: documents.count vs chunks.count 비율.
"""


DOC_SECURITY_POLICY = """[보안 정책 — JWT, API key, RBAC]

1. JWT
- access token: 10분 만료. refresh token: 30일.
- 페이로드: sub(account_id), tenant_id, role, exp.
- 시크릿 회전: 분기별. 회전 후 모든 active session 강제 logout.

2. API Key
- agent 별 발급. prefix(공개) + secret(해시 저장).
- rate limit per_min 강제. 초과 시 429.

3. RBAC
- viewer: 조회 only. editor: 등록/수정. admin: 사용자/설정. owner: 전권 + 양도.
- skill/tool 단위 권한은 agent allowed_skills 로 추가 제한.

4. 감사
- 모든 mutation 은 audit_log 에 기록. account_id, tenant_id, action, payload_hash, ts.
- 90일 보존 후 cold storage.
"""


DOC_INCIDENT_RESPONSE = """[장애 대응 매뉴얼 (SLA, 우선순위)]

1. 우선순위
- P0 — 전체 서비스 다운 (login/chat 양쪽 fail). 응답 30분.
- P1 — 핵심 기능 1 모듈 다운 (search 0 hits 전체). 응답 2시간.
- P2 — 부분 기능 저하 (특정 tenant 만, 또는 latency 2배). 응답 24시간.
- P3 — 비기능 / 표시 문제. 다음 영업일.

2. 초기 대응
- /health, /metrics 확인 → 어떤 컴포넌트 실패인지 식별.
- vLLM 다운 → fallback 모드 (deterministic intent + cached search) 자동 전환 확인.
- DB 다운 → read replica 승격 절차.

3. 커뮤니케이션
- P0/P1 즉시 status page 업데이트. 30분마다 진척 갱신.
- 사후 RCA 24시간 내 공유.

4. 회복 검증
- 자동 smoke + 수동 5분 sanity. P0 는 외부 stakeholder 통보 필수.
"""


DOC_MONITORING = """[성능 모니터링 — Grafana, Prometheus 대시보드]

1. 핵심 지표
- API: requests/sec, p50/p95/p99 latency, 5xx rate.
- LLM: vLLM tokens/sec, queue depth, GPU util.
- Search: dense/keyword/rerank 단계별 ms.
- DB: connection pool, slow query (>500ms).

2. 알람
- p95 latency > 2s sustained 5분 → warn.
- 5xx > 1% sustained 5분 → page.
- vLLM queue > 50 sustained 1분 → warn.

3. 대시보드
- Overview (서비스 전체)
- Tenant 별 사용량 (top 10)
- LLM 비용 (tokens × 단가)
- Search 품질 (rerank score 분포)

4. 로그
- structured log (json). trace_id, span_id 포함.
- intent / skill / tool / search / llm 단계별 span.
"""


DOC_VLLM_GEMMA = """[vLLM Gemma 모델 배포 / 교체]

1. 현재 모델
- Gemma-2-27b-it AWQ. 컨텍스트 32k, max-num-seqs 8.
- B200 전환 시: 양자화 제거, 컨텍스트 65536, max-num-seqs 16.

2. 배포 절차
- model 디렉토리 → /models/gemma-… 마운트.
- vLLM Docker compose env: MODEL_PATH, GPU_MEM_UTIL, MAX_MODEL_LEN.
- gpu-mem-util 0.85 (0.75 시도했으나 unstable, 0.85 원복).

3. 교체
- 신모델 staging 1주 — 기존 chat session 회귀 테스트.
- prompt template 차이 확인 (system role 처리, special token).

4. 모니터링
- tokens/sec, ttft, completion 길이 분포.
- 체인지 후 회귀: KB 8턴 시나리오, 페르소나 100%, scope 4/4.
"""


DOC_DATA_BACKUP_POLICY = """[Postgres / Qdrant / ES 백업 정책]

1. Postgres
- daily logical (pg_dump) + WAL archive.
- weekly physical base backup.
- RTO 30분 / RPO 5분.

2. Qdrant
- snapshot per collection daily 02:00 KST.
- cross-region replica (옵션) — 비용 vs 가용성 tradeoff.
- 복구 검증: 분기 1회 dry-run restore.

3. Elasticsearch
- snapshot repository (S3).
- daily incremental + weekly full.
- 인덱스 템플릿 버전 관리 (변경 시 reindex 절차).

4. 보존 / 비용
- 30일 hot, 90일 warm, 1년 cold (Glacier).
- 월간 비용 리포트 + 사용량 대비 검토.
"""


DOC_USER_FAQ = """[사용자 지원 / FAQ]

1. 자주 묻는 질문
- "비밀번호 분실" → /auth/password/reset 이메일 링크 (15분 만료).
- "tenant 전환 안 됨" → 멤버십 확인. owner 가 admin 격하한 경우 reload.
- "검색 결과 0건" → 활성 tenant 확인 → 자료 색인 상태 확인.

2. 문의 채널
- 사내 Slack #aicm-support → 1차 분류.
- P0/P1 은 페이지로 즉시 escalate.

3. 응대 원칙
- 사용자 화면 그대로 재현 → traceback → 원인 확정 후 안내.
- 추측 우회 금지. 일시 회피 시에도 RCA 별도 진행.

4. 만족도
- 분기 1회 NPS. < 30 시 우선순위 P1 회의 안건.
"""


DOC_OPERATOR_ONBOARDING = """[신입 운영자 온보딩]

1. 첫 주
- 플랫폼 개요 (이 문서) 읽기.
- 13 demo 계정 + admin 계정으로 로그인 → 모든 기능 클릭해보기.
- 1 ticket 동행 (선임 운영자 옆).

2. 둘째 주
- intent / skill / agent 시스템 작동 원리 학습.
- 새 skill yaml 1개 작성 → 코드 리뷰.

3. 셋째 주
- 단독 ticket 처리 (P3 only). 선임 daily 회고.

4. 인증
- 한 달 후 평가: P2 단독 가능 여부. 통과 시 P1 권한 부여.
"""


DOC_USAGE_STATS = """[월간 사용 통계 분석 양식]

1. 수치
- 월간 active users, sessions, messages, search queries.
- tenant 별 top 10. document/chunk count 변화.
- LLM tokens 사용량 + 비용.

2. 정성
- intent 분포 변화 (월간 비교).
- 신규 stuck pattern (slot fill 실패, 무답 등) 식별.
- skill 별 trigger 횟수 + 성공률.

3. 액션 아이템
- 사용량 급증 tenant → capacity planning.
- 정확도 하락 영역 → prompt/RAG 튜닝 작업 등록.

4. 보고
- 월말 마지막 영업일 운영팀 공유.
- 분기말 경영진 요약 (1 page).
"""


DOC_FEEDBACK_TRIAGE = """[고객 피드백 분류 / 응대 절차]

1. 채널
- in-app feedback (chat ⋮ 메뉴), email, Slack 공유 채널.

2. 분류
- bug: 즉시 ticket. 우선순위 P0~P3.
- feature request: backlog. 분기 우선순위 회의.
- praise: 팀 share. 사례화.

3. SLA
- 24시간 내 1차 응답 (자동/수동 무관).
- bug fix → 우선순위 별 deadline.

4. 통계
- 월간 피드백 count, 카테고리 분포, 평균 응답 시간.
- 주요 패턴은 FAQ 갱신.
"""


DOC_ESCALATION_MATRIX = """[장애 발생 시 escalation matrix]

1. 1차 — 운영자 (24시간 oncall)
- 모든 alert 1차 수신. P0/P1 즉시 인지.
- 30분 내 미해결 → 2차.

2. 2차 — 시니어 엔지니어
- P0 즉시 호출 (페이지). P1 30분 내.
- root cause 분석 + fix.

3. 3차 — 팀 리드 + CTO
- P0 1시간 미해결 시. 외부 커뮤니케이션 결정.

4. 외부
- 고객 영향 P0/P1 → 영업 + CS 동시 통보.
- 법적 영향 사고 → 법무팀 우선 통보.
"""


DOC_DATA_WIPE = """[데이터 wipe / 청소 가이드]

1. 단일 tenant wipe
- 사전 백업 → /api/v1/tenants/{id}/data:wipe (admin only).
- 비동기 처리. 진행 상황 audit log 추적.

2. 단일 document
- /api/v1/documents/{id} DELETE → cascade (blocks/chunks/qdrant/es).

3. 만료 데이터 자동 청소
- 90일 미접속 session → soft delete.
- 1년 미사용 document → archive.

4. 안전 장치
- legal_hold=true 인 document 는 wipe API 거부.
- production wipe 는 2 명 승인 필수 (4-eyes).
"""


DOC_NEW_DOMAIN_ONBOARDING = """[신규 도메인 (예: 의료, 금융) 온보딩 절차]

1. 사전 분석
- 도메인 어휘 사전 (50~200 핵심 용어).
- 컴플라이언스 요구 (의료: 환자정보 마스킹, 금융: 거래 한도).

2. tenant 셋업
- organizational tenant 생성 → admin/editor 멤버십 부여.
- repo 구조 가이드 (예: 정책/매뉴얼/사례 구분).

3. RAG 튜닝
- 도메인 corpus 100~500 문서 시드 → embedding 분포 확인.
- intent 분류기에 도메인 패턴 prompt 추가.

4. 검수
- 도메인 전문가 50 케이스 골든셋. 정답률 95%+ 달성 후 일반 사용자 오픈.
"""


DOC_DEMO_SCENARIO_KB = """[Demo 시연 시나리오 — KB 콜센터]

1. 컨텍스트
- KB금융 콜센터 상담사. 이체 한도, 대출 절차, 카드 발급 자주 응대.

2. 시연 흐름 (5분)
- 로그인 → KB workspace 전환.
- chat: "이체 한도 어떻게 변경?" → 정책 doc 인용 + 절차 step-by-step.
- chat: "대출 가심사 시간?" → 1~3 영업일, 다음 단계 안내.
- 검색 탭 → "보이스피싱 방지" → 지연이체 정책 doc.

3. 강조 포인트
- 출처(citation) 명시 — 환각 방지.
- 후속 질문 자연스럽게 (참조해소).

4. 실패 시 대응
- 만약 0 hits → 활성 tenant 확인 (KB workspace 인지).
"""


DOC_DEMO_SCENARIO_SHINHAN = """[Demo 시연 시나리오 — 신한 디지털]

1. 컨텍스트
- 신한금융 디지털 채널. 앱 가이드, 인증 정책, 이벤트.

2. 시연 흐름 (5분)
- 로그인 → 신한 workspace.
- chat: "앱 OTP 등록 절차" → 화면 흐름 + 주의사항.
- chat: "오픈뱅킹 한도" → 정책 + 한도 변경 방법.
- 검색: "비대면 본인 인증" → 단계 + 보안 권고.

3. 강조 포인트
- 동일 질문도 신한 컨텍스트에서는 신한 정책 인용.
- KB 와 절대 섞이지 않는 격리 시연.

4. 추가 시연
- skill 만들기 — "신한 이벤트 안내" 실시간 추가.
"""


DOC_DEMO_SCENARIO_SAMSUNG = """[Demo 시연 시나리오 — 삼성 반도체 SOP]

1. 컨텍스트
- 삼성전자 반도체 라인 운영자. SOP, 안전 절차, 장애 대응.

2. 시연 흐름 (5분)
- 로그인 → 삼성 workspace.
- chat: "라인 정전 시 SOP" → 즉시 조치 + 보고 라인.
- chat: "장비 점검 주기" → 일/주/월 체크리스트.
- 검색: "화학물질 누출" → 안전 매뉴얼 + 비상 연락.

3. 강조 포인트
- 운영자 화면에서 즉시 사용 가능 — 모바일 친화 UI.
- 매뉴얼 update 시 자동 인덱싱 (admin 트리거).

4. 보안
- 일부 SOP 는 legal_hold=true → 외부 export 차단 시연.
"""


DOC_COST_ESTIMATE = """[비용 산정 — LLM tokens, 인프라]

1. LLM
- Gemma-2-27b 자체 호스팅. 추론 비용은 GPU 시간 (RTX 5090 시간당 X원).
- 외부 API (특수 케이스만): GPT-4o ~$0.005/1k input, $0.015/1k output.

2. 인프라
- Postgres: managed 또는 self-host. 월 X원 / 100GB.
- Qdrant: self-host. RAM 1GB / 100만 vectors 권장.
- ES: 디스크 IO 큰 영향. NVMe 권장.

3. 사용자 단가 (가이드)
- 사용자 1명 / 월 = LLM 평균 50k tokens + 인프라 분담.
- tier별 가격 정책 — basic/pro/enterprise.

4. 분기별 검토
- 사용량 폭증 tenant 별도 협의. 비용 분담 재조정.
"""


DOC_CUSTOMER_MEETING = """[고객사 미팅 준비 자료]

1. 미팅 전 (D-3)
- 고객사 도메인 / 사용 현황 파악.
- 최근 30일 사용 통계 출력. 정확도 / latency 지표 정리.
- 미해결 ticket 리스트.

2. 미팅 자료
- 1 page summary (사용량, 만족도, 미해결 이슈).
- 시연 (사용 사례 1~2 개).
- 로드맵 다음 분기 핵심 항목 3~5 개.

3. 미팅 중
- 고객 발언은 메모 → 24시간 내 정리.
- 약속한 항목은 ticket 으로 즉시 등록.

4. 미팅 후 (D+1)
- 회의록 공유.
- 액션 아이템 owner + due date 명시.
"""


DOC_POC_PROCESS = """[POC 진행 표준 절차]

1. 사전 (Week 0)
- 목표 정의 (성공 기준 정량). 데이터 sample 검토.
- 일정 4~6주. 주차별 마일스톤.

2. 셋업 (Week 1)
- staging tenant 생성. 데이터 50~200 docs 시드.
- 핵심 intent 5~10 개 정의. 골든셋 50 케이스.

3. 튜닝 (Week 2~3)
- 정확도 측정 → prompt / RAG 튜닝.
- 주간 데모 + 피드백 반영.

4. 평가 (Week 4)
- 성공 기준 충족 확인. 본 계약 / 종료 결정.
- POC 데이터는 동의 시 본 계약 tenant 로 마이그레이션.
"""


DOC_ROADMAP_Q1 = """[Q1 2026 로드맵]

1. 핵심 과제
- 페르소나 100% 안정화 (V5 wave 마감).
- KB 8턴 시나리오 정확도 0.531 → 0.95+.
- B200 외부 GPU 전환 검토.

2. 신기능
- 크롤링 / 뉴스 / 주식 정보 통합 (E코스).
- chat 내 문서 업로드.
- 페르소나 프리셋 + 계정 설정 페이지.

3. 인프라
- Postgres 백업 RTO 단축 (30분 → 10분).
- 모니터링 대시보드 v2 (tenant 별 분석 강화).

4. 운영
- 신입 운영자 온보딩 자동화.
- 분기 리포트 템플릿 표준화.
"""


DOC_FEATURE_PRIORITY = """[기능 우선순위 요청 양식]

1. 기본 정보
- 요청자, 일자, 영향 받는 tenant 수, 예상 사용 빈도.

2. 비즈니스 가치
- 매출 영향 (직접/간접). 사용자 만족도 영향.
- 기존 우회책 가능 여부.

3. 기술 평가
- 예상 작업량 (S/M/L/XL).
- 의존 모듈 / 회귀 위험.

4. 결정
- 분기 우선순위 회의에서 채택 / 보류 / 거절.
- 채택 시 owner + 일정 부여.
"""


DOC_USER_INTERVIEW = """[사용자 인터뷰 인사이트 모음]

1. 콜센터 상담사 (KB)
- "출처가 명확해서 답변에 자신감 생긴다."
- "동일 질문 반복해도 일관된 답이 좋다."
- 개선: 모바일에서 화면 스크롤 불편.

2. 운영팀 (삼성)
- "SOP 검색이 빨라졌다 — 종이 매뉴얼 대비 10배."
- 개선: 한국어 오타 자동 교정 부족.

3. 디지털 마케터 (신한)
- "이벤트 정책 자동 응답이 콜수 30% 감소시켰다."
- 개선: 채팅 내 이미지 업로드 필요.

4. 종합
- 정확도 + 출처 = 신뢰. 속도 = 채택률. 모바일 UX = 일선 만족도.
- 다음 분기 목표: 상기 3 영역 각 +20%.
"""


# ── Doc lists ────────────────────────────────────────────────────────


PLATFORM_ADMIN_DOCS: list[tuple[str, str, str]] = [
    ("AICM 플랫폼 운영 가이드.md", DOC_PLATFORM_OVERVIEW, "guide"),
    ("Skills YAML 작성 패턴 v1.1.md", DOC_SKILLS_YAML, "guide"),
    ("외부 에이전트 발급 절차.md", DOC_AGENT_KEYS, "guide"),
    ("RAG 튜닝 가이드.md", DOC_RAG_TUNING, "guide"),
    ("Intent Classifier 추가 방법.md", DOC_INTENT_CLASSIFIER, "guide"),
    ("Tenant 격리 · membership 관리.md", DOC_TENANT_ISOLATION, "guide"),
    ("Demo 계정 시드 절차.md", DOC_DEMO_SEEDING, "guide"),
    ("프로덕션 배포 체크리스트.md", DOC_DEPLOY_CHECKLIST, "guide"),
    ("백업 / 복구 절차.md", DOC_BACKUP_RESTORE, "guide"),
    ("보안 정책 — JWT, API key, RBAC.md", DOC_SECURITY_POLICY, "policy"),
    ("장애 대응 매뉴얼 (SLA, 우선순위).md", DOC_INCIDENT_RESPONSE, "guide"),
    ("성능 모니터링 — Grafana, Prometheus 대시보드.md", DOC_MONITORING, "guide"),
    ("vLLM Gemma 모델 배포 / 교체.md", DOC_VLLM_GEMMA, "guide"),
    ("Postgres / Qdrant / ES 백업 정책.md", DOC_DATA_BACKUP_POLICY, "policy"),
    ("사용자 지원 / FAQ.md", DOC_USER_FAQ, "faq"),
]


OPERATIONS_DOCS: list[tuple[str, str, str]] = [
    ("신입 운영자 온보딩.md", DOC_OPERATOR_ONBOARDING, "guide"),
    ("월간 사용 통계 분석 양식.md", DOC_USAGE_STATS, "template"),
    ("고객 피드백 분류 / 응대 절차.md", DOC_FEEDBACK_TRIAGE, "guide"),
    ("장애 발생 시 escalation matrix.md", DOC_ESCALATION_MATRIX, "guide"),
    ("데이터 wipe / 청소 가이드.md", DOC_DATA_WIPE, "guide"),
    ("신규 도메인 온보딩 절차.md", DOC_NEW_DOMAIN_ONBOARDING, "guide"),
    ("Demo 시연 시나리오 — KB 콜센터.md", DOC_DEMO_SCENARIO_KB, "scenario"),
    ("Demo 시연 시나리오 — 신한 디지털.md", DOC_DEMO_SCENARIO_SHINHAN, "scenario"),
    ("Demo 시연 시나리오 — 삼성 반도체 SOP.md", DOC_DEMO_SCENARIO_SAMSUNG, "scenario"),
    ("비용 산정 — LLM tokens, 인프라.md", DOC_COST_ESTIMATE, "guide"),
    ("고객사 미팅 준비 자료.md", DOC_CUSTOMER_MEETING, "guide"),
    ("POC 진행 표준 절차.md", DOC_POC_PROCESS, "guide"),
    ("Q1 2026 로드맵.md", DOC_ROADMAP_Q1, "memo"),
    ("기능 우선순위 요청 양식.md", DOC_FEATURE_PRIORITY, "template"),
    ("사용자 인터뷰 인사이트 모음.md", DOC_USER_INTERVIEW, "memo"),
]


REPOS: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "platform-admin",
        "AICM 플랫폼 운영 · 보안 · 배포 가이드",
        PLATFORM_ADMIN_DOCS,
    ),
    (
        "operations",
        "운영 절차 · demo 시나리오 · 로드맵",
        OPERATIONS_DOCS,
    ),
]


# ── Plan ──────────────────────────────────────────────────────────────


@dataclass
class Plan:
    admin_found: bool = False
    repos_created: int = 0
    repos_reused: int = 0
    documents_inserted: int = 0
    documents_skipped: int = 0
    inserted_doc_ids: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    def line(self, m: str) -> None:
        self.log.append(m)

    def summary(self) -> str:
        return (
            f"admin={'ok' if self.admin_found else 'MISS'} "
            f"repos +{self.repos_created} (reused {self.repos_reused}) "
            f"docs +{self.documents_inserted} skip={self.documents_skipped}"
        )


# ── DB helpers ────────────────────────────────────────────────────────


async def _lookup_account(
    conn: AsyncConnection, *, email: str
) -> tuple[UUID, UUID] | None:
    r = (
        await conn.execute(
            text(
                "SELECT id, personal_tenant_id FROM accounts "
                "WHERE email = :e AND is_active = true"
            ),
            {"e": email},
        )
    ).first()
    if not r:
        return None
    return r[0], r[1]


async def _ensure_repo(
    conn: AsyncConnection, *, tenant_id: UUID, name: str, description: str
) -> tuple[UUID, bool]:
    existing = (
        await conn.execute(
            text(
                "SELECT id FROM repositories WHERE tenant_id = :t AND name = :n"
            ),
            {"t": tenant_id, "n": name},
        )
    ).first()
    if existing:
        return existing[0], False
    r = await conn.execute(
        text(
            """
            INSERT INTO repositories
              (id, tenant_id, name, description,
               config, search_mode, display_config, llm_config, is_active)
            VALUES
              (gen_random_uuid(), :t, :n, :d,
               CAST(:cfg AS jsonb), 'simple',
               '{}'::jsonb, '{}'::jsonb, true)
            RETURNING id
            """
        ),
        {
            "t": tenant_id,
            "n": name,
            "d": description,
            "cfg": json.dumps({"seed": True, "seed_by": SEED_MARK}),
        },
    )
    return r.scalar_one(), True


async def _ensure_doctype(
    conn: AsyncConnection, *, tenant_id: UUID, name: str
) -> UUID:
    r = await conn.execute(
        text(
            """
            INSERT INTO document_types (id, tenant_id, name, description, is_system)
            VALUES (gen_random_uuid(), :t, :n, :desc, true)
            ON CONFLICT ON CONSTRAINT uq_document_types_tenant_name
              DO UPDATE SET description = EXCLUDED.description
            RETURNING id
            """
        ),
        {"t": tenant_id, "n": name, "desc": f"seed:{name}"},
    )
    return r.scalar_one()


async def _insert_document(
    conn: AsyncConnection,
    *,
    tenant_id: UUID,
    repo_id: UUID,
    doctype_id: UUID,
    title: str,
    body_text: str,
    doctype: str,
) -> tuple[bool, UUID | None]:
    existing = (
        await conn.execute(
            text(
                "SELECT id FROM documents WHERE repository_id = :r AND title = :t"
            ),
            {"r": repo_id, "t": title},
        )
    ).first()
    if existing:
        return False, existing[0]

    meta = {
        "seed": True,
        "seed_by": SEED_MARK,
        "profile_email": ADMIN_EMAIL,
        "doctype": doctype,
        "body_text": body_text,
        "pipeline_skipped": True,  # index_demo_docs.py 가 처리
    }
    r = await conn.execute(
        text(
            """
            INSERT INTO documents (
                id, tenant_id, repository_id, document_type_id, title,
                description, source_format, version, status,
                processing_meta, legal_hold
            )
            VALUES (
                gen_random_uuid(),
                :tid, :rid, :dtid, :title,
                :desc, 'md', 1, 'active',
                CAST(:meta AS jsonb), false
            )
            RETURNING id
            """
        ),
        {
            "tid": tenant_id,
            "rid": repo_id,
            "dtid": doctype_id,
            "title": title,
            "desc": f"[admin_inventory] {doctype}",
            "meta": json.dumps(meta, ensure_ascii=False),
        },
    )
    return True, r.scalar_one()


async def _wipe(conn: AsyncConnection) -> int:
    r = await conn.execute(
        text("DELETE FROM documents WHERE (processing_meta ->> 'seed_by') = :m"),
        {"m": SEED_MARK},
    )
    return r.rowcount or 0


# ── Orchestration ─────────────────────────────────────────────────────


async def run_seed(*, execute: bool, reseed: bool) -> Plan:
    plan = Plan()
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)

    try:
        if reseed and execute:
            async with engine.begin() as conn:
                n = await _wipe(conn)
                plan.line(f"[wipe] removed {n} admin_inventory docs")

        async with engine.begin() as conn:
            acc = await _lookup_account(conn, email=ADMIN_EMAIL)
            if not acc:
                plan.line(f"[MISS] {ADMIN_EMAIL} not found")
                return plan
            _, tenant_id = acc
            plan.admin_found = True
            plan.line(f"[ok] admin tenant_id = {tenant_id}")

        for repo_name, repo_desc, docs in REPOS:
            async with engine.begin() as conn:
                if not execute:
                    plan.line(
                        f"[dry] would ensure repo '{repo_name}' "
                        f"+ {len(docs)} docs"
                    )
                    continue

                repo_id, created = await _ensure_repo(
                    conn,
                    tenant_id=tenant_id,
                    name=repo_name,
                    description=repo_desc,
                )
                if created:
                    plan.repos_created += 1
                    plan.line(f"[seed] repo CREATED '{repo_name}' = {repo_id}")
                else:
                    plan.repos_reused += 1
                    plan.line(f"[seed] repo reused '{repo_name}' = {repo_id}")

                for title, body, doctype in docs:
                    dt_id = await _ensure_doctype(
                        conn, tenant_id=tenant_id, name=doctype
                    )
                    inserted, doc_id = await _insert_document(
                        conn,
                        tenant_id=tenant_id,
                        repo_id=repo_id,
                        doctype_id=dt_id,
                        title=title,
                        body_text=body,
                        doctype=doctype,
                    )
                    if inserted:
                        plan.documents_inserted += 1
                        if doc_id:
                            plan.inserted_doc_ids.append(str(doc_id))
                    else:
                        plan.documents_skipped += 1
                plan.line(
                    f"[seed] '{repo_name}' docs +{len(docs)} "
                    f"(insert {plan.documents_inserted} skip {plan.documents_skipped})"
                )
    finally:
        await engine.dispose()

    return plan


def _run_indexer() -> int:
    """index_demo_docs.py --execute --reindex 호출 (seed_admin_inventory 마커 픽업)."""
    cmd = [
        "python",
        "scripts/seed/index_demo_docs.py",
        "--execute",
        "--reindex",
    ]
    print(f"[index] $ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--reseed", action="store_true")
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="INSERT 후 index_demo_docs.py --execute --reindex 자동 호출",
    )
    args = parser.parse_args()

    plan = asyncio.run(run_seed(execute=args.execute, reseed=args.reseed))
    prefix = "[admin_inventory]" if args.execute else "[dry]"
    print(f"{prefix} {plan.summary()}")
    for line in plan.log:
        print(f"  {line}")

    if not args.execute:
        print("Run with --execute to apply.")
        return 0

    if args.reindex and plan.documents_inserted + plan.documents_skipped > 0:
        rc = _run_indexer()
        if rc != 0:
            print(f"[index] FAILED rc={rc}")
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
