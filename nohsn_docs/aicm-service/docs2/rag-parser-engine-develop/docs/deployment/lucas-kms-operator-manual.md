# Lucas-KMS — 운영자 매뉴얼 (KMS-only)

작성: 2026-05-19
대상: Tenant 관리자 (tenant_admin) / 운영자 (operator) / 검토자 (viewer)
모태: `Doc/solution/2026-05-19-locus-admin-manual.md` 의 KMS 영역
중요: Lucas-KMS 는 *KMS-only* product — **Agent / Chat / SOP-inject 기능 없음**

> 본 매뉴얼은 통합 Locus 매뉴얼의 KMS 부분만 추출 + KMS 단독 운영 보강. Agent / SOP / 챗 위임은 모두 *별도 product (Locus)* 영역.

---

## 0. 빠른 안내

| 항목 | 위치 |
|---|---|
| Admin UI (V1 KMS patch) | https://kms.gov-tenant.example.kr/ |
| API 문서 (Swagger) | https://kms.gov-tenant.example.kr/api/v1/docs (production 은 JWT + IP allowlist) |
| KMS Library | Admin UI → Library |
| 검색 테스트 | Admin UI → Search (또는 API `/api/v1/search`) |
| 검토 큐 | Admin UI → Library → 검토 대기 필터 |

JWT 토큰은 1h 유효, refresh token 7일. 첫 로그인 시 비밀번호 변경 강제.

---

## 1. Library — Repo 관리

### 1.1 Repo 생성

```
Admin UI → Library → "+ Repo"
  - 이름: 예) "공공기관 SaaS 가이드"
  - 설명: 자유
  - tenant: (자동 — 로그인 tenant 귀속)
  - 가시성: tenant 내 모든 operator 접근 가능 / 특정 user 만
```

API:

```bash
curl -X POST .../api/v1/repositories \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"공공기관 SaaS 가이드","description":"..."}'
```

### 1.2 문서 업로드

```
Repo 선택 → "+ 업로드"
  - 지원: PDF, DOCX, MD, HTML, TXT
  - 최대: 100MB (nginx 제한, MAX_UPLOAD_SIZE_MB 와 동기화)
  - 풀옵션 자동 적용 (vision + noise_filter + ontology + semantic_chunk)
```

API:

```bash
curl -X POST .../api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@guide.pdf" \
  -F "repository_id=<repo UUID>"
```

> 풀옵션 적용은 *KMS 자료화 풀옵션 절칙* — 시간보다 품질 우선.

**처리 시간 가이드** (외부 vLLM Gemma-4-31B 기준):
- 30p PDF: 약 3-5분
- 150p PDF (스캔 포함): 약 13-17분
- 500p+ PDF: 약 1시간 — 야간 처리 권장

### 1.3 처리 상태 확인

```
Repo → 문서 클릭 → 상태 패널
  - status: uploaded → parsing → segmenting → embedding → pending_review → active
  - 진행률 표시
  - 실패 시 retry 버튼 (자동 1회 retry 후 활성)
```

| status | 의미 |
|---|---|
| `uploaded` | 업로드 완료, 파싱 대기 |
| `parsing` | 텍스트/표/이미지 추출 중 |
| `segmenting` | LLM block 분할 중 (외부 vLLM 호출) |
| `embedding` | BGE-M3 임베딩 + 색인 중 |
| `pending_review` | 검토 대기 — 운영자 *review* 필요 |
| `active` | 검색 활성 |
| `failed` | 실패 — DLQ 조사 필요 |
| `archived` | 보관 — 검색 제외 |

### 1.4 검토 (Review)

```
pending_review 문서 → "검토" 클릭
  - 청크별 미리보기 (markdown + page bbox)
  - 노이즈 chunks 검토
  - 표 / 이미지 caption 확인
  - "active 로 승격" 버튼 → 검색 활성
```

검토 포인트:
- 표가 *paragraph* 가 아닌 *table* block 으로 잡혔는가
- 노이즈 (헤더/푸터/페이지번호) 가 본문 chunk 에 섞이지 않았는가
- 이미지 caption 이 본문 문맥과 일치하는가
- citation 좌표 (page + bbox) 가 정확한가 — 임의 chunk 클릭 → PDF viewer 의 정확한 위치 표시

`auto_approve=true` repo 는 pending_review skip — *신뢰 가능 자료* 만 사용.

### 1.5 Archive / 삭제

```
문서 → "더보기" → "archive"
  - 검색에서 즉시 제외
  - chunks 는 ES/Qdrant 에 잔존 (복원 가능)

완전 삭제 — Admin SQL/CLI 필요 (irreversible)
```

완전 삭제 (운영자):

