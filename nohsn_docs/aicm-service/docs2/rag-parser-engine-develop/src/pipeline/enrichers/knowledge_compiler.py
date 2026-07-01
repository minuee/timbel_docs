"""Knowledge Compiler — LLM-WIKI 패턴 기반 지식 컴파일 레이어.

Karpathy LLM-WIKI 3대 기능을 AICM 블럭 파이프라인에 내재화:

Ingest (문서 입력 시점):
  1. 문맥 접두사 (Contextual Retrieval)
  2. 메타데이터 추출 (키워드/엔터티)
  3. 문서 요약 블럭 생성
  4. 엔터티/개념 블럭 생성 — LLM-WIKI 신규
  5. 크로스링크 메타데이터 — LLM-WIKI 신규
  6. 저장소 인덱스 블럭 갱신 — LLM-WIKI 신규

specs/06 2D 참조.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from uuid import UUID, uuid4

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType
from src.pipeline.models.document import ProcessingConfig, SourceLocation

log = get_logger(__name__)


# D17-v5 spec B (§1) — KC idempotency cleanup
# KC 가 *직접* 발급한 source 마커. cleanup 대상은 generated=True AND
# source ∈ _KC_GENERATED_SOURCES *동시 충족* 시에만. 외부 enricher 가
# 동일 source 값을 우연히 가져도 (generated=False) 보존.
KC_VERSION = 1
_KC_GENERATED_SOURCES: frozenset[str] = frozenset({
    "llm_summary",
    "stats_summary",
    "entity_page",
})

# KC 가 채운 contextual_prefix 임을 표시하는 internal metadata key.
# 다음 cleanup 진입 시 이 마커가 있는 block 의 contextual_prefix 만 reset.
# 외부/이전 단계가 채운 prefix 는 마커 없으므로 보존됨.
# *internal key* — 언더스코어 prefix 로 식별.
_KC_OWNED_CTX_PREFIX_MARKER = "_kc_owned_contextual_prefix"


class KnowledgeCompiler:
    """블럭 목록에 LLM-WIKI 스타일 지식 컴파일을 적용한다.

    Ingest 단계:
    1. 문맥 접두사 (Contextual Retrieval)
    2. 메타데이터 추출
    3. 문서 요약 블럭 생성
    4. 엔터티/개념 블럭 생성
    5. 크로스링크 메타데이터 주입
    """

    def __init__(self, config: ProcessingConfig, llm_client: object | None = None) -> None:
        self.config = config
        self._llm_client = llm_client

    async def compile(
        self,
        blocks: list[BlockObject],
        document_text: str = "",
        document_title: str = "",
    ) -> list[BlockObject]:
        """블럭 목록에 지식 컴파일을 적용한다.

        Parameters
        ----------
        blocks : list[BlockObject]
            세그멘테이션 결과 블럭 목록
        document_text : str
            전체 문서 원문
        document_title : str
            문서 제목

        Returns
        -------
        list[BlockObject]
            보강된 블럭 목록 (요약·엔터티 블럭 포함)
        """
        if not blocks:
            return blocks

        # D17-v5 §1 — idempotency cleanup
        # 동일 입력에 N회 호출되어도 결과가 누적되지 않도록 cleanup → regen.
        # 사용자/외부 enricher block 은 보존 (generated=True + source 화이트리스트
        # AND 조건). KC 가 채운 contextual_prefix 도 마커 가진 경우만 reset.
        blocks = self._cleanup_prior_kc_outputs(blocks)

        # 1~2.2) 병렬 실행 가능한 LLM 보강 단계들 (모두 block 단위, 서로 독립)
        import asyncio as _asyncio

        parallel_tasks = []
        if self.config.contextual_retrieval:
            parallel_tasks.append(
                self._apply_contextual_prefix(blocks, document_text, document_title)
            )
        if self.config.auto_metadata:
            parallel_tasks.append(self._apply_metadata_extraction(blocks))
        parallel_tasks.append(self._classify_ontology(blocks, document_title))
        parallel_tasks.append(self._map_categories(blocks))

        # 모두 같은 blocks 리스트를 제자리 수정하므로 반환값 무시
        await _asyncio.gather(*parallel_tasks, return_exceptions=True)

        # 2.2.5) heading_path 자동 추출 — D17 P1 step 6 (image_describer 전에 실행해야
        # vision prompt 가 컨텍스트로 활용 가능)
        try:
            from src.pipeline.enrichers.heading_propagator import propagate_heading_paths

            propagate_heading_paths(blocks)
        except Exception as exc:
            log.warning("heading_propagator_failed", error=str(exc))

        # 2.3 + 2.5) 표/이미지 분석도 병렬
        await _asyncio.gather(
            self._analyze_tables(blocks),
            self._describe_images(blocks, document_title=document_title),
            return_exceptions=True,
        )

        # 2.6) Search summary 생성 + 다층 키워드 추출 (병렬)
        search_summary_task = None
        multilayer_kw_task = None

        if self.config.enable_search_summary:
            search_summary_task = self._generate_search_summaries(blocks)
        if self.config.enable_query_keywords:
            multilayer_kw_task = self._extract_multilayer_keywords(blocks)

        enrichment_tasks = [t for t in (search_summary_task, multilayer_kw_task) if t]
        if enrichment_tasks:
            await _asyncio.gather(*enrichment_tasks, return_exceptions=True)

        # 2.7) LLM 자가 검증 (선택적)
        if self.config.enable_self_verification:
            try:
                from src.pipeline.enrichers.self_verifier import SelfVerifier

                verifier = SelfVerifier(llm_client=self._llm_client)
                blocks = await verifier.verify_all(blocks, document_text)
            except Exception as exc:
                log.warning("self_verification_step_failed", error=str(exc))

        # 3) 문서 요약 블럭 생성
        summary_block = await self._generate_summary_block(
            blocks, document_text, document_title
        )
        if summary_block:
            blocks.append(summary_block)

        # 4) 엔터티/개념 블럭 생성 (LLM-WIKI Ingest)
        entity_blocks = await self._generate_entity_blocks(blocks, document_title)
        blocks.extend(entity_blocks)

        # 5) 크로스링크 메타데이터 주입
        self._inject_crosslinks(blocks)

        # block_index 재정렬
        for i, block in enumerate(blocks):
            block.block_index = i

        log.info(
            "knowledge_compilation_complete",
            block_count=len(blocks),
            contextual_retrieval=self.config.contextual_retrieval,
            auto_metadata=self.config.auto_metadata,
            has_summary=summary_block is not None,
            entity_blocks=len(entity_blocks),
        )
        return blocks

    # ------------------------------------------------------------------
    # D17-v5 §1 — KC idempotency cleanup (cleanup → regen 매번)
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_prior_kc_outputs(
        blocks: list[BlockObject],
    ) -> list[BlockObject]:
        """KC 가 *직접* 생성/수정한 산출물만 제거. 외부/사용자 block 보존.

        제거 대상:
        - generated=True AND source ∈ _KC_GENERATED_SOURCES 인 block
          (KC 가 만든 SUMMARY/ENTITY block — 외부 enricher 가 동일 source
          값을 가져도 generated=False 면 보존됨).

        정리 대상 (block 자체는 보존, KC-owned metadata 만 pop):
        - metadata['crosslinks' / 'linked_block_ids' / 'crosslink_count'] 제거
        - block.contextual_prefix — _KC_OWNED_CTX_PREFIX_MARKER 마커가 있는
          block 만 None reset. 외부/이전 단계가 채운 prefix 는 보존.

        D17-v5 spec B (사용자 절칙: 회귀 0). GPT-5 v2 phase0 GO.
        """
        cleaned: list[BlockObject] = []
        for b in blocks:
            meta = b.metadata if isinstance(b.metadata, dict) else None
            if meta is None:
                cleaned.append(b)
                continue

            # KC 가 발급한 SUMMARY/ENTITY block 인지 검사 — AND 조건
            is_kc_generated = (
                bool(meta.get("generated"))
                and str(meta.get("source", "")) in _KC_GENERATED_SOURCES
            )
            if is_kc_generated:
                # 제거 (regen 단계에서 새로 생성됨)
                continue

            # KC-owned metadata 키만 pop (regen 단계에서 새로 생성)
            for k in ("crosslinks", "linked_block_ids", "crosslink_count"):
                meta.pop(k, None)

            # contextual_prefix — KC-owned 마커 있는 경우만 reset
            if (
                b.contextual_prefix is not None
                and meta.get(_KC_OWNED_CTX_PREFIX_MARKER) is True
            ):
                b.contextual_prefix = None
                meta.pop(_KC_OWNED_CTX_PREFIX_MARKER, None)

            cleaned.append(b)

        log.info(
            "kc_cleanup_prior_outputs",
            input=len(blocks),
            removed=len(blocks) - len(cleaned),
            kc_version=KC_VERSION,
        )
        return cleaned

    # ------------------------------------------------------------------
    # 2.1) 온톨로지 분류 (LLM-first, 모든 포맷 지원)
    # ------------------------------------------------------------------

    async def _classify_ontology(
        self, blocks: list[BlockObject], document_title: str
    ) -> list[BlockObject]:
        """블럭에 nature/time_reference/entities 분류를 적용한다.

        PDF 3-stage 파이프라인에서 이미 분류된 블럭은 건너뛰고,
        비-PDF 문서(DOCX/HWP/MD/TXT 등)의 블럭은 새로 분류한다.
        """
        if self._llm_client is None:
            return blocks

        try:
            from src.pipeline.enrichers.ontology_classifier import OntologyClassifier

            classifier = OntologyClassifier(
                llm_client=self._llm_client,
                document_type="문서",  # TODO: document_structure에서 가져오기
                document_title=document_title,
            )
            return await classifier.classify_all(blocks)
        except Exception as exc:
            log.warning("ontology_classification_step_failed", error=str(exc))
        return blocks

    # ------------------------------------------------------------------
    # 2.2) 카테고리 매핑 (domain_category_ids)
    # ------------------------------------------------------------------

    async def _map_categories(self, blocks: list[BlockObject]) -> list[BlockObject]:
        """블럭을 테넌트 카테고리에 매핑한다.

        첫 블럭의 document_id에서 repository_id를 조회하여
        해당 저장소의 카테고리 목록을 로드하고 각 블럭을 매핑한다.
        """
        if not blocks or self._llm_client is None:
            return blocks

        try:
            from sqlalchemy import text as _text

            from src.core.database import async_session_factory
            from src.pipeline.enrichers.category_mapper import (
                CategoryMapper,
                load_tenant_categories,
            )

            # document_id → repository_id 조회
            doc_id = blocks[0].document_id
            async with async_session_factory() as session:
                r = await session.execute(
                    _text("SELECT repository_id FROM documents WHERE id = :did"),
                    {"did": str(doc_id)},
                )
                row = r.fetchone()
                if not row:
                    return blocks
                repository_id = row[0]

            categories = await load_tenant_categories(repository_id)
            if not categories:
                return blocks

            mapper = CategoryMapper(
                llm_client=self._llm_client,
                categories=categories,
            )
            return await mapper.map_all(blocks)
        except Exception as exc:
            log.warning("category_mapping_step_failed", error=str(exc))
        return blocks

    # ------------------------------------------------------------------
    # 2.5) 이미지 설명 생성
    # ------------------------------------------------------------------

    async def _describe_images(
        self,
        blocks: list[BlockObject],
        document_title: str = "",
    ) -> list[BlockObject]:
        """이미지 블럭에 Vision LLM 설명을 추가한다.

        D17 (2026-05-08): bbox+hash dedup 으로 vision LLM 호출 cost 절감
        (반복 image bbox 그룹당 대표 1장만 LLM 호출 → 결과 broadcast).
        """
        try:
            from src.pipeline.enrichers.image_describer import ImageDescriber
            from src.pipeline.enrichers.image_dedup_helper import dedup_image_calls

            describer = ImageDescriber(llm_client=self._llm_client)
            return await dedup_image_calls(blocks, describer, document_title)
        except Exception as exc:
            log.warning("image_description_step_failed", error=str(exc))
        return blocks

    # ------------------------------------------------------------------
    # 2.6) Search summary 생성
    # ------------------------------------------------------------------

    async def _generate_search_summaries(
        self, blocks: list[BlockObject]
    ) -> list[BlockObject]:
        """각 블럭에 검색 최적화 요약을 생성한다."""
        try:
            from src.pipeline.enrichers.search_summary_generator import (
                SearchSummaryGenerator,
            )

            generator = SearchSummaryGenerator(llm_client=self._llm_client)
            return await generator.generate_all(blocks)
        except Exception as exc:
            log.warning("search_summary_step_failed", error=str(exc))
        return blocks

    # ------------------------------------------------------------------
    # 2.7) 다층 키워드 추출
    # ------------------------------------------------------------------

    async def _extract_multilayer_keywords(
        self, blocks: list[BlockObject]
    ) -> list[BlockObject]:
        """각 블럭에서 query_keywords, synonyms, topic_tags를 추출한다."""
        try:
            from src.pipeline.enrichers.metadata_extractor import (
                MultilayerKeywordExtractor,
            )

            extractor = MultilayerKeywordExtractor(llm_client=self._llm_client)
            return await extractor.extract_all(blocks)
        except Exception as exc:
            log.warning("multilayer_keyword_step_failed", error=str(exc))
        return blocks

    # ------------------------------------------------------------------
    # 4) 엔터티/개념 블럭 생성 (LLM-WIKI 신규)
    # ------------------------------------------------------------------

    async def _generate_entity_blocks(
        self,
        blocks: list[BlockObject],
        document_title: str,
    ) -> list[BlockObject]:
        """블럭들에서 추출된 엔터티를 개별 엔터티 블럭으로 생성한다.

        LLM-WIKI의 entities/ 디렉토리에 해당.
        각 엔터티 블럭은 해당 엔터티가 언급된 모든 블럭의 내용을 종합한다.
        """
        # 메타데이터에서 엔터티 수집 (두 시스템 통합)
        # 1) metadata_extractor 결과 (extracted_metadata.entities: ["이름1", "이름2"])
        # 2) stage3/ontology_classifier 결과 (metadata.entities: {"people": [], "orgs": [], ...})
        entity_mentions: dict[str, list[BlockObject]] = defaultdict(list)
        for block in blocks:
            if block.block_type == BlockType.SUMMARY:
                continue

            # 시스템 1: extracted_metadata.entities (단순 리스트)
            ext_meta = block.extracted_metadata or {}
            entities_list = ext_meta.get("entities", [])
            if isinstance(entities_list, list):
                for entity in entities_list:
                    if isinstance(entity, str):
                        entity_clean = entity.strip()
                    elif isinstance(entity, dict):
                        entity_clean = entity.get("name", "").strip()
                    else:
                        continue
                    if len(entity_clean) >= 2:
                        entity_mentions[entity_clean].append(block)

            # 시스템 2: metadata.entities (structured: {people, orgs, ...})
            structured = (block.metadata or {}).get("entities")
            if isinstance(structured, dict):
                for bucket in ("people", "orgs", "speakers", "locations"):
                    names = structured.get(bucket, [])
                    if isinstance(names, list):
                        for name in names:
                            if isinstance(name, str) and len(name.strip()) >= 2:
                                entity_mentions[name.strip()].append(block)

        if not entity_mentions:
            return []

        # 2회 이상 언급된 엔터티만 블럭 생성 (노이즈 필터)
        significant_entities = {
            name: mentions
            for name, mentions in entity_mentions.items()
            if len(mentions) >= 2
        }

        if not significant_entities and self._llm_client is None:
            return []

        # LLM이 있으면 엔터티 페이지 생성, 없으면 통계 기반
        entity_blocks: list[BlockObject] = []
        doc_id = blocks[0].document_id if blocks else uuid4()

        if self._llm_client and significant_entities:
            entity_blocks = await self._llm_entity_blocks(
                significant_entities, doc_id, document_title
            )
        elif significant_entities:
            entity_blocks = self._stats_entity_blocks(
                significant_entities, doc_id, document_title
            )

        log.info(
            "entity_blocks_generated",
            total_entities=len(entity_mentions),
            significant_entities=len(significant_entities),
            entity_blocks=len(entity_blocks),
        )
        return entity_blocks

    async def _llm_entity_blocks(
        self,
        entity_mentions: dict[str, list[BlockObject]],
        doc_id: UUID,
        document_title: str,
    ) -> list[BlockObject]:
        """LLM으로 엔터티 페이지를 생성한다."""
        blocks: list[BlockObject] = []

        # 배치 처리: 최대 10개 엔터티씩
        entity_items = list(entity_mentions.items())[:20]  # 문서당 최대 20 엔터티

        prompt = self._build_entity_prompt(entity_items, document_title)
        try:
            raw = await self._call_llm(prompt)
            parsed = self._parse_entity_response(raw)

            for entry in parsed:
                name = entry.get("name", "")
                description = entry.get("description", "")
                related = entry.get("related", [])
                if not name or not description:
                    continue

                content = f"# {name}\n\n{description}"
                if related:
                    content += f"\n\n관련 개념: {', '.join(related)}"

                block = BlockObject(
                    id=uuid4(),
                    document_id=doc_id,
                    block_type=BlockType.SUMMARY,
                    content=content,
                    block_index=0,
                    token_count=len(content),
                    source_location=SourceLocation(),
                    metadata={
                        "generated": True,
                        "source": "entity_page",
                        "entity_name": name,
                        "related_entities": related,
                        "mention_count": len(entity_mentions.get(name, [])),
                    },
                )
                block.compute_hash()
                blocks.append(block)

        except Exception as exc:
            log.warning("llm_entity_generation_failed", error=str(exc))
            blocks = self._stats_entity_blocks(
                dict(entity_items), doc_id, document_title
            )

        return blocks

    @staticmethod
    def _stats_entity_blocks(
        entity_mentions: dict[str, list[BlockObject]],
        doc_id: UUID,
        document_title: str,
    ) -> list[BlockObject]:
        """LLM 없이 통계 기반 엔터티 블럭을 생성한다."""
        blocks: list[BlockObject] = []

        for name, mentions in entity_mentions.items():
            # 언급된 블럭의 앞 100자를 수집
            snippets = []
            for m in mentions[:5]:
                snippet = m.content[:100].replace("\n", " ")
                snippets.append(f"- {snippet}")

            content = f"# {name}\n\n문서 '{document_title}'에서 {len(mentions)}회 언급.\n\n언급 맥락:\n" + "\n".join(snippets)

            block = BlockObject(
                id=uuid4(),
                document_id=doc_id,
                block_type=BlockType.SUMMARY,
                content=content,
                block_index=0,
                token_count=len(content),
                source_location=SourceLocation(),
                metadata={
                    "generated": True,
                    "source": "entity_page",
                    "entity_name": name,
                    "mention_count": len(mentions),
                },
            )
            block.compute_hash()
            blocks.append(block)

        return blocks

    @staticmethod
    def _build_entity_prompt(
        entity_items: list[tuple[str, list[BlockObject]]],
        document_title: str,
    ) -> str:
        """엔터티 페이지 생성 프롬프트."""
        entity_info = []
        for name, mentions in entity_items:
            contexts = [m.content[:150].replace("\n", " ") for m in mentions[:3]]
            entity_info.append(f"엔터티: {name} ({len(mentions)}회 언급)\n맥락: " + " | ".join(contexts))

        return f"""문서 '{document_title}'에서 추출된 엔터티들의 설명 페이지를 생성하세요.

