"""OpenAI-compatible Vision LLM 클라이언트 (vLLM + Gemma 4).

vLLM 서빙 엔드포인트를 OpenAI-compatible API로 호출한다.
1회 재시도, 구조화된 에러 핸들링 포함.
"""

from __future__ import annotations

import base64
import json
import re
import time
from uuid import UUID as _UUID

import openai

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# LLM 비용 추정 (self-hosted = 0)
# ---------------------------------------------------------------------------
_COST_PER_1K: dict[str, tuple[float, float]] = {
    "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit": (0.0, 0.0),
    "gemma-4-26b-a4b": (0.0, 0.0),
}


async def _log_llm_usage(
    model: str,
    task: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    tenant_id: _UUID | None = None,
    document_id: _UUID | None = None,
) -> None:
    """LLM 사용량을 DB에 기록한다 (fire-and-forget, 실패 시 로그만)."""
    try:
        from src.core.database import async_session_factory
        from src.core.models.llm_usage import LLMUsage

        rates = _COST_PER_1K.get(model, (0.0, 0.0))
        cost_usd = (input_tokens / 1000.0) * rates[0] + (output_tokens / 1000.0) * rates[1]

        async with async_session_factory() as session:
            usage = LLMUsage(
                tenant_id=tenant_id,
                model=model,
                task=task,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                cost_usd=round(cost_usd, 6),
                document_id=document_id,
            )
            session.add(usage)
            await session.commit()
    except Exception as exc:
        log.warning("llm_usage_log_failed", error=str(exc))

# 최대 재시도 횟수
_MAX_RETRIES = 1


class VisionLLMClient:
    """OpenAI-compatible Vision API 클라이언트 (vLLM + Gemma 4)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model or settings.VLLM_MODEL
        self._client = openai.AsyncOpenAI(
            api_key=api_key or settings.VLLM_API_KEY or "dummy",
            base_url=base_url or settings.VLLM_URL,
        )

    async def call(
        self,
        prompt: str,
        images: list[bytes] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        task: str = "general",
        tenant_id: _UUID | None = None,
        document_id: _UUID | None = None,
    ) -> str:
        """Vision LLM 호출. 이미지 + 텍스트 동시 전달. 1회 재시도."""
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                start = time.monotonic()

                text, usage_info = await self._call_openai(
                    prompt, images, max_tokens, temperature
                )

                latency_ms = int((time.monotonic() - start) * 1000)
                log.info(
                    "llm_call_success",
                    model=self._model,
                    latency_ms=latency_ms,
                    attempt=attempt + 1,
                    image_count=len(images) if images else 0,
                    prompt_len=len(prompt),
                )

                await _log_llm_usage(
                    model=self._model,
                    task=task,
                    input_tokens=usage_info.get("input_tokens", 0),
                    output_tokens=usage_info.get("output_tokens", 0),
                    latency_ms=latency_ms,
                    tenant_id=tenant_id,
                    document_id=document_id,
                )

                return text

            except openai.RateLimitError as e:
                last_error = e
                log.warning("llm_rate_limit", model=self._model, attempt=attempt + 1, error=str(e))
            except openai.APIError as e:
                last_error = e
                log.warning("llm_api_error", model=self._model, attempt=attempt + 1, error=str(e))
            except Exception as e:
                last_error = e
                log.error("llm_unexpected_error", model=self._model, attempt=attempt + 1, error=str(e))
                if attempt >= _MAX_RETRIES:
                    break

        raise RuntimeError(
            f"LLM 호출 실패 (model={self._model}, retries={_MAX_RETRIES}): {last_error}"
        )

    async def _call_openai(
        self,
        prompt: str,
        images: list[bytes] | None,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict]:
        """OpenAI-compatible API 호출 (vLLM). (텍스트, 사용량 dict) 반환."""
        content: list[dict] = []
        if images:
            for img_bytes in images:
                b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    }
                )
        content.append({"type": "text", "text": prompt})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens,
            temperature=temperature,
        )

        usage_info = {}
        if response.usage:
            usage_info = {
                "input_tokens": response.usage.prompt_tokens or 0,
                "output_tokens": response.usage.completion_tokens or 0,
            }

        return response.choices[0].message.content or "", usage_info

    @staticmethod
    def parse_json(text: str) -> dict | list:
        """LLM 응답에서 JSON 추출."""
        cleaned = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
        cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)
        cleaned = cleaned.strip()

        code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        if code_block:
            cleaned = code_block.group(1).strip()

        if cleaned and cleaned[0] not in ("{", "["):
            for start_char in ("{", "["):
                start = cleaned.find(start_char)
                if start >= 0:
                    end_char = "}" if start_char == "{" else "]"
                    end = cleaned.rfind(end_char)
                    if end > start:
                        cleaned = cleaned[start : end + 1]
                        break

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("json_parse_failed", text_preview=cleaned[:200])
            return {}
