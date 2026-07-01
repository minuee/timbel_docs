"""Auto Metadata Extraction -- LLM 으로 청크에서 구조화된 메타데이터 자동 추출.

Phase 2 Task B-7 → v2 확장.

v1 추출 항목:
- keywords: list[str]  -- 핵심 키워드 3-5개
- entities: list[str]  -- 고유명사 (상품명, 법률명, 시스템명)
- topic: str           -- 주제 분류
- language: str        -- 언어 코드 (ko/en)

v2 추가 항목 (다층 키워드):
- query_keywords: list[str]  -- 사용자가 검색할 만한 질문형 표현
- synonyms: list[str]        -- 동의어/유의어 확장
- topic_tags: list[str]      -- 상위 주제 태그 (예: "제조", "재무")

v2.1: JSON 파싱 실패 복구 강화
- LLM 응답 전처리 (마크다운 펜스, 설명 텍스트 제거)
- 파싱 실패 시 1회 재시도 (교정 프롬프트)
- 부분 JSON 복구 (개별 객체 단위 파싱)
- 필수 필드 검증 및 기본값 채움
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from src.common.logging import get_logger
from src.pipeline.models.document import ChunkObject

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# v1 메타데이터 필수 필드 및 기본값
# ---------------------------------------------------------------------------
_V1_REQUIRED_FIELDS: dict[str, Any] = {
    "keywords": [],
    "entities": [],
    "topic": "",
    "language": "ko",
}

# v2 다층 키워드 필수 필드 및 기본값
_V2_REQUIRED_FIELDS: dict[str, Any] = {
    "query_keywords": [],
    "synonyms": [],
    "topic_tags": [],
}

# JSON 재시도 프롬프트
_RETRY_SYSTEM_PROMPT = (
    "앞선 응답이 유효한 JSON 형식이 아니었습니다. "
    "오직 JSON 배열만 반환하세요. 마크다운 펜스(```), 설명 텍스트, 주석 없이 "
    "순수한 JSON 배열만 출력하세요."
)

# RTX 5090 8K context + Guided JSON Decoding — 배치 5개로 출력 길이 단축, 신뢰도↑
_BATCH_SIZE = 5


def _build_batch_schema(n: int) -> dict[str, Any]:
    """배치 크기 n 에 맞춘 vLLM Guided Decoding용 JSON Schema.

    build_batch_metadata_prompt 가 실제로 요구하는 3필드(keywords/entities/topic)만
    포함하고, 배치 길이를 minItems/maxItems 로 강제한다.
    v2 필드(synonyms/topic_tags/query_keywords)는 MultilayerKeywordExtractor,
    search_summary 는 SearchSummaryGenerator 가 별도로 생성하므로 여기서는 제외.
    """
    return {
        "type": "array",
        "minItems": n,
        "maxItems": n,
        "items": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "entities": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "topic": {"type": "string"},
            },
            "required": ["keywords", "entities", "topic"],
        },
    }
# 배치 동시 실행 한도 (vLLM --max-num-seqs 4 와 매칭)
_BATCH_CONCURRENCY = 4
_MULTILAYER_CONCURRENCY = 4
_MIN_CONTENT_FOR_MULTILAYER = 50

METADATA_PROMPT = """다음 텍스트 청크들에서 메타데이터를 추출하세요.

각 청크에 대해 아래 JSON 형식으로 응답하세요:
{{
  "chunks": [
    {{
      "index": 0,
      "keywords": ["키워드1", "키워드2", "키워드3"],
      "entities": ["고유명사1", "고유명사2"],
      "topic": "주제 분류 (1-3단어)",
      "language": "ko 또는 en"
    }}
  ]
}}

규칙:
- keywords: 핵심 키워드 3-5개 (명사 위주)
- entities: 고유명사 (상품명, 법률명, 기관명, 시스템명 등). 없으면 빈 배열
- topic: 청크의 주제를 1-3단어로 분류
- language: 주요 언어 코드

청크 목록:
{chunks_text}

JSON 응답:"""

# ---------------------------------------------------------------------------
# v2: 다층 키워드 추출 프롬프트
# ---------------------------------------------------------------------------
MULTILAYER_KEYWORD_PROMPT = """다음 블럭 내용에서 다층 검색 키워드를 추출하세요.

