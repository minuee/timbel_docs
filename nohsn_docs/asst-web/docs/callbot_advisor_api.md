# 콜봇 · 어드바이저 — AICM 검색/답변 연동 API 레퍼런스

> 콜봇(callbot)·어드바이저(advisor)가 호출하는 AICM(aicm-service) 검색/RAG 답변 API를
> **현재 코드 기준**으로 정리한 단일 레퍼런스. 모든 스키마는 추측이 아니라
> `aicm-service` 소스에서 추출했다(파일·라인 표기). 작성 2026-06-05 (feature/rag-integration).

---

## 0. 소비자 모델

| 소비자 | 정체 | 인증 | 용도 |
|--------|------|------|------|
| 웹(aicm-web) | 우리 repo | 토큰(X-auth-token) + 카테고리 권한 enforce | 검색 + RAG 답변 |
| **콜봇** | 외부(CCaaS 봇그래프 RAG 노드) | 무인증(토큰 선택) | 검색 청크만 받아 자체 LLM으로 답변 |
| **어드바이저** | 외부 `asst-service`(`/aicc/asst-service`, 우리 repo 아님) | (정책 미확정 — 아래 §6) | 검색 + RAG 답변, 북마크는 asst-service 자체 관리 |

aicm-service는 검색 결과/생성형 답변만 제공한다. 어드바이저의 즐겨찾기·북마크는
asst-service 소관이며 AICM에는 해당 API가 없다.

---

## 1. 공통

- **Base (게이트웨이 경유)**: `https://{gateway}/aicc/aicm-service` + `/api/aicm/v1`
  - 예: `POST https://ecpad.etaas.co.kr/aicc/aicm-service/api/aicm/v1/search/retrieve_doc`
  - 게이트웨이 미경유(직접)일 때 prefix는 `/api/aicm/v1`.
  - ※ 구 콜봇 문서(`aicm-rag-migration.md`)는 `/api/search/...`로 표기 — 현재 실제 경로는 `/api/aicm/v1/search/...`.
- **인증 헤더**: `X-auth-token: <accessToken>` (웹/어드바이저). 콜봇 internal 검색은 토큰 없이 호출 가능.
- **권한 enforce (2026-06-02~)**: 토큰을 보내는 호출은 `PermissionEnforcer`가 적용된다.
  - 관리자(admin/system 등): 전체 분류 검색.
  - 상담원(agent): 권한그룹에 할당된 분류만. 할당 분류 0개면 빈 결과(또는 403).
  - 적용 엔드포인트: `retrieve_doc`, `integrated`, `by_category`, `rag_assist`.
  - `internal/document`(콜봇)은 **무인증이라 권한 게이트 없음**.
- **분류 id 조회**: 검색/필터에 넘길 `category_ids`(또는 `category_id`)는 **§8 카테고리 목록 API**로 얻는다. (`X-auth-token` 헤더는 필수지만 값 검증은 없음 → 더미 토큰+`workspace_id`로 콜봇/어드바이저 사용 가능.)

---

## 2. `POST /search/internal/document` — 콜봇 경량 검색

`aicm-service/api/endpoints/documents/search_endpoints.py:268`
스키마: `api/schemas/search_schemas.py:22` (`InternalSearchRequest`)

무인증·검색만(답변 X). **cross-encoder rerank 적용**, llm_rewrite off. AICM은 답변/요약/distill을 하지 않는다.

### 요청 (현재 코드가 받는 필드 — 콜봇 문서와 정합)
```json
{
  "workspace_id": "uuid",
  "text": "환불 절차 알려줘",
  "top_k": 5,
  "threshold": 0.5,
  "filters": { "approved": "production" },
  "search_type": "hybrid",
  "category_ids": ["cat-uuid", "..."]
}
```
| 필드 | 타입 | 기본 | 비고 |
|------|------|------|------|
| `workspace_id` | string | (필수) | |
| `text` | string | (필수) | 검색 쿼리 |
| `top_k` | int | 5 | |
| `threshold` | float? | null | 점수 < threshold 결과 제외 |
| `filters.approved` | string? | — | `"production"`이면 운영(effective) 문서만 반환 |
| `search_type` | string? | hybrid | 검색 모드(현재 hybrid 고정) |
| `category_ids` | string[]? | null | 있으면 해당 분류, 없으면 workspace 전체 |

