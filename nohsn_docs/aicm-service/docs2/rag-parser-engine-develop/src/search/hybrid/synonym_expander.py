"""동의어 사전 기반 질의 확장."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger

log = get_logger(__name__)

# 기본 동의어 사전 파일 경로
_DEFAULT_SYNONYM_PATH = Path(__file__).resolve().parents[3] / "data" / "synonyms" / "ko_synonyms.json"


class SynonymExpander:
    """
    동의어 사전 기반 질의 확장.

    사전 구조: {"대출": ["여신", "론", "loan"], "이자": ["금리", "이율"], ...}
    저장소: PostgreSQL (테넌트별 커스텀 동의어) + 기본 사전 (JSON 파일)

    확장 전략:
    1. 질의에서 명사 추출 (형태소 분석 결과의 키워드)
    2. 동의어 사전 lookup
    3. for_keyword에 동의어 추가 (OR 확장)
    4. for_dense/for_sparse는 원본 유지 (의미 검색은 동의어 불필요)
    """

    def __init__(
        self,
        default_dict_path: Path | str | None = None,
        db_session: AsyncSession | None = None,
    ) -> None:
        self._dict_path = Path(default_dict_path) if default_dict_path else _DEFAULT_SYNONYM_PATH
        self._db_session = db_session
        self._base_dict: dict[str, list[str]] | None = None
        self._tenant_cache: dict[UUID, dict[str, list[str]]] = {}

    def _load_base_dict(self) -> dict[str, list[str]]:
        """기본 동의어 사전 로드 (JSON 파일)."""
        if self._base_dict is not None:
            return self._base_dict
        try:
            with open(self._dict_path, encoding="utf-8") as f:
                raw = json.load(f)
            # 양방향 매핑 구축
            self._base_dict = self._build_bidirectional(raw)
            log.info("synonym_base_dict_loaded", entries=len(self._base_dict))
        except FileNotFoundError:
            log.warning("synonym_dict_not_found", path=str(self._dict_path))
            self._base_dict = {}
        except json.JSONDecodeError:
            log.warning("synonym_dict_parse_error", path=str(self._dict_path))
            self._base_dict = {}
        return self._base_dict

    @staticmethod
    def _build_bidirectional(raw: dict[str, list[str]]) -> dict[str, list[str]]:
        """단방향 사전을 양방향으로 확장."""
        result: dict[str, list[str]] = {}
        for key, synonyms in raw.items():
            all_terms = [key] + synonyms
            for term in all_terms:
                existing = result.get(term, [])
                for other in all_terms:
                    if other != term and other not in existing:
                        existing.append(other)
                result[term] = existing
        return result

    async def load_tenant_synonyms(self, tenant_id: UUID) -> dict[str, list[str]]:
        """테넌트별 커스텀 동의어를 DB에서 로드."""
        if tenant_id in self._tenant_cache:
            return self._tenant_cache[tenant_id]

        tenant_dict: dict[str, list[str]] = {}

        if self._db_session is not None:
            try:
                result = await self._db_session.execute(
                    text(
                        "SELECT term, synonyms FROM tenant_synonyms "
                        "WHERE tenant_id = :tenant_id AND is_active = true"
                    ),
                    {"tenant_id": str(tenant_id)},
                )
                rows = result.fetchall()
                for row in rows:
                    term = row[0]
                    syns = row[1] if isinstance(row[1], list) else []
                    tenant_dict[term] = syns
                # 양방향으로 확장
                tenant_dict = self._build_bidirectional(tenant_dict)
                log.info(
                    "tenant_synonyms_loaded",
                    tenant_id=str(tenant_id),
                    entries=len(tenant_dict),
                )
            except Exception:
                log.warning(
                    "tenant_synonyms_load_failed",
                    tenant_id=str(tenant_id),
                    exc_info=True,
                )

        self._tenant_cache[tenant_id] = tenant_dict
        return tenant_dict

    def invalidate_tenant_cache(self, tenant_id: UUID) -> None:
        """테넌트 동의어 캐시 무효화."""
        self._tenant_cache.pop(tenant_id, None)

    async def expand(
        self,
        keywords: list[str],
        tenant_id: UUID | None = None,
    ) -> list[str]:
        """
        키워드 리스트를 동의어로 확장.

        Args:
            keywords: 형태소 분석 후 추출된 키워드
            tenant_id: 테넌트별 동의어 사전 적용 (선택)

        Returns:
            원본 키워드 + 동의어가 합쳐진 확장 키워드 리스트
        """
        base_dict = self._load_base_dict()

        # 테넌트 사전 병합
        merged_dict = dict(base_dict)
        if tenant_id is not None:
            tenant_dict = await self.load_tenant_synonyms(tenant_id)
            for term, syns in tenant_dict.items():
                existing = merged_dict.get(term, [])
                for s in syns:
                    if s not in existing:
                        existing.append(s)
                merged_dict[term] = existing

        # 키워드 확장
        expanded: list[str] = list(keywords)
        added: set[str] = set(keywords)

        for kw in keywords:
            synonyms = merged_dict.get(kw, [])
            for syn in synonyms:
                if syn not in added:
                    expanded.append(syn)
                    added.add(syn)

        if len(expanded) > len(keywords):
            log.info(
                "synonym_expansion_applied",
                original=keywords,
                expanded_count=len(expanded) - len(keywords),
            )

        return expanded
