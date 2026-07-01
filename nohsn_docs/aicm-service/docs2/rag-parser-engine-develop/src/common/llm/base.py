"""LLM 클라이언트 기본 인터페이스."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import Enum

from pydantic import BaseModel


class LLMTask(str, Enum):
    """LLM 작업 유형 — auto 모드에서 라우팅 결정에 사용."""

    RAG_GENERATION = "rag_generation"
    VISION_OCR = "vision_ocr"
    CONTEXTUAL_RETRIEVAL = "contextual_retrieval"
    METADATA_EXTRACTION = "metadata_extraction"
    TABLE_SUMMARY = "table_summary"
    BATCH_PROCESSING = "batch_processing"
    DOCUMENT_STRUCTURE = "document_structure"
    PARSE_NOISE_REMOVAL = "parse_noise_removal"
    PARSE_WORD_FIX = "parse_word_fix"
    PARSE_REORDER = "parse_reorder"
    CHAT_INTENT = "chat_intent"
    CDC_EXTRACTION = "cdc_extraction"
    SERIES_ANALYSIS = "series_analysis"
    TRANSITION_ANALYSIS = "transition_analysis"


class LLMRoutingMode(str, Enum):
    """LLM 라우팅 모드.

    VLLM (현재 표준): 모든 호출을 B200 Gemma 4 31B로 → 권장
    AUTO: Claude 우선, vLLM fallback (legacy)
    CLAUDE: Claude만 (legacy)
    QWEN: vLLM(Qwen 또는 Gemma)만 (legacy)
    """

    AUTO = "auto"
    CLAUDE = "claude"
    QWEN = "qwen"
    VLLM = "vllm"  # B200 Gemma 4 31B 전용 (신규 표준)
    GEMMA = "gemma"  # 별칭


class LLMRequest(BaseModel):
    """LLM 텍스트 생성 요청."""

    prompt: str
    system_prompt: str | None = None
    max_tokens: int = 1000
    temperature: float = 0.3
    response_format: str | None = None  # "json" for structured output
    guided_json: dict | None = None  # JSON Schema for vLLM guided decoding (outlines)


class LLMVisionRequest(BaseModel):
    """LLM 이미지 입력 기반 생성 요청."""

    prompt: str
    images: list[bytes]  # base64 decoded image bytes
    max_tokens: int = 1000


class LLMResponse(BaseModel):
    """LLM 응답."""

    text: str
    model: str
    usage: dict  # {"input_tokens": int, "output_tokens": int}
    latency_ms: int


class LLMStreamChunk(BaseModel):
    """LLM 스트리밍 응답 청크."""

    text: str
    model: str
    finish_reason: str | None = None


class BaseLLMClient(ABC):
    """LLM 클라이언트 인터페이스."""

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """텍스트 생성."""

    @abstractmethod
    async def generate_vision(self, request: LLMVisionRequest) -> LLMResponse:
        """이미지 입력 기반 생성 (OCR, 표 인식 등)."""

    @abstractmethod
    def generate_stream(
        self, request: LLMRequest
    ) -> AsyncIterator["LLMStreamChunk"]:
        """텍스트 스트리밍 생성. 토큰 단위 async iterator 반환."""
        # 구현체에서 async generator로 구현한다.
        # abstract + yield 패턴:
        yield  # type: ignore[misc]