### 응답 (콜봇 연동 포맷 — `search_endpoints.py:internal_search_document`)
```json
{
  "total_cnt": 2,
  "search_query": "나라사랑",
  "hybrid": [
    {
      "doc": {
        "workspace_id": "...",
        "document_id": "<AICM 암호화 id>",
        "document_name": "KB나라사랑적금(직업군인용)_특약",
        "title": "KB나라사랑적금(직업군인용)_특약",
        "store_id": "...",
        "section_id": "<block_id>",
        "section_path": [],
        "content": "...(매칭 블록 본문)...",
        "category_id": "<평문 분류 uuid>",
        "keywords": ["..."],
        "attachments": [ /* 첨부 enriched 목록 */ ],
        "version_name": "v1.0.0",
        "page_info": null,
        "approved": "production"
      },
      "score": 0.87,
      "is_intersection": true
    }
  ]
}
```

설계 노트:
- 문서 단위로 **최고 점수 블록을 대표**로 하나의 `hybrid` 항목 생성(중복 문서 병합). `content`=대표 블록 본문, `score`=대표 블록 점수.
- `doc.*` 필드(name/title/store_id/keywords/attachments/version_name/category_id)는 rag 결과를 AICM DB에서 **배치 보강**. rag가 주는 키가 `metadata.aicm_doc_id`든 rag_doc_id든 `DocumentsModel.id·rag_doc_id` 양쪽으로 매칭한다.
- `approved`: 운영 버전(`effective_contents_id`)이 있으면 `"production"`, 없으면 `"draft"`.
- `search_query`: rewrite OFF라 입력 `text`를 그대로 반환(모니터링용).
- `is_intersection`: 현재 항상 `true`(hybrid).
- **rerank (2026-06-09~ 적용)**: 하이브리드(dense/sparse/keyword + RRF) 후 **B200 cross-encoder reranker로 재정렬**된 청크를 반환(`enable_rerank=True`). 콜봇은 답변 생성이 없어 순위 품질이 중요하므로 on. 비용 **~100ms**(대부분 원격 B200 네트워크, 모델 8~10ms). `llm_rewrite`는 "rerank까지" 범위 밖이라 off 유지.
- AICM DB에 없는 고아 KMS 문서는 제외(retrieve_doc과 동일 정책).

> ### ✅ 콜봇 담당자 문서(`aicm-rag-migration.md`)와 정합화 완료 (2026-06-05)
> 과거 코드 응답은 `{total, results[]}` 평면 포맷이라 콜봇 문서(2.3, `{total_cnt, search_query, hybrid[]}`)와 달라 그대로면 콜봇이 깨졌다. 또 콜봇이 보내던 `filters.approved`·`search_type`을 코드가 무시해 미승인 문서가 섞일 수 있었다.
> → `internal_search_document`를 콜봇 기대 포맷으로 보강하고 `filters.approved=production`(운영 문서만)·`search_type`을 처리하도록 수정함. `title`=문서명, `section_id`=블록 id로 매핑.
> **남은 차이(참고)**: `section_path`는 현재 빈 배열(블록 경로 미보강), `categories`(이름 배열)는 미제공(대신 `category_id` 제공). 콜봇이 이 둘을 실제로 쓰면 추가 보강 필요.

---

## 3. `POST /search/retrieve_doc` — 시맨틱 검색(문서 후보)

