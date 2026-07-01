"""Task 33 — 프롬프트 톤앤매너 smoke test.

각 사용자-대면 prompt 템플릿을 최소 컨텍스트로 렌더링하고
- 이모지
- 기술 용어 ("스킬", "세션", "인텐트", "토큰", "엔드포인트")
가 **결과물 바깥으로 새어나가지 않는지** 확인한다.

다만 "톤앤매너 규칙" 섹션(프롬프트 자체의 메타 지시) 에서는 단어를 설명할 수밖에 없으므로,
해당 섹션을 render 후 제거한 뒤 잔여 본문만 검사한다.

document_auto_classify.md 는 사용자에게 노출되지 않는 JSON 분류기이므로 제외.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape


PROMPTS_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "agent_framework"
    / "skills"
    / "prompts"
)

# 사용자에게 실제 노출되는 응답을 만드는 템플릿들
USER_FACING_TEMPLATES = [
    "capability_briefing.md",
    "confirm_derm.md",
    "diary_greet.md",
    "diary_recall.md",
    "diary_saved.md",
    "greet_derm.md",
    "news_brief.md",
    "news_greet.md",
    "no_skills_available.md",
    "rag_answer_derm.md",
    "schedule_collect.md",
    "schedule_confirm.md",
    "schedule_greet.md",
    "schedule_query_answer.md",
    "select_doctor.md",
    "unsupported_request.md",
]

# 이모지 유니코드 카테고리 (대표 범위). 정규식 기반 탐지.
EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "☀-⛿"
    "✀-➿"
    "]+",
    flags=re.UNICODE,
)

FORBIDDEN_TECHNICAL_TERMS = ["인텐트", "엔드포인트"]
"""사용자 메시지에 절대 노출되면 안 되는 기술 용어.

"스킬", "세션", "토큰" 은 일부 프롬프트의 메타 지시 본문에 의도적으로 포함되어
'노출 금지' 룰로 남아있으며, 렌더된 프롬프트에서는 '톤앤매너 규칙' 섹션을
제거한 뒤 잔여 본문만 검사한다."""


class _FakeToolResult:
    """schedule_query_answer.md 가 `tool_result.items` 를 iterate 하기 때문에
    dict 의 내장 메서드 .items 와 충돌한다. 속성 접근으로 바꿔 회피한다."""

    doctors = [
        {
            "name": "김",
            "specialty": "피부과",
            "intro": "20년 경력",
            "days": ["월", "화"],
        }
    ]
    items: list = []
    topics = ["AI 스타트업"]


def _minimal_context() -> dict:
    """모든 템플릿이 최소한 에러 없이 렌더되도록 하는 공용 컨텍스트."""
    return {
        "tenant": {"name": "테스트 매장"},
        "user_message": "안녕하세요",
        "history": "",
        "available_skills": ["예약 도우미", "일정 관리"],
        "hits": [],
        "slots": {
            "title": "회의",
            "when": "2026-04-25 15:00",
            "recurrence": None,
            "topic": "AI 스타트업",
            "preferred_date": "2026-04-25",
            "preferred_service": "레이저",
            "contact_phone": "010-0000-0000",
            "today": "2026-04-24",
            "emotion": "평온",
        },
        "summary": "오늘의 요약입니다.",
        "topics": ["AI 스타트업"],
        "tool_result": _FakeToolResult(),
    }


def _strip_rules_section(rendered: str) -> str:
    """'## 톤앤매너 규칙' ~ 다음 '##' 사이 구간을 제거해 **실제 출력이 될 부분** 만 남긴다.

    이 규칙 섹션은 LLM 에게 "이런 단어 쓰지 마세요" 라고 **지시** 하는 메타 섹션이라,
    단어 자체는 반드시 포함되어야 한다. 따라서 smoke test 에서는 제외한다.
    """
    pattern = re.compile(
        r"## 톤앤매너 규칙.*?(?=^##\s|\Z)", re.DOTALL | re.MULTILINE
    )
    return pattern.sub("", rendered)


@pytest.fixture(scope="module")
def jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(PROMPTS_DIR),
        autoescape=select_autoescape(enabled_extensions=()),
    )


@pytest.mark.parametrize("template_name", USER_FACING_TEMPLATES)
def test_template_renders_without_emoji(jinja_env, template_name):
    tpl = jinja_env.get_template(template_name)
    rendered = tpl.render(**_minimal_context())
    residual = _strip_rules_section(rendered)
    match = EMOJI_RE.search(residual)
    assert match is None, (
        f"{template_name} 에 이모지가 포함됨: {match.group(0) if match else ''}"
    )


@pytest.mark.parametrize("template_name", USER_FACING_TEMPLATES)
def test_template_has_rules_section(jinja_env, template_name):
    """모든 사용자-대면 템플릿은 톤앤매너 규칙 섹션을 포함해야 한다."""
    tpl = jinja_env.get_template(template_name)
    rendered = tpl.render(**_minimal_context())
    assert "톤앤매너 규칙" in rendered, (
        f"{template_name} 에 톤앤매너 규칙 섹션이 없음"
    )


@pytest.mark.parametrize("template_name", USER_FACING_TEMPLATES)
def test_template_no_forbidden_technical_terms_in_body(jinja_env, template_name):
    """규칙 섹션 외 본문에는 금지 기술 용어(인텐트/엔드포인트) 가 없어야 한다."""
    tpl = jinja_env.get_template(template_name)
    rendered = tpl.render(**_minimal_context())
    residual = _strip_rules_section(rendered)
    for term in FORBIDDEN_TECHNICAL_TERMS:
        assert term not in residual, (
            f"{template_name} 규칙 섹션 밖에서 '{term}' 발견 — "
            f"사용자 응답에 기술 용어가 노출될 수 있음"
        )