## 블럭 내용
{content}

## 추출 항목

### 1. query_keywords (검색 질의형 표현)
- 사용자가 이 블럭을 찾기 위해 검색창에 입력할 만한 표현 3-5개
- 질문형("~는 어떻게?", "~란?") 또는 명령형("~ 방법", "~ 절차") 포함
- 실제 검색 행동을 반영한 자연스러운 표현

### 2. synonyms (동의어/유의어)
- 블럭에 등장하는 핵심 용어의 동의어/유의어 3-5개
- 영어 ↔ 한국어, 약어 ↔ 풀네임, 전문용어 ↔ 일상용어 포함
- 예: "ROI" → "투자수익률", "KPI" → "핵심성과지표"

### 3. topic_tags (상위 주제 태그)
- 이 블럭이 속하는 상위 주제 분류 1-3개
- 예: "제조", "재무", "인사관리", "품질관리", "영업", "IT인프라"
- 너무 세분화하지 말고 대분류 수준

## 출력 형식
JSON 객체만 반환. 다른 텍스트 없이.

```json
{{
  "query_keywords": ["검색 표현1", "검색 표현2"],
  "synonyms": ["동의어1", "동의어2"],
  "topic_tags": ["주제1", "주제2"]
}}
```"""


class MetadataExtractor:
    """LLM 으로 청크에서 구조화된 메타데이터를 자동 추출한다.

    배치 처리: 동일 문서의 청크를 5개씩 묶어 1회 LLM 호출 (비용 절감).
    추출된 메타데이터는 chunk.extracted_metadata 와 chunk.metadata 에 병합 저장.

    v2: extract_multilayer_keywords()로 추가 키워드 레이어 생성 가능.
    """

    async def extract(self, chunks: list[ChunkObject]) -> list[ChunkObject]:
        """청크 목록에서 메타데이터를 추출하여 부착한다.

        Parameters
        ----------
        chunks : list[ChunkObject]
            원본 청크 목록

        Returns
        -------
        list[ChunkObject]
            extracted_metadata 가 부착된 청크 목록
        """
        if not chunks:
            return chunks

        # 배치 분할
        batches: list[tuple[int, list[ChunkObject]]] = []
        for batch_start in range(0, len(chunks), _BATCH_SIZE):
            batch_end = min(batch_start + _BATCH_SIZE, len(chunks))
            batches.append((batch_start, chunks[batch_start:batch_end]))

        # 배치 동시 실행 (Semaphore 로 동시성 제한)
        sem = asyncio.Semaphore(_BATCH_CONCURRENCY)

        async def _run_one(batch_start: int, batch: list[ChunkObject]) -> tuple[int, list[dict[str, Any]] | Exception]:
            async with sem:
                try:
                    return batch_start, await self._extract_batch(batch)
                except Exception as exc:  # noqa: BLE001
                    return batch_start, exc

        results = await asyncio.gather(*[_run_one(s, b) for s, b in batches])

        success_count = 0
        fail_count = 0
        for batch_start, result in results:
            if isinstance(result, Exception):
                log.warning(
                    "metadata_extraction_batch_failed",
                    batch_start=batch_start,
                    error=str(result),
                )
                # 배치 크기는 실제 batches 에서 다시 조회
                bs = next((len(b) for s, b in batches if s == batch_start), 0)
                fail_count += bs
                continue
            for i, meta in enumerate(result):
                chunk_idx = batch_start + i
                if chunk_idx < len(chunks) and meta:
                    chunks[chunk_idx].extracted_metadata = meta
                    chunks[chunk_idx].metadata.update(meta)
                    success_count += 1

        log.info(
            "metadata_extraction_complete",
            total=len(chunks),
            batches=len(batches),
            batch_size=_BATCH_SIZE,
            concurrency=_BATCH_CONCURRENCY,
            success=success_count,
            failed=fail_count,
        )

        return chunks

    async def _extract_batch(
        self, batch: list[ChunkObject]
    ) -> list[dict[str, Any]]:
        """배치 단위로 LLM 메타데이터 추출을 수행한다.

        파싱 실패 시 교정 프롬프트로 1회 재시도한다.
        """
        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router

        # 청크 텍스트 구성
        chunks_text_parts: list[str] = []
        for i, chunk in enumerate(batch):
            # 청크 내용 앞 500자로 제한 (비용 절감)
            content = chunk.content[:500]
            chunks_text_parts.append(f"--- 청크 {i} ---\n{content}")

        chunks_text = "\n\n".join(chunks_text_parts)

        # 공식 프롬프트 사용 (prompts/metadata_extraction.py, v1.0.0)
        from src.pipeline.prompts.metadata_extraction import build_batch_metadata_prompt

        prompt = build_batch_metadata_prompt(chunks_text)
        batch_schema = _build_batch_schema(len(batch))

        request = LLMRequest(
            prompt=prompt,
            system_prompt=(
                "당신은 텍스트에서 메타데이터를 정확하게 추출하는 전문가입니다. "
                "반드시 유효한 JSON 형식으로만 응답하세요."
            ),
            max_tokens=1200,
            temperature=0.1,
            response_format="json",
            guided_json=batch_schema,
        )

        response = await llm_router.route(
            task=LLMTask.METADATA_EXTRACTION,
            request=request,
        )

        # 1차 파싱 시도
        results, parse_ok = self._parse_response_with_status(response.text, len(batch))

        if parse_ok:
            return results

        # ---------------------------------------------------------------
        # 파싱 실패 → 1회 재시도 (교정 프롬프트)
        # ---------------------------------------------------------------
        log.warning(
            "metadata_batch_retry",
            reason="json_parse_failed_on_first_attempt",
            batch_size=len(batch),
        )

        retry_request = LLMRequest(
            prompt=prompt,
            system_prompt=_RETRY_SYSTEM_PROMPT,
            max_tokens=1200,
            temperature=0.0,  # 재시도 시 더 결정적으로
            response_format="json",
            guided_json=batch_schema,
        )

        retry_response = await llm_router.route(
            task=LLMTask.METADATA_EXTRACTION,
            request=retry_request,
        )

        retry_results, retry_ok = self._parse_response_with_status(
            retry_response.text, len(batch),
        )

        if retry_ok:
            log.info("metadata_batch_retry_success", batch_size=len(batch))
        else:
            log.warning(
                "metadata_batch_retry_also_failed",
                batch_size=len(batch),
                parsed_count=sum(1 for r in retry_results if r),
            )

        return retry_results

    # ------------------------------------------------------------------
    # 응답 전처리
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_llm_response(raw: str) -> str:
        """LLM 응답에서 마크다운 펜스, 설명 텍스트 등을 제거하고 순수 JSON만 추출한다.

        Guided JSON으로 받은 valid한 응답은 정규식 처리 없이 그대로 반환 (정규식이 망가뜨리는 케이스 방지).
        """
        text = raw.strip()

        # 0) Fast path — valid JSON이면 그대로 반환 (Guided Decoding 응답 보존)
        try:
            import json as _json
            _json.loads(text)
            return text
        except Exception:
            pass

        # 1) <think>...</think> 블록 제거 (일부 모델)
        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)

        # 2) 마크다운 코드 펜스 제거 — ```json ... ``` 또는 ``` ... ```
        #    여러 번 감싸는 경우도 처리
        fence_pattern = re.compile(
            r"```(?:json|JSON)?\s*\n?(.*?)```", re.DOTALL,
        )
        match = fence_pattern.search(text)
        if match:
            text = match.group(1).strip()

        # 3) 남은 ``` 잔여물 제거
        text = text.replace("```json", "").replace("```JSON", "").replace("```", "").strip()

        # 4) JSON 앞뒤에 붙은 설명 텍스트 제거 — 첫 '[' 또는 '{'부터 마지막 ']' 또는 '}'까지 추출
        first_bracket = -1
        last_bracket = -1
        for i, ch in enumerate(text):
            if ch in ("[", "{"):
                first_bracket = i
                break
        for i in range(len(text) - 1, -1, -1):
            if text[i] in ("]", "}"):
                last_bracket = i
                break
        if first_bracket >= 0 and last_bracket > first_bracket:
            text = text[first_bracket : last_bracket + 1]

        # 5) 트레일링 쉼표 제거 (LLM이 가끔 마지막 요소 뒤에 쉼표를 붙임)
        text = re.sub(r",\s*([}\]])", r"\1", text)

        # 6) 작은따옴표를 큰따옴표로 변환 (속성명에 작은따옴표 사용 시)
        #    주의: 값 내부의 작은따옴표는 건드리지 않기 위해 속성명 패턴만 교체
        text = re.sub(r"(?<=[\[{,])\s*'([^']+)'\s*:", r' "\1":', text)

        return text

    # ------------------------------------------------------------------
    # 개별 메타데이터 객체 정규화 + 필수 필드 검증
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_v1_item(item: dict[str, Any]) -> dict[str, Any]:
        """단일 v1 메타데이터 객체를 정규화하고 필수 필드를 채운다."""
        # entities: structured list[dict] → flat list[str]
        entities = item.get("entities", [])
        if isinstance(entities, list):
            flat_entities: list[str] = []
            for ent in entities:
                if isinstance(ent, str):
                    flat_entities.append(ent)
                elif isinstance(ent, dict):
                    name = ent.get("name", "")
                    if name:
                        flat_entities.append(name)
            entities = flat_entities
        else:
            entities = []

        result: dict[str, Any] = {
            "keywords": item.get("keywords", []) if isinstance(item.get("keywords"), list) else [],
            "entities": entities,
            "topic": item.get("topic", "") if isinstance(item.get("topic"), str) else "",
            "language": item.get("language", "ko") if isinstance(item.get("language"), str) else "ko",
        }

        # v2 다층 키워드 필드가 함께 들어온 경우 병합
        for field, default in _V2_REQUIRED_FIELDS.items():
            val = item.get(field)
            if isinstance(val, list):
                result[field] = [str(v).strip() for v in val if isinstance(v, str) and v.strip()]
            elif val is not None:
                result[field] = default

        return result

    # ------------------------------------------------------------------
    # 부분 JSON 복구: 개별 객체 단위 파싱
    # ------------------------------------------------------------------
    @staticmethod
    def _try_partial_parse(text: str, expected_count: int) -> list[dict[str, Any]]:
        """전체 JSON 파싱이 실패했을 때, 개별 JSON 객체를 하나씩 추출한다.

        `{...}` 블록을 정규식으로 찾아 각각 파싱을 시도한다.
        """
        results: list[dict[str, Any]] = [{} for _ in range(expected_count)]
        # { 로 시작해서 대응하는 } 까지 — 중첩 괄호를 고려한 greedy 하지 않은 매칭
        obj_pattern = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)
        found = obj_pattern.findall(text)

        parsed_count = 0
        for raw_obj in found:
            try:
                # 트레일링 쉼표 제거
                cleaned = re.sub(r",\s*([}\]])", r"\1", raw_obj)
                item = json.loads(cleaned)
                if not isinstance(item, dict):
                    continue

                idx = item.get("index", parsed_count)
                if not isinstance(idx, int):
                    idx = parsed_count
                if 0 <= idx < expected_count:
                    results[idx] = MetadataExtractor._normalize_v1_item(item)
                    parsed_count += 1
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        if parsed_count > 0:
            log.info(
                "metadata_partial_parse_recovered",
                recovered=parsed_count,
                expected=expected_count,
            )

        return results

    # ------------------------------------------------------------------
    # 메인 파싱 (상태 반환 버전)
    # ------------------------------------------------------------------
    def _parse_response_with_status(
        self, response_text: str, expected_count: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """파싱 결과와 성공 여부(bool)를 함께 반환한다.

        Returns
        -------
        tuple[list[dict], bool]
            (결과 리스트, 전체 파싱 성공 여부)
        """
        results = self._parse_response(response_text, expected_count)
        # 최소 1개라도 비어있지 않은 결과가 있으면 부분 성공
        non_empty = sum(1 for r in results if r)
        fully_ok = non_empty == expected_count
        return results, fully_ok

    @staticmethod
    def _parse_response(response_text: str, expected_count: int) -> list[dict[str, Any]]:
        """LLM 응답을 파싱하여 메타데이터 딕셔너리 리스트를 반환한다.

        새 프롬프트 (build_batch_metadata_prompt) 형식: 배열 `[{...}, ...]`
        이전 형식 (dict with "chunks"): `{"chunks": [{"index": 0, ...}, ...]}`
        둘 다 지원 (하위 호환).

        파싱 전략:
        1) 응답 전처리 (_clean_llm_response)
        2) 전체 JSON 파싱 시도
        3) 실패 시 부분 파싱 (_try_partial_parse)
        4) 각 객체에 필수 필드 검증 (_normalize_v1_item)
        """
        results: list[dict[str, Any]] = [{} for _ in range(expected_count)]

        # 1) 전처리
        text = MetadataExtractor._clean_llm_response(response_text)

        # 2) 전체 JSON 파싱
        full_parse_ok = False
        try:
            data = json.loads(text)
            full_parse_ok = True

            # 새 형식: 직접 배열
            chunks_meta: list[Any]
            if isinstance(data, list):
                chunks_meta = data
            elif isinstance(data, dict):
                # 이전 형식: {"chunks": [...]}
                chunks_meta = data.get("chunks", [])
                if not isinstance(chunks_meta, list):
                    chunks_meta = []
            else:
                chunks_meta = []

            # 배열에 순서대로 매핑 (index가 있으면 사용, 없으면 순서대로)
            for i, item in enumerate(chunks_meta[:expected_count]):
                if not isinstance(item, dict):
                    continue
                idx = item.get("index", i)
                if not isinstance(idx, int):
                    idx = i
                if 0 <= idx < expected_count:
                    results[idx] = MetadataExtractor._normalize_v1_item(item)

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning("metadata_json_parse_failed", error=str(exc))

        # 3) 전체 파싱 실패 시 부분 복구 시도
        if not full_parse_ok:
            results = MetadataExtractor._try_partial_parse(text, expected_count)

        return results


class MultilayerKeywordExtractor:
    """다층 키워드 추출기 -- query_keywords, synonyms, topic_tags.

    기존 MetadataExtractor가 생성하는 keywords/entities/topic 외에,
    검색 품질을 높이기 위한 추가 키워드 레이어를 LLM으로 생성한다.

    추출 항목:
    - query_keywords: 사용자가 검색할 만한 질문형/명령형 표현
    - synonyms: 동의어/유의어 확장 (영↔한, 약어↔풀네임)
    - topic_tags: 상위 주제 태그 (대분류)

    결과는 block.extracted_metadata에 병합,
    block.metadata에도 동시 저장된다.
    """

    def __init__(self, llm_client: Any | None = None) -> None:
        self._llm_client = llm_client
        # D56 §E PR-E: Redis 기반 enricher cache.
        from src.pipeline.enrichers.cache import EnricherRedisCache
        from src.common.config import settings as _settings

        self._cache = EnricherRedisCache(
            name="metadata_extractor",
            schema_version="v2",  # v2 다층 키워드 스키마
            prompt_version="v2_1",
            prompt_text=MULTILAYER_KEYWORD_PROMPT,
            model_id=getattr(_settings, "VLLM_MODEL", "gemma-4-31b"),
            inference_params={"temperature": 0.1, "max_tokens": 800},
        )

    async def extract_all(self, blocks: list, force: bool = False) -> list:
        """모든 블럭에서 다층 키워드를 추출한다.

        Parameters
        ----------
        blocks : list[BlockObject]
            블럭 목록

        Returns
        -------
        list[BlockObject]
            query_keywords, synonyms, topic_tags가 부착된 블럭 목록
        """
        from src.pipeline.models.block import BlockType

        if not blocks:
            return blocks

        targets = [
            b for b in blocks
            if b.block_type not in (BlockType.SUMMARY, BlockType.DIVIDER, BlockType.TABLE_OF_CONTENTS)
            # force(수동 생성)면 길이 임계값을 우회한다. 자동 파이프라인은 기존 임계값 유지.
            and (force or len(b.content) >= _MIN_CONTENT_FOR_MULTILAYER)
        ]

        if not targets:
            return blocks

        success_count = 0
        fail_count = 0
        cache_hit = 0
        sem = asyncio.Semaphore(_MULTILAYER_CONCURRENCY)

        async def _extract_one(block: object) -> None:
            nonlocal success_count, fail_count, cache_hit

            cache_key = block.block_hash or block.compute_hash()
            cached = await self._cache.get(cache_key)
            if cached is not None and isinstance(cached, dict):
                self._apply_keywords(block, cached)
                cache_hit += 1
                return

            async with sem:
                try:
                    keywords_data = await self._extract_keywords(block.content)
                    if keywords_data:
                        self._apply_keywords(block, keywords_data)
                        await self._cache.set(cache_key, keywords_data)
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception as exc:
                    log.warning(
                        "multilayer_keyword_extraction_failed",
                        block_id=str(block.id),
                        error=str(exc),
                    )
                    fail_count += 1

        await asyncio.gather(*[_extract_one(b) for b in targets])

        log.info(
            "multilayer_keyword_extraction_complete",
            total=len(blocks),
            targets=len(targets),
            success=success_count,
            cache_hit=cache_hit,
            failed=fail_count,
        )

        return blocks

    @staticmethod
    def _apply_keywords(block: object, keywords_data: dict[str, Any]) -> None:
        """추출된 다층 키워드를 블럭에 적용한다."""
        # extracted_metadata에 병합
        if block.extracted_metadata is None:
            block.extracted_metadata = {}
        block.extracted_metadata.update(keywords_data)

        # metadata에도 병합
        block.metadata.update(keywords_data)

    async def _extract_keywords(self, content: str) -> dict[str, Any]:
        """단일 블럭에서 다층 키워드를 추출한다."""
        if self._llm_client is not None:
            return await self._call_llm(content)
        return await self._call_router(content)

    async def _call_llm(self, content: str) -> dict[str, Any]:
        """직접 주입된 LLM 클라이언트로 다층 키워드를 추출한다."""
        prompt = MULTILAYER_KEYWORD_PROMPT.format(content=content[:1000])

        # OpenAI 호환
        try:
            from openai import AsyncOpenAI, OpenAI

            if isinstance(self._llm_client, AsyncOpenAI):
                from src.common.config import settings

                model = getattr(settings, "VLLM_MODEL", "gemma-4-31b")
                response = await self._llm_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=400,
                )
                text = response.choices[0].message.content or ""
                text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
                return self._parse_keywords_response(text)

            if isinstance(self._llm_client, OpenAI):
                from src.common.config import settings

                model = getattr(settings, "VLLM_MODEL", "gemma-4-31b")
                response = await asyncio.to_thread(
                    self._llm_client.chat.completions.create,
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=400,
                )
                text = response.choices[0].message.content or ""
                text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
                return self._parse_keywords_response(text)
        except ImportError:
            pass

        # D40 Phase A — generic adapter (VLLMAdapter 등) 지원.
        # KC._call_llm 와 동일 패턴 — hasattr(client, "generate") 시 호출.
        # 이 fallback 이 없었기에 topic_tags 0% 회귀가 발생했다.
        if hasattr(self._llm_client, "generate"):
            text = await self._llm_client.generate(prompt)  # type: ignore[union-attr]
            text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
            return self._parse_keywords_response(text)

        raise RuntimeError("LLM 클라이언트를 사용할 수 없습니다")

    async def _call_router(self, content: str) -> dict[str, Any]:
        """LLM 라우터를 통해 다층 키워드를 추출한다."""
        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router

        prompt = MULTILAYER_KEYWORD_PROMPT.format(content=content[:1000])

        request = LLMRequest(
            prompt=prompt,
            system_prompt=(
                "당신은 검색 최적화 키워드 전문가입니다. "
                "반드시 유효한 JSON 형식으로만 응답하세요."
            ),
            max_tokens=400,
            temperature=0.2,
            response_format="json",
        )

        response = await llm_router.route(
            task=LLMTask.METADATA_EXTRACTION,
            request=request,
        )

        return self._parse_keywords_response(response.text)

    @staticmethod
    def _parse_keywords_response(raw: str) -> dict[str, Any]:
        """LLM 응답을 파싱하여 다층 키워드 딕셔너리를 반환한다."""
        # MetadataExtractor의 전처리 로직 재사용
        cleaned = MetadataExtractor._clean_llm_response(raw)

        try:
            data = json.loads(cleaned)
            if not isinstance(data, dict):
                return {}

            result: dict[str, Any] = {}

            # 필수 필드별 추출 + 기본값 보장
            for field, default in _V2_REQUIRED_FIELDS.items():
                val = data.get(field, default)
                if isinstance(val, list):
                    result[field] = [
                        str(v).strip() for v in val if isinstance(v, str) and v.strip()
                    ]
                else:
                    result[field] = default

            return result

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning("multilayer_keywords_parse_failed", error=str(exc))
            return {}
