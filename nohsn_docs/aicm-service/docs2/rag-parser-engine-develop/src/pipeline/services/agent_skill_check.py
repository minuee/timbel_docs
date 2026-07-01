"""agent_* 타입 문서 여부 체크 헬퍼.

Stage A: KMS-Plus 에이전트 스킬을 KMS 문서로 관리하되, 블록 파이프라인은 건너뛴다.
Stage B-2/B-3/4/5: 일정·일기·뉴스·리마인더도 동일 ``documents`` 테이블을
사용하지만, block/embedding 대상은 아님.

seed_agent_skills 스크립트는 Kafka 이벤트를 발행하지 않아 파이프라인에 진입하지
않지만, 향후 UI 업로드로 편집할 때나 외부 이벤트가 새어나올 경우를 대비해
parse_worker 진입부에서 이 함수로 조기 차단한다.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.common.logging import get_logger
from src.core.database import async_session_factory

log = get_logger(__name__)

# Stage A: agent_skill 만.
# Stage B-2/3/4/5: schedule/diary/news_sub/news_report/reminder 추가. 전부 파이프라인 skip.
AGENT_SKIP_DOC_TYPES: frozenset[str] = frozenset(
    {
        "agent_skill",
        "agent_schedule",
        "agent_diary",
        "agent_news_sub",
        "agent_news_report",
        "agent_reminder",
    }
)

# 하위 호환 — 기존 import 유지 (Stage A 코드/테스트가 참조).
AGENT_SKILL_DOC_TYPE_NAME = "agent_skill"


async def is_agent_skill_document(document_id: UUID) -> bool:
    """documents.document_type 이 agent_* 비인덱싱 타입인지 여부.

    이름은 Stage A 호환을 위해 ``is_agent_skill_document`` 유지하지만 의미는
    "agent 관리 데이터 문서인가" 로 확장됨 (skill 외 schedule/diary/…).
    None 타입/문서 없음은 False.
    """
    async with async_session_factory() as sess:
        row = (
            await sess.execute(
                text(
                    """
                    SELECT dt.name
                    FROM documents d
                    LEFT JOIN document_types dt ON d.document_type_id = dt.id
                    WHERE d.id = :did
                    """
                ),
                {"did": document_id},
            )
        ).first()
    if not row:
        return False
    return row[0] in AGENT_SKIP_DOC_TYPES
