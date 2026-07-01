"""mail.compose — 메일 초안 LLM 생성.

사용자 발화 "X 한테 Y 내용으로 메일 초안 작성해줘" 류 plan_orchestrator 가 호출.
실제 발송은 *하지 않음* — draft (subject + body_text) 만 만들어 사용자에게 확인.

Args:
- recipient (str | list[str], 옵션): 받는 사람. 다음 발송 단계 args 로 전달.
- subject_hint (str, 옵션): 사용자가 제시한 제목 힌트.
- body_hint (str, 옵션): 사용자가 제시한 본문 핵심 메시지 (필수에 가까움 — 없으면 hint 비어도 LLM 이 일반 인사문 생성).
- tone (str, 옵션): 어투 — "정중"/"친근"/"비즈니스"/"간결". 기본 "정중".
- language (str, 옵션): "ko"|"en". 기본 "ko".
- topic (str, 옵션): body_hint 의 별칭. plan_orchestrator 가 어느 키로 채울지 모를 때 대비.

반환: {success, draft: {to, subject, body_text}, summary, error?}

Note: 실제 발송은 별도 mail.send step 으로 plan 에 연결됨. 이 tool 자체는
network IO 없음 — vLLM 1회 호출만.
"""
from __future__ import annotations

import json
from typing import Any

from src.agent_framework.llm.vllm_adapter import VLLMAdapter
from src.common.logging import get_logger


log = get_logger(__name__)


# 모듈 레벨 싱글턴 — VLLMAdapter 는 stateless 라 안전.
# dependencies.py 의 인스턴스를 inject 할 수도 있지만 tool 시그니처가
# (args:dict)→dict 로 고정되어 있어 module 싱글턴이 가장 단순.
_LLM: VLLMAdapter | None = None


def _get_llm() -> VLLMAdapter:
    global _LLM
    if _LLM is None:
        _LLM = VLLMAdapter()
    return _LLM


def _coerce_recipients(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        out: list[str] = []
        for x in v:
            if isinstance(x, str) and x.strip():
                out.extend([s.strip() for s in x.split(",") if s.strip()])
        return out
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return []


_SYSTEM_PROMPT = """당신은 메일 초안을 작성하는 비서입니다. 사용자의 의도를 받아
자연스럽고 핵심이 분명한 한국어 (또는 지정 언어) 메일을 작성합니다.

원칙:
- 제목은 25자 내외, 본문 핵심을 한 줄로 압축.
- 본문은 인사 → 본론 → 마무리 3단 구성. 200자 이내가 기본 (사용자가 길게
  요구하면 늘려도 됨).
- 격식·어투는 tone 슬롯에 맞춤. 미지정 시 정중한 비즈니스 어투.
- 사용자 hint 가 모호하면 일반적인 비즈니스 메일로 합리적 추정.
- 발송자 이름·연락처 등 모르는 정보는 placeholder ([이름]) 로 두지 말고
  생략. 사용자가 마무리 단계에서 직접 채움.
- 응답은 *반드시* JSON object 한 개 — {"subject": str, "body_text": str}."""


def _build_user_prompt(
    *,
    recipient: list[str],
    subject_hint: str,
    body_hint: str,
    tone: str,
    language: str,
) -> str:
    recipient_line = (
        f"받는 사람: {', '.join(recipient)}" if recipient else "받는 사람: (미지정)"
    )
    subj_line = f"제목 힌트: {subject_hint}" if subject_hint else "제목 힌트: (없음 — 본문 hint 로 추론)"
    body_line = f"본문 핵심: {body_hint}" if body_hint else "본문 핵심: (없음 — 일반 안부/요청 톤)"
    return (
        f"{recipient_line}\n"
        f"{subj_line}\n"
        f"{body_line}\n"
        f"어투: {tone}\n"
        f"언어: {language}\n\n"
        "위 정보를 바탕으로 메일 초안을 JSON 으로 작성해 주세요."
    )


def _safe_parse_json(text: str) -> dict[str, Any] | None:
    """LLM 응답에서 JSON object 추출. 코드펜스/주변 텍스트 톨러런트."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    # ```json ... ``` 제거
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    # 가장 바깥쪽 { } 추출
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        s = s[start : end + 1]
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        return None
    return None


async def compose(args: dict[str, Any]) -> dict[str, Any]:
    """메일 초안 생성. LLM 한 번 호출 후 {subject, body_text} 반환.

    실패 케이스:
    - LLM 호출 자체 실패 → success=False, error 명시.
    - LLM 응답 JSON 파싱 실패 → fallback 으로 raw text 를 body_text 로 활용.
    """
    recipient = _coerce_recipients(
        args.get("recipient") or args.get("to") or args.get("recipients")
    )
    subject_hint = (args.get("subject_hint") or args.get("subject") or "").strip()
    body_hint = (
        args.get("body_hint")
        or args.get("topic")
        or args.get("body")
        or args.get("content")
        or args.get("message")
        or ""
    )
    body_hint = str(body_hint).strip()
    tone = (args.get("tone") or "정중").strip()
    language = (args.get("language") or "ko").strip()

    if not recipient and not body_hint and not subject_hint:
        # 모든 슬롯 비어있으면 LLM 호출 의미 없음 — 사용자에게 되묻기 유도.
        return {
            "success": False,
            "error": "메일 초안 작성에 필요한 최소 정보가 없습니다 (받는 사람 / 본문 핵심 / 제목 중 하나).",
        }

    user_prompt = _build_user_prompt(
        recipient=recipient,
        subject_hint=subject_hint,
        body_hint=body_hint,
        tone=tone,
        language=language,
    )

    try:
        raw = await _get_llm().complete(
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            response_format="json_object",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("mail_compose_llm_failed", error=str(exc)[:200])
        return {
            "success": False,
            "error": f"메일 초안 생성에 실패했습니다: {exc}",
        }

    parsed = _safe_parse_json(raw)
    if parsed is None:
        # JSON 형식 실패 — raw 를 body_text 로 사용.
        log.info("mail_compose_json_fallback", raw_len=len(raw or ""))
        subject = subject_hint or "(제목 미정)"
        body_text = (raw or "").strip() or body_hint or "(본문 미정)"
    else:
        subject = str(parsed.get("subject") or subject_hint or "(제목 미정)").strip()
        body_text = str(parsed.get("body_text") or parsed.get("body") or "").strip()
        if not body_text:
            body_text = body_hint or "(본문 미정)"

    to_field: list[str] | str = recipient if len(recipient) != 1 else recipient[0]
    draft = {
        "to": to_field,
        "subject": subject,
        "body_text": body_text,
    }

    summary_to = ", ".join(recipient) if recipient else "(받는 사람 미지정)"
    summary = f"메일 초안 작성 완료 — '{subject}' → {summary_to}"
    log.info(
        "mail_compose_ok",
        to_count=len(recipient),
        subject=subject[:60],
        body_len=len(body_text),
    )
    return {
        "success": True,
        "draft": draft,
        "summary": summary,
    }
