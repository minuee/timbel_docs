# 청크 임베딩 컨텍스트 prefix — 설계 (spec)

> 2026-06-22 · 대상: rag-parser-engine(KMS) `src/pipeline/workers/embed_worker.py`
> 문제 #1(검색 오류: 제품 특정 질의가 정답 chunk를 못 끌어옴) 해결. 문제 #2(다중질문 분해)는 **별도 spec**.

## 1. 배경 / 문제 (실측 확정)
펀드 간이투자설명서(docx) 검색에서, **더 구체적인 단일 질의가 오히려 실패**한다.

AWS 대신증권 워크스페이스(`019eb9a8…`) 실측:
- Q2 "미래에셋 환매수수료 50% 맞죠" → 미래에셋 환매수수료 chunk가 top-5(#2)에 잡힘 → 정답 답변.
- Q1 "미래에셋 **차세대Fun 펀드** 환매수수료 50% 맞죠" → 미래에셋 환매수수료 chunk가 **8위**(top_k=5 컷오프 탈락) → "정보 없음" 오답.

`top_k=20` 진단으로 확정한 메커니즘:
1. 정답 chunk(환매수수료 표)는 **표(table)라 펀드명이 본문에 없음**("| 구분 | 15시 30분 이전 | …").
2. "차세대Fun 펀드"가 **제품 개요 chunk**(KOSPI200/펀더멘탈/수익률 — 펀드명이 본문에 있음)를 상위로 끌어올려 정답 chunk를 밀어냄(#1·#4·#7이 개요).
3. dense 점수가 **0.50~0.54로 압축**(간이투자설명서가 펀드마다 거의 동일 양식) → 작은 쿼리 변화로 순위가 뒤집힘.
4. 다른 펀드(한투·하나)의 환매수수료 chunk가 미래에셋 것보다 위(#5·#6 > #8) → **펀드 식별 실패**.

근본 원인: **표 chunk의 임베딩 입력 텍스트에 소속 펀드명이 없어** 제품 특정 질의에 매칭되지 않는다.

### 현재 임베딩 입력 (확인)
- 임베딩 입력 = `embed_worker.py:597` `embedding_texts = [b.embedding_text() for b in blocks]` → BGE-M3.
- `BlockObject.embedding_text()`(`block.py:113-203`): TABLE 블록은 `table_markdown + table_nl`만. 펀드명·섹션 없음.
- 펀드명은 `contextual_prefix`에 들어갈 수 있으나 이를 채우는 `contextual_retrieval` 플래그가 **기본 False**(`document.py:123`) → 현재 비어 있음.
- `heading_path`(섹션 경로)는 heading_propagator가 항상 계산해 `source_location.heading_path`에 저장하지만 **임베딩 텍스트엔 미반영**.

## 2. 목표
인덱싱 시 각 블록의 **임베딩 입력 텍스트**에 소속 **문서 제목(펀드명) + 섹션(heading_path)** 을 **결정적으로** prepend한다. 제품 특정 질의가 정답 chunk(표 포함)를 끌어오게 한다. **LLM 미사용, 저장 블록·검색 반환·콜봇 응답 불변(임베딩 벡터에만 영향).**

비목표: 다중질문 분해(#2, 별도), 검색측 코드 변경, 블록 모델/세그멘테이션 변경, contextual_retrieval(LLM) 활성화.

## 3. 접근 (결정적 prepend, 접근 A)
검토한 대안:
- **A. 결정적 prepend (채택)**: embed_worker에서 `[펀드명 + 섹션]`을 임베딩 텍스트 앞에 결정적으로 붙임. 비용 0(LLM 없음), 수정 1곳.
- B. contextual_retrieval=True(LLM 맥락 생성): 블록당 LLM 호출 → 인제스트 느림·고비용. 결정적으로 충분하므로 비채택.

핵심 메커니즘: 펀드명 토큰이 chunk 임베딩 텍스트에 실제 존재 → dense·sparse 양쪽에서 제품 특정 질의 매칭 상승. 문서 내 chunk 간은 **섹션(heading_path)** 으로 변별 유지, 펀드 간은 **제목**으로 변별 강화.

## 4. 설계

### 4.1 수정 지점 (단일)
`src/pipeline/workers/embed_worker.py` `handle_document_blocked`:
- **조회 순서 정정(필수)**: `document_title`은 현재 `_get_document_meta`가 line 614(임베딩 597행 *이후*)에서 조회 → **597행 위로 이동**하여 임베딩 텍스트 생성 전에 확보. (또는 `event.title` 사용. heading_path는 `block.source_location`에 이미 있음.)
- line 597 `embedding_texts = [b.embedding_text() for b in blocks]` 를 각 블록에 prefix를 붙이는 형태로 교체:
  ```python
  embedding_texts = [_with_context_prefix(b, document_title) for b in blocks]
  ```

### 4.2 prefix 조립 규칙 (`_with_context_prefix`)
```
prefix 구성요소:
  title   = document_title 에서 확장자(.docx/.pdf 등) 제거, strip
  section = " > ".join(block.source_location.heading_path)  # 없으면 ""

규칙:
  - title 과 section 모두 없음           → prefix 없음 (block.embedding_text() 그대로)
  - section 없음                          → "{title}\n\n{embedding_text}"
  - 둘 다 있음                            → "{title} > {section}\n\n{embedding_text}"
  - block.metadata.contextual_prefix 존재 → prepend skip (이중 문서맥락 회피)
```
- 라벨 토큰("문서:","섹션:")은 **쓰지 않는다**(공통 토큰 sparse 희석 최소화). 고유명(펀드명/섹션명)만.
- prefix는 **1줄**, 짧게 유지(본문 비중 희석·dense 시프트 최소화).

### 4.3 변경 / 불변 경계 (중요)
**변경**: BGE-M3 `encode()`에 들어가는 텍스트(=dense·sparse 벡터)만.
**불변(확인됨)**:
- Qdrant payload `content` = `block.content`(raw, `embed_worker.py:836`)
- ES 인덱스 `content` = `block.content`(raw, :1008)
- 검색 반환 content(qdrant_dense/es_keyword) = payload raw content
- rerank 입력 = payload raw content(`cross_encoder.py:98`)
- section_title = qna_title
→ **prefix는 사용자/콜봇/LLM에 노출되지 않고, 저장·키워드·rerank 텍스트로 새지 않는다.**

## 5. 기존 문서 재임베딩
- 배포 후 `from_stage='embedding'` 재시도(`documents.py:1561,1806`)로 **재파싱 없이 재임베딩만**(DB 블록 로드 → BGE-M3 재인코딩 → Qdrant/ES delete+upsert, 멱등). 본 변경은 임베딩 입력 텍스트만 바꾸므로 이 경로로 일괄 적용 가능.
- 전제: DB 블록의 `source_location.heading_path`가 존재. 구문서로 비어 있으면 섹션 없는 prefix(펀드명만)로라도 적용됨(효과 일부). heading_path 자체를 새로 채우려면 `from_stage='enriching'` 필요(비용↑) — 기본은 `embedding`.
- 적용 대상/순서: 검증은 timbel(개발) 워크스페이스 일부 펀드 문서부터 → 전체 → AWS.

## 6. 영향 리뷰 요약 (착수 전 합의)
**안전(소스 확정)**: content 누출 0, ES 키워드 무영향, rerank 점수 무영향(raw content), embedding_text 단일호출처, 벡터차원 불변, 재임베딩 멱등.

**리스크 3 + 완화(설계 반영됨)**:
1. **콜봇 threshold=0.5 점수 시프트** — rerank ON(콜봇 항상)이면 score=rerank_score(raw) → **안전**. reranker 폴백(B200 장애) 시에만 dense점수로 시프트. 완화: prefix 짧게 + 도입 전후 점수분포 비교(§7). dense 후보 threshold(0.3, `qdrant_dense.py:70`) 진입 여부도 검증.
2. **빈 heading_path** — 신뢰도 게이팅(≥0.6)·페이지reset로 다수 블록이 `[]`. 완화: §4.2 빈값 가드(섹션 생략).
3. **sparse 희석 / contextual_prefix 이중** — 완화: 라벨 토큰 제거(§4.2), contextual_prefix 보유 블록 skip(§4.2).

## 7. 검증 / 회귀
- **효과**: timbel 재임베딩 후 Q1("미래에셋 차세대Fun 환매수수료") → 미래에셋 환매수수료 chunk가 **8위 → top-3** 진입.
- **회귀**:
  - Q2("미래에셋 환매수수료") 정상 유지.
  - 일반 토픽 질의("환매수수료"), 비펀드 문서 검색 무영향.
  - **rerank ON 점수분포** 도입 전/후 비교(회귀 케이스: 멀티턴·부정형·시간slot 질의)로 0.5 컷오프 통과율 안정 확인.
- before/after는 동일 쿼리셋·동일 워크스페이스에서 비교. AWS 적용은 timbel 검증 후.

## 8. 테스트
- **단위(`_with_context_prefix`)**: ① 제목+섹션 둘 다 → `"{title} > {section}\n\n…"` ② 섹션 빈 배열 → 제목만 ③ 제목 빈값 → prefix 생략 ④ contextual_prefix 존재 → skip ⑤ 제목 확장자 제거 ⑥ TABLE 블록 embedding_text 보존(prefix만 앞에).
- **통합**: 펀드 문서 1건 재임베딩 → Q1 쿼리 → 정답 chunk 순위 상승 확인. payload content에 prefix 미포함 확인(누출 0).

## 9. 배포
- KMS(rag-parser) worker 이미지 변경(`src/pipeline/workers/embed_worker.py`). 영구배포는 [[project_perm_deploy_recipe]] 절차(소스 동기화→worker rebuild→up). 배포는 사전 공지 후([[feedback_deploy_announce]]).
- 적용 후 재임베딩 트리거 → 검증(§7) → 이상 시 prefix 비활성(env/플래그로 즉시 끌 수 있게 둘지 구현계획에서 결정).

## 10. 미해결 / 후속
- 문제 #2(다중질문 분해→멀티검색)는 별도 spec(이 작업 완료 후).
- heading_path 품질 자체 개선(게이팅 임계·페이지reset)은 범위 외.
- reranker 폴백 정책(임계 우회)은 본 변경과 독립한 기존 이슈 — 별도.