`search_endpoints.py:188` · 스키마 `search_schemas.py:5` (`RetrieveDocRequest`)
토큰 권한 enforce 적용. 웹·어드바이저 공용. 필터 상세: `aicm-service/docs/retrieve_doc_filter_guide.md`(단 ES 시절 기준이라 일부 stale).

### 요청
```json
{
  "text": "검색어",
  "workspace_id": "uuid",
  "task_id": "task-uuid",
  "choices": ["..."],
  "top_k": 3,
  "filters": { "필드": "값 또는 배열" },
  "with_llm": false
}
```
`task_id` 필수. `filters`는 Dict(저장소/문서ID/카테고리/작성일 범위 등).

### 응답 (`services/rag_search_service.py` 상단 docstring + 구현)
```json
{
  "total": 2,
  "retrieved_docs": [
    {
      "id": "<aicm_doc_id>",
      "blocks_map": [
        { "id": "<block_id>", "content": "...", "score": 0.81 }
      ]
    }
  ]
}
```
`retrieved_docs` 항목은 AICM DB 조인으로 보강(`_enrich_with_db`)되어 문서 메타(이름 등)가 추가된다.
권한 스코프(agent)는 AICM content의 raw 분류를 viewable과 재대조해 비허가 문서를 제외한다.

---

## 4. `GET /search/integrated` — 통합 검색(분류별 묶음)

`search_endpoints.py:46`. 토큰 권한 enforce. 검색어는 인기/최근 키워드로 기록됨.

### 요청 (query string)
`?workspace_id=<uuid>&query=<검색어>`

### 응답 (`services/rag_integrated_search_service.py:170,262`)
```json
{
  "total": 12,
  "categories": [ /* rag-parser 카테고리 트리 */ ],
  "documents": {
    "<root_category_id>": {
      "items": [ /* doc_detail: document_id·이름·분류·점수 등 */ ]
    }
  }
}
```
권한 없는 분류만 가진 agent는 `{ "total": 0, "categories": [], "documents": {} }`.

---

## 5. `GET /search/by_category` — 분류 내 검색(페이지네이션)

`search_endpoints.py:95`. 토큰 권한 enforce(해당 분류 열람 권한 없으면 403).

### 요청 (query string)
| 파라미터 | 기본 | 비고 |
|----------|------|------|
| `workspace_id` | (필수) | |
| `category_id` | (필수) | 해당 분류 + 하위 분류 검색 |
| `query` | (필수) | 검색어 |
| `page` | 1 | |
| `limit` | 20 | 1~100 |
| `sort_by` | created_at | created_at/updated_at/hit_count |
| `sort_order` | desc | asc/desc |

### 응답
`doc_service.search_documents_by_category(...)` 반환(페이지네이션된 문서 목록). 필드 상세는
`db` 서비스 구현 참조.

---

## 6. `POST /search/rag_assist` — RAG 생성형 답변 (SSE)

`search_endpoints.py:222` · 스키마 `search_schemas.py:15` (`RagAssistRequest`)
rag-parser `assist-stream`을 패스스루(권한 게이트 포함). 2026-06-05 분류 권한 필터 배포됨.

### 요청
```json
{
  "workspace_id": "uuid",
  "query": "질문",
  "enable_distill": true,
  "conversation_history": [ { "role": "user", "content": "..." } ]
}
```

### 응답 — `text/event-stream`(SSE)
rag-parser SSE 라인을 가공 없이 전달. 이벤트 순서(2026-06-11 실측):
`intent → query_analysis → sources → distilled(옵션) → token × N → done`
(`clients/rag_service_client.py:356` assist_stream docstring)

> **알려진 한계**: rag_assist는 패스스루라 로컬 DB 조인 필터를 거치지 않아, rag-parser에
> 직접 등록된 orphan 문서가 근거에 노출될 수 있음(정상 AICM 업로드 운영이면 무발생).

---

## 7. 어드바이저(advisor) 미확정 사항

