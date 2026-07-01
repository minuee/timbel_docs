from __future__ import annotations
from pathlib import Path
from typing import Any, AsyncIterator, Protocol

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.agent_framework.runtime.time_context import prepend_time


PROMPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "prompts"


# Locus 응답 스타일 가드 — 모든 skill prompt 위에 일괄 prepend.
# 사용자 메모리 (feedback_no_emoji / feedback_no_hardcoding_first_principle /
# feedback_pattern_over_case_enumeration) 의 정면 반영. 89개 yaml 의 자유 분장
# (이모지·예시 열거·정형 ack) 을 LLM 출력층에서 일괄 차단.
_STYLE_GUARD = (
    "## 응답 스타일 절대 규칙\n"
    "1. 이모지·이모티콘 사용 금지. 텍스트만.\n"
    "2. \"(예: ...)\" 같은 예시 열거 금지. 사용자가 모를 때만 한 줄 안내, 예시는 0개 또는 1개.\n"
    "3. 사용자 발화에 이미 정보가 있으면 다시 묻지 않는다. 받은 정보로 즉시 진행.\n"
    "4. 정형 ack 문자열(\"감사합니다\", \"꼼꼼하게 기록해 드릴게요\" 등) 금지. "
    "입력 내용에 기반한 답변만.\n"
    "5. 친근한 존댓말. 핵심만 간결히. 광고·홍보 어조 금지.\n"
    "6. \"발사·발화\" 같은 군대 어휘 금지.\n"
)


def _wrap_system(system: str) -> str:
    """skill prompt 위에 시간 prefix + 스타일 가드를 prepend."""
    return prepend_time(_STYLE_GUARD + system)


class StreamingLLM(Protocol):
    def stream(
        self, system: str, user: str | list[dict]
    ) -> AsyncIterator[str]: ...


class ResponseGenerator:
    def __init__(self, llm_client: StreamingLLM, prompts_dir: Path = PROMPTS_DIR):
        self.llm = llm_client
        self.env = Environment(
            loader=FileSystemLoader(prompts_dir),
            autoescape=select_autoescape(enabled_extensions=()),
        )

    def render(self, template_name: str, context: dict[str, Any]) -> str:
        tpl = self.env.get_template(template_name)
        return tpl.render(**context)

    async def stream(
        self,
        template_name: str,
        context: dict[str, Any],
        system: str = "너는 친절한 AI 에이전트다.",
        attachments: list[Any] | None = None,
    ) -> AsyncIterator[str]:
        """Template rendered user text + optional image attachments.

        Task 24.5 — attachments 가 있으면 OpenAI vision content list 로 조립해
        멀티모달 LLM 경로로 전송. 없으면 기존 str 경로 유지 (회귀 없음).
        """
        user_text = self.render(template_name, context)
        final_system = _wrap_system(system)
        if not attachments:
            async for token in self.llm.stream(final_system, user_text):
                yield token
            return

        content: list[dict] = [{"type": "text", "text": user_text}]
        for a in attachments:
            mime = getattr(a, "mime", None)
            b64 = getattr(a, "data_base64", None)
            if mime is None and isinstance(a, dict):
                mime = a.get("mime")
                b64 = a.get("data_base64")
            if mime and b64 and str(mime).startswith("image/"):
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    }
                )

        # 첨부에서 image 가 하나도 추출 안 됐으면 str 경로로 fallback
        if len(content) == 1:
            async for token in self.llm.stream(final_system, user_text):
                yield token
            return

        async for token in self.llm.stream(final_system, content):
            yield token
