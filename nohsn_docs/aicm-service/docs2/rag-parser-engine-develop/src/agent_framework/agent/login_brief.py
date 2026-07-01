"""Login brief — 사용자 페르소나·시점에 맞춘 첫 메시지 합성.

Phase 3 (KMS-Plus) 의 "처음 챗을 열면 빈 화면이 아니라 페르소나 맞춤형 인사말 +
오늘 컨텍스트 + (옵션) 자원 상태 요약" 을 위한 모듈.

**책임 경계**:
- 본 모듈은 **순수 templating + persona resolution** 만 담당.
- 실제 inventory_summary 조회는 caller (engine 의 _maybe_login_brief hook 등) 가
  ``kms_inventory.get_summary`` 를 통해 미리 만들어 넘긴다.
- 즉 본 함수에는 외부 I/O 가 없어 단위 테스트가 결정적.

페르소나 우선순위:
  account.profile_type > tenant.business_type > "default"
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


PERSONA_TEMPLATES: dict[str, str] = {
    "medical": (
        "안녕하세요. 오늘은 {date}이고, "
        "환자 정보·예약·진료 가이드 도와드리겠습니다."
    ),
    "cs": (
        "안녕하세요. 오늘은 {date}이고, "
        "응대 가이드·고객 정책을 즉시 조회해 드립니다."
    ),
    "finance": (
        "안녕하세요. 오늘은 {date}이고, "
        "시장 동향·관심 종목 변동을 알려드립니다."
    ),
    "dev": (
        "안녕하세요. 오늘은 {date}이고, "
        "활성 기능·검토 대기 상태를 요약해 드립니다."
    ),
    "default": (
        "안녕하세요. 오늘은 {date}이고, "
        "무엇을 도와드릴까요?"
    ),
}
"""페르소나별 인사 템플릿. {date} 만 치환된다.

코드 상의 분기/조건문 대신 dict lookup 으로 일반화 — 새 페르소나 추가는 dict 항목
한 줄로 끝난다 (feedback: 케이스 열거 대신 패턴/원칙 설계).
"""


def detect_persona(account: dict[str, Any] | None, tenant: dict[str, Any] | None = None) -> str:
    """페르소나 결정. account.profile_type > tenant.business_type > 'default'."""
    if account:
        p = (account.get("profile_type") or "").strip().lower()
        if p and p in PERSONA_TEMPLATES:
            return p
    if tenant:
        p = (tenant.get("business_type") or "").strip().lower()
        if p and p in PERSONA_TEMPLATES:
            return p
    return "default"


async def build_brief(
    account: dict[str, Any] | None,
    tenant: dict[str, Any] | None,
    inventory_summary: str | None = None,
    *,
    now: datetime | None = None,
) -> str:
    """페르소나 결정 → 인사 템플릿 렌더 → (옵션) inventory_summary 첨부.

    Parameters
    ----------
    account : dict | None
        ``profile_type`` 키를 읽음. None 이면 default.
    tenant : dict | None
        ``business_type`` 키 fallback.
    inventory_summary : str | None
        ``kms_inventory.get_summary`` 가 만든 ``summary_ko`` 같은 문자열을 받으면
        인사말 뒤에 한 줄 띄워 첨부.
    now : datetime | None
        테스트 결정성을 위한 시점 주입. None 이면 ``datetime.now()``.

    Returns
    -------
    str
        조립된 한국어 brief.
    """
    persona = detect_persona(account, tenant)
    when = (now or datetime.now()).strftime("%Y년 %m월 %d일")
    base = PERSONA_TEMPLATES[persona].format(date=when)
    if inventory_summary:
        base = base + " " + inventory_summary.strip()
    return base