```bash
docker compose exec lucas-kms-api \
  python -m scripts.maintenance.doc_purge \
    --doc-id <uuid> \
    --tenant-id <uuid> \
    --confirm
```

audit_logs 에 `doc_purged` event 기록 — 법적 보관 의무 확인 후 실행.

---

## 2. 검색 / RAG 사용

> Lucas-KMS 는 *Agent / Chat 없음*. 검색은 API 직접 호출 또는 Admin UI 의 Search 패널.

### 2.1 검색 (`/search`)

```bash
curl -X POST .../api/v1/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "조달청 등록 절차",
    "repository_ids": ["<repo uuid>"],
    "top_k": 10
  }'
```

응답:

```json
{
  "results": [
    {
      "chunk_id": "...",
      "document_id": "...",
      "score": 0.87,
      "text": "...",
      "page": 12,
      "bbox": [...],
      "citation_url": "/api/v1/citations/<chunk_id>?token=..."
    }
  ]
}
```

### 2.2 RAG (`/rag/assist-stream`)

SSE stream — *retrieval-only* (KMS 가 외부 사용처에 retrieval 결과 + distill 만 제공. 답변 생성 책임은 호출 측):

```bash
curl -N -X POST .../api/v1/rag/assist-stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "조달청 SaaS 등록 절차 알려줘",
    "repository_ids": ["<repo uuid>"]
  }'
```

이벤트 시퀀스:
- `intent` — in_domain / out_of_domain 판정
- `retrieved` — top-k chunks
- `distilled` — LLM 압축 본문
- `done` — 종료

> KMS 자료 *재해석 / 후가공* 은 호출 측 책임 — KMS 는 retrieval + distill 까지.

### 2.3 RAG (`/rag`) — 답변 생성 포함

답변까지 KMS 가 생성하는 endpoint (LLM call 추가):

```bash
curl -N -X POST .../api/v1/rag \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query":"...","repository_ids":[...]}'
```

> Lucas-KMS 단독 운영 시 `/rag` 도 노출. 통합 Locus 에서는 agent 가 `/rag/assist-stream` 만 호출 후 자체 답변 — 사용 패턴 차이.

### 2.4 검색 품질 개선 가이드

답이 부정확 / 누락 시:
1. **자료 가공 먼저 의심** — chunk 가 본문을 정확히 잡았는지 (review 패널)
2. block_type 확인 — 표가 `paragraph` 면 segmenter 가 못 잡음 → reprocess
3. 노이즈 chunk 가 검색 결과 점유 → review 에서 제외
4. *retrieval 도구 자체는 검증됨* (BGE-M3 + reranker) — 검색 품질 부족 시 자료 가공 먼저

> 자료화 풀옵션 절칙 — vision/noise_filter/ontology/semantic_chunk 빠짐없이 적용.

---

## 3. 운영 모니터링

### 3.1 로그

```bash
# API
docker logs -f lucas-kms-api

# pipeline workers
docker logs -f lucas-kms-pipeline-worker-large
docker logs -f lucas-kms-pipeline-worker-small

# DLQ scheduler
docker logs -f lucas-kms-pipeline-worker-large | grep dlq_
```

**주의 로그 패턴**:
- `split_job_starvation` — 정상 동작 (DLQ 차단으로 무한 cycle 방지)
- `dlq_auto_retry_skipped_status` — archived doc 의 retry skip (정상)
- `consumer_partition_revoked` — rebalance (정상)
- `consumer_supervisor_restart` — consumer 재시작 (조사 필요 — 빈번 시 root cause)
- `vllm_circuit_open` — 외부 vLLM 장애 차단 활성 (조사 필요)
- `rls_denied_session_no_tenant` — RLS context 미설정 (코드 버그 가능 — 보고)

### 3.2 지표

| 지표 | 의미 | 정상 범위 |
|---|---|---|
| Kafka consumer lag (split topic) | split job 대기 | < 10 |
| Kafka consumer lag (part_ready) | part 처리 대기 | < 20 |
| Pipeline doc duration (p95) | 평균 처리 시간 | < 17분 (150p PDF) |
| Search latency (p95) | 검색 응답 | < 1.5초 |
| RAG first-token latency (p95) | 첫 토큰까지 | < 3초 |
| DLQ depth | DLQ 적재 | < 5 |
| vLLM failure rate | 외부 vLLM 실패 비율 | < 1% |
| vLLM circuit state | 상태 | closed |

### 3.3 알람

다음 상황에 alert event 발생:
- pipeline doc auto-retry 실행
- DLQ depth >= 10
- consumer supervisor restart (>= 3회/시간)
- vLLM 호출 실패율 >= 5%
- vLLM circuit open
- 디스크 사용률 80%+
- 백업 cron 실패