1. **인증 정책**: 메모리/초기 설계엔 "어드바이저 무인증·AI응답"이나, 현재 검색·rag_assist는
   토큰+권한 enforce다. 어드바이저가 무인증이어야 한다면 콜봇처럼 무인증 전용 엔드포인트
   (예: `/search/internal/assist`)를 신설할지, 토큰 기반으로 갈지 결정 필요.
2. **북마크/즐겨찾기**: asst-service 소관. AICM에 API 없음 → asst-service 연동돼야 테스트 가능.

---

## 8. 카테고리 목록 조회 API (검색 전 분류 선택용)

`aicm-service/api/endpoints/category_endpoints.py` (router `prefix="/category"`, `category_endpoints.py:20`)

콜봇·어드바이저가 검색(`§2 internal/document`의 `category_ids`, `§5 by_category`의 `category_id` 등)에 넘길 **분류 id를 얻는 조회 API**. 4개 모두 `_get_rag_client_for_workspace(workspace_id, token, db)`로 rag-parser(KMS) 카테고리 트리(`get_category_tree` = KMS `/categories/tree`, **active 분류만**)를 받아 가공해 반환한다.

**인증/권한 (중요):**
- **토큰 값 검증은 없으나 `X-auth-token` 헤더는 필수** — 앱에 전역 인증 의존성은 없지만(`main.py:72`), 이 엔드포인트들은 `X-auth-token` 헤더를 **필수 헤더로 선언**한다(누락 시 **422 `Field required`**, 실측 2026-06-10). 단 `get_rag_client_for_workspace`가 토큰 **값은 사용하지 않으므로**(`rag_dependencies.py:11` — `workspace_id`로 `workspace_rag_config`만 조회) **임의의 더미 값이면 통과**한다. → 콜봇/어드바이저는 **`X-auth-token: <아무값>` 헤더 + `workspace_id`**로 호출(무로그인 OK, 토큰 검증 안 함).
- **권한 필터 없음** — 검색계 엔드포인트와 달리 `PermissionEnforcer` 미적용. 즉 **전체(active) 분류 트리**를 반환한다. 콜봇/어드바이저는 통합 시스템이 분류를 선택해 `category_ids`로 넘기는 신뢰 모델이라 무방.
- 콜봇/어드바이저 **전용 네임스페이스 엔드포인트는 없음** — 웹과 동일한 범용 `/category/*`를 사용.

### 8.1 `GET /category/get_category` — 전체 트리 / 단건 (`category_endpoints.py:92`)
| 파라미터 | 필수 | 비고 |
|----------|------|------|
| `workspace_id` | ✓ | |
| `category_id` | — | 없으면 **전체 트리**, 있으면 해당 단건(flat 검색, 없으면 `{}`) |

전체 트리 응답(각 노드 = KMS `get_tree` 노드):
```json
[
  {
    "id": "uuid",
    "name": "테스트_부모",
    "description": "",
    "parent_id": null,
    "sort_order": 0,
    "path": ["테스트_부모"],
    "children": [
      { "id": "uuid", "name": "한투_자식", "parent_id": "<부모 uuid>", "children": [], "path": ["테스트_부모","한투_자식"], "...": "..." }
    ]
  }
]
```

### 8.2 `GET /category/get_top_category` — 최상위(root)만 (`category_endpoints.py:116`)
파라미터: `workspace_id`(필수). 응답: `parent_id`가 없는 root 노드 배열(각 노드는 위와 동일 구조, `children` 포함).

### 8.3 `GET /category/get_child_category` — 직계 자식 (`category_endpoints.py:133`)
파라미터: `workspace_id`(필수), `category_id`(필수). 응답: 해당 분류의 **직계 자식** flat 배열(`parent_id == category_id`).

### 8.4 `GET /category/get_category_path` — 분류 경로 (`category_endpoints.py:153`)
파라미터: `workspace_id`(필수), `category_id`(필수). 응답: root~leaf 경로를 `' > '` 구분자로 연결한 문자열(브레드크럼 표시용).

