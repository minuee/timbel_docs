"""Multi-skill orchestrator — 한 발화로 여러 skill 동시 실행 + 합성.

Wave Insight 의 핵심 컴포넌트.

흐름:
1. is_compound_query — LLM 이 발화가 cross-domain 합성을 필요로 하는지 판단.
2. select_subskills — eligible 한 read-only skill 들 중 LLM 이 sub-skill 선택 + args 결정.
3. 병렬 실행 — 각 sub-skill 의 ProcessRunner 를 independent 하게 advance.
4. synthesize — 결과들을 한국어 자연 답변으로 합성 (synthesizer 모듈).

안전:
- read_only & consequential=false 만 자동 호출 후보. write_external/irreversible 은 사용자 승인 경로 필요 → orchestrator 에서 자동 X.
- LLM 환각으로 등록 안 된 skill 이름 반환 시 필터.

LLM 인터페이스:
- callable (prompt: str) -> str | Awaitable[str]  (간단 형식)
- 또는 ``llm.generate(prompt) -> Awaitable[str]`` 객체  (지원)
- ProcessRunner 는 자체 LLMClient 를 별도 사용. orchestrator 의 LLM 은 합성/판단용.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Callable, Protocol

from src.agent_framework.llm.json_parse import extract_json


class _SkillProto(Protocol):
    name: str
    description: str
    side_effect_level: str
    consequential: bool


class MultiSkillOrchestrator:
    """LLM 으로 compound query 판단 + sub-skill 병렬 실행 + 합성.

    Args:
        llm_client: callable(prompt:str) -> str | Awaitable[str], 또는
                    ``.generate(prompt)`` 메서드를 가진 객체.
        skill_registry: ``.list_skills() -> list[SkillV2]`` 인터페이스.
        process_runner_factory: ``factory(skill_name=...) -> runner`` —
                    runner.advance(user_input=..., state=...) -> StepResult-like.
    """

    def __init__(
        self,
        *,
        llm_client: Any,
        skill_registry: Any,
        process_runner_factory: Callable[..., Any],
        grounding_fn: Callable[..., Any] | None = None,
    ):
        self.llm = llm_client
        self.registry = skill_registry
        self.runner_factory = process_runner_factory
        self.grounding_fn = grounding_fn

    # ------------------------------------------------------------------
    # 1. compound 판단
    # ------------------------------------------------------------------

    async def is_compound_query(self, user_text: str) -> dict:
        """발화가 multi-skill 합성을 필요로 하는지 판단.

        반환: ``{compound: bool, reason: str, required_domains: list[str]}``
        """
        prompt = f'''사용자 발화 분석. cross-domain 분석/의견/요약 같은 합성이 필요한지 판단.

발화: "{user_text}"

JSON 형식으로 출력:
{{
  "compound": true/false,
  "reason": "...",
  "required_domains": ["schedule","expense","health"...] 또는 []
}}

판단 원칙:
- compound=true: 여러 도메인 결합 (예 "일정 + 비용", "이번 달 분석", "패턴 의견", "한 달 돌아보기")
- compound=false: 단일 도메인 (예 "오늘 일정 알려줘", "지난주 지출 보여줘", "운동 기록 추가")
- required_domains 후보: schedule, expense, health, news, knowledge 등.
'''
        raw = await self._call_llm(prompt, json_mode=True, max_tokens=200)
        try:
            parsed = extract_json(raw)
            if isinstance(parsed, dict):
                return parsed
            return {"compound": False, "reason": "non_dict_response", "required_domains": []}
        except (ValueError, json.JSONDecodeError):
            return {
                "compound": False,
                "reason": "parse_failed",
                "required_domains": [],
                "raw_preview": str(raw)[:120],
            }

    # ------------------------------------------------------------------
    # 2. sub-skill 선택
    # ------------------------------------------------------------------

    async def select_subskills(
        self,
        *,
        user_text: str,
        required_domains: list[str],
        eligible_skills: list[_SkillProto],
    ) -> list[dict]:
        """LLM 으로 sub-skill 후보 + 각 args 결정. read_only 만 후보."""
        if not eligible_skills:
            return []
        skill_summary = "\n".join(
            f"- {s.name}: {s.description}" for s in eligible_skills
        )
        prompt = f'''사용자 발화에 답하기 위해 호출할 sub-skill 들을 선택. 각 skill 의 args 도 결정.

발화: "{user_text}"
필요 도메인: {required_domains}

가능한 skill (모두 read_only 자동 호출 가능):
{skill_summary}

JSON 출력:
{{
  "subskills": [
    {{"name": "...", "args": {{...}}, "rationale": "..."}}
  ]
}}

원칙:
- skill 이름은 위 목록에 있는 것만. 없으면 빈 리스트.
- args 는 skill 이 elicit 으로 받을 슬롯들 — 발화에서 추출한 값(period_start/period_end 등).
- 발화와 관련 없는 skill 은 포함하지 말 것.
'''
        raw = await self._call_llm(prompt, json_mode=True, max_tokens=600)
        try:
            parsed = extract_json(raw)
        except (ValueError, json.JSONDecodeError):
            return []
        subs = parsed.get("subskills") if isinstance(parsed, dict) else None
        if not isinstance(subs, list):
            return []
        # 등록된 skill 만 통과
        names = {s.name for s in eligible_skills}
        out: list[dict] = []
        for s in subs:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name", "")).strip()
            if name and name in names:
                out.append(
                    {
                        "name": name,
                        "args": dict(s.get("args") or {}),
                        "rationale": str(s.get("rationale", "")),
                    }
                )
        return out

    # ------------------------------------------------------------------
    # 3. 메인 진입점 — 한 turn 처리
    # ------------------------------------------------------------------

    async def run(
        self,
        *,
        user_text: str,
        account: dict | None = None,
        tenant: dict | None = None,
        persona: dict | None = None,
        ledger_snapshot: dict | None = None,
    ) -> dict:
        """compound 판단 → subskill 선택 → 병렬 실행 → 합성 (Wave 6).

        Wave 6 변경:
        - sub-skill 별 grounding 병렬 retrieval (self.grounding_fn 주입 시)
        - synthesizer 시그니처 확장 — persona/domain_summary/grounding_docs_merged/ledger 전달
        - synthesizer 반환 SynthesizeResult — answer/confidence/missing_info/used_blocks

        반환:
        - compound=False:  ``{compound: False, reason: ...}``
        - 정상:  ``{compound: True, subskills, sub_results, answer, confidence,
                    missing_info, used_blocks, grounding_docs_merged, domain_summary}``
        """
        compound = await self.is_compound_query(user_text)
        if not compound.get("compound"):
            return {"compound": False, "reason": compound.get("reason", "")}

        # eligible: read_only & consequential=false
        all_skills = list(self.registry.list_skills())
        eligible = [
            s
            for s in all_skills
            if getattr(s, "side_effect_level", "read_only") == "read_only"
            and not getattr(s, "consequential", False)
        ]

        subs = await self.select_subskills(
            user_text=user_text,
            required_domains=list(compound.get("required_domains") or []),
            eligible_skills=eligible,
        )
        if not subs:
            return {"compound": True, "subskills": [], "answer": None,
                    "confidence": 0.0, "sub_results": []}

        # sub-skill catalog (eligible 안에서 lookup)
        catalog: dict[str, Any] = {getattr(s, "name", ""): s for s in eligible}

        # 병렬 실행 — sub-skill 별 grounding + advance(auto)
        results = await asyncio.gather(
            *(self._run_one(
                spec,
                catalog=catalog,
                user_text=user_text,
                tenant=tenant,
                persona=persona,
            ) for spec in subs)
        )

        # grounding_docs 합본 + domain_summary 추출 (모든 sub-skill 의 grounding 통합)
        merged_docs: list[dict] = []
        seen_block_ids: set[str] = set()
        domain_summary: str | None = None
        for r in results:
            for g in (r.get("grounding_docs") or []):
                bid = str(g.get("block_id") or "")
                if bid and bid in seen_block_ids:
                    continue
                if bid:
                    seen_block_ids.add(bid)
                merged_docs.append(g)
            if not domain_summary and r.get("domain_summary"):
                domain_summary = r["domain_summary"]

        # 합성 (synthesizer.synthesize 위임 — Wave 6 시그니처)
        from src.agent_framework.skills.synthesizer import synthesize

        synth = await synthesize(
            user_text=user_text,
            sub_results=results,
            llm_client=self.llm,
            persona=persona,
            domain_summary=domain_summary,
            grounding_docs_merged=merged_docs,
            ledger_snapshot=ledger_snapshot,
        )
        if isinstance(synth, str):
            answer_text = synth
            confidence = 0.0
            missing_info = None
            used_blocks: list[str] = []
        else:
            answer_text = synth.answer_text
            confidence = synth.confidence
            missing_info = synth.missing_info
            used_blocks = synth.used_blocks
        return {
            "compound": True,
            "subskills": [r["name"] for r in results],
            "sub_results": results,
            "answer": answer_text,
            "confidence": confidence,
            "missing_info": missing_info,
            "used_blocks": used_blocks,
            "grounding_docs_merged": merged_docs,
            "domain_summary": domain_summary,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _run_one(
        self,
        spec: dict,
        *,
        catalog: dict | None = None,
        user_text: str | None = None,
        tenant: dict | None = None,
        persona: dict | None = None,
    ) -> dict:
        """단일 sub-skill 실행 — grounding + runner.advance(auto) + fragment_confidence.

        Wave 6 변경:
        - self.grounding_fn 주입 시 sub-skill 의 knowledge_scope 로 grounding 병렬
        - process_runner.advance 는 mode='auto' 권장 (compound 안 elicit 우회)
        - fragment_confidence 자리 (D 코스 hook)

        반환: ``{name, result?, error?, grounding_docs?, domain_summary?, answer_fragment?,
                  fragment_confidence?, used_blocks?}``
        """
        name = spec["name"]
        result: dict[str, Any] = {"name": name}

        # 1) grounding (옵션) — knowledge_scope 가 있으면 활용
        skill = (catalog or {}).get(name)
        knowledge_scope = []
        if skill is not None:
            role = getattr(skill, "role", None)
            knowledge_scope = list(getattr(role, "knowledge_scope", None) or [])

        if self.grounding_fn is not None and tenant and user_text:
            try:
                gpack = await self.grounding_fn(
                    tenant_id=tenant.get("tenant_id"),
                    tenant_kind=tenant.get("kind"),
                    tenant_slug=tenant.get("slug"),
                    query=user_text,
                    knowledge_scope=knowledge_scope,
                )
                if isinstance(gpack, dict):
                    result["grounding_docs"] = gpack.get("grounding_docs", [])
                    result["domain_summary"] = gpack.get("domain_summary")
            except Exception as e:  # noqa: BLE001
                result["grounding_error"] = str(e)[:160]

        # 2) advance — process 가 있을 때만
        try:
            runner = self.runner_factory(skill_name=name) if self.runner_factory else None
        except Exception as e:  # noqa: BLE001
            runner = None
            result["runner_error"] = str(e)[:160]

        if runner is not None:
            try:
                advance = getattr(runner, "advance", None)
                if advance is None:
                    result["error"] = "runner has no advance()"
                else:
                    # mode="auto" — compound 안에선 LLM auto-fill, interactive 미사용
                    try:
                        ret = advance(user_input=spec.get("args") or {}, state={}, mode="auto")
                    except TypeError:
                        # 옛 시그니처 (mode 인자 없음) backward compat
                        ret = advance(user_input=spec.get("args") or {}, state={})
                    if inspect.isawaitable(ret):
                        ret = await ret
                    if hasattr(ret, "response"):
                        payload = {
                            "response": ret.response,
                            "next_state": getattr(ret, "next_state", {}),
                            "done": getattr(ret, "done", False),
                        }
                    else:
                        payload = ret
                    result["result"] = payload
                    if isinstance(payload, dict) and payload.get("response"):
                        result["answer_fragment"] = str(payload["response"])[:1500]
            except Exception as e:  # noqa: BLE001
                result["error"] = str(e)[:200]

        # 3) fragment_confidence 는 D 코스 hook 자리 — 본 wave (C 코스만) 에서는 None
        result.setdefault("fragment_confidence", None)
        result.setdefault("used_blocks",
                          [g.get("block_id") for g in result.get("grounding_docs", []) if g.get("block_id")])
        return result

    async def _call_llm(
        self, prompt: str, *, json_mode: bool = False, max_tokens: int = 500
    ) -> str:
        """callable / .generate / .complete 모두 지원."""
        # callable form
        if callable(self.llm) and not hasattr(self.llm, "generate") and not hasattr(self.llm, "complete"):
            maybe = self.llm(prompt)
            if inspect.isawaitable(maybe):
                return await maybe
            return str(maybe)
        # .generate(prompt)
        gen = getattr(self.llm, "generate", None)
        if callable(gen):
            maybe = gen(prompt)
            if inspect.isawaitable(maybe):
                return await maybe
            return str(maybe)
        # .complete(system, user, response_format=...)
        comp = getattr(self.llm, "complete", None)
        if callable(comp):
            maybe = comp(
                "JSON 형식으로만 응답.",
                prompt,
                response_format="json_object" if json_mode else None,
            )
            if inspect.isawaitable(maybe):
                return await maybe
            return str(maybe)
        # callable 이지만 generate/complete 도 있는 경우 (위에서 못 잡음) — fallback
        if callable(self.llm):
            maybe = self.llm(prompt)
            if inspect.isawaitable(maybe):
                return await maybe
            return str(maybe)
        raise RuntimeError("llm_client not usable: needs callable or .generate/.complete")
