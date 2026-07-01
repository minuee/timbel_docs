"""PII (개인식별정보) 스캐너 서비스.

문서의 블럭 콘텐츠에서 주민등록번호, 전화번호, 이메일, 신용카드 번호,
계좌번호, 영문 이름+주소 등의 PII 패턴을 정규식으로 탐지한다.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.core.models.block import Block
from src.core.models.document import Document

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# PII 패턴 정의
# ---------------------------------------------------------------------------

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "주민등록번호": re.compile(
        r"\b(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))[-\s]?([1-4]\d{6})\b"
    ),
    "전화번호": re.compile(
        r"\b(0(?:1[0-9]|2|3[1-3]|4[1-4]|5[1-5]|6[1-4]))[-.\s]?"
        r"(\d{3,4})[-.\s]?(\d{4})\b"
    ),
    "이메일": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    ),
    "신용카드번호": re.compile(
        r"\b(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})\b"
    ),
    "계좌번호": re.compile(
        r"\b(\d{2,6})[-\s]?(\d{2,6})[-\s]?(\d{2,8})\b"
    ),
    "영문_이름": re.compile(
        r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
    ),
}

# 계좌번호는 오탐이 많으므로 최소 10자리 이상만 탐지
_MIN_ACCOUNT_DIGITS = 10


# ---------------------------------------------------------------------------
# 데이터 모델
# ---------------------------------------------------------------------------


class PIIMatch(BaseModel):
    """PII 탐지 결과."""

    match_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    block_id: uuid.UUID
    pattern_type: str = Field(description="탐지된 PII 유형")
    position: dict[str, int] = Field(description="시작/끝 위치 {'start': N, 'end': N}")
    sample: str = Field(description="마스킹된 샘플 (앞 2자 + *** + 뒤 2자)")
    resolved: bool = Field(default=False, description="오탐 처리 여부")
    resolved_action: str | None = Field(default=None, description="resolved 시 액션")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PIIScanResult(BaseModel):
    """PII 스캔 전체 결과."""

    document_id: uuid.UUID
    total_blocks_scanned: int
    total_matches: int
    matches: list[PIIMatch]
    scanned_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# 마스킹 헬퍼
# ---------------------------------------------------------------------------


def _mask_value(raw: str) -> str:
    """PII 값을 마스킹한다. 앞 2자 + *** + 뒤 2자."""
    if len(raw) <= 4:
        return raw[:1] + "***" + raw[-1:]
    return raw[:2] + "***" + raw[-2:]


# ---------------------------------------------------------------------------
# 스캐너
# ---------------------------------------------------------------------------


async def scan_document(
    document_id: uuid.UUID,
    db: AsyncSession,
) -> PIIScanResult:
    """문서의 모든 블럭을 스캔하여 PII 매칭 결과를 반환한다.

    Args:
        document_id: 스캔 대상 문서 ID
        db: 비동기 DB 세션

    Returns:
        PIIScanResult: 스캔 결과 (매칭 목록 포함)
    """
    # 문서 존재 확인
    doc_stmt = select(Document.id).where(Document.id == document_id)
    doc_result = await db.execute(doc_stmt)
    if doc_result.scalar_one_or_none() is None:
        from src.core.exceptions import DocumentNotFoundError

        raise DocumentNotFoundError(str(document_id))

    # 블럭 로드
    blocks_stmt = (
        select(Block)
        .where(Block.document_id == document_id)
        .order_by(Block.block_index)
    )
    result = await db.execute(blocks_stmt)
    blocks = list(result.scalars().all())

    all_matches: list[PIIMatch] = []

    for block in blocks:
        content = block.content or ""
        if not content.strip():
            continue

        for pattern_name, pattern in PII_PATTERNS.items():
            for m in pattern.finditer(content):
                raw = m.group(0)

                # 계좌번호 오탐 필터: 숫자만 추출하여 최소 자릿수 확인
                if pattern_name == "계좌번호":
                    digits_only = re.sub(r"[^0-9]", "", raw)
                    if len(digits_only) < _MIN_ACCOUNT_DIGITS:
                        continue

                all_matches.append(
                    PIIMatch(
                        block_id=block.id,
                        pattern_type=pattern_name,
                        position={"start": m.start(), "end": m.end()},
                        sample=_mask_value(raw),
                    )
                )

    logger.info(
        "pii_scan_completed",
        document_id=str(document_id),
        blocks_scanned=len(blocks),
        matches_found=len(all_matches),
    )

    return PIIScanResult(
        document_id=document_id,
        total_blocks_scanned=len(blocks),
        total_matches=len(all_matches),
        matches=all_matches,
    )