엔터티 목록:
{chr(10).join(entity_info)}

JSON 배열로 출력. 다른 텍스트 없이:
[{{"name":"엔터티명","description":"2~3문장 설명","related":["관련엔터티1"]}}]"""

    @staticmethod
    def _parse_entity_response(raw: str) -> list[dict]:
        """엔터티 LLM 응답 파싱."""
        cleaned = raw.strip()
        if "```" in cleaned:
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return []

    # ------------------------------------------------------------------
    # 5) 크로스링크 메타데이터 주입
    # ------------------------------------------------------------------

    @staticmethod
    def _inject_crosslinks(blocks: list[BlockObject]) -> None:
        """블럭 간 크로스링크 메타데이터를 주입한다.

        1) 같은 엔터티(structured + flat 리스트) 언급 블럭 연결
        2) 같은 domain_category_ids를 공유하는 블럭 연결
        3) 엔터티 페이지 블럭 연결
        """
        # 엔터티 → 블럭 ID 매핑
        entity_to_blocks: dict[str, list[str]] = defaultdict(list)
        category_to_blocks: dict[str, list[str]] = defaultdict(list)

        for block in blocks:
            # flat entities (metadata_extractor)
            ext_meta = block.extracted_metadata or {}
            for entity in ext_meta.get("entities", []):
                if isinstance(entity, str):
                    entity_to_blocks[entity.strip()].append(str(block.id))
                elif isinstance(entity, dict):
                    name = entity.get("name", "").strip()
                    if name:
                        entity_to_blocks[name].append(str(block.id))

            # structured entities (ontology_classifier)
            structured = (block.metadata or {}).get("entities")
            if isinstance(structured, dict):
                for bucket in ("people", "orgs", "speakers", "locations"):
                    for name in structured.get(bucket, []) or []:
                        if isinstance(name, str) and name.strip():
                            entity_to_blocks[name.strip()].append(str(block.id))

            # 엔터티 페이지 블럭
            entity_name = block.metadata.get("entity_name")
            if entity_name:
                entity_to_blocks[entity_name].append(str(block.id))

            # 도메인 카테고리
            for cat in block.metadata.get("domain_category_ids", []) or []:
                if isinstance(cat, dict):
                    cat_id = cat.get("id")
                    if cat_id:
                        category_to_blocks[str(cat_id)].append(str(block.id))

        # 각 블럭에 linked_block_ids 주입
        for block in blocks:
            linked: set[str] = set()

            # 엔터티 기반 링크
            ext_meta = block.extracted_metadata or {}
            for entity in ext_meta.get("entities", []):
                key = entity.strip() if isinstance(entity, str) else (
                    entity.get("name", "").strip() if isinstance(entity, dict) else ""
                )
                if key:
                    for bid in entity_to_blocks.get(key, []):
                        if bid != str(block.id):
                            linked.add(bid)

            structured = (block.metadata or {}).get("entities")
            if isinstance(structured, dict):
                for bucket in ("people", "orgs", "speakers", "locations"):
                    for name in structured.get(bucket, []) or []:
                        if isinstance(name, str):
                            for bid in entity_to_blocks.get(name.strip(), []):
                                if bid != str(block.id):
                                    linked.add(bid)

            entity_name = block.metadata.get("entity_name")
            if entity_name:
                for bid in entity_to_blocks.get(entity_name, []):
                    if bid != str(block.id):
                        linked.add(bid)

            # 카테고리 기반 링크 (같은 카테고리)
            for cat in block.metadata.get("domain_category_ids", []) or []:
                if isinstance(cat, dict):
                    cat_id = cat.get("id")
                    if cat_id:
                        for bid in category_to_blocks.get(str(cat_id), []):
                            if bid != str(block.id):
                                linked.add(bid)

            if linked:
                # 최대 20개로 제한 (너무 많은 링크는 노이즈)
                linked_list = list(linked)[:20]
                block.metadata["linked_block_ids"] = linked_list
                block.metadata["crosslink_count"] = len(linked_list)

    async def _analyze_tables(self, blocks: list[BlockObject]) -> list[BlockObject]:
        """표 블럭의 의미를 분석하여 메타데이터에 저장한다. 병렬 처리."""
        if self._llm_client is None:
            return blocks

        try:
            from src.pipeline.prompts.table_semantic import build_table_analysis_prompt
        except ImportError:
            log.debug("table_semantic_prompt_not_available")
            return blocks

        table_blocks = [
            b for b in blocks
            if b.block_type == BlockType.TABLE
            and b.table_markdown
            and not b.metadata.get("table_analysis")
        ]
        if not table_blocks:
            return blocks

        from src.common.llm_utils import extract_json_object

        async def _analyze_one(block: BlockObject) -> None:
            context = self._get_table_context(block, blocks)
            prompt = build_table_analysis_prompt(block.table_markdown, context)
            try:
                response = await self._call_llm(prompt)
                analysis = extract_json_object(response)
                if not analysis:
                    log.warning(
                        "table_analysis_empty_json",
                        block_id=str(block.id),
                        response_preview=response[:200] if response else "",
                    )
                    return
                block.metadata["table_analysis"] = analysis

                # table_nl: 자연어 해석 (3~5 문장) — 검색 임베딩 + RAG 에 사용
                # 기존에 이미 채워져 있으면 존중 (Stage3 vision 경로), 비어 있으면 새로 채움
                new_nl = analysis.get("table_nl", "") or ""
                if new_nl and not block.metadata.get("table_nl"):
                    block.metadata["table_nl"] = new_nl

                table_desc = analysis.get("description", "")
                if table_desc and not block.content.startswith(table_desc):
                    block.content = f"{table_desc}\n\n{block.content}"
                    block.compute_hash()

                log.info(
                    "table_analyzed",
                    table_type=analysis.get("table_type"),
                    block_id=str(block.id),
                    desc_len=len(table_desc),
                    nl_len=len(new_nl),
                )
            except Exception as exc:
                log.warning(
                    "table_analysis_failed",
                    block_id=str(block.id),
                    error=str(exc)[:200],
                )

        import asyncio
        await asyncio.gather(*[_analyze_one(b) for b in table_blocks])
        return blocks

    @staticmethod
    def _get_table_context(
        table_block: BlockObject, all_blocks: list[BlockObject]
    ) -> str:
        """표 전후 블럭에서 맥락 텍스트를 추출한다."""
        idx = table_block.block_index
        context_parts = []
        for b in all_blocks:
            if b.block_type == BlockType.TABLE:
                continue
            if abs(b.block_index - idx) <= 2:  # 전후 2블럭
                context_parts.append(b.content[:200])
        return " ".join(context_parts)[:500]

    async def _apply_contextual_prefix(
        self,
        blocks: list[BlockObject],
        document_text: str,
        document_title: str,
    ) -> list[BlockObject]:
        """각 블럭에 문맥 접두사를 추가한다.

        v2 우선: 블럭 파이프라인이면 v2 (다층 맥락 + 검색 키워드) 사용.
        v2 실패 시 v1 fallback.
        """
        try:
            from src.pipeline.enrichers.contextual_retrieval import ContextualRetriever

            retriever = ContextualRetriever()

            # v2 시도: 블럭 직접 처리 (다층 맥락, 인접 블럭, 검색 키워드)
            try:
                # 문서 요약 수집 (이미 생성된 summary 블럭이 있으면 사용)
                doc_summary = ""
                for b in blocks:
                    if b.block_type == BlockType.SUMMARY and b.metadata.get("source") in (
                        "llm_summary", "stats_summary"
                    ):
                        doc_summary = b.content[:300]
                        break

                # D17-v5 §1 — v2 enrich 직전 prefix snapshot (id → prev value).
                # KC 가 실제로 *새로 쓰거나 변경* 한 block 만 KC-owned 마커 부여.
                # (외부 / 이전 단계 가 채운 prefix 가 v2 에서 변경되지 않았다면
                # 그대로 보존, 마커 X — risk 3 fix).
                _prev_prefix_by_id = {b.id: b.contextual_prefix for b in blocks}

                blocks = await retriever.enrich_blocks_v2(
                    blocks=blocks,
                    document_text=document_text,
                    document_title=document_title,
                    document_type="",  # 향후 document_structure에서 가져오기
                    document_summary=doc_summary,
                )
                # KC 가 실제로 변경한 block 만 마커 inject
                for _b in blocks:
                    prev = _prev_prefix_by_id.get(_b.id)
                    if (
                        _b.contextual_prefix is not None
                        and _b.contextual_prefix != prev
                        and isinstance(_b.metadata, dict)
                    ):
                        _b.metadata[_KC_OWNED_CTX_PREFIX_MARKER] = True
                log.info("contextual_prefix_v2_applied", block_count=len(blocks))
                return blocks
            except Exception as exc:
                log.warning("contextual_prefix_v2_failed_fallback_v1", error=str(exc))

            # v1 fallback: ChunkObject 호환 래퍼
            from src.pipeline.models.document import ChunkObject, ChunkStrategy

            fake_chunks = [
                ChunkObject(
                    id=b.id,
                    document_id=b.document_id,
                    content=b.content,
                    chunk_index=b.block_index,
                    chunk_hash=b.block_hash,
                    token_count=b.token_count,
                    strategy=ChunkStrategy.SEMANTIC,
                    source_location=b.source_location,
                )
                for b in blocks
                if b.block_type != BlockType.SUMMARY
            ]
            try:
                enriched = await retriever.enrich(
                    chunks=fake_chunks,
                    document_text=document_text,
                    document_title=document_title,
                )
                enriched_map = {c.id: c.contextual_prefix for c in enriched}
                for block in blocks:
                    if block.id in enriched_map:
                        # D17-v5 §1 — KC 가 실제로 변경한 block 만 마커 부여
                        prev = block.contextual_prefix
                        new_prefix = enriched_map[block.id]
                        block.contextual_prefix = new_prefix
                        if (
                            new_prefix is not None
                            and new_prefix != prev
                            and isinstance(block.metadata, dict)
                        ):
                            block.metadata[_KC_OWNED_CTX_PREFIX_MARKER] = True
            except Exception as exc:
                log.warning("contextual_prefix_v1_failed", error=str(exc))

            log.info("contextual_prefix_applied", block_count=len(blocks))
        except ImportError:
            log.warning("contextual_retrieval_module_not_available")

        return blocks

    async def _apply_metadata_extraction(
        self,
        blocks: list[BlockObject],
    ) -> list[BlockObject]:
        """각 블럭에서 키워드·엔터티·주제를 추출한다."""
        try:
            from src.pipeline.enrichers.metadata_extractor import MetadataExtractor

            extractor = MetadataExtractor()

            # ChunkObject 호환 래퍼로 배치 추출
            from src.pipeline.models.document import ChunkObject, ChunkStrategy

            fake_chunks = [
                ChunkObject(
                    id=b.id,
                    document_id=b.document_id,
                    content=b.content,
                    chunk_index=b.block_index,
                    chunk_hash=b.block_hash,
                    token_count=b.token_count,
                    strategy=ChunkStrategy.SEMANTIC,
                    source_location=b.source_location,
                )
                for b in blocks
            ]
            try:
                enriched = await extractor.extract(fake_chunks)
                for block, chunk in zip(blocks, enriched):
                    block.extracted_metadata = chunk.extracted_metadata
            except Exception as exc:
                log.warning("metadata_extraction_failed", error=str(exc))

            log.info("metadata_extraction_applied", block_count=len(blocks))
        except (ImportError, AttributeError):
            log.warning("metadata_extractor_module_not_available")

        return blocks

    async def _generate_summary_block(
        self,
        blocks: list[BlockObject],
        document_text: str,
        document_title: str,
    ) -> BlockObject | None:
        """문서 전체 요약 블럭을 생성한다."""
        if self._llm_client is None:
            # LLM 없으면 간단한 통계 요약
            return self._generate_stats_summary(blocks, document_title)

        try:
            prompt = self._build_summary_prompt(blocks, document_text, document_title)
            summary_text = await self._call_llm(prompt)

            if not summary_text or len(summary_text.strip()) < 20:
                return self._generate_stats_summary(blocks, document_title)

            doc_id = blocks[0].document_id if blocks else uuid4()
            block = BlockObject(
                id=uuid4(),
                document_id=doc_id,
                block_type=BlockType.SUMMARY,
                content=summary_text.strip(),
                block_index=len(blocks),
                token_count=len(summary_text),
                source_location=SourceLocation(),
                metadata={"generated": True, "source": "llm_summary"},
            )
            block.compute_hash()
            return block

        except Exception as exc:
            log.warning("summary_generation_failed", error=str(exc))
            return self._generate_stats_summary(blocks, document_title)

    @staticmethod
    def _generate_stats_summary(
        blocks: list[BlockObject],
        document_title: str,
    ) -> BlockObject | None:
        """LLM 없이 통계 기반 문서 요약을 생성한다."""
        if not blocks:
            return None

        text_count = sum(1 for b in blocks if b.block_type == BlockType.PARAGRAPH)
        table_count = sum(1 for b in blocks if b.block_type == BlockType.TABLE)
        image_count = sum(1 for b in blocks if b.block_type == BlockType.IMAGE)
        total_tokens = sum(b.token_count for b in blocks)

        parts = [f"문서 '{document_title}'"]
        details: list[str] = []
        if text_count:
            details.append(f"텍스트 {text_count}개")
        if table_count:
            details.append(f"표 {table_count}개")
        if image_count:
            details.append(f"이미지 {image_count}개")
        parts.append(f"총 {len(blocks)}개 블럭 ({', '.join(details)})")
        parts.append(f"약 {total_tokens}자 분량")

        summary = " — ".join(parts) + "."

        doc_id = blocks[0].document_id
        block = BlockObject(
            id=uuid4(),
            document_id=doc_id,
            block_type=BlockType.SUMMARY,
            content=summary,
            block_index=len(blocks),
            token_count=len(summary),
            source_location=SourceLocation(),
            metadata={"generated": True, "source": "stats_summary"},
        )
        block.compute_hash()
        return block

    @staticmethod
    def _build_summary_prompt(
        blocks: list[BlockObject],
        document_text: str,
        document_title: str,
    ) -> str:
        """요약 생성용 프롬프트를 구성한다."""
        # 블럭 힌트 수집
        hints = []
        for b in blocks[:30]:  # 최대 30개 블럭 힌트
            hint = b.metadata.get("hint", "")
            if hint:
                hints.append(f"- [{b.block_type.value}] {hint}")

        hints_text = "\n".join(hints) if hints else "없음"

        return f"""다음 문서를 1~3문장으로 요약하세요.

