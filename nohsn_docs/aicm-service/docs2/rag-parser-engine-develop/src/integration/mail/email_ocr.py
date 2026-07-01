"""이메일 첨부 이미지 OCR — Vision LLM (gemma-4-31b) + sha256 기반 Redis 캐시.

호출 경로:
    webhook_inbound._create_inbound_document
        → metadata["_attachment_payloads"] (B1 산출물) 발견 시
            → ocr_email_attachments(payloads)
                → for each payload:
                    sha256 = sha256(base64.b64decode(data_base64))
                    cache hit  → ocr_text 즉시 반환 (LLM 호출 X)
                    cache miss → vLLM image_url chat completion → cache set (TTL 30d)

원칙:
- **이미지 attachment 만 OCR 대상**: content_type 이 image/* 또는 filename 확장자 화이트리스트.
- **5MB 초과 skip**: vLLM payload 한도 + 메모리 보호. data_base64 의 raw byte 길이 기준.
- **fail-soft**: LLM 호출 실패 시 ocr_text="(OCR 실패)" + warning 로그. 호출자 흐름 안 막음.
- **cache key**: ``email_ocr:<sha256>`` — 동일 이미지 (첨부/배경/배너) 두 번째 등장 시 LLM 호출 0.
- **cache value**: JSON ``{"ocr_text": "...", "summary": "..."}`` (TTL 30 day).

cache 메커니즘:
    Redis (kms-redis 컨테이너, REDIS_URL). _redis_store 의 별도 client 패턴 참조 —
    여기는 별도 namespace 라 자체 helper 로 충분.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

import redis.asyncio as aioredis

from src.common.config import settings
from src.common.llm.base import LLMTask, LLMVisionRequest
from src.common.llm.router import llm_router
from src.common.logging import get_logger

log = get_logger(__name__)


# ── 상수 ──────────────────────────────────────────────────────────────────

CACHE_KEY_PREFIX = "email_ocr"
CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 day

# vLLM payload 한도 + 메모리 보호. 디코딩된 raw byte 기준.
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB

# OCR prompt — JSON 파싱 의존 X. 평문 OCR 결과만.
_OCR_PROMPT = (
    "이 이미지에서 모든 텍스트를 한국어로 정확히 추출하라. "
    "광고/포스터/배너의 행사명·일자·장소·등록 안내 모두 포함. "
    "JSON 출력 X — 평문 OCR 결과만."
)

# image attachment 판별 — content_type 우선, 없으면 확장자 fallback.
_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}


# ── Redis 클라이언트 ──────────────────────────────────────────────────────


_redis_client: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis | None:
    """Redis 클라이언트 lazy init. 실패 시 None — cache miss 처럼 동작."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    url = os.environ.get("REDIS_URL", settings.REDIS_URL)
    try:
        _redis_client = aioredis.from_url(url, decode_responses=True)
        # 가벼운 ping 으로 연결 확인 — 실패 시 None 으로 폴백.
        await _redis_client.ping()
    except Exception as exc:  # noqa: BLE001
        log.warning("email_ocr_redis_unavailable", error=str(exc))
        _redis_client = None
    return _redis_client


# ── helpers ──────────────────────────────────────────────────────────────


def _is_image_payload(payload: dict[str, Any]) -> bool:
    """content_type 또는 filename 확장자로 이미지 여부 판단."""
    ct = str(payload.get("content_type") or "").lower()
    if ct.startswith("image/"):
        return True
    fn = str(payload.get("filename") or "").lower()
    if "." in fn:
        ext = fn.rsplit(".", 1)[-1]
        if ext in _IMAGE_EXTS:
            return True
    return False


def _compute_sha256(data_base64: str) -> tuple[str, bytes, int]:
    """base64 → (sha256_hex, raw_bytes, raw_len). 디코딩 실패 시 빈 결과."""
    try:
        raw = base64.b64decode(data_base64, validate=False)
    except Exception:  # noqa: BLE001
        return "", b"", 0
    return hashlib.sha256(raw).hexdigest(), raw, len(raw)


