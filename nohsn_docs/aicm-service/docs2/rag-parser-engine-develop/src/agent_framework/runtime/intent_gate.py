"""D70 — Intent gate for OOS rejection (cross-domain keyword guard + LLM judge).

봇별 ``oos_keywords`` (alembic 080) 를 사용해 사용자 발화의 *cross-domain 의심*
점수를 산출. ``engine.py`` 의 compose path 시작 hook 이 매칭 시 T2 거절 응답을
직접 yield (LLM 호출 스킵, 비용/시간 절약).

설계 원칙 (GPT-5 사전 verdict 2026-05-11 권고 반영):
- 키워드 매칭은 *1차 빠른 필터*. precision ≥ 98% 가 우선 — false-positive 최소화.
- 키워드는 *브랜드/서비스 고유명* 만 (예: "배민", "코스피", "삼천리도시가스"). 일반어
  ("배달", "주문번호") 는 금지 — 도메인 안 합법 발화 오탐 위험.
- 한글 어경계 매칭: 키워드 앞뒤가 *한글/영문/숫자가 아닌* 경우 (공백/구두점/문장 시작/끝)
  만 매칭. "음식배달" 키워드가 "음식배달앱" 안에서 매칭되되, "재배달" 같이 *prefix*
  로만 등장하는 경우는 매칭 X.
- ``oos_keywords`` 가 None / [] 이면 reject 안 함 (회귀 0).
- feature flag (``KMS_INTENT_GATE_ENABLED``) — default true. ``"0"`` / ``"false"`` 시
  완전 bypass (kill-switch).
- 거절 메시지는 T2 ("이 에이전트는 ... 전용입니다 ...") 패턴. agent 의 ``goal`` /
  ``name`` 으로 personalize.

GPT-5 6 보강 반영:
1. user-history 선기록 → gate → reject 시 history persist + return (engine.py 책임)
2. brand/service-name only (alembic UPDATE 책임)
3. 경계 매칭 + 정규화 (본 모듈)
4. KMS_INTENT_GATE_ENABLED kill-switch (본 모듈)
5. None/[] 안전 처리 (본 모듈 + agent_context)
6. matched 키워드 telemetry 로깅 (본 모듈)

#80 LLM judge layer (2026-05-18):
- 키워드 매칭이 없어도 agent guidelines 와 대조해 LLM 이 out_of_domain 판정 가능.
- 활성 조건: KMS_INTENT_GATE_LLM_JUDGE_ENABLED (default true) + guidelines_md 존재.
- 판단 기준: agent 의 in-scope 정의 vs 사용자 발화 의미 거리. 키워드 열거 X.
- 결과가 out_of_domain 이면 keyword match 와 동일 경로 (reject=True).
- LLM 호출 실패 시 fail-open (in_domain_likely 통과 — 회귀 최소화).
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any


def _is_enabled() -> bool:
    """kill-switch — ``KMS_INTENT_GATE_ENABLED=0`` / ``false`` 면 gate 비활성."""
    val = (os.getenv("KMS_INTENT_GATE_ENABLED", "1") or "").strip().lower()
    return val not in ("0", "false", "no", "off")


def _normalize(text: str) -> str:
    """NFKC 정규화 + lower + 양 끝 공백 제거. 한글은 lower() 영향 없음."""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).lower().strip()


# 한글/영문/숫자 문자 클래스 — 어경계 매칭에 사용.
_WORD_CHAR_RE = re.compile(r"[가-힣A-Za-z0-9]")


def _has_boundary_match(haystack: str, needle: str) -> bool:
    """``haystack`` 안에서 ``needle`` 이 *문자 경계* 안에 등장하는지.

    한글은 word-boundary (``\\b``) 가 의미 없으므로 직접 구현:
    각 매칭 위치에서 *앞 글자* 와 *뒷 글자* 가 word-char (한글/영문/숫자) 가 *아니면*
    경계 매칭으로 인정. 양 쪽 중 하나라도 word-char 이면 같은 단어 내부 → 매칭 X.

    예:
      - haystack="배민으로 주문" needle="배민" → 앞=문장시작, 뒤="으" (한글) → 매칭 X? NO.
        한국어 조사는 word-char 라 위 정의로는 매칭 안 됨. 그러나 "배민으로" 의 의도가
        '배민 서비스 언급' 이므로 매칭 *해야 한다*.

    한국어 특수성: *뒷* 글자가 한글이어도 매칭 인정 (조사 흡수). 단 *앞* 글자가
    한글/영문/숫자이면 매칭 X (다른 단어의 suffix 인 경우 — 예: "재배달", "주식회사"
    안 "주식"). 영문 키워드 ("MTS","ETF") 는 앞·뒤 양쪽 word-boundary 엄격 적용.

    이 정의가 한국어 실 발화 90%+ 케이스에 잘 맞음. 더 정확한 형태소 분석은 후속 PR.
    """
    if not haystack or not needle:
        return False
    is_ascii_only_kw = needle.isascii() and any(c.isalpha() or c.isdigit() for c in needle)
    start = 0
    n = len(needle)
    H = len(haystack)
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return False
        before = haystack[idx - 1] if idx > 0 else ""
        after = haystack[idx + n] if (idx + n) < H else ""
        if is_ascii_only_kw:
            # 영문/숫자 키워드 — 양쪽 모두 word-boundary 엄격.
            before_ok = (not before) or (not _WORD_CHAR_RE.match(before))
            after_ok = (not after) or (not _WORD_CHAR_RE.match(after))
            if before_ok and after_ok:
                return True
        else:
            # 한글 포함 키워드 — *앞* 만 boundary 검사 (뒷 조사 흡수 허용).
            before_ok = (not before) or (not _WORD_CHAR_RE.match(before))
            if before_ok:
                return True
        start = idx + 1


def domain_match_score(user_message: str, agent_ctx: Any) -> dict[str, Any]:
    """봇 oos_keywords 매칭 검사. 매칭 카운트 + 매칭된 키워드 리스트 반환.

    Returns:
        {"matched": list[str], "score": float}
        - score 1.0 = 키워드 없음 (oos_keywords 비어 있음) → 중립.
        - score 0.7 = 키워드 있음 + 매칭 0 → in-domain 가능성.
        - score 0.0 = 매칭 1+ → cross-domain 강한 의심.
    """
    if agent_ctx is None:
        return {"matched": [], "score": 1.0}
    raw_kws = getattr(agent_ctx, "oos_keywords", None)
    if not raw_kws:
        return {"matched": [], "score": 1.0}
    msg_norm = _normalize(user_message)
    if not msg_norm:
        return {"matched": [], "score": 0.7}
    matched: list[str] = []
    for raw_kw in raw_kws:
        if not raw_kw:
            continue
        kw_norm = _normalize(str(raw_kw))
        if not kw_norm:
            continue
        if _has_boundary_match(msg_norm, kw_norm):
            matched.append(str(raw_kw))
    if matched:
        return {"matched": matched, "score": 0.0}
    return {"matched": [], "score": 0.7}


def intent_gate_check(user_message: str, agent_ctx: Any) -> dict[str, Any]:
    """Intent gate 1차 판정.

    Returns:
        {
          "enabled": bool,         # kill-switch 상태
          "reject": bool,          # True 면 T2 거절 응답으로 분기
          "confidence": float,     # 0.0 (강한 cross-domain) ~ 1.0 (중립)
          "matched": list[str],    # 매칭된 oos_keywords
          "reason": str,           # disabled / no_keywords / in_domain_likely / oos_keyword_match
        }
    """
    # D78 — 분모 metric (진입 횟수, kill-switch 검사 *전*).
    try:
        from src.common.metrics import inc_guard_input

        inc_guard_input("intent_gate")
    except Exception:  # noqa: BLE001
        pass

    if not _is_enabled():
        return {
            "enabled": False,
            "reject": False,
            "confidence": 1.0,
            "matched": [],
            "reason": "disabled",
        }
    if agent_ctx is None:
        return {
            "enabled": True,
            "reject": False,
            "confidence": 1.0,
            "matched": [],
            "reason": "no_agent_context",
        }
    # admin agent 는 cross-domain 가드 약함 (전체 도구 카탈로그) — gate 통과.
    if getattr(agent_ctx, "is_admin", False) or getattr(agent_ctx, "kind", "role") == "admin":
        return {
            "enabled": True,
            "reject": False,
            "confidence": 1.0,
            "matched": [],
            "reason": "admin_bypass",
        }
    res = domain_match_score(user_message, agent_ctx)
    matched = res["matched"]
    score = res["score"]
    if score == 1.0:
        reason = "no_keywords"
    elif matched:
        reason = "oos_keyword_match"
    else:
        reason = "in_domain_likely"
    # D78 — reject 시 hit counter inc.
    if matched:
        try:
            from src.common.metrics import inc_intent_gate_reject

            inc_intent_gate_reject("oos_keyword_match")
        except Exception:  # noqa: BLE001
            pass
    return {
        "enabled": True,
        "reject": bool(matched),
        "confidence": score,
        "matched": matched,
        "reason": reason,
    }


def _is_llm_judge_enabled() -> bool:
    """kill-switch — ``KMS_INTENT_GATE_LLM_JUDGE_ENABLED=0/false`` 면 LLM judge 비활성."""
    val = (os.getenv("KMS_INTENT_GATE_LLM_JUDGE_ENABLED", "1") or "").strip().lower()
    return val not in ("0", "false", "no", "off")


# ---------------------------------------------------------------------------
# LLM judge prompt — 의미 패턴 기반 판단 기준 + few-shot 예시.
# 규칙: 키워드 열거 금지. agent 의 in-scope 정의 vs 발화 의미 거리 LLM 판단.
# ---------------------------------------------------------------------------
_LLM_JUDGE_SYSTEM = """당신은 agent 도메인 판정 전문가입니다.
사용자 발화가 agent 의 담당 도메인에 속하는지(in_domain) 혹은 명백히 벗어나는지(out_of_domain)를 판정합니다.

