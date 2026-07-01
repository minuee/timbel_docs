"""OCR 엔진 추상화 -- PaddleOCR PP-StructureV3 + 내부 vLLM Vision 폴백.

1차: PaddleOCR PP-StructureV3 (로컬 GPU). CUDA 차단 환경에선 자동 스킵.
2차: 내부 vLLM Vision (B200 gemma-4-31b). OpenAI-compat image_url 포맷.

네이밍 히스토리: 과거 "Claude Vision" 폴백으로 시작했으나 LLM 라우터가
단일 vLLM 으로 통합되면서 실제 호출은 내부 vLLM 만 간다. "claude_vision"
레거시 라벨을 "vlm_vision" 으로 교체했다 (2026-04-17).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Optional

from src.common.logging import get_logger

log = get_logger(__name__)

_OCR_CONFIDENCE_THRESHOLD = 0.7
_MIN_TEXT_LENGTH_FOR_ACCEPT = 50


@dataclass
class OCRResult:
    """OCR 추론 결과."""

    texts: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)  # Markdown 표 문자열
    confidence: float = 0.0
    has_content: bool = False
    engine_used: str = ""  # "paddleocr" / "vlm_vision"


class OCREngine:
    """2단계 OCR 전략.

    1차: PaddleOCR PP-StructureV3 (한국어 PP-OCRv5 모델, 로컬 GPU)
         - 텍스트 인식 + 표 구조 인식 + 레이아웃 분석 동시 수행
         - confidence >= 0.7 이면 결과 채택
         - 로컬 GPU 가 차단된 환경(CUDA_VISIBLE_DEVICES="") 에서는 자동 스킵
    2차 (fallback): 내부 vLLM Vision (B200 gemma-4-31b)
         - 1차 OCR confidence < 0.7 또는 텍스트 추출량 < 50자
         - 이미지를 base64 인코딩하여 OpenAI-compat image_url 포맷으로 전송
         - 표/도식/차트 포함 이미지는 구조적 설명 요청
    """

    def __init__(self) -> None:
        self._paddle_available: Optional[bool] = None
        self._paddle_pipeline: Optional[object] = None

    async def extract(self, image_bytes: bytes, media_type: str = "image/png") -> OCRResult:
        """이미지에서 텍스트와 표를 추출한다.

        Parameters
        ----------
        image_bytes : bytes
            이미지 바이트 데이터
        media_type : str
            이미지 MIME 타입

        Returns
        -------
        OCRResult
        """
        # 1차: PaddleOCR
        paddle_result = await self._try_paddleocr(image_bytes)
        if paddle_result and paddle_result.confidence >= _OCR_CONFIDENCE_THRESHOLD:
            total_text = " ".join(paddle_result.texts)
            if len(total_text) >= _MIN_TEXT_LENGTH_FOR_ACCEPT:
                log.info(
                    "ocr_paddleocr_accepted",
                    confidence=paddle_result.confidence,
                    text_count=len(paddle_result.texts),
                    table_count=len(paddle_result.tables),
                )
                return paddle_result

        # 2차: 내부 vLLM Vision fallback
        log.info(
            "ocr_fallback_to_vlm_vision",
            paddle_confidence=paddle_result.confidence if paddle_result else 0.0,
        )
        vision_result = await self._try_vlm_vision(image_bytes, media_type)
        return vision_result

    # ------------------------------------------------------------------
    # PaddleOCR
    # ------------------------------------------------------------------
    async def _try_paddleocr(self, image_bytes: bytes) -> Optional[OCRResult]:
        """PaddleOCR PP-StructureV3 로 OCR 을 시도한다."""
        if self._paddle_available is False:
            return None

        try:
            return await asyncio.to_thread(self._paddleocr_sync, image_bytes)
        except ImportError:
            self._paddle_available = False
            log.warning("paddleocr_not_installed")
            return None
        except Exception as exc:
            log.warning("paddleocr_failed", error=str(exc))
            return None

    def _paddleocr_sync(self, image_bytes: bytes) -> OCRResult:
        """PaddleOCR 동기 추론."""
        import io
        import re

        import numpy as np
        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img)

        if self._paddle_pipeline is None:
            self._paddle_pipeline = self._init_paddle()

        if self._paddle_pipeline is None:
            self._paddle_available = False
            return OCRResult(confidence=0.0, engine_used="paddleocr")

        results = list(self._paddle_pipeline.predict(img_array))  # type: ignore[union-attr]
        if not results:
            return OCRResult(confidence=0.0, engine_used="paddleocr")

        res = results[0]
        md = getattr(res, "markdown", None)
        if not isinstance(md, dict):
            return OCRResult(confidence=0.0, engine_used="paddleocr")

        markdown_text = md.get("markdown_texts", "")
        if not markdown_text:
            return OCRResult(confidence=0.0, engine_used="paddleocr")

        # 텍스트/표 분리
        texts, tables = self._parse_paddle_markdown(markdown_text)

        # 신뢰도 추정: 텍스트 길이 기반 휴리스틱
        total_len = sum(len(t) for t in texts) + sum(len(t) for t in tables)
        confidence = min(1.0, total_len / 200) if total_len > 0 else 0.0

        self._paddle_available = True

        return OCRResult(
            texts=texts,
            tables=tables,
            confidence=confidence,
            has_content=bool(texts or tables),
            engine_used="paddleocr",
        )

    # 모듈 레벨 캐시: paddlex 미설치 환경에서 매번 import 재시도/경고 방지
    _paddle_available: Optional[bool] = None  # None=미확인, True=사용 가능, False=영구 비활성
    _paddle_pipeline_cached: Optional[object] = None

    def _init_paddle(self) -> Optional[object]:
        """PaddleOCR 파이프라인을 초기화한다.

        - 첫 호출에서 import 시도, 결과를 클래스 변수에 캐시
        - 미설치 시 한 번만 INFO 로그, 이후 호출은 즉시 None 반환 (경고 스팸 방지)
        - 로컬 GPU 차단 환경(CUDA_VISIBLE_DEVICES 이 빈 문자열) 에선 바로 스킵 후 vLLM Vision 폴백
        """
        cls = type(self)
        if cls._paddle_available is False:
            return None
        if cls._paddle_available is True and cls._paddle_pipeline_cached is not None:
            return cls._paddle_pipeline_cached

        # B200 환경 체크 — 로컬 GPU 가 차단됐으면 PaddleOCR 시도조차 안 함
        cuda_env = os.environ.get("CUDA_VISIBLE_DEVICES")
        if cuda_env is not None and cuda_env.strip() == "":
            cls._paddle_available = False
            log.info(
                "paddleocr_skipped_no_local_gpu",
                reason="CUDA_VISIBLE_DEVICES is empty (B200 remote-only mode)",
                fallback="vlm_vision",
            )
            return None

        try:
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddlex import create_pipeline

            log.info("paddleocr_loading")
            pipeline = create_pipeline(pipeline="PP-StructureV3", device="gpu:0")
            log.info("paddleocr_loaded")
            cls._paddle_available = True
            cls._paddle_pipeline_cached = pipeline
            return pipeline
        except Exception as exc:
            # 한 번만 INFO 로 안내 — 본문 OCR 미사용 폴백으로 동작
            cls._paddle_available = False
            log.info(
                "paddleocr_unavailable_using_fallback",
                error=str(exc)[:120],
                fallback="vlm_vision",
            )
            return None

    @staticmethod
    def _parse_paddle_markdown(markdown_text: str) -> tuple[list[str], list[str]]:
        """PaddleOCR 마크다운 결과에서 텍스트와 표를 분리한다."""
        import re

        texts: list[str] = []
        tables: list[str] = []

        # <img> 태그 포함 시 순수 이미지 영역이므로 제외
        if "<img " in markdown_text or "<img/" in markdown_text:
            return texts, tables

        # HTML 표 패턴 감지
        html_table_pattern = re.compile(
            r"<div[^>]*>.*?<table[^>]*>(.*?)</table>.*?</div>",
            re.DOTALL | re.IGNORECASE,
        )

        last_end = 0
        for match in html_table_pattern.finditer(markdown_text):
            before_text = markdown_text[last_end : match.start()].strip()
            if before_text:
                cleaned = re.sub(r"^#+\s*", "", before_text, flags=re.MULTILINE).strip()
                if cleaned:
                    texts.append(cleaned)

            # HTML -> Markdown 표 변환
            table_html = match.group(0)
            try:
                import pandas as pd
                from io import StringIO

                dfs = pd.read_html(StringIO(table_html))
                if dfs:
                    df = dfs[0].fillna("").astype(str)
                    tables.append(df.to_markdown(index=False))
            except Exception:
                # 정규식 폴백
                rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE)
                md_rows: list[str] = []
                for i, row in enumerate(rows):
                    cells = re.findall(
                        r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE
                    )
                    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                    if cells:
                        md_rows.append("| " + " | ".join(cells) + " |")
                        if i == 0:
                            md_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
                if md_rows:
                    tables.append("\n".join(md_rows))

            last_end = match.end()

        after_text = markdown_text[last_end:].strip()
        if after_text:
            cleaned = re.sub(r"^#+\s*", "", after_text, flags=re.MULTILINE).strip()
            if cleaned:
                texts.append(cleaned)

        # Markdown 표 패턴도 별도 감지 (PaddleOCR가 직접 Markdown을 출력한 경우)
        if not tables:
            md_table_pattern = re.compile(
                r"(\|[^\n]+\|\n\|[\s\-:|]+\|\n(?:\|[^\n]+\|\n?)+)", re.MULTILINE
            )
            remaining = "\n".join(texts)
            md_matches = md_table_pattern.findall(remaining)
            if md_matches:
                for md_match in md_matches:
                    tables.append(md_match.strip())
                # 표 영역을 텍스트에서 제거
                cleaned_text = md_table_pattern.sub("", remaining).strip()
                texts = [cleaned_text] if cleaned_text else []

        return texts, tables

    # ------------------------------------------------------------------
    # 내부 vLLM Vision fallback (B200 gemma-4-31b)
    # ------------------------------------------------------------------
    async def _try_vlm_vision(
        self, image_bytes: bytes, media_type: str
    ) -> OCRResult:
        """내부 vLLM Vision 으로 이미지 텍스트를 추출한다.

        LLMRouter → QwenLLMClient.generate_vision → B200 vLLM gemma-4-31b
        (OpenAI-compat image_url base64 포맷).
        """
        try:
            from src.common.llm.base import LLMTask, LLMVisionRequest
            from src.common.llm.router import llm_router

            request = LLMVisionRequest(
                prompt=(
                    "이 이미지에서 모든 텍스트를 추출하세요. "
                    "표가 있으면 Markdown 표 형식으로 변환하세요. "
                    "텍스트 영역과 표 영역을 구분하여 출력하세요. "
                    "표는 반드시 '|||' 형태의 Markdown 표로 작성하세요."
                ),
                images=[image_bytes],
                max_tokens=2000,
            )

            response = await llm_router.route_vision(
                task=LLMTask.VISION_OCR,
                request=request,
            )

            # 응답에서 텍스트/표 분리
            texts, tables = self._parse_vision_response(response.text)

            return OCRResult(
                texts=texts,
                tables=tables,
                confidence=0.9,  # 내부 vLLM Vision 은 높은 신뢰도
                has_content=bool(texts or tables),
                engine_used="vlm_vision",
            )

        except Exception as exc:
            log.error("vlm_vision_failed", error=str(exc))
            return OCRResult(confidence=0.0, engine_used="vlm_vision")

    @staticmethod
    def _parse_vision_response(response_text: str) -> tuple[list[str], list[str]]:
        """vLLM Vision 응답에서 텍스트와 표를 분리한다."""
        import re

        texts: list[str] = []
        tables: list[str] = []

        # Markdown 표 패턴
        md_table_pattern = re.compile(
            r"(\|[^\n]+\|\n\|[\s\-:|]+\|\n(?:\|[^\n]+\|\n?)+)", re.MULTILINE
        )

        matches = md_table_pattern.findall(response_text)
        for match in matches:
            tables.append(match.strip())

        # 표를 제거한 나머지 텍스트
        remaining = md_table_pattern.sub("", response_text).strip()
        if remaining:
            # 빈 줄로 분리된 단락들
            paragraphs = [p.strip() for p in remaining.split("\n\n") if p.strip()]
            texts.extend(paragraphs)

        return texts, tables