운영자 contact 은 multi-tenant 매뉴얼 §5 참조.

---

## 4. 사고 회복

### 4.1 doc 처리 stuck (status=parsing 60분+)

원인 후보: parser worker crash / 외부 vLLM timeout / lock deadlock.

```
회복:
1. Admin UI → 해당 doc → "force retry" 버튼
   (자동: status=failed → active 로 재시도)
2. 워커 재시작: docker compose restart lucas-kms-pipeline-worker-large
3. 로그 확인: docker logs lucas-kms-pipeline-worker-large | grep doc_id
4. 외부 vLLM 상태 확인: curl https://kms.gov-tenant.example.kr/readyz | jq .vllm
```

### 4.2 doc 처리 실패 (status=failed)

```
1. Admin UI → DLQ 패널
2. 실패 사유 확인 (parser_error / segmenter_error / embedding_error)
3. 자동 1회 retry 동작 — 그래도 실패 시 수동 검토
4. 자료 결함이면: 원본 수정 → 재업로드
5. 시스템 결함이면: 운영자 (super_admin) 보고
```

### 4.3 split_job_starvation 무한 cycle

fix A 적용 후 *원천 발생 X*. 그래도 발생 시:

```
1. 로그: "split_job_starvation_detected" 검색
2. main consumer + merge consumer 의 partition 할당 확인:
   docker exec -it lucas-kms-kafka kafka-consumer-groups.sh \
     --bootstrap-server localhost:9092 \
     --describe --group lucas-kms-pipeline-large
3. DLQ scheduler 차단 동작 확인:
   docker logs lucas-kms-pipeline-worker-large | grep "split_job_starvation_blocked"
4. 둘 다 정상인데 cycle 도면: 워커 재시작
```

### 4.4 외부 vLLM endpoint 장애

```
증상: /readyz 의 vllm == not_ok, /rag p95 폭증, circuit open

회복 순서:
1. 외부 vLLM 운영팀 확인 (별도 contact)
2. 임시 fallback 모드 (FEATURE_LLM=false) — 검색은 가능, distill/RAG 답변 품질 저하
3. circuit half-open 30s 후 자동 recovery 시도
4. endpoint 자체 교체 필요 시 배포 가이드 §5.3 참조
```

### 4.5 모든 처리 멈춤 — Kafka / DB 장애

```
1. kafka 상태: docker ps | grep lucas-kms-kafka
2. postgres 상태: docker ps | grep lucas-kms-postgres
3. 외부 vLLM 상태: curl <LUCAS_VLLM_ENDPOINT>/v1/models -H "Authorization: Bearer $LUCAS_VLLM_API_KEY"

각 장애에 해당 service 만 재시작. 전체 stack 재시작은 *최후* (배포 가이드 §5.5).
```

---

## 5. 보안

### 5.1 Tenant 격리

- DB 의 모든 주요 테이블에 *RLS* 적용 (tenant_id 자동 filter)
- search/RAG 의 모든 query 에 자동 적용
- API 의 JWT 에 tenant_id 인코딩
- multi-store (Qdrant / ES / MinIO / Redis / Kafka) 모두 tenant naming + filter

격리 검증 절차: multi-tenant 매뉴얼 §2.

### 5.2 인증

- JWT 1h 유효, refresh token 7일
- 역할: super_admin / tenant_admin / operator / viewer
- operator 는 자기 tenant 의 doc/repo CRUD
- viewer 는 search 만

### 5.3 비밀

- API key 는 `.env.lucas-kms` 파일 (git 미포함)
- `LUCAS_VLLM_API_KEY`, `JWT_SECRET`, `CITATION_HMAC_SECRET` 등
- 로그에 비밀 노출 안 됨 (logger redact filter 적용)
- PII (이메일/주민/카드) 도 audit_logs 저장 시 redact

---

## 6. 백업 / 복구

배포 가이드 §6 참조. 운영자 일일 점검 항목:

- [ ] 백업 cron 마지막 성공 시각 확인 (postgres / qdrant / es / minio)
- [ ] 디스크 여유 확인

복구는 super_admin 절차 — 운영자는 보고 후 대기.

---

## 7. FAQ

**Q. 표가 답에서 잘림 (4행 중 2행만)**
A. distill 우회 fix 적용됨 — 그래도 발생 시 chunk 의 `block_type` 이 `"table"` 인지 확인. `"paragraph"` 면 segmenter 가 표를 못 잡은 것. 자료 재처리 (Admin UI → doc → "reprocess").

**Q. citation 클릭하면 잘못된 page 로 이동**
A. shallow copy bug fix 후 *신규 ingest* 부터 정확. 옛 자료는 *reprocess* 필요 (Admin UI → doc → "reprocess").

