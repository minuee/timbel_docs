"""파서 출력 모델 — specs/02 2.2 기준."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class HeadingInfo(BaseModel):
    """감지된 헤딩 정보."""

    level: int  # 1 = h1 (가장 큰 폰트), 2 = h2, ...
    text: str
    page: int
    char_offset: int


class TextBlock(BaseModel):
    """페이지 내 텍스트 블록 -- 원본 위치 추적의 최소 단위."""

    text: str
    start_char_offset: int
    end_char_offset: int
    bbox: Optional[list[float]] = None  # [x0, y0, x1, y1]
    paragraph_index: Optional[int] = None
    heading_level: Optional[int] = None  # None = 본문, 1 = h1, 2 = h2, ...


class TableContent(BaseModel):
    """추출된 표."""

    page_number: int
    table_index: int
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    markdown: str = ""
    confidence: float = 1.0
    bbox: Optional[list[float]] = None


class ImageContent(BaseModel):
    """추출된 이미지."""

    page_number: int
    image_index: int
    image_path: str
    ocr_text: Optional[str] = None
    description: Optional[str] = None
    bbox: Optional[list[float]] = None


class PageContent(BaseModel):
    """페이지별 구조화 콘텐츠."""

    page_number: int
    text: str = ""
    text_blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[TableContent] = Field(default_factory=list)
    images: list[ImageContent] = Field(default_factory=list)
    layout_type: str = "single"  # single / multi_column / mixed
    ocr_used: bool = False


class ParseResult(BaseModel):
    """파서 최종 출력."""

    raw_text: str = ""
    pages: list[PageContent] = Field(default_factory=list)
    tables: list[TableContent] = Field(default_factory=list)
    images: list[ImageContent] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    source_file_path: str = ""
    # LibreOffice 등으로 변환된 임시 PDF 경로. ConvertingParser 가 설정하며
    # block_worker 가 Vision 파이프라인 입력으로 재사용한 뒤 cleanup_temp() 로 제거한다.
    pdf_path: Optional[str] = None
    # 처리 완료 후 삭제해야 할 임시 파일/디렉토리 목록.
    temp_paths: list[str] = Field(default_factory=list)

    def cleanup_temp(self) -> None:
        """ConvertingParser 가 남긴 임시 변환본을 정리한다. 예외는 무시."""
        import os as _os
        import shutil as _shutil

        for path in list(self.temp_paths):
            try:
                if _os.path.isdir(path):
                    _shutil.rmtree(path, ignore_errors=True)
                elif _os.path.isfile(path):
                    _os.remove(path)
            except Exception:
                pass
        self.temp_paths.clear()
        self.pdf_path = None
