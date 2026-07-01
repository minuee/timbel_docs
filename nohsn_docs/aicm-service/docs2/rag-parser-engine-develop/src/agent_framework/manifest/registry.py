"""DomainManifest schema — frontend schema-driven UI 렌더용 카탈로그.

신규 도메인 추가 시 frontend 코드 변경 없이 manifest YAML 한 파일만 추가하면
sidebar / dashboard / 액션 폼이 자동 렌더되도록 설계.

설계 원칙
---------
- manifest 는 *카탈로그* (정적 정의 OK). 응답 본문 / endpoint 데이터는 LLM·DB·도구
  호출에서 동적으로 옴.
- 이모지 사용 금지 — ``icon`` 필드는 lucide-react 와 호환되는 이름 식별자
  ("mail", "calendar", "wallet" 등) 만 사용.
- 사용자별 활성화 상태는 ``user_enabled`` 로 응답 시점에 채움 — manifest 자체는
  사용자와 무관한 카탈로그.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ColumnFormat = Literal[
    "text", "date", "datetime", "currency", "percent", "badge", "number"
]

WidgetType = Literal["stat", "chart", "list"]
ChartKind = Literal["pie", "bar", "line", "area"]
DomainStatus = Literal["active", "available", "upcoming", "deprecated"]


@dataclass
class ColumnDef:
    """list_endpoint 응답 컬럼 정의."""

    key: str
    label: str
    format: ColumnFormat = "text"


@dataclass
class WidgetDef:
    """summary_endpoint 응답을 어떻게 위젯으로 렌더링할지 정의."""

    type: WidgetType
    label: str
    key: str
    kind: ChartKind | None = None  # type=chart 일 때만
    format: ColumnFormat = "text"


@dataclass
class ActionDef:
    """quick action — frontend 가 form_schema 를 JSON Schema 로 받아 폼 자동 생성."""

    id: str
    label: str
    method: str = "POST"
    endpoint: str | None = None
    form_schema: dict[str, Any] | None = None


@dataclass
class DomainManifest:
    """단일 도메인 카탈로그 entry."""

    id: str
    label: str
    icon: str
    status: DomainStatus

    # 데이터 endpoints (없는 도메인은 None — frontend 가 placeholder 표시)
    list_endpoint: str | None = None
    summary_endpoint: str | None = None
    detail_endpoint: str | None = None

    # 표시
    list_columns: list[ColumnDef] = field(default_factory=list)
    summary_widgets: list[WidgetDef] = field(default_factory=list)

    # 액션
    quick_actions: list[ActionDef] = field(default_factory=list)

    # chat 연동
    chat_intents: list[str] = field(default_factory=list)
    card_renderer: str | None = None  # frontend 의 known component 이름

    # upcoming 도메인 안내
    upcoming_message: str | None = None

    # 노출 그룹 — accounts.preferences.user_groups 와 교집합 매칭.
    # 빈 리스트는 "모든 그룹에 노출" 의미 (legacy / 보수적 default).
    # admin 그룹 사용자는 router 에서 무조건 모든 도메인 노출 처리.
    available_for_groups: list[str] = field(default_factory=list)

    # 사용자별 활성화 — manifest 자체에는 보존 안 함, 응답 시 채워짐.
    user_enabled: bool | None = None

    # 정렬
    sort_order: int = 100

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화 가능 dict 로 변환."""
        return asdict(self)


__all__ = [
    "ActionDef",
    "ChartKind",
    "ColumnDef",
    "ColumnFormat",
    "DomainManifest",
    "DomainStatus",
    "WidgetDef",
    "WidgetType",
]
