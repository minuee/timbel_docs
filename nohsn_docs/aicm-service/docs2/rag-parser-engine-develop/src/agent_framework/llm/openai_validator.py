"""OpenAI 를 2nd judge 로 사용하는 cross-validation 모듈.

목적: 우리 vLLM (gemma-31B) 기반 LLM-driven 판단 (intent / overlap / synonym / qa)
의 결과를 OpenAI gpt-4o-mini 와 cross-check 해 회귀 / 분류 정확도 회귀를
탐지한다. 운영 시는 항상 OFF — `KMS_OPENAI_VALIDATOR=true` 가 설정된 경우에만
활성화. 키는 반드시 `OPENAI_API_KEY` 환경 변수로 주입 (코드/문서/로그에 절대 박지
말 것). 키 미설정 시 `is_enabled()` 가 False 반환 → graceful skip.

테스트 단위:
 - 모듈 로드 / `is_enabled()` 분기.
 - `validate_*` 4 종은 OpenAI client 를 mock 으로 주입해 JSON 파싱·반환 형태만
   검증 (실 호출 X — 비용 0).
 - 통합 호출은 `KMS_OPENAI_VALIDATOR=true` + 실 `OPENAI_API_KEY` 가 모두 있는
   경우에만 별도 스크립트(`scripts/eval/validate_kb_soldiers_scenario.py`) 에서.
"""

from __future__ import annotations

import json
import os
from typing import Any


# 2026-04-25: 사용자 지시로 최신 모델로 업그레이드. 환경 변수 override 허용.
_DEFAULT_MODEL = os.environ.get("KMS_OPENAI_VALIDATOR_MODEL", "gpt-5.5")


def is_enabled() -> bool:
    """`KMS_OPENAI_VALIDATOR=true` AND `OPENAI_API_KEY` 둘 다 있을 때만 True."""
    if os.environ.get("KMS_OPENAI_VALIDATOR", "").lower() not in ("1", "true", "yes"):
        return False
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    return True


_client: Any | None = None


def _make_client():
    """openai SDK client 생성. import 는 lazy (테스트 환경 의존성 회피)."""
    global _client
    if _client is None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        from openai import OpenAI  # lazy import

        _client = OpenAI(api_key=key)
    return _client


def reset_client_for_tests() -> None:
    """테스트에서 mock client 강제 주입 후 정리용."""
    global _client
    _client = None


def set_client_for_tests(client: Any) -> None:
    """테스트에서 mock client 주입."""
    global _client
    _client = client


def _call_json(*, prompt: str, model: str = _DEFAULT_MODEL, max_tokens: int = 200) -> dict:
    """OpenAI chat.completions 동기 호출 → JSON object 반환.

    2026-04-25 — 모델 신구 호환:
    - gpt-5.x 계열: ``max_completion_tokens`` 사용 + temperature 인자 미지원 (default=1)
    - gpt-4o/4 계열: ``max_tokens`` + ``temperature=0``
    위 차이를 모델 prefix 로 분기.
    """
    client = _make_client()
    is_gpt5 = model.startswith("gpt-5") or model.startswith("o1") or model.startswith("o3")
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    if is_gpt5:
        kwargs["max_completion_tokens"] = max_tokens
        # temperature 미설정 → default=1 (gpt-5 시리즈가 0 거부)
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = 0
    resp = client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"agree": False, "error": "json_parse_failed", "raw": text}


# ---------- 4 종 validator ----------

def validate_intent(*, user_text: str, our_label: str, our_confidence: float) -> dict:
    """우리 intent classifier 결과를 OpenAI 에 2nd opinion 으로 묻는다.

    Returns: {agree, openai_label, confidence, reason}
    """
    prompt = (
        "사용자 발화 의도 분류 검증.\n"
        f'우리 분류: {our_label} (confidence {our_confidence:.2f})\n\n'
        f'사용자 발화: "{user_text}"\n\n'
        "이 분류가 맞는지 평가하고, 본인 의견을 JSON 으로:\n"
        '{"agree": true/false, "openai_label": "...", "confidence": 0~1, "reason": "한 줄"}\n\n'
        "가능한 label: book / cancel / list / search / chat / unsupported / log / recall / capability / etc.\n"
    )
    return _call_json(prompt=prompt)


def validate_overlap_relation(
    *,
    new_summary: str,
    peer_title: str,
    peer_snippet: str,
    our_relation: str,
    our_confidence: float,
) -> dict:
    """KnowledgeOverlapAnalyzer 의 relation 분류 검증.

    Returns: {agree, openai_relation, confidence, reason}
    """
    prompt = (
        "두 문서 사이 관계 분류 검증.\n"
        f"신규 요약: {new_summary}\n"
        f"기존 제목: {peer_title}\n"
        f"기존 발췌: {peer_snippet}\n"
        f"우리 분류: {our_relation} (confidence {our_confidence:.2f})\n\n"
        "다음 6 라벨 중 정답으로 평가 + JSON:\n"
        "duplicate / supersedes_existing / superseded_by_existing / conflicts / complementary / unrelated\n\n"
        '{"agree": true/false, "openai_relation": "...", "confidence": 0~1, "reason": "..."}\n'
    )
    return _call_json(prompt=prompt)


def validate_synonym(*, term_a: str, term_b: str, our_decision: bool) -> dict:
    """두 용어가 동의어/별칭 관계인지 검증.

    Returns: {agree, openai_decision, confidence, reason}
    """
    prompt = (
        "두 용어가 동의어/별칭 관계인지 검증.\n"
        f"용어 A: {term_a}\n"
        f"용어 B: {term_b}\n"
        f'우리 판정: {"동의어" if our_decision else "다른 개념"}\n\n'
        '{"agree": true/false, "openai_decision": true/false, "confidence": 0~1, "reason": "..."}\n'
    )
    return _call_json(prompt=prompt)


def validate_qa_pair(
    *,
    question: str,
    our_answer: str,
    reference_answer: str,
) -> dict:
    """우리 답변과 정답(reference) 답변의 의미상 일치도 평가.

    Returns: {semantic_score, agree_facts, missing_facts, extra_facts, reason}
    """
    prompt = (
        "두 답변이 의미상 같은지 평가. 단어 일치가 아니라 사실/의도 일치 기준.\n"
        f"질문: {question}\n"
        f"우리 답변: {our_answer}\n"
        f"정답 답변: {reference_answer}\n\n"
        "JSON:\n"
        '{"semantic_score": 0~1, "agree_facts": ["일치 사실"], '
        '"missing_facts": ["우리 답변이 빠뜨린 것"], '
        '"extra_facts": ["우리 답변이 더 말한 것"], '
        '"reason": "한 줄"}\n'
    )
    return _call_json(prompt=prompt, max_tokens=400)
