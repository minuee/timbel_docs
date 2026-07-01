"""Lint Worker — LLM-WIKI Lint 패턴 구현.

주기적으로 블럭을 스캔하여 정합성을 검사한다:
1. 중복 블럭 감지 (유사 content 해시)
2. 고아 블럭 감지 (문서 삭제 후 남은 블럭)
3. 비인덱스 블럭 감지 (벡터화 안 된 블럭)
4. LLM 시맨틱 린트 (모순, 누락, 품질 이슈) — 선택적

배치 스케줄로 실행하거나, API로 수동 트리거 가능.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.common.logging import get_logger

log = get_logger(__name__)


@dataclass
class LintIssue:
    """린트 검사에서 발견된 이슈."""

    issue_type: str  # duplicate, orphan, unindexed, contradiction, quality
    severity: str  # info, warning, error
    block_id: UUID | None = None
    block_ids: list[UUID] = field(default_factory=list)
    message: str = ""
    suggestion: str = ""


@dataclass
class LintReport:
    """린트 검사 결과 리포트."""

    repository_id: UUID
    total_blocks: int = 0
    issues: list[LintIssue] = field(default_factory=list)
    scanned_at: str = ""

    @property
    def issue_count(self) -> dict[str, int]:
        """이슈 타입별 개수."""
        counts: dict[str, int] = defaultdict(int)
        for issue in self.issues:
            counts[issue.issue_type] += 1
        return dict(counts)

    @property
    def has_errors(self) -> bool:
        """에러 수준 이슈 존재 여부."""
        return any(i.severity == "error" for i in self.issues)


class LintWorker:
    """블럭 정합성 검사 워커.

    정적 린트 (DB 쿼리 기반):
    - 중복 해시 감지
    - 고아 블럭 감지
    - 비인덱스 블럭 감지

    시맨틱 린트 (LLM 기반, 선택적):
    - 모순 감지
    - 품질 이슈
    """

    def __init__(self, llm_client: object | None = None) -> None:
        self._llm_client = llm_client

    async def lint_repository(
        self,
        repository_id: UUID,
        skip_llm: bool = False,
    ) -> LintReport:
        """저장소의 모든 블럭을 린트한다.

        Parameters
        ----------
        repository_id : UUID
            대상 저장소
        skip_llm : bool
            True면 정적 린트만 수행

        Returns
        -------
        LintReport
            검사 결과
        """
        from datetime import datetime

        report = LintReport(
            repository_id=repository_id,
            scanned_at=datetime.utcnow().isoformat(),
        )

        try:
            from sqlalchemy import func, select

            from src.core.database import async_session_factory
            from src.core.models.block import Block
            from src.core.models.document import Document

            async with async_session_factory() as session:
                # 전체 블럭 로드
                stmt = select(Block).where(Block.repository_id == repository_id)
                result = await session.execute(stmt)
                blocks = list(result.scalars().all())
                report.total_blocks = len(blocks)

                if not blocks:
                    return report

                # 1) 중복 해시 감지
                report.issues.extend(self._check_duplicates(blocks))

                # 2) 고아 블럭 감지
                orphans = await self._check_orphans(session, blocks)
                report.issues.extend(orphans)

                # 3) 비인덱스 블럭 감지
                report.issues.extend(self._check_unindexed(blocks))

                # 4) LLM 시맨틱 린트 (선택적)
                if not skip_llm and self._llm_client is not None:
                    semantic_issues = await self._semantic_lint(blocks)
                    report.issues.extend(semantic_issues)

        except ImportError:
            log.warning("database_not_available_lint_skipped")
        except Exception as exc:
            log.error("lint_failed", repository_id=str(repository_id), error=str(exc))

        log.info(
            "lint_complete",
            repository_id=str(repository_id),
            total_blocks=report.total_blocks,
            issues=report.issue_count,
        )
        return report

    @staticmethod
    def _check_duplicates(blocks: list[Any]) -> list[LintIssue]:
        """동일 block_hash를 가진 블럭 감지."""
        hash_map: dict[str, list[Any]] = defaultdict(list)
        for block in blocks:
            hash_map[block.block_hash].append(block)

        issues: list[LintIssue] = []
        for hash_val, dupes in hash_map.items():
            if len(dupes) > 1:
                issues.append(
                    LintIssue(
                        issue_type="duplicate",
                        severity="warning",
                        block_ids=[b.id for b in dupes],
                        message=f"동일 해시 블럭 {len(dupes)}개 발견 (hash: {hash_val[:16]}...)",
                        suggestion="중복 블럭 중 하나만 유지하고 나머지 삭제 권장",
                    )
                )
        return issues

    @staticmethod
    async def _check_orphans(session: Any, blocks: list[Any]) -> list[LintIssue]:
        """소속 문서가 삭제된 고아 블럭 감지."""
        from sqlalchemy import select

        from src.core.models.document import Document

        doc_ids = {b.document_id for b in blocks}
        if not doc_ids:
            return []

        stmt = select(Document.id).where(Document.id.in_(doc_ids))
        result = await session.execute(stmt)
        existing_ids = {row[0] for row in result.all()}

        orphan_doc_ids = doc_ids - existing_ids
        if not orphan_doc_ids:
            return []

        issues: list[LintIssue] = []
        for doc_id in orphan_doc_ids:
            orphan_blocks = [b for b in blocks if b.document_id == doc_id]
            issues.append(
                LintIssue(
                    issue_type="orphan",
                    severity="error",
                    block_ids=[b.id for b in orphan_blocks],
                    message=f"삭제된 문서({doc_id})에 속한 블럭 {len(orphan_blocks)}개",
                    suggestion="고아 블럭 삭제 또는 문서 복구 필요",
                )
            )
        return issues

    @staticmethod
    def _check_unindexed(blocks: list[Any]) -> list[LintIssue]:
        """벡터화되지 않은 블럭 감지."""
        unindexed = [b for b in blocks if not getattr(b, "is_indexed", False)]
        if not unindexed:
            return []

        return [
            LintIssue(
                issue_type="unindexed",
                severity="warning",
                block_ids=[b.id for b in unindexed],
                message=f"미인덱싱 블럭 {len(unindexed)}개 (검색 불가)",
                suggestion="블럭 재인덱싱 필요 (POST /blocks/{id}/re-index)",
            )
        ]

    async def _semantic_lint(self, blocks: list[Any]) -> list[LintIssue]:
        """LLM으로 블럭 내용의 시맨틱 이슈를 검사한다."""
        if self._llm_client is None:
            return []

        # 텍스트 블럭만 대상 (최대 30개)
        text_blocks = [
            b for b in blocks
            if b.block_type == "paragraph" and len(b.content) > 50
        ][:30]

        if not text_blocks:
            return []

        # 블럭 내용을 요약하여 LLM에 전달
        block_summaries = []
        for b in text_blocks:
            block_summaries.append(
                f"[Block {b.block_index}] {b.content[:200]}"
            )

        prompt = f"""다음은 하나의 저장소에 있는 블럭들입니다. 정합성 이슈를 찾아주세요.

