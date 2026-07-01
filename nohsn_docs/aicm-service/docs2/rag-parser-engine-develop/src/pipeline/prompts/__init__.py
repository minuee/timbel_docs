"""AICM 문서 파이프라인 LLM 프롬프트 모듈.

블럭 인식, 분류, 메타데이터 추출에 사용되는 모든 프롬프트 빌더를 제공한다.
에이든(AIDEN) AI 비서 페르소나 프롬프트도 포함한다.
"""

from src.pipeline.prompts.aiden_persona import (
    build_cdc_extraction_prompt,
    build_cdc_unified_prompt,
    build_system_prompt,
    format_cdc_confirmation,
    format_search_results_for_chat,
)
from src.pipeline.prompts.block_segmentation import build_segmentation_prompt
from src.pipeline.prompts.caption_detection import build_caption_detection_prompt
from src.pipeline.prompts.document_structure import build_structure_analysis_prompt
from src.pipeline.prompts.metadata_extraction import build_metadata_prompt
from src.pipeline.prompts.parse_postprocessor import (
    build_column_reorder_prompt,
    build_noise_removal_prompt,
    build_word_break_fix_prompt,
)
from src.pipeline.prompts.table_semantic import build_table_analysis_prompt

__all__ = [
    "build_segmentation_prompt",
    "build_structure_analysis_prompt",
    "build_caption_detection_prompt",
    "build_table_analysis_prompt",
    "build_metadata_prompt",
    "build_noise_removal_prompt",
    "build_word_break_fix_prompt",
    "build_column_reorder_prompt",
    # AIDEN persona
    "build_system_prompt",
    "build_cdc_extraction_prompt",
    "build_cdc_unified_prompt",
    "format_search_results_for_chat",
    "format_cdc_confirmation",
]
