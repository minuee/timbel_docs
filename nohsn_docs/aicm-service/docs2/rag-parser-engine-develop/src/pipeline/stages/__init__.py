"""3단계 LLM 문서 처리 파이프라인.

Stage 1: DocumentUnderstanding — 문서 전체 이해 (첫 3페이지 Vision)
Stage 2: BlockSegmentation — 블럭 분할 (5페이지씩 배치)
Stage 3: BlockEnrichment — 블럭 보강 (table/image LLM + 키워드 추출)

LLMPipeline: 전체 오케스트레이터
"""

from src.pipeline.stages.llm_client import VisionLLMClient
from src.pipeline.stages.models import DocumentContext, PageData, RawBlock, StageResult
from src.pipeline.stages.pipeline import LLMPipeline
from src.pipeline.stages.stage1_understand import DocumentUnderstanding
from src.pipeline.stages.stage2_segment import BlockSegmentation
from src.pipeline.stages.stage3_enrich import BlockEnrichment

__all__ = [
    "BlockEnrichment",
    "BlockSegmentation",
    "DocumentContext",
    "DocumentUnderstanding",
    "LLMPipeline",
    "PageData",
    "RawBlock",
    "StageResult",
    "VisionLLMClient",
]
