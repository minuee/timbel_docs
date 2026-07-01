"""Qwen3.5-35B-A3B vLLM OpenAI-compatible 클라이언트."""

import base64
import time
from collections.abc import AsyncIterator

import openai

from src.common.config import settings
from src.common.llm.base import (
    BaseLLMClient,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    LLMVisionRequest,
)
from src.common.logging import get_logger

log = get_logger(__name__)


class QwenLLMClient(BaseLLMClient):
    """Qwen3.5-35B-A3B via vLLM — 대량 배치, 표 요약, 비용 효율 작업에 최적."""

    def __init__(
        self,
        url: str | None = None,
        model: str | None = None,
        label: str = "primary",
    ) -> None:
        self._client = openai.AsyncOpenAI(
            base_url=url or settings.VLLM_URL,
            api_key=settings.VLLM_API_KEY or "dummy",
            timeout=120.0,  # SSH 터널 레이턴시 + 긴 프롬프트 처리 여유
        )
        self._model = model or settings.VLLM_MODEL
        self._label = label  # used in logs to distinguish primary vs fallback endpoints

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """텍스트 생성."""
        start = time.monotonic()

        messages: list[dict] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        # vLLM Structured Output (OpenAI 호환 json_schema) — 100% 유효 JSON 보장
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.guided_json is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "schema": request.guided_json,
                },
            }

        response = await self._client.chat.completions.create(**kwargs)

        latency_ms = int((time.monotonic() - start) * 1000)
        text = response.choices[0].message.content or ""

        log.debug(
            "qwen_generate",
            endpoint=self._label,
            model=self._model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            latency_ms=latency_ms,
        )

        _usage = response.usage
        _details = getattr(_usage, "prompt_tokens_details", None) if _usage else None
        return LLMResponse(
            text=text,
            model=self._model,
            usage={
                "input_tokens": _usage.prompt_tokens if _usage else 0,
                "output_tokens": _usage.completion_tokens if _usage else 0,
                "cached_tokens": getattr(_details, "cached_tokens", None),  # prefix cache 측정
            },
            latency_ms=latency_ms,
        )

    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Qwen 스트리밍 텍스트 생성. OpenAI SDK stream=True 사용."""
        messages: list[dict] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stream=True,
        )

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if choice is None:
                continue
            delta_content = choice.delta.content or ""
            finish_reason = choice.finish_reason

            if delta_content:
                yield LLMStreamChunk(text=delta_content, model=self._model)

            if finish_reason:
                log.debug(
                    "qwen_stream_complete",
                    endpoint=self._label,
                    model=self._model,
                    finish_reason=finish_reason,
                )
                yield LLMStreamChunk(
                    text="",
                    model=self._model,
                    finish_reason=finish_reason,
                )

    async def generate_vision(self, request: LLMVisionRequest) -> LLMResponse:
        """이미지 입력 기반 생성 (Qwen Vision)."""
        start = time.monotonic()

        content: list[dict] = []
        for img_bytes in request.images:
            b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                }
            )
        content.append({"type": "text", "text": request.prompt})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],
            max_tokens=request.max_tokens,
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        return LLMResponse(
            text=response.choices[0].message.content or "",
            model=self._model,
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            latency_ms=latency_ms,
        )