async def _cache_get(sha256: str) -> dict[str, Any] | None:
    r = await _get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(f"{CACHE_KEY_PREFIX}:{sha256}")
    except Exception as exc:  # noqa: BLE001
        log.debug("email_ocr_cache_get_failed", sha256=sha256[:12], error=str(exc))
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def _cache_set(sha256: str, value: dict[str, Any]) -> None:
    r = await _get_redis()
    if r is None:
        return
    try:
        await r.set(
            f"{CACHE_KEY_PREFIX}:{sha256}",
            json.dumps(value, ensure_ascii=False),
            ex=CACHE_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("email_ocr_cache_set_failed", sha256=sha256[:12], error=str(exc))


# ── vLLM vision 호출 ─────────────────────────────────────────────────────


async def _call_vision_ocr(raw_bytes: bytes) -> str:
    """vLLM gemma-4-31b vision 호출 → 평문 OCR 결과.

    실패 시 RuntimeError 전파 (호출자가 fallback 처리).
    """
    request = LLMVisionRequest(
        prompt=_OCR_PROMPT,
        images=[raw_bytes],
        max_tokens=1500,
    )
    response = await llm_router.route_vision(task=LLMTask.VISION_OCR, request=request)
    return (response.text or "").strip()


def _summarize(ocr_text: str, max_len: int = 240) -> str:
    """OCR 결과 1-2줄 요약 — LLM 호출 X. 본문 첫 N자 + 줄바꿈 정리."""
    if not ocr_text:
        return ""
    flat = " ".join(line.strip() for line in ocr_text.splitlines() if line.strip())
    return flat[:max_len]


# ── public API ───────────────────────────────────────────────────────────


async def ocr_email_attachments(
    payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """첨부 payload 리스트 → OCR 결과 리스트.

    Args:
        payloads: ``[{filename, content_type, data_base64, sha256?}, ...]``

    Returns:
        ``[{filename, sha256, ocr_text, summary, cached: bool, skipped?: str}, ...]``
        — 이미지가 아닌 첨부는 결과에서 제외 (호출자가 OCR 결과만 본문 합성).
    """
    if not payloads:
        return []

    results: list[dict[str, Any]] = []
    for idx, payload in enumerate(payloads):
        if not isinstance(payload, dict):
            continue
        if not _is_image_payload(payload):
            log.debug(
                "email_ocr_skip_non_image",
                idx=idx,
                content_type=payload.get("content_type"),
                filename=payload.get("filename"),
            )
            continue

        data_b64 = str(payload.get("data_base64") or "")
        if not data_b64:
            continue

        # sha256 — payload 가 미리 계산해 줬으면 신뢰 X (검증 X 라 크리티컬 X 지만,
        # cache key 정합성 위해 항상 재계산).
        sha256, raw_bytes, raw_len = _compute_sha256(data_b64)
        if not sha256 or raw_len == 0:
            log.warning(
                "email_ocr_invalid_base64",
                filename=payload.get("filename"),
            )
            continue

        filename = str(payload.get("filename") or f"image_{idx}")

        # 5MB 초과 skip
        if raw_len > MAX_IMAGE_BYTES:
            log.warning(
                "email_ocr_skip_too_large",
                filename=filename,
                size_bytes=raw_len,
                limit=MAX_IMAGE_BYTES,
            )
            results.append(
                {
                    "filename": filename,
                    "sha256": sha256,
                    "ocr_text": "(이미지가 너무 커 OCR 생략)",
                    "summary": "",
                    "cached": False,
                    "skipped": "too_large",
                }
            )
            continue

        # cache hit
        cached = await _cache_get(sha256)
        if cached is not None and cached.get("ocr_text"):
            log.info(
                "email_ocr_cache_hit",
                filename=filename,
                sha256=sha256[:12],
                size_bytes=raw_len,
            )
            results.append(
                {
                    "filename": filename,
                    "sha256": sha256,
                    "ocr_text": str(cached.get("ocr_text") or ""),
                    "summary": str(
                        cached.get("summary")
                        or _summarize(str(cached.get("ocr_text") or ""))
                    ),
                    "cached": True,
                }
            )
            continue

        # cache miss → LLM 호출
        try:
            ocr_text = await _call_vision_ocr(raw_bytes)
            if not ocr_text:
                ocr_text = "(OCR 결과 없음)"
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "email_ocr_llm_failed",
                filename=filename,
                sha256=sha256[:12],
                error=str(exc),
            )
            ocr_text = "(OCR 실패)"

        summary = _summarize(ocr_text) if not ocr_text.startswith("(OCR ") else ""

        # 성공일 때만 cache 저장 — "(OCR 실패)" 는 다음 polling 에서 재시도.
        if not ocr_text.startswith("(OCR ") and ocr_text != "(OCR 결과 없음)":
            await _cache_set(
                sha256,
                {"ocr_text": ocr_text, "summary": summary},
            )
            log.info(
                "email_ocr_llm_done_cached",
                filename=filename,
                sha256=sha256[:12],
                ocr_len=len(ocr_text),
                size_bytes=raw_len,
            )
        else:
            log.info(
                "email_ocr_llm_no_cache",
                filename=filename,
                sha256=sha256[:12],
                ocr_text_kind=ocr_text[:20],
            )

        results.append(
            {
                "filename": filename,
                "sha256": sha256,
                "ocr_text": ocr_text,
                "summary": summary,
                "cached": False,
            }
        )

    return results


def render_ocr_block(ocr_results: list[dict[str, Any]]) -> str:
    """OCR 결과 리스트 → 본문 합성용 평문 블록.

    형식:
        [첨부 이미지 OCR — filename1.png]
        ... text ...

        [첨부 이미지 OCR — filename2.jpg]
        ... text ...
    """
    if not ocr_results:
        return ""
    blocks: list[str] = []
    for r in ocr_results:
        text = str(r.get("ocr_text") or "").strip()
        if not text:
            continue
        fn = str(r.get("filename") or "image")
        blocks.append(f"[첨부 이미지 OCR — {fn}]\n{text}")
    return "\n\n".join(blocks)
