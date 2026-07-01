"""Ack generator — 즉시 ack (E2B @7020 wrapper, 300ms timeout, static fallback).

§C #1 (즉시 ack). Dual-model 의 핵심: 무거운 31B deep 모델 답변 전에 작은
E2B/E4B 모델로 <300ms 짧은 응답을 먼저 발화 → "잠시만요, 검색 중입니다" 식.

본 모듈은:
 - 환경변수 KMS_ACK_MODEL_URL (기본 None — 정적 fallback) 가 있으면 OpenAI
   호환 /v1/chat/completions 로 짧은 prompt 호출.
 - timeout 안에 응답 못 받으면 정적 ack 문자열로 fallback.

LLM 호출 실패 시도 fallback. 사용자 발화 분류 결과(intent) 가 주어지면
prompt 에 hint 로 포함.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import httpx

from src.common.logging import get_logger

log = get_logger(__name__)


# 정적 fallback ack — 한국어 짧은 자연어, 마크다운 없음 (TTS 친화).
DEFAULT_STATIC_ACKS: tuple[str, ...] = (
    "네, 잠시만요.",
    "확인해 보겠습니다.",
    "잠시만요, 살펴보고 있습니다.",
)


@dataclass(frozen=True)
class AckResult:
    text: str
    source: str  # "model" | "static" | "skipped"
    duration_ms: int


class AckGenerator:
    """ack 생성기.

    Parameters
    ----------
    base_url : str | None
        OpenAI 호환 ack 모델 base url (예: "http://localhost:7020/v1").
        None 이면 항상 static fallback 만.
    model : str
        모델 이름 (vLLM 의 served-model-name).
    timeout_ms : int
        LLM 호출 타임아웃 — 초과 시 fallback. 기본 300.
    static_acks : tuple[str, ...]
        fallback 풀.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str = "kms-ack",
        timeout_ms: int = 300,
        static_acks: tuple[str, ...] = DEFAULT_STATIC_ACKS,
        api_key: str = "EMPTY",
    ):
        self.base_url = (
            base_url
            if base_url is not None
            else os.environ.get("KMS_ACK_MODEL_URL")
        )
        self.model = model
        self.timeout_ms = max(50, timeout_ms)
        self.static_acks = tuple(static_acks)
        self.api_key = api_key
        self._round_robin = 0

    def _pick_static(self) -> str:
        if not self.static_acks:
            return "잠시만요."
        text = self.static_acks[self._round_robin % len(self.static_acks)]
        self._round_robin += 1
        return text

    async def generate(
        self,
        user_message: str,
        *,
        hint_intents: list[str] | None = None,
    ) -> AckResult:
        """짧은 ack 1 문장 반환. timeout/실패 시 static fallback.

        skipped(빈 입력) — base_url 없거나 user_message 빈 문자열.
        """
        if not user_message or not user_message.strip():
            return AckResult(text="", source="skipped", duration_ms=0)

        if not self.base_url:
            return AckResult(text=self._pick_static(), source="static", duration_ms=0)

        prompt = (
            "다음 사용자 발화에 대한 즉각적인 응대 한 문장을 한국어로, 15자 이내로 만드세요. "
            '예: "네, 잠시만요." / "확인해 보겠습니다." 다른 설명 없이 한 문장만 출력합니다.\n\n'
            f"발화: {user_message[:280]}\n"
        )
        if hint_intents:
            prompt += f"의도 후보: {', '.join(hint_intents[:3])}\n"

        timeout_s = self.timeout_ms / 1000.0
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "당신은 빠른 응대 ack 모델입니다."},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 32,
                        "temperature": 0.3,
                    },
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                duration_ms = int((loop.time() - t0) * 1000)
                if resp.status_code != 200:
                    log.warning(
                        "ack_model_non_200",
                        status=resp.status_code,
                        duration_ms=duration_ms,
                    )
                    return AckResult(
                        text=self._pick_static(),
                        source="static",
                        duration_ms=duration_ms,
                    )
                payload = resp.json()
                text = (
                    (payload.get("choices") or [{}])[0]
                    .get("message", {})
                    .get("content", "")
                ).strip()
                if not text:
                    return AckResult(
                        text=self._pick_static(),
                        source="static",
                        duration_ms=duration_ms,
                    )
                # 30 자 안전 truncate
                if len(text) > 30:
                    text = text[:30].rstrip()
                return AckResult(
                    text=text, source="model", duration_ms=duration_ms
                )
        except (httpx.TimeoutException, asyncio.TimeoutError):
            duration_ms = int((loop.time() - t0) * 1000)
            log.info(
                "ack_model_timeout",
                duration_ms=duration_ms,
                budget_ms=self.timeout_ms,
            )
            return AckResult(
                text=self._pick_static(), source="static", duration_ms=duration_ms
            )
        except (httpx.HTTPError, OSError) as e:
            duration_ms = int((loop.time() - t0) * 1000)
            log.warning(
                "ack_model_failed",
                error=str(e),
                duration_ms=duration_ms,
            )
            return AckResult(
                text=self._pick_static(), source="static", duration_ms=duration_ms
            )