블럭 목록:
{chr(10).join(block_summaries)}

찾아야 할 이슈:
1. 모순: 서로 다른 블럭이 상반된 정보를 담고 있는 경우
2. 품질: 내용이 불완전하거나 의미가 불분명한 블럭
3. 누락: 다른 블럭에서 참조하지만 설명이 없는 개념

JSON 배열로 출력. 이슈가 없으면 빈 배열 []:
[{{"type":"contradiction","blocks":[0,5],"message":"설명"}},
 {{"type":"quality","blocks":[3],"message":"설명"}}]"""

        try:
            import json
            import re

            raw = await self._call_llm(prompt)
            raw = re.sub(r"<think>.*?</think>\s*", "", raw, flags=re.DOTALL).strip()

            if "```" in raw:
                start = raw.find("[")
                end = raw.rfind("]")
                if start >= 0 and end > start:
                    raw = raw[start : end + 1]

            items = json.loads(raw)
            if not isinstance(items, list):
                return []

            issues: list[LintIssue] = []
            for item in items:
                issue_type = item.get("type", "quality")
                block_indices = item.get("blocks", [])
                message = item.get("message", "")

                # block_index → block_id 매핑
                block_ids = []
                for idx in block_indices:
                    if isinstance(idx, int) and idx < len(text_blocks):
                        block_ids.append(text_blocks[idx].id)

                issues.append(
                    LintIssue(
                        issue_type=issue_type,
                        severity="info",
                        block_ids=block_ids,
                        message=message,
                    )
                )

            return issues

        except Exception as exc:
            log.warning("semantic_lint_failed", error=str(exc))
            return []

    async def _call_llm(self, prompt: str) -> str:
        """LLM API 호출."""
        import re

        try:
            from openai import AsyncOpenAI, OpenAI

            if isinstance(self._llm_client, OpenAI):
                import asyncio

                resp = await asyncio.to_thread(
                    self._llm_client.chat.completions.create,
                    model="Qwen/Qwen3.5-27B",
                    messages=[
                        {"role": "system", "content": "JSON만 출력하세요."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=1000,
                )
                text = resp.choices[0].message.content or ""
                return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()

            if isinstance(self._llm_client, AsyncOpenAI):
                resp = await self._llm_client.chat.completions.create(
                    model="Qwen/Qwen3.5-27B",
                    messages=[
                        {"role": "system", "content": "JSON만 출력하세요."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=1000,
                )
                text = resp.choices[0].message.content or ""
                return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
        except ImportError:
            pass

        # D40 Phase A — VLLMAdapter 등 generic adapter 지원.
        if hasattr(self._llm_client, "generate"):
            text = await self._llm_client.generate(prompt)  # type: ignore[union-attr]
            return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()

        raise RuntimeError("LLM 클라이언트 사용 불가")
