"""vLLM fallback endpoint registry.

Parses VLLM_FALLBACKS env value into a list of EndpointSpec.
- "" → []
- "auto" → default GB10 3-tier ordering
- JSON list → explicit list
"""
from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointSpec:
    label: str          # "primary", "gb10_31b_dense", ...
    url: str            # "http://host.docker.internal:7026/v1"
    model: str          # "gemma-4-31b-dense"


# NVIDIA GB10 DGX Spark vLLM 기본 폴백 체인 (B200 장애 시).
# 순서: 31b_dense (primary 품질 근접) → 26b_moe (2배 빠름, 품질 소폭 하락) → e4b (긴급 티어)
# e2b 는 기본에서 제외 — 배터리 절약 티어는 명시적 opt-in.
DEFAULT_GB10_FALLBACKS: list[EndpointSpec] = [
    EndpointSpec("gb10_31b_dense", "http://host.docker.internal:7026/v1", "gemma-4-31b-dense"),
    EndpointSpec("gb10_26b_moe",   "http://host.docker.internal:7025/v1", "gemma-4-26b-moe"),
    EndpointSpec("gb10_e4b",       "http://host.docker.internal:7021/v1", "gemma-4-e4b"),
]


def parse_fallbacks(raw: str) -> list[EndpointSpec]:
    """VLLM_FALLBACKS 환경 변수 값을 EndpointSpec 리스트로 파싱.

    Args:
        raw: 환경 변수 원본 문자열.
            - "" / 공백     → [] (폴백 없음)
            - "auto"        → DEFAULT_GB10_FALLBACKS (3-tier)
            - JSON 리스트    → 명시 엔드포인트 리스트

    Returns:
        파싱된 EndpointSpec 리스트. 형식 오류 시 빈 리스트 반환 (router 에서 경고 로그).
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.lower() == "auto":
        return list(DEFAULT_GB10_FALLBACKS)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 로그 경고는 router 초기화 시 처리 — 여기서는 빈 리스트 반환
        return []
    out: list[EndpointSpec] = []
    if not isinstance(data, list):
        return []
    for item in data:
        try:
            out.append(
                EndpointSpec(
                    label=str(item["label"]),
                    url=str(item["url"]),
                    model=str(item["model"]),
                )
            )
        except (KeyError, TypeError):
            continue
    return out
