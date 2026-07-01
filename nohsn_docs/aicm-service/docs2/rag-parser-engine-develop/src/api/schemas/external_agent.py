"""OpenAI Chat Completions 호환 schema (dispatch #150, 2026-05-07).

Endpoint: ``POST /api/v1/external/agent/{agent_id}/chat/completions``

OpenAI Python/JS SDK / LangChain / Vercel AI SDK 등이 base_url 만 바꾸면 그대로 사용
가능. spec: docs/superpowers/specs/2026-05-07-openai-compatible-endpoint.md

GPT-5 P0/P1 fix 반영:
- 알 수 없는 필드 수용하되 무시 (model_config = ConfigDict(extra='allow'))
- content 는 str 만 (multimodal array 는 router 에서 400)
- 마지막 message role 은 user 또는 assistant
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """OpenAI chat message — role + content.

    content 는 string 만 (multimodal content-parts array 는 router 에서 400).
    name / tool_call_id 등 추가 필드는 OpenAI 호환을 위해 수용 (extra='allow').
    """

    model_config = ConfigDict(extra="allow")

    role: Literal["system", "user", "assistant", "tool", "function"]
    # content 는 str | list[dict] 둘 다 허용 (multimodal). 단 router 가 array 시
    # 400 으로 거절. None 도 허용 — assistant 가 tool_calls 만 있는 경우 OpenAI 형식.
    content: str | list[Any] | None = None


class ChatCompletionRequest(BaseModel):
    """OpenAI Chat Completions request body.

    필수: messages (마지막은 user 또는 assistant).
    optional: stream, model (무시), temperature, max_tokens, ... (모두 수용 후 무시).
    알 수 없는 OpenAI 표준 필드 (top_p, n, presence_penalty, frequency_penalty, stop,
    user, response_format, logit_bias, logprobs, seed, metadata, stream_options …) 도
    400 X — extra='allow' 로 수용.
    """

    model_config = ConfigDict(extra="allow")

    messages: list[ChatMessage] = Field(..., min_length=1)
    stream: bool = False
    model: str | None = None  # 무시 — agent_id 가 진실
    temperature: float | None = None
    max_tokens: int | None = None


# ---------------------------------------------------------------------------
# Non-streaming response
# ---------------------------------------------------------------------------


class ChatCompletionResponseMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatCompletionResponseMessage
    finish_reason: Literal["stop", "length", "content_filter", "tool_calls"]


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage


# ---------------------------------------------------------------------------
# Streaming chunk (SSE)
# ---------------------------------------------------------------------------


class ChatCompletionDelta(BaseModel):
    """Streaming chunk delta — role 또는 content 둘 중 하나만 (또는 빈 dict).

    GPT-5 P1/10:
    - 첫 chunk: ``{"role": "assistant"}`` 만.
    - 후속 chunk: ``{"content": "..."}`` 만.
    - 마지막 chunk: ``{}`` (빈 dict) + finish_reason set.
    """

    model_config = ConfigDict(extra="allow")

    role: Literal["assistant"] | None = None
    content: str | None = None


class ChatCompletionChunkChoice(BaseModel):
    index: int
    delta: ChatCompletionDelta
    finish_reason: Literal["stop", "length", "content_filter", "tool_calls"] | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice]


# ---------------------------------------------------------------------------
# Error response (OpenAI 호환)
# ---------------------------------------------------------------------------


class OpenAIError(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class OpenAIErrorEnvelope(BaseModel):
    error: OpenAIError