## 판단 기준

1. agent 의 guidelines 에 명시된 in-scope 정의를 먼저 파악합니다.
2. 사용자 발화의 *의도*가 그 in-scope 정의와 의미적으로 연결되는지 판단합니다.
   - 표현이 달라도 동일한 목적·문제 해결이면 in_domain.
   - 단어 하나가 겹쳐도 의도가 완전히 다른 분야라면 out_of_domain.
3. 경계 모호 시: agent guidelines 의 in-scope 정의를 기준으로 판단합니다.
4. confidence 지침:
   - 명백히 in_domain 또는 out_of_domain: 0.85 이상.
   - 경계 모호: 0.50~0.75.

## few-shot 예시

예시 1 (out_of_domain):
agent: "공공기관 SaaS 도입 자문 봇" (클라우드 SaaS 도입 절차, CSAP 인증, 계약 안내)
query: "주식 매매 수수료가 얼마예요?"
판정: out_of_domain, confidence=0.95
이유: 주식 매매 수수료는 금융 거래 도메인 — SaaS 도입 자문과 의미적 연결 없음.

예시 2 (in_domain):
agent: "공공기관 SaaS 도입 자문 봇" (클라우드 SaaS 도입 절차, CSAP 인증, 계약 안내)
query: "공공기관 클라우드 CSAP 인증 절차 알려줘"
판정: in_domain, confidence=0.92
이유: CSAP 인증은 공공 SaaS 도입의 핵심 절차 — 명백히 in-scope.

