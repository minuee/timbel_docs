"""vLLM ↔ agent_framework LLM Protocol 어댑터.

agent_framework 의 SlotFiller / ResponseGenerator / FallbackRouter 는
단순한 `complete(system, user, *, response_format)` / `stream(system, user)`
시그니처의 Protocol 을 기대한다. 반면 프로젝트의 공용 LLM 은
`src.common.llm.router.llm_router` (LLMRequest/LLMResponse + LLMTask 라우팅)
형태이므로, 이 얇은 어댑터를 거쳐 연결한다.

Task 14 도입 — Skill runtime 이 기존 vLLM 파이프라인을 재사용하게 해서
chat 엔드포인트에서 별도 LLM 연결을 만들지 않도록 한다.

Task 24.5 확장 — ``user`` 가 OpenAI vision 포맷 ``list[dict]`` (멀티모달) 이면
llm_router 를 우회하고 vLLM OpenAI API 를 httpx 로 직접 호출한다. circuit
breaker 는 텍스트-only 경로에만 적용되지만, 멀티모달은 채팅창에서만 쓰이고
빈도가 낮아 트레이드오프 허용.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from src.common.config import settings
from src.common.llm.base import LLMRequest, LLMTask
from src.common.llm.router import llm_router


class VLLMAdapter:
    """`complete()` + `stream()` 을 제공하는 단일 어댑터.

    내부적으로 ``llm_router`` 싱글턴을 재사용 — circuit breaker, 동시성 가드,
    통계 수집이 그대로 적용된다 (str user 일 때).  list user 는 vLLM 직접 호출.
    """

    def __init__(self, task: LLMTask = LLMTask.RAG_GENERATION) -> None:
        self._task = task
        # 멀티모달 경로용 vLLM OpenAI-compatible 엔드포인트 (llm_router 우회)
        self._vllm_base = getattr(settings, "VLLM_URL", None) or getattr(
            settings, "SLLM_GEMMA_URL", "http://vllm:8000/v1"
        )
        self._vllm_model = getattr(settings, "VLLM_MODEL", None) or getattr(
            settings, "SLLM_GEMMA_MODEL", "gemma-4"
        )

    async def _call(
        self,
        system: str,
        user: str | list[dict],
        *,
        response_format: str | None = None,
        model: str | None = None,
    ) -> tuple[str, dict]:
        """str-user 와 list-user 경로를 통합한 private 구현체.

        항상 ``(text, usage_dict)`` 를 반환한다.  usage_dict 는 키 구조::

            {
                "prompt_tokens": int | None,
                "completion_tokens": int | None,
                "total_tokens": int | None,
                "cached_tokens": int | None,  # prefix cache hit — None if absent
            }

        ``resp.usage`` 가 None 이더라도 (circuit-breaker fallback 등) usage_dict
        는 항상 dict 로 반환되어 caller 에서 None 체크가 불필요하다.

        ``model`` 이 None 이면 llm_router 의 기본 모델 (31B) 사용.
        str 이면 vLLM OpenAI-compatible API 를 직접 호출해 해당 모델로 요청.
        기존 caller 는 model 인자 없이 호출하므로 동작 byte-equal.
        """
        # D28 §3 — 분기 조건 명명 + LLMRequest 통합 TODO.
        # `_use_router_path` 는 router 능력 한계의 fallback 분기이지 진짜 결함이 아니다
        # (GPT-5 phase0 PASS).
        #
        # 두 path 의 의미:
        #   - router_path  : llm_router.route() 사용. circuit breaker / 동시성 가드 /
        #                    통계 수집 모두 적용. 단, str user + 기본 모델만 가능.
        #   - direct_path  : vLLM OpenAI-compat API 를 httpx 로 직접 호출. 이유:
        #                    (a) list[dict] (멀티모달 vision content) — llm_router
        #                        의 LLMRequest schema 가 content-part list 미지원
        #                    (b) model override — LLMRequest 가 model 필드를 안 가짐
        #
        # TODO (별도 PR): LLMRequest 에 ``model: str | None`` + ``multimodal_content:
        # list[dict] | None`` 필드 도입 후, llm_router 계층이 (i) 멀티모달 message
        # 직렬화/검증, (ii) model override 전달 (모델 선택 로직/메트릭 라벨 포함),
        # (iii) 필요 시 스트리밍/툴콜 부가 기능까지 지원하도록 확장 → 본 분기 단일
        # router path 로 통합. circuit breaker / 통계 수집을 모든 호출에 적용 가능.
        # 본 PR (D28) 은 작은 변경 우선 — 큰 refactor 분리.
        _use_router_path: bool = isinstance(user, str) and model is None
        if _use_router_path:
            request = LLMRequest(
                prompt=user,
                system_prompt=system,
                max_tokens=2048,
                temperature=0.0,
                response_format=response_format,
            )
            resp = await llm_router.route(task=self._task, request=request)
            # resp.usage 가 None 이거나 dict 가 아닐 수 있음 (circuit-breaker fallback 등) — null-safety
            raw = getattr(resp, "usage", None)
            if not isinstance(raw, dict):
                raw = {}
            prompt_details = (raw.get("prompt_tokens_details") if isinstance(raw, dict) else None) or {}
            usage: dict = {
                "prompt_tokens": raw.get("prompt_tokens"),
                "completion_tokens": raw.get("completion_tokens"),
                "total_tokens": raw.get("total_tokens"),
                "cached_tokens": prompt_details.get("cached_tokens") if prompt_details else raw.get("cached_tokens"),
            }
            return resp.text, usage

        # model override (str user) — vLLM 직접 호출로 지정 모델 사용.
        # 멀티모달 (list user) 도 동일 경로 — model 인자 우선, 없으면 self._vllm_model.
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        used_model = model if model is not None else self._vllm_model
        payload: dict = {
            "model": used_model,
            "messages": messages,
            "max_tokens": 2048,
            "temperature": 0.0,
        }
        if response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{self._vllm_base}/chat/completions", json=payload
            )
            r.raise_for_status()
            data = r.json()
        text = data["choices"][0]["message"]["content"]
        raw_usage = data.get("usage") or {}
        details = raw_usage.get("prompt_tokens_details") or {}
        usage = {
            "prompt_tokens": raw_usage.get("prompt_tokens"),
            "completion_tokens": raw_usage.get("completion_tokens"),
            "total_tokens": raw_usage.get("total_tokens"),
            "cached_tokens": details.get("cached_tokens"),
        }
        return text, usage

    async def complete(
        self,
        system: str,
        user: str | list[dict],
        *,
        response_format: str | None = None,
        model: str | None = None,
    ) -> str:
        """단일-턴 비스트리밍 generation.

        ``user`` 가 str 이면 기존 llm_router 경로 — circuit breaker/동시성 가드
        재사용.  list[dict] (OpenAI vision content 포맷) 이면 vLLM chat/completions
        API 를 httpx 로 직접 호출.

        ``model`` 이 None 이 아니면 llm_router 를 우회하고 vLLM 직접 호출로
        해당 모델 사용 (PLAN_MODEL_SMALL 등 small-model override 경로). 기존
        caller 는 model 인자 없이 호출하므로 동작 byte-equal.

        내부적으로 ``_call`` 에 위임하고 text 만 반환한다.
        """
        text, _ = await self._call(system, user, response_format=response_format, model=model)
        return text

    async def complete_with_usage(
        self,
        system: str,
        user: str | list[dict],
        *,
        response_format: str | None = None,
        model: str | None = None,
    ) -> tuple[str, dict]:
        """complete() 와 동일하되 (text, usage) 튜플 반환.

        usage dict 는 항상 dict (None 불가) — ``_call`` 이 null-safety 를 보장.

        usage dict 구조::

            {
                "prompt_tokens": int | None,
                "completion_tokens": int | None,
                "total_tokens": int | None,
                "cached_tokens": int | None,  # prefix cache hit — None if unavailable
            }

        ``model`` override — complete() 와 동일하게 None 이면 기본 31B.
        기존 complete_with_usage() caller 는 영향 없음 — 이 메서드는 추가 노출 전용.
        """
        return await self._call(system, user, response_format=response_format, model=model)

    async def stream(
        self,
        system: str,
        user: str | list[dict],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """토큰 스트림.

        str user → llm_router.route_stream 재사용.
        list user → vLLM /chat/completions stream=True 직접 SSE 파싱.

        ``temperature`` / ``max_tokens`` 인자는 default 가 기존 0.3 / 2048 이라
        기존 caller (skill_v2_persona_answer 등) 동작 byte-equal.  L2 P0
        latency (2026-05-07) 의 _llm_compose_tool_answer_stream 만 *0.0* 으로
        호출 — non-stream complete() 와 디코딩 파라미터 일치 (GPT-5 권고).
        """
        if isinstance(user, str):
            request = LLMRequest(
                prompt=user,
                system_prompt=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            async for chunk in llm_router.route_stream(task=self._task, request=request):
                if chunk.text:
                    yield chunk.text
            return

        # 멀티모달 스트림
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        payload = {
            "model": self._vllm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", f"{self._vllm_base}/chat/completions", json=payload
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    chunk = line[len("data: "):].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        d = json.loads(chunk)
                        delta = d["choices"][0].get("delta", {}).get("content")
                        if delta:
                            yield delta
                    except Exception:
                        continue

    async def chat_completion_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        stream: bool = False,
    ) -> dict:
        """OpenAI-compatible chat completion with tools/function calling.

        tool-calling loop 전용. 기존 complete()/stream() 과 별개 경로.

        NOTE: Gemma 4 가 vLLM pythonic tool parser 와 맞지 않는 출력을 내서
        실제 프로덕션 경로에서는 사용하지 않음 (JSON 모드로 대체).
        후속 vLLM 버전이 Gemma tool parser 지원하면 재활성화 가능.
        """
        payload = {
            "model": self._vllm_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 1024,
            "stream": stream,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{self._vllm_base}/chat/completions", json=payload)
            r.raise_for_status()
            return r.json()

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        response_format: str | None = None,
    ) -> str:
        """KC `_call_llm` 의 generic fallback (`hasattr(client, "generate")`) 호환.

        KC `_call_llm` 는 `await self._llm_client.generate(prompt)` 시그니처를
        기대하므로 단일 `prompt: str` 입력으로 LLM 응답 문자열을 반환한다.

        구현: 내부적으로 `complete()` 를 호출하되 system 기본값은
        ``"You are a helpful Korean AI assistant."`` — KC prompt 들은 자체적으로
        system instruction 까지 포함하므로 가벼운 기본 system 만 주입.

        `_call()` 은 내부적으로 max_tokens=2048, temperature=0.0 사용 — KC 의
        per-call decoding 파라미터 (temperature 0.1~0.3, max_tokens 200~1200) 와
        다르지만, KC 의 topic_tags/search_summary 응답 길이는 모두 1200 이하라
        잘림 없음. 정밀 제어 필요 시 후속 PR 로 `_call()` 시그니처 확장.

        D40 Phase A — KC ↔ VLLMAdapter 인터페이스 불일치 (topic_tags 0%) 해소.
        기존 caller (KC 외) 는 영향 없음 — 신규 메서드.
        """
        sys_prompt = system if system is not None else (
            "You are a helpful Korean AI assistant. "
            "사용자 지시에 정확히 따라 응답하세요."
        )
        text, _ = await self._call(
            sys_prompt,
            prompt,
            response_format=response_format,
            model=None,
        )
        return text

    async def chat_completion_json(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        """OpenAI chat completion with response_format=json_object. content 반환.

        Task 26-B: tool-calling loop 가 JSON 모드 클라이언트 파싱 방식으로
        전환하면서 사용. Gemma 는 매 턴 단일 JSON 객체만 출력하도록 system
        프롬프트로 강제되고, 이 메서드는 그 content 를 그대로 반환한다.
        """
        payload = {
            "model": self._vllm_model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(f"{self._vllm_base}/chat/completions", json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""


class IntentClassifierAdapter:
    """기존 `classify_intent` (bool 기반) 를 skill-level intent 리스트 형태로 어댑트.

    # DEPRECATED Task 14.5 — use MultiLabelIntentClassifier instead
    (제거는 Week 5 polish sweep 에서 일괄. dependencies.py 에서는 이미 사용 안함.)

    KMS-Plus 설계에서는 각 스킬이 trigger intent 를 선언하는데, v1 에서는
    기존 분류기가 `search` boolean 만 반환한다. 현재 스킬 라우팅은 상세
    intent 레이블을 필요로 하므로 — 여기서는 안전한 기본 동작으로 `search=True`
    일 때 `general_query` 하나만 반환. 실제 multi-label 분류기는 별도 Task
    (Week 3 이후) 에서 교체한다.

    테스트 / 데모에서는 `classify_multi` 를 AsyncMock 으로 바꿔 직접 레이블을
    주입하는 것이 정석.
    """

    async def classify_multi(
        self,
        user_message: str,
        history: list[dict] | None = None,
    ) -> list[str]:
        from src.search.intent_classifier import classify_intent

        result = await classify_intent(user_message, conversation_history=history)
        return ["general_query"] if result.search else []
