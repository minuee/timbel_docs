"""카테고리 CRUD 서비스 (다단계 계층 구조 지원)."""

from __future__ import annotations

import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.common.logging import get_logger
from src.core.exceptions import (
    CategoryCircularReferenceError,
    CategoryNotFoundError,
    DuplicateNameError,
    RepositoryNotFoundError,
)
from src.core.models.category import Category
from src.core.models.repository import Repository

logger = get_logger(__name__)


class CategoryService:
    """카테고리 CRUD + 계층 트리 서비스."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _update_category_embedding(self, category: Category) -> None:
        """카테고리 설명+동의어로 BGE-M3 임베딩을 생성한다 (Phase A-4).

        BGE-M3 가 사용 불가능하면 graceful skip.
        """
        text_parts: list[str] = []
        if category.name:
            text_parts.append(category.name)
        if hasattr(category, "description") and category.description:
            text_parts.append(category.description)
        if hasattr(category, "synonyms") and category.synonyms:
            text_parts.extend(category.synonyms)

        if not text_parts:
            return

        embedding_text = " ".join(text_parts)

        try:
            from src.pipeline.embedders.bge_m3 import BGEM3Embedder

            embedder = BGEM3Embedder()
            # [수정 2026-06-10] BGEM3Embedder엔 embed()가 없어 매번 AttributeError로
            # graceful skip돼 카테고리 임베딩이 항상 실패했음. 실제 단건 API는 embed_single.
            result = await embedder.embed_single(embedding_text)
            # Store first 20 dims as preview in metadata; full vector in Qdrant
            if not hasattr(category, "meta_info") or category.meta_info is None:
                category.meta_info = {}  # type: ignore[assignment]
            category.meta_info["embedding_preview"] = result.dense[:20]  # type: ignore[index]
            logger.info(
                "category_embedding_generated",
                category_id=str(category.id),
                text_length=len(embedding_text),
            )
        except Exception as exc:
            logger.warning("category_embedding_failed", error=str(exc))

    async def _validate_repository(
        self,
        repository_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Repository:
        """저장소 존재 및 테넌트 소속 검증."""
        stmt = select(Repository).where(
            Repository.id == repository_id,
            Repository.tenant_id == tenant_id,
        )
        result = await self.db.execute(stmt)
        repo = result.scalar_one_or_none()
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))
        return repo

    async def _check_circular_reference(
        self,
        category_id: uuid.UUID,
        new_parent_id: uuid.UUID,
    ) -> None:
        """순환 참조 검사. new_parent_id의 조상 중에 category_id가 있으면 예외."""
        current_id: uuid.UUID | None = new_parent_id
        visited: set[uuid.UUID] = set()

        while current_id is not None:
            if current_id == category_id:
                raise CategoryCircularReferenceError(str(category_id))
            if current_id in visited:
                break
            visited.add(current_id)

            stmt = select(Category.parent_id).where(Category.id == current_id)
            result = await self.db.execute(stmt)
            row = result.one_or_none()
            current_id = row[0] if row else None

    async def create(
        self,
        *,
        repository_id: uuid.UUID,
        tenant_id: uuid.UUID,
        name: str,
        description: str | None = None,
        parent_id: uuid.UUID | None = None,
        sort_order: int = 0,
        icon: str | None = None,
    ) -> Category:
        """새 카테고리를 생성한다.

        Args:
            repository_id: 소속 저장소 ID
            tenant_id: 테넌트 ID (저장소 소속 검증용)
            name: 카테고리 이름
            description: 카테고리 설명
            parent_id: 상위 카테고리 ID (선택)
            sort_order: 정렬 순서

        Returns:
            생성된 Category 객체

        Raises:
            RepositoryNotFoundError: 저장소가 존재하지 않을 때
            DuplicateNameError: 동일 저장소/부모 하위에 같은 이름이 존재할 때
        """
        await self._validate_repository(repository_id, tenant_id)

        # 부모 카테고리 존재 검증
        if parent_id is not None:
            await self.get_by_id(parent_id, repository_id=repository_id)

        category = Category(
            repository_id=repository_id,
            name=name,
            description=description,
            parent_id=parent_id,
            sort_order=sort_order,
            icon=icon,
        )
        self.db.add(category)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise DuplicateNameError("category", name)

        # Phase A-4: 카테고리 임베딩 자동 생성
        await self._update_category_embedding(category)

        logger.info("category_created", category_id=str(category.id), name=name)
        return category

    async def get_by_id(
        self,
        category_id: uuid.UUID,
        *,
        repository_id: uuid.UUID | None = None,
    ) -> Category:
        """ID로 카테고리를 조회한다.

        Raises:
            CategoryNotFoundError: 카테고리가 존재하지 않을 때
        """
        stmt = select(Category).where(Category.id == category_id)
        if repository_id is not None:
            stmt = stmt.where(Category.repository_id == repository_id)
        result = await self.db.execute(stmt)
        category = result.scalar_one_or_none()
        if category is None:
            raise CategoryNotFoundError(str(category_id))
        return category

    async def get_with_subtree(
        self,
        category_id: uuid.UUID,
        *,
        repository_id: uuid.UUID | None = None,
    ) -> Category:
        """활성 서브트리(children, 재귀)를 eager-load 한 카테고리를 반환한다.

        [수정 2026-06-10] 단일 카테고리 응답(get/create/update)의 재귀 직렬화용.
        이슈: 핸들러가 db.refresh(["children"]) 로 1레벨만 적재 → CategoryResponse 재귀
              직렬화 중 손자를 async 밖에서 lazy-load → MissingGreenlet → 500.
        수정: 전체 하위를 selectinload(recursion_depth=-1) 로 미리 적재(=lazy 제거).
              동시에 and_(is_active=True) 로 soft-delete 된 하위는 제외.
        """
        stmt = select(Category).where(Category.id == category_id)
        if repository_id is not None:
            stmt = stmt.where(Category.repository_id == repository_id)
        stmt = stmt.options(
            selectinload(
                Category.children.and_(Category.is_active.is_(True)),
                recursion_depth=-1,
            )
        )
        result = await self.db.execute(stmt)
        category = result.scalar_one_or_none()
        if category is None:
            raise CategoryNotFoundError(str(category_id))
        return category

    async def list_by_repository(
        self,
        repository_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
        include_inactive: bool = False,
    ) -> list[Category]:
        """저장소의 카테고리 목록을 조회한다. parent_id로 특정 레벨만 조회 가능.

        Args:
            repository_id: 저장소 ID
            tenant_id: 테넌트 ID (저장소 소속 검증용)
            parent_id: 상위 카테고리 ID (None이면 루트 카테고리만)
            include_inactive: 비활성 카테고리 포함 여부
        """
        await self._validate_repository(repository_id, tenant_id)

        # [수정 2026-06-10] children 에 is_active 필터를 적용한다.
        # 이슈: soft-delete(is_active=False) 된 자식이 selectinload 로 그대로 적재되어
        #       이 메서드를 쓰는 GET /repositories/{repo}/categories 응답에 누출됨.
        # 원인: 루트 레벨만 is_active 필터하고 children 로더에는 필터가 없었음.
        # 수정: relationship.and_() 로 children(및 재귀 하위)도 is_active=True 만 적재.
        stmt = (
            select(Category)
            .options(
                selectinload(
                    Category.children.and_(Category.is_active.is_(True)),
                    recursion_depth=-1,
                )
            )
            .where(Category.repository_id == repository_id)
            .order_by(Category.sort_order, Category.name)
        )

        if parent_id is not None:
            stmt = stmt.where(Category.parent_id == parent_id)
        else:
            stmt = stmt.where(Category.parent_id.is_(None))

        if not include_inactive:
            stmt = stmt.where(Category.is_active.is_(True))

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_tree(
        self,
        repository_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
    ) -> list[dict]:
        """저장소의 전체 카테고리 트리를 반환한다.

        Returns:
            트리 구조의 딕셔너리 리스트. 각 항목에 children 키가 포함된다.
        """
        await self._validate_repository(repository_id, tenant_id)

        stmt = (
            select(Category)
            .where(
                Category.repository_id == repository_id,
                Category.is_active.is_(True),
            )
            .order_by(Category.sort_order, Category.name)
        )
        result = await self.db.execute(stmt)
        categories = list(result.scalars().all())

        # 트리 구성
        by_id: dict[uuid.UUID, dict] = {}
        id_to_parent: dict[uuid.UUID, uuid.UUID | None] = {}
        id_to_name: dict[uuid.UUID, str] = {}
        roots: list[dict] = []

        for cat in categories:
            node = {
                "id": cat.id,
                "name": cat.name,
                "description": cat.description,
                "parent_id": cat.parent_id,
                "sort_order": cat.sort_order,
                "icon": cat.icon,
                "children": [],
                "path": [],
            }
            by_id[cat.id] = node
            id_to_parent[cat.id] = cat.parent_id
            id_to_name[cat.id] = cat.name

        # 각 노드의 조상 경로를 루트부터 현재 노드 이름 순으로 계산
        for cat in categories:
            path_parts: list[str] = []
            current_id: uuid.UUID | None = cat.id
            visited: set[uuid.UUID] = set()
            while current_id is not None and current_id not in visited:
                visited.add(current_id)
                path_parts.insert(0, id_to_name[current_id])
                current_id = id_to_parent.get(current_id)
            by_id[cat.id]["path"] = path_parts

        for cat in categories:
            node = by_id[cat.id]
            if cat.parent_id is not None and cat.parent_id in by_id:
                by_id[cat.parent_id]["children"].append(node)
            else:
                roots.append(node)

        return roots

    async def update(
        self,
        category_id: uuid.UUID,
        *,
        repository_id: uuid.UUID,
        tenant_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        parent_id: uuid.UUID | None = ...,  # type: ignore[assignment]
        sort_order: int | None = None,
        is_active: bool | None = None,
        icon: str | None = None,
    ) -> Category:
        """카테고리 정보를 수정한다.

        parent_id를 변경할 때 순환 참조를 검사한다.

        Raises:
            CategoryNotFoundError: 카테고리가 존재하지 않을 때
            CategoryCircularReferenceError: 순환 참조가 발생할 때
            DuplicateNameError: 동일 이름이 존재할 때
        """
        await self._validate_repository(repository_id, tenant_id)
        category = await self.get_by_id(category_id, repository_id=repository_id)

        if name is not None:
            category.name = name
        if description is not None:
            category.description = description
        if parent_id is not ...:
            if parent_id is not None:
                await self._check_circular_reference(category_id, parent_id)
            category.parent_id = parent_id  # type: ignore[assignment]
        if sort_order is not None:
            category.sort_order = sort_order
        if is_active is not None:
            category.is_active = is_active
        if icon is not None:
            category.icon = icon

        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise DuplicateNameError("category", name or category.name)

        # Phase A-4: 카테고리 임베딩 재생성 (이름/설명 변경 시)
        if name is not None or description is not None:
            await self._update_category_embedding(category)

        logger.info("category_updated", category_id=str(category_id))
        return category

    async def delete(
        self,
        category_id: uuid.UUID,
        *,
        repository_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        """카테고리를 소프트 삭제한다.

        Raises:
            CategoryNotFoundError: 카테고리가 존재하지 않을 때
        """
        await self._validate_repository(repository_id, tenant_id)
        category = await self.get_by_id(category_id, repository_id=repository_id)
        category.is_active = False
        await self.db.flush()
        logger.info("category_deleted", category_id=str(category_id))

    async def get_descendants(
        self,
        category_id: uuid.UUID,
        *,
        repository_id: uuid.UUID,
    ) -> list[Category]:
        """카테고리의 모든 하위 카테고리를 재귀적으로 반환한다 (검색 필터용)."""
        descendants: list[Category] = []
        queue: list[uuid.UUID] = [category_id]

        while queue:
            current_id = queue.pop(0)
            stmt = (
                select(Category)
                .where(
                    Category.parent_id == current_id,
                    Category.repository_id == repository_id,
                    Category.is_active.is_(True),
                )
            )
            result = await self.db.execute(stmt)
            children = list(result.scalars().all())
            descendants.extend(children)
            queue.extend([c.id for c in children])

        return descendants