**Q. KMS 색인 어디까지 됐는지 모르겠음**
A. Admin UI → 해당 doc → "처리 로그" 패널. 단계별 시간 / 상태 표시. 또는 API `GET /api/v1/documents/{id}/log`.

**Q. 한 부서만 보는 자료를 다른 부서가 보면 안 됨**
A. tenant 격리는 RLS + multi-store 가 자동. tenant *내부* 의 부서 분리는 (1) repo 를 부서별 분리, (2) user 의 `accessible_repository_ids` 제한 — Admin UI → Users → repo 권한 설정.

**Q. 외부 vLLM endpoint 가 자주 끊김**
A. (1) `/readyz` 의 vllm 상태 확인, (2) 외부 endpoint 운영팀 contact, (3) circuit breaker 가 fallback 으로 자동 보호 — 검색은 정상 가능. (4) 빈번하면 super_admin 에게 endpoint 교체 요청 (배포 가이드 §5.3).

**Q. DLQ 가 쌓이는데 어떻게 처리?**
A. (1) Admin UI → DLQ 패널 → 실패 사유별 분류, (2) 자료 결함 → 원본 수정 후 재업로드, (3) 시스템 결함 → super_admin 보고. *자동 1회 retry* 동작 — 그래도 실패면 수동 검토 필요.

**Q. Lucas-KMS 에서 agent 만들 수 있나요?**
A. *없습니다* — Lucas-KMS 는 KMS-only product. Agent / Chat / SOP-inject 은 통합 Locus solution 의 영역. agent 가 필요하면 Locus 통합 솔루션을 사용하세요.

**Q. 다국어 (영어 / 한국어) 지원?**
A. V1 frontend MVP 는 한국어 우선. 다국어 토글은 Phase 5+ (spec rev4 §5.1). 자료 자체는 한/영 혼용 처리 가능 (BGE-M3 multilingual).

**Q. 사용자가 챗 중간에 자료 추가하고 싶음**
A. Lucas-KMS 단독에서는 챗 UI 가 없으므로 *직접 적용 안 됨*. Library UI 에서 upload 후 search 활용. 챗 컨텍스트 첨부는 Locus 통합 솔루션의 기능.

**Q. multi-tenant 격리가 정말 안전한가?**
A. 다층 방어 — Postgres RLS + Qdrant filter + ES filter + MinIO bucket + Redis namespace + Kafka tenant_id. 회귀 테스트 (`test_multi_tenant_isolation.py`) 매 PR 검증 + 분기 1회 수동 검증. 격리 절차 상세: multi-tenant 매뉴얼.

---

## 8. 운영자 일일 체크리스트

- [ ] DLQ depth 5 미만
- [ ] consumer lag 30 미만 (모든 topic)
- [ ] failed status doc 없음 (또는 운영자 확인 됨)
- [ ] 외부 vLLM healthy (`/readyz` vllm == ok)
- [ ] 검토 큐 (pending_review) 정체 없음 (24h 내 처리)

## 9. 운영자 주간 체크리스트

- [ ] backup 정상 (postgres / qdrant / es / minio)
- [ ] 신규 doc upload 정상 (smoke test)
- [ ] 검색 품질 sample 검토 (10건 — 정답률, citation 정확도)
- [ ] 사용자 피드백 수집 (incident / 개선)
- [ ] 디스크/메모리 70% 이하

---

## 10. 문의 / 지원

- 배포/인프라 super_admin: 별도 contact
- 분리 spec: `docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md`
- 통합 솔루션 매뉴얼 (참고): `Doc/solution/2026-05-19-locus-admin-manual.md`
- 사고 보고: `Doc/research/YYYY-MM-DD-*.md`

---

## 11. 통합 Locus 매뉴얼 대비 차이 요약

| 영역 | 통합 Locus | Lucas-KMS |
|---|---|---|
| KMS Library | 동일 | 동일 |
| 검색 / RAG | 동일 (`/search`, `/rag/assist-stream`) | 동일 |
| Agent 생성/관리 | 있음 | **없음** |
| 챗 UI (Admin UI) | 있음 | **없음** (Library + Search 만) |
| SOP-inject | 있음 | **없음** |
| Agent 위임 | 있음 | **없음** |
| 외부 채널 (Telegram 등) | 있음 | **없음** |
| persona / guidelines_md | 있음 | **없음** |
| Frontend | V3 (chat-first SPA) + V1 (admin) | V1 (KMS patch) 만 |
| Swagger | 활성 | production 은 JWT + IP allowlist |

> 본 매뉴얼은 *Lucas-KMS 단독 운영자* 용. Locus 통합 솔루션 운영자는 `Doc/solution/2026-05-19-locus-admin-manual.md` 참조.