> 권장 흐름: ① `get_category`(또는 `get_top_category`/`get_child_category`)로 분류 목록 → ② 사용자가 고른 분류 `id`를 §2 `internal/document`의 `category_ids`(또는 §5 `by_category`의 `category_id`)로 전달. `category_ids` 미전달 시 workspace 전체 검색.

---

## 9. 새 서버(192.168.101.192) 연동 부록 — mock 단계 검증용

> 위 §1~§8은 **API 계약(소비 모델)**이라 배포 무관하게 동일하다. 이 부록은 작업자가
> **새 서버(192.168.101.192)에 실제로 붙어 검증**하는 데 필요한 그 서버 고유 정보다.
> 모든 값은 **2026-06-11 실측**. 현재 user-service는 **mock**(`mock-user-service`)이며,
> 아래 표에 **user-service 전환 시 교체 대상**을 명시한다.

### 9.1 접속 (Base URL)
| 경로 | URL | 비고 |
|------|-----|------|
| 권장(nginx 프록시) | `http://192.168.101.192:8173/api/aicm/v1` | nginx가 `/api/aicm/`를 aicm-service로 프록시(검증됨) |
| 직접(aicm-service) | `http://192.168.101.192:32012/api/aicm/v1` | host published 포트 |
| 서버 내부 워커 | `http://localhost:8173` 또는 `http://localhost:32012` | 아래 네트워크 주의 |

- **네트워크 주의:** `callbot-*` 컨테이너는 **host 네트워크**, `aicm_dev_service`는 **timbel_network** →
  **컨테이너명 DNS(`aicm_dev_service:32012`)로 도달 불가**. 같은 서버의 host-net 워커는
  `localhost:8173`/`localhost:32012`(또는 `192.168.101.192:포트`)로 호출한다.
- `mock-user-service`(:32021)는 host에 published 안 됨(:32021을 `aicc-ce-service`가 점유 → 내부 전용) — 워커가 직접 부를 일 없음.

### 9.2 필수 파라미터 (mock 값 / 교체 대상)
| 항목 | 현재 mock 값 | user-service 후 |
|------|--------------|-----------------|
| `workspace_id` | `019bfe5d-d00f-74c9-b6f6-416a9bfa1dc6` | 실 workspace_id로 교체 (**하드코딩 금지 → 설정값**) |
| tenant_id(참고) | `00000000-0000-0000-0000-000000000001` | 실 tenant (API 본문엔 직접 안 넣음) |
| `X-auth-token` | 임의 더미값(콜봇은 생략) | 어드바이저는 실 토큰(§9.4) |

### 9.3 검증된 호출 예시 (실측 2026-06-11)
콜봇 경량 검색(§2):
```bash
curl -X POST http://192.168.101.192:8173/api/aicm/v1/search/internal/document \
  -H 'Content-Type: application/json' \
  -d '{"workspace_id":"019bfe5d-d00f-74c9-b6f6-416a9bfa1dc6","text":"적금","top_k":3,"filters":{"approved":"production"}}'
# → {"total_cnt":1,"search_query":"적금","hybrid":[{"doc":{"document_id":"2113b41b-...",
#     "document_name":"KB청년 도약플러스적금_특약.pdf", ...}, "score":..., "is_intersection":true}]}
```
카테고리 목록(§8.2):
```bash
curl 'http://192.168.101.192:8173/api/aicm/v1/category/get_top_category?workspace_id=019bfe5d-d00f-74c9-b6f6-416a9bfa1dc6' \
  -H 'X-auth-token: dummy'
# → [{"id":"1798ce53-...","name":"한국투자증권","parent_id":null,
#     "children":[{"name":"한투_메뉴얼", ...}]}]
```
어드바이저 RAG 답변 SSE(§6):
```bash
curl -N -X POST http://192.168.101.192:8173/api/aicm/v1/search/rag_assist \
  -H 'X-auth-token: dummy' -H 'Content-Type: application/json' \
  -d '{"workspace_id":"019bfe5d-d00f-74c9-b6f6-416a9bfa1dc6","query":"적금 알려줘","enable_distill":false}'
# → event: intent / event: query_analysis / ... / event: done
```

