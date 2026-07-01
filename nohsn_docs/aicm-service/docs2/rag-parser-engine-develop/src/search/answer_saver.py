"""Answer Saver — LLM-WIKI query --save 패턴 구현.

RAG 답변을 블럭으로 저장하여 재검색 시 활용한다.
같은 질문이 다시 오면 컴파일된 답변 블럭이 직접 히트 → 토큰 절감 + 응답 속도 향상.

KMS 검색과 RAG 검색 모두에 효과:
- KMS: 이전에 생성된 답변이 검색 결과에 포함 → 사용자가 즉시 활용
- RAG: 컴파일된 답변이 컨텍스트에 포함 → 더 정확한 답변 기반
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from src.common.logging import get_logger

log = get_logger(__name__)


class AnswerSaver:
    """RAG 답변을 블럭으로 저장하는 서비스.

    사용 시점: RAG generation 모드로 답변 생성 후, save=True 일 때 호출.
    """

    async def save_answer(
        self,
        query: str,
        answer: str,
        source_block_ids: list[UUID],
        repository_id: UUID,
        document_id: UUID | None = None,
        confidence: float = 0.0,
    ) -> UUID | None:
        """RAG 답변을 Block 레코드로 저장한다.

        Parameters
        ----------
        query : str
            원본 질문
        answer : str
            생성된 답변
        source_block_ids : list[UUID]
            답변 근거가 된 블럭 ID 목록
        repository_id : UUID
            저장 대상 저장소
        document_id : UUID | None
            연관 문서 ID (없으면 저장소 수준 답변)
        confidence : float
            답변 신뢰도 (rerank 점수 기반)

        Returns
        -------
        UUID | None
            저장된 블럭 ID, 실패 시 None
        """
        if not answer or len(answer.strip()) < 10:
            return None

        # 중복 방지: 동일 질문+답변 해시 체크
        answer_hash = hashlib.sha256(
            f"{query}::{answer}".encode("utf-8")
        ).hexdigest()

        try:
            from sqlalchemy import select

            from src.core.database import async_session_factory
            from src.core.models.block import Block

            async with async_session_factory() as session:
                # 중복 체크
                dup_stmt = select(Block.id).where(
                    Block.repository_id == repository_id,
                    Block.block_hash == answer_hash,
                )
                existing = (await session.execute(dup_stmt)).scalar_one_or_none()
                if existing:
                    log.info("answer_already_saved", block_id=str(existing))
                    return existing

                # 답변 블럭 생성
                content = f"Q: {query}\n\nA: {answer}"

                block = Block(
                    id=uuid4(),
                    document_id=document_id or uuid4(),
                    repository_id=repository_id,
                    block_type="summary",
                    content=content,
                    block_index=0,
                    block_hash=answer_hash,
                    token_count=len(content),
                    source_location={},
                    meta_info={
                        "generated": True,
                        "source": "rag_answer",
                        "original_query": query,
                        "source_block_ids": [str(bid) for bid in source_block_ids],
                        "confidence": confidence,
                        "saved_at": datetime.utcnow().isoformat(),
                    },
                    is_indexed=False,
                )

                session.add(block)
                await session.commit()

                log.info(
                    "answer_saved_as_block",
                    block_id=str(block.id),
                    query=query[:100],
                    answer_len=len(answer),
                    source_count=len(source_block_ids),
                )
                return block.id

        except ImportError:
            log.warning("database_not_available_answer_save_skipped")
            return None
        except Exception as exc:
            log.warning("answer_save_failed", error=str(exc))
            return None


class RepositoryIndexBuilder:
    """저장소 인덱스 블럭을 생성/갱신한다.

    LLM-WIKI의 index.md에 해당.
    저장소 내 모든 문서의 제목 + 한줄 요약 + 주요 키워드를 하나의 블럭으로 관리.
    """

    async def rebuild_index(self, repository_id: UUID) -> UUID | None:
        """저장소 인덱스 블럭을 재빌드한다.

        Returns
        -------
        UUID | None
            인덱스 블럭 ID
        """
        try:
            from sqlalchemy import func, select

            from src.core.database import async_session_factory
            from src.core.models.block import Block
            from src.core.models.document import Document

            async with async_session_factory() as session:
                # 저장소의 모든 active 문서 조회
                doc_stmt = (
                    select(
                        Document.id,
                        Document.title,
                        Document.source_format,
                        Document.processing_meta,
                    )
                    .where(
                        Document.repository_id == repository_id,
                        Document.status == "active",
                    )
                    .order_by(Document.title)
                )
                docs = (await session.execute(doc_stmt)).all()

                if not docs:
                    return None

                # 인덱스 내용 생성
                lines = [f"# 저장소 문서 인덱스 ({len(docs)}개 문서)\n"]
                for doc in docs:
                    meta = doc.processing_meta or {}
                    summary = meta.get("summary", "")
                    difficulty = meta.get("difficulty", "")
                    page_count = meta.get("page_count", "")

                    line = f"- **{doc.title}**"
                    if doc.source_format:
                        line += f" [{doc.source_format}]"
                    if page_count:
                        line += f" ({page_count}쪽)"
                    if summary:
                        line += f" — {summary[:100]}"
                    lines.append(line)

                content = "\n".join(lines)
                index_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

                # 기존 인덱스 블럭 찾기 (업데이트 또는 생성)
                existing_stmt = select(Block).where(
                    Block.repository_id == repository_id,
                    Block.meta_info["source"].as_string() == "repository_index",
                )
                existing = (await session.execute(existing_stmt)).scalar_one_or_none()

                if existing:
                    existing.content = content
                    existing.block_hash = index_hash
                    existing.token_count = len(content)
                    existing.is_indexed = False  # 재벡터화 필요
                    await session.commit()
                    log.info("repository_index_updated", block_id=str(existing.id))
                    return existing.id
                else:
                    block = Block(
                        id=uuid4(),
                        document_id=docs[0].id,  # 첫 문서에 연결
                        repository_id=repository_id,
                        block_type="summary",
                        content=content,
                        block_index=0,
                        block_hash=index_hash,
                        token_count=len(content),
                        source_location={},
                        meta_info={
                            "generated": True,
                            "source": "repository_index",
                            "document_count": len(docs),
                        },
                        is_indexed=False,
                    )
                    session.add(block)
                    await session.commit()
                    log.info("repository_index_created", block_id=str(block.id))
                    return block.id

        except ImportError:
            log.warning("database_not_available")
            return None
        except Exception as exc:
            log.warning("repository_index_build_failed", error=str(exc))
            return None