## 문서 제목
{document_title}

## 블럭 목록 (힌트)
{hints_text}

## 문서 본문 (처음 5000자)
{document_text[:5000]}

## 요약 규칙
1. 문서의 주제와 목적을 명확히 서술하세요.
2. 주요 내용 키워드를 포함하세요.
3. 1~3문장으로 간결하게 작성하세요.
4. 요약 텍스트만 출력하세요.

요약:"""

    async def _call_llm(self, prompt: str) -> str:
        """LLM API 를 호출한다 (OpenAI 호환 / Anthropic / 제네릭)."""
        import re

        # OpenAI 호환 (vLLM, Qwen 등)
        try:
            from openai import AsyncOpenAI, OpenAI

            if isinstance(self._llm_client, AsyncOpenAI):
                response = await self._llm_client.chat.completions.create(
                    model=self.config.block_boundary_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=1200,  # table_analysis: table_nl 3~5문장 포함해 여유
                )
                text = response.choices[0].message.content or ""
                return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()

            if isinstance(self._llm_client, OpenAI):
                import asyncio

                response = await asyncio.to_thread(
                    self._llm_client.chat.completions.create,
                    model=self.config.block_boundary_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=500,
                )
                text = response.choices[0].message.content or ""
                return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
        except ImportError:
            pass


        # 제네릭
        if hasattr(self._llm_client, "generate"):
            return await self._llm_client.generate(prompt)  # type: ignore[union-attr]

        raise RuntimeError("LLM 클라이언트를 사용할 수 없습니다")