### 9.4 인증: mock → user-service 전환 시 차이 (소비자별 이식성)
| 소비자 | 엔드포인트 | mock 단계 | user-service 후 | 지금 검증의 이식성 |
|--------|-----------|-----------|-----------------|--------------------|
| 콜봇 | `internal/document` | 무인증 | 무관(토큰 안 봄) | **완전 이식** |
| 카테고리 | `/category/*` | 더미토큰(값 미검증) | 동일(workspace_id로 RAG config 조회, 토큰값 미사용) | **완전 이식** |
| 어드바이저 | `rag_assist`·`retrieve_doc`·`integrated`·`by_category` | 더미토큰 → 전체 권한 통과 | **실 토큰 필요**(PermissionEnforcer가 진짜 사용자·권한 해석) → 더미토큰 **거부 가능** | 흐름·응답 이식, **인증만 재확정**(§7) |

→ 콜봇·카테고리는 user-service가 와도 그대로. 어드바이저는 **검색·답변 흐름/응답 포맷은 지금 검증**되고, **인증 부분만** 실 user-service 도입 시 확정한다.

### 9.5 데이터 표현 주의
- 이 서버는 `is_cipher=false` → 응답의 `document_id`는 **평문 UUID**(예 `2113b41b-...`). §2가 "AICM 암호화 id"로 적은 것과 달리 raw다. 배포에 따라 암호화될 수 있으니 **항상 불투명 문자열로 취급**(파싱·가정 금지).

### 9.6 가동 전제
- 검색/답변은 새 서버 rag-parser(`lucas-kms-api`)가 가동 중이어야 함. `rag_assist`는 LLM 포함이라 **B200 터널**도 필요.
- `mock-user-service` 가동 필요(workspace RAG config 조회 경로). user-service 전환 시 이 의존이 실 서비스로 대체됨.

---

## 변경 이력
| 날짜 | 내용 |
|------|------|
| 2026-06-05 | 최초 작성. 코드 기준 5개 엔드포인트 정리 + 콜봇 문서 응답 포맷 불일치 명시 |
| 2026-06-05 | `internal/document`를 콜봇 hybrid 포맷으로 정합화 + `filters.approved`/`search_type` 처리 구현(aicm-service `873f212`). §2 갱신 |
| 2026-06-09 | 콜봇 검색에 cross-encoder rerank 적용(`enable_rerank=True`, aicm-service `f2732b3`) — 요구사항 "콜봇은 rerank까지 처리". rerank 비용 ~100ms(원격 B200 실측). §2 갱신 |
| 2026-06-10 | §8 카테고리 목록 조회 API 추가(`/category/get_category`·`get_top_category`·`get_child_category`·`get_category_path`). `X-auth-token` 헤더 필수이나 값 검증 없음(더미 토큰+`workspace_id`로 호출, 권한필터 없음=전체 active 트리). 콜봇/어드바이저가 `category_ids` 선택 시 사용. §1 포인터 추가. (초안의 "무인증·헤더불요"는 실측 422로 정정) |
| 2026-06-11 | §9 새 서버(192.168.101.192) 연동 부록 추가 — Base URL(:8173 nginx/:32012 직접), mock workspace_id(`019bfe5d…`)·tenant·더미토큰 규칙, host-net 워커 주소 주의, 검증된 curl 3종(콜봇·카테고리·rag_assist 실측 200), mock→user-service 인증 이식성 표, is_cipher=false(raw document_id) 주의, 가동 전제. 콜봇·카테고리는 user-service 후도 그대로/어드바이저는 인증만 재확정 |
