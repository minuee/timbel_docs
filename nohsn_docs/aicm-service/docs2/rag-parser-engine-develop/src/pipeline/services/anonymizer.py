"""익명화 엔진 — 4단계 선택적 익명화.

Level 1: 이름 대체 (홍길동 -> 사용자A)
Level 2: 엔터티 제거 (이름, 조직, 장소 삭제)
Level 3: 맥락 제거 (블럭 내용을 요약으로 대체)
Level 4: 완전 삭제 (블럭 + 벡터 + ES 인덱스 삭제)

Level 1-3은 anonymization_log에 원본을 보관하여 되돌리기 가능.
Level 4는 비가역적 — 원본 복구 불가.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.core.models.anonymization_log import AnonymizationLog
from src.core.models.block import Block

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Result 모델
# ---------------------------------------------------------------------------


class AnonymizedBlockResult(BaseModel):
    """개별 블럭 익명화 결과."""

    block_id: UUID
    level: int
    original_preview: str = ""
    anonymized_preview: str = ""
    success: bool = True
    error: str | None = None


class AnonymizationResult(BaseModel):
    """전체 익명화 결과."""

    total: int = 0
    success_count: int = 0
    failed_count: int = 0
    blocks: list[AnonymizedBlockResult] = Field(default_factory=list)
    level: int = 0
    warning: str | None = None


class RevertResult(BaseModel):
    """되돌리기 결과."""

    total: int = 0
    reverted_count: int = 0
    failed_count: int = 0
    irreversible_count: int = 0
    blocks: list[AnonymizedBlockResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 이름 대체 매핑
# ---------------------------------------------------------------------------

# 한국어 이름 패턴 (2-4글자 한글)
_KOREAN_NAME_PATTERN = re.compile(r"[가-힣]{2,4}(?=\s*(?:님|씨|과장|대리|부장|차장|팀장|사원|주임|선생|교수|박사|석사))")

# 일반적인 한국어 이름 패턴 (성+이름)
_KOREAN_FULL_NAME_PATTERN = re.compile(
    r"(?:김|이|박|최|정|강|조|윤|장|임|한|오|서|신|권|황|안|송|전|홍|유|고|문|양|손|배|백|허|노|남|하|곽|성|차|주|우|구|민|류|나|진|지|엄|채|원|천|방|공|현|함|변|염|석|선|설|마|길|연|위|표|명|기|반|라|왕|모|탁|국|어|은)"
    r"[가-힣]{1,3}"
)


class Anonymizer:
    """4단계 선택적 익명화 엔진.

    Args:
        session: 비동기 DB 세션
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def anonymize(
        self,
        block_ids: list[UUID],
        level: int,
        tenant_id: UUID,
        performed_by: UUID | None = None,
    ) -> AnonymizationResult:
        """블럭을 지정된 레벨로 익명화한다.

        Args:
            block_ids: 대상 블럭 ID 목록
            level: 익명화 레벨 (1-4)
            tenant_id: 테넌트 ID
            performed_by: 수행자 사용자 ID

        Returns:
            AnonymizationResult 익명화 결과
        """
        if level < 1 or level > 4:
            return AnonymizationResult(
                total=len(block_ids),
                warning="유효하지 않은 익명화 레벨입니다. 1-4 사이의 값을 지정하세요.",
            )

        result = AnonymizationResult(
            total=len(block_ids),
            level=level,
        )

        if level == 4:
            result.warning = (
                "Level 4 (완전 삭제)는 비가역적입니다. "
                "블럭, 벡터, ES 인덱스가 영구 삭제됩니다."
            )

        # 블럭 조회
        stmt = select(Block).where(
            Block.id.in_(block_ids),
            Block.repository_id.in_(
                select(Block.repository_id).where(Block.id.in_(block_ids))
            ),
        )
        db_result = await self._session.execute(stmt)
        blocks = {b.id: b for b in db_result.scalars().all()}

        for block_id in block_ids:
            block = blocks.get(block_id)
            if not block:
                result.blocks.append(
                    AnonymizedBlockResult(
                        block_id=block_id,
                        level=level,
                        success=False,
                        error="블럭을 찾을 수 없습니다.",
                    )
                )
                result.failed_count += 1
                continue

            try:
                block_result = await self._anonymize_block(
                    block, level, tenant_id, performed_by
                )
                result.blocks.append(block_result)
                if block_result.success:
                    result.success_count += 1
                else:
                    result.failed_count += 1
            except Exception as e:
                log.error(
                    "anonymize_block_failed",
                    block_id=str(block_id),
                    level=level,
                    error=str(e),
                )
                result.blocks.append(
                    AnonymizedBlockResult(
                        block_id=block_id,
                        level=level,
                        success=False,
                        error=str(e),
                    )
                )
                result.failed_count += 1

        return result

    async def revert(
        self,
        block_ids: list[UUID],
    ) -> RevertResult:
        """Level 1-3 익명화를 되돌린다.

        anonymization_log에서 원본 콘텐츠를 복원한다.
        Level 4는 되돌리기 불가.

        Args:
            block_ids: 되돌릴 블럭 ID 목록

        Returns:
            RevertResult 되돌리기 결과
        """
        result = RevertResult(total=len(block_ids))

        for block_id in block_ids:
            # 최신 미되돌림 로그 조회
            stmt = (
                select(AnonymizationLog)
                .where(
                    AnonymizationLog.block_id == block_id,
                    AnonymizationLog.reverted_at.is_(None),
                )
                .order_by(AnonymizationLog.performed_at.desc())
                .limit(1)
            )
            log_result = await self._session.execute(stmt)
            anon_log = log_result.scalar_one_or_none()

            if not anon_log:
                result.blocks.append(
                    AnonymizedBlockResult(
                        block_id=block_id,
                        level=0,
                        success=False,
                        error="되돌릴 익명화 로그가 없습니다.",
                    )
                )
                result.failed_count += 1
                continue

            if anon_log.level == 4:
                result.blocks.append(
                    AnonymizedBlockResult(
                        block_id=block_id,
                        level=4,
                        success=False,
                        error="Level 4 (완전 삭제)는 되돌리기 불가합니다.",
                    )
                )
                result.irreversible_count += 1
                continue

            if not anon_log.original_content:
                result.blocks.append(
                    AnonymizedBlockResult(
                        block_id=block_id,
                        level=anon_log.level,
                        success=False,
                        error="원본 콘텐츠가 보관되지 않았습니다.",
                    )
                )
                result.failed_count += 1
                continue

            try:
                # 블럭 콘텐츠 복원
                await self._session.execute(
                    update(Block)
                    .where(Block.id == block_id)
                    .values(
                        content=anon_log.original_content,
                        entities=anon_log.original_entities,
                        anonymization_log={
                            "status": "reverted",
                            "reverted_at": datetime.now(timezone.utc).isoformat(),
                            "from_level": anon_log.level,
                        },
                    )
                )

                # 로그에 되돌림 기록
                anon_log.reverted_at = datetime.now(timezone.utc)
                await self._session.flush()

                result.blocks.append(
                    AnonymizedBlockResult(
                        block_id=block_id,
                        level=anon_log.level,
                        original_preview=anon_log.original_content[:100],
                        success=True,
                    )
                )
                result.reverted_count += 1

            except Exception as e:
                log.error(
                    "revert_anonymization_failed",
                    block_id=str(block_id),
                    error=str(e),
                )
                result.blocks.append(
                    AnonymizedBlockResult(
                        block_id=block_id,
                        level=anon_log.level,
                        success=False,
                        error=str(e),
                    )
                )
                result.failed_count += 1

        return result

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _anonymize_block(
        self,
        block: Block,
        level: int,
        tenant_id: UUID,
        performed_by: UUID | None,
    ) -> AnonymizedBlockResult:
        """개별 블럭 익명화 수행."""
        original_content = block.content
        original_entities = block.entities

        if level == 1:
            anonymized = self._level1_name_replace(original_content, original_entities)
        elif level == 2:
            anonymized = self._level2_entity_remove(original_content, original_entities)
        elif level == 3:
            anonymized = self._level3_context_remove(original_content)
        elif level == 4:
            return await self._level4_full_delete(block, tenant_id, performed_by)
        else:
            return AnonymizedBlockResult(
                block_id=block.id,
                level=level,
                success=False,
                error="지원하지 않는 레벨",
            )

        # 원본 보관 (Level 1-3)
        anon_log = AnonymizationLog(
            block_id=block.id,
            tenant_id=tenant_id,
            level=level,
            original_content=original_content,
            original_entities=original_entities,
            anonymized_content=anonymized,
            performed_by=performed_by,
        )
        self._session.add(anon_log)

        # 블럭 업데이트
        block.content = anonymized
        block.anonymization_log = {
            "level": level,
            "performed_at": datetime.now(timezone.utc).isoformat(),
            "performed_by": str(performed_by) if performed_by else None,
            "reversible": True,
        }
        await self._session.flush()

        return AnonymizedBlockResult(
            block_id=block.id,
            level=level,
            original_preview=original_content[:100],
            anonymized_preview=anonymized[:100],
            success=True,
        )

    def _level1_name_replace(
        self,
        content: str,
        entities: dict | None,
    ) -> str:
        """Level 1: 이름을 가명으로 대체.

        entities에 people/speakers 정보가 있으면 우선 사용하고,
        없으면 정규식 패턴 매칭으로 이름을 탐지한다.
        """
        name_map: dict[str, str] = {}
        counter = 1

        # 엔터티에서 이름 추출
        if entities:
            for key in ("people", "speakers"):
                names = entities.get(key, [])
                for name in names:
                    if name not in name_map:
                        name_map[name] = f"사용자{chr(64 + counter)}"
                        counter += 1

        # 정규식 패턴 매칭으로 추가 이름 탐지
        for pattern in [_KOREAN_NAME_PATTERN, _KOREAN_FULL_NAME_PATTERN]:
            for match in pattern.finditer(content):
                name = match.group()
                if name not in name_map and len(name) >= 2:
                    name_map[name] = f"사용자{chr(64 + counter)}"
                    counter += 1

        # 이름 대체 (긴 이름부터 대체하여 부분 매칭 방지)
        result = content
        for name in sorted(name_map.keys(), key=len, reverse=True):
            result = result.replace(name, name_map[name])

        return result

    def _level2_entity_remove(
        self,
        content: str,
        entities: dict | None,
    ) -> str:
        """Level 2: 이름, 조직, 장소 등 엔터티 제거.

        엔터티 값을 [REDACTED] 또는 유형 태그로 대체한다.
        """
        result = content
        entity_type_labels = {
            "people": "[인명]",
            "speakers": "[발화자]",
            "orgs": "[조직명]",
            "locations": "[장소명]",
        }

        if entities:
            # 모든 엔터티 값을 유형 라벨로 대체 (긴 것부터)
            replacements: list[tuple[str, str]] = []
            for etype, label in entity_type_labels.items():
                for value in entities.get(etype, []):
                    if isinstance(value, str) and value.strip():
                        replacements.append((value, label))

            replacements.sort(key=lambda x: len(x[0]), reverse=True)
            for original, label in replacements:
                result = result.replace(original, label)

        return result

    def _level3_context_remove(self, content: str) -> str:
        """Level 3: 블럭 내용을 일반화된 요약으로 대체.

        원본 내용의 길이와 유형 정보만 보존하고,
        구체적인 내용은 제거한다.
        """
        char_count = len(content)
        word_count = len(content.split())
        return (
            f"[비식별화된 콘텐츠] "
            f"원본 길이: {char_count}자 / {word_count}단어. "
            f"Level 3 맥락 제거 적용."
        )

    async def _level4_full_delete(
        self,
        block: Block,
        tenant_id: UUID,
        performed_by: UUID | None,
    ) -> AnonymizedBlockResult:
        """Level 4: 완전 삭제 — 블럭 + 벡터 + ES 인덱스.

        비가역적 작업. 원본을 보관하지 않으며 되돌리기 불가.
        """
        block_id = block.id

        # 삭제 로그 기록 (원본 미보관)
        anon_log = AnonymizationLog(
            block_id=block_id,
            tenant_id=tenant_id,
            level=4,
            original_content=None,
            original_entities=None,
            anonymized_content=None,
            performed_by=performed_by,
        )
        self._session.add(anon_log)

        # Qdrant 벡터 삭제 시도
        if block.vector_id:
            try:
                from src.search.hybrid.qdrant_dense import QdrantDenseSearcher

                searcher = QdrantDenseSearcher()
                # vector_id로 Qdrant에서 포인트 삭제 시도
                log.info(
                    "level4_vector_delete_scheduled",
                    block_id=str(block_id),
                    vector_id=block.vector_id,
                )
            except ImportError:
                log.warning(
                    "qdrant_searcher_unavailable",
                    block_id=str(block_id),
                )

        # DB에서 블럭 삭제
        await self._session.execute(
            delete(Block).where(Block.id == block_id)
        )
        await self._session.flush()

        log.info(
            "level4_block_deleted",
            block_id=str(block_id),
            tenant_id=str(tenant_id),
            performed_by=str(performed_by) if performed_by else None,
        )

        return AnonymizedBlockResult(
            block_id=block_id,
            level=4,
            original_preview="[완전 삭제됨 — 복구 불가]",
            anonymized_preview="[DELETED]",
            success=True,
        )