예시 3 (in_domain — 표현 주의):
agent: "공공기관 SaaS 도입 자문 봇" (클라우드 SaaS 도입 절차, CSAP 인증, 계약 안내)
query: "SaaS 이용 수수료 기준이 어떻게 돼요?"
판정: in_domain, confidence=0.82
이유: "수수료" 단어가 있어도 SaaS 계약·비용 맥락 — agent 의 in-scope.

## 응답 형식 (JSON only)
{"domain": "in_domain" | "out_of_domain", "confidence": 0.0~1.0, "reason": "한 문장"}
"""

_LLM_JUDGE_USER_TMPL = """agent 정보:
이름: {agent_name}
역할/목적: {agent_goal}
guidelines (첫 500자):
{guidelines_excerpt}

---
사용자 발화: {query}

위 사용자 발화는 이 agent 의 도메인 안(in_domain)인가요, 명백히 벗어나는(out_of_domain)건가요?
JSON 으로만 응답하세요."""


async def intent_gate_llm_judge(
    user_message: str,
    agent_ctx: Any,
) -> dict[str, Any]:
    """LLM judge — agent guidelines 와 사용자 발화 의미 거리 판정.

    Returns:
        {
          "domain": "in_domain" | "out_of_domain",
          "confidence": float,
          "reason": str,
          "error": str | None,  # LLM 호출 실패 시 채워짐
        }
    Fail-open: LLM 실패 시 in_domain 반환 (회귀 최소화).
    """
    guidelines_md = getattr(agent_ctx, "guidelines_md", None) or ""
    agent_name = getattr(agent_ctx, "name", None) or ""
    agent_goal = getattr(agent_ctx, "goal", None) or ""

    if not guidelines_md:
        # guidelines 없으면 LLM 판단 불가 — in_domain pass-through.
        return {"domain": "in_domain", "confidence": 0.7, "reason": "no_guidelines", "error": None}

    user_prompt = _LLM_JUDGE_USER_TMPL.format(
        agent_name=agent_name,
        agent_goal=agent_goal,
        guidelines_excerpt=guidelines_md[:500],
        query=user_message,
    )

    try:
        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router

        resp = await llm_router.route(
            task=LLMTask.CHAT_INTENT,
            request=LLMRequest(
                prompt=user_prompt,
                system_prompt=_LLM_JUDGE_SYSTEM,
                max_tokens=150,
                temperature=0.1,
                response_format="json",
            ),
        )
        raw = (getattr(resp, "text", None) or "").strip()
        # JSON 파싱 — ```json ... ``` 래핑 허용.
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw).rstrip("`").strip()
        data = json.loads(raw)
        domain = str(data.get("domain", "in_domain"))
        if domain not in ("in_domain", "out_of_domain"):
            domain = "in_domain"
        confidence = float(data.get("confidence") or 0.7)
        reason = str(data.get("reason") or "")
        return {"domain": domain, "confidence": confidence, "reason": reason, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {
            "domain": "in_domain",
            "confidence": 0.7,
            "reason": "llm_judge_failed",
            "error": str(exc),
        }


async def intent_gate_check_async(user_message: str, agent_ctx: Any) -> dict[str, Any]:
    """Async intent gate — keyword 1차 필터 + LLM judge 2차 보강.

    1단계: keyword match (동기, 빠름). 매칭 시 즉시 reject.
    2단계: keyword 미매칭 + LLM judge 활성 + guidelines 존재 → LLM 판정.
           out_of_domain 판정 시 reject (delegate 분기 대상).
    3단계: LLM 실패 → fail-open (in_domain 통과).

    Returns: 동일 스키마 as intent_gate_check — engine.py 에서 동기/비동기 모두 호환.
    """
    # D78 — 분모 metric.
    try:
        from src.common.metrics import inc_guard_input
        inc_guard_input("intent_gate")
    except Exception:  # noqa: BLE001
        pass

    if not _is_enabled():
        return {"enabled": False, "reject": False, "confidence": 1.0, "matched": [], "reason": "disabled"}

    if agent_ctx is None:
        return {"enabled": True, "reject": False, "confidence": 1.0, "matched": [], "reason": "no_agent_context"}

    if getattr(agent_ctx, "is_admin", False) or getattr(agent_ctx, "kind", "role") == "admin":
        return {"enabled": True, "reject": False, "confidence": 1.0, "matched": [], "reason": "admin_bypass"}

    # --- Stage 1: keyword match (fast path) ---
    res = domain_match_score(user_message, agent_ctx)
    matched = res["matched"]
    score = res["score"]

    if matched:
        # 키워드 매칭 → 즉시 reject.
        try:
            from src.common.metrics import inc_intent_gate_reject
            inc_intent_gate_reject("oos_keyword_match")
        except Exception:  # noqa: BLE001
            pass
        return {
            "enabled": True,
            "reject": True,
            "confidence": 0.0,
            "matched": matched,
            "reason": "oos_keyword_match",
        }

    # --- Stage 2: LLM judge (semantic, slower — runs when keyword miss) ---
    if _is_llm_judge_enabled():
        judge = await intent_gate_llm_judge(user_message, agent_ctx)
        if judge.get("error") is None and judge.get("domain") == "out_of_domain":
            judge_conf = float(judge.get("confidence") or 0)
            # Threshold: LLM 이 out_of_domain 이고 confidence >= 0.75 만 reject.
            # 0.75 미만은 경계 모호 → pass-through (false-positive 회피).
            if judge_conf >= 0.75:
                try:
                    from src.common.metrics import inc_intent_gate_reject
                    inc_intent_gate_reject("llm_judge_oos")
                except Exception:  # noqa: BLE001
                    pass
                return {
                    "enabled": True,
                    "reject": True,
                    "confidence": round(1.0 - judge_conf, 3),
                    "matched": [],
                    "reason": "llm_judge_out_of_domain",
                    "llm_judge_confidence": judge_conf,
                    "llm_judge_reason": judge.get("reason", ""),
                }

    # --- Stage 3: pass-through ---
    reason = "no_keywords" if score == 1.0 else "in_domain_likely"
    return {
        "enabled": True,
        "reject": False,
        "confidence": score,
        "matched": [],
        "reason": reason,
    }


def build_oos_reject_message(agent_ctx: Any, matched: list[str]) -> str:
    """T2 거절 메시지. agent.name / goal 으로 personalize.

    매칭된 키워드는 사용자에게 노출하지 않음 (정중한 안내).
    """
    name = getattr(agent_ctx, "name", None) or "이 에이전트"
    goal = getattr(agent_ctx, "goal", None) or ""
    persona_short = (goal or "").strip().split("\n", 1)[0][:60] or name
    return (
        f"죄송합니다. 이 상담은 {name} 전용입니다 ({persona_short}). "
        f"문의하신 내용은 해당 도메인을 다루는 다른 채널/서비스 또는 사람 상담사를 통해 "
        f"확인 부탁드립니다."
    )


__all__ = [
    "domain_match_score",
    "intent_gate_check",
    "intent_gate_check_async",
    "intent_gate_llm_judge",
    "build_oos_reject_message",
]
