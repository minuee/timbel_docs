"""Intent Classifier — 사용자 발화가 지식 검색이 필요한지 판단.

상담사 실시간 보조 시나리오: 고객과의 대화 중 casual 발화(인사/날씨/감정/공감)는
검색 skip, 지식/업무 질의만 검색 실행. 결과는 intent_logs 테이블에 누적 저장해
후속 룰 필터/소형 분류기 학습에 활용.

parallel 실행이 가능하도록 독립 async 함수로 노출. 분류 자체는 vLLM Gemma 호출.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.common.logging import get_logger
from src.common.time_utils import now_prefix

log = get_logger(__name__)

# vLLM 호출 hang 방지 — 3 초 이상 걸리면 포기하고 보수적으로 search=True.
# 실측 p99 ~1.6s (2026-04-17 30케이스) 기준 2x 마진. 데모 중 화면 멈춤 방지.
_CLASSIFY_TIMEOUT_S = 3.0

# Intent 결과 캐시 — 동일 (query, history 최근 3턴, domain) 조합은 LLM 재호출 생략.
# 상담 세션에서 같은 문의가 반복될 때 280ms → 5ms 로 단축.
_INTENT_CACHE_PREFIX = "aicm:intent_cache:"
_INTENT_CACHE_TTL_S = 60 * 60 * 2  # 2시간


def _make_intent_cache_key(
    query: str,
    conversation_history: list[dict] | None,
    domain_description: str | None,
    available_repos: list[dict] | None = None,
) -> str:
    recent = (conversation_history or [])[-3:]
    recent_blob = "|".join(
        f"{t.get('role','')}:{t.get('content','')}" for t in recent
    )
    # PR-F — 카탈로그가 다르면 캐시도 분리 (다른 사용자/세션의 repo 추천이
    # 섞이지 않도록). id+name 만 hash — description 변경에는 둔감.
    repo_blob = "|".join(
        f"{r.get('id','')}:{r.get('name','')}"
        for r in (available_repos or [])
    )
    raw = f"{query}\x00{recent_blob}\x00{domain_description or ''}\x00{repo_blob}"
    return _INTENT_CACHE_PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _get_intent_cache(key: str) -> "IntentResult | None":
    try:
        import redis.asyncio as aioredis

        from src.common.config import settings

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            raw = await client.get(key)
        finally:
            await client.close()
        if not raw:
            return None
        data = json.loads(raw)
        return IntentResult(**data)
    except Exception as exc:
        log.debug("intent_cache_get_failed", error=str(exc))
        return None


async def _set_intent_cache(key: str, result: "IntentResult") -> None:
    try:
        import redis.asyncio as aioredis

        from src.common.config import settings

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await client.setex(
                key,
                _INTENT_CACHE_TTL_S,
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
            )
        finally:
            await client.close()
    except Exception as exc:
        log.debug("intent_cache_set_failed", error=str(exc))


class IntentResult(BaseModel):
    """분류 결과.

    PR-F (KMS-Plus, 2026-04-27) — 의도 정밀 추출. binary search 만 보던 기존
    분류기를 *도메인·유형·대상 키워드·저장소 매칭* 까지 한 번에 LLM 으로 추출
    하도록 확장. 모든 새 필드는 backward-compat — None / 빈 리스트 default.
    """

    search: bool = Field(..., description="True=검색 필요, False=일상 대화")
    reason: str = Field("", description="분류 사유")
    latency_ms: int = Field(0, description="LLM 분류 호출 소요 시간")
    model_used: str = Field("", description="사용된 모델")
    # PR-F 정밀 추출 — 발화의 의도 도메인 (kms / schedule / diary / news / casual / other)
    domain: str | None = Field(None, description="의도 도메인 라벨")
    # 의도 유형 (factual_lookup / procedural / constraint / create / list / delete / casual / other)
    kind: str | None = Field(None, description="의도 유형 라벨")
    # 발화에서 추출된 대상 키워드 (저장소 매칭·grounding scope 좁히기 용)
    target_keywords: list[str] = Field(default_factory=list, description="대상 키워드")
    # 호출자가 available_repos 카탈로그를 제공한 경우, LLM 이 해당 후보 중 매칭한 repo id list
    target_repository_ids: list[str] = Field(default_factory=list, description="자동 타겟팅된 저장소 ID 목록")


_INTENT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "search": {"type": "boolean", "description": "지식 검색이 필요하면 true, 일상 대화면 false"},
        "reason": {"type": "string", "description": "한국어 한 줄 사유. 최대 40자."},
        "domain": {
            "type": "string",
            "description": "의도 도메인: kms|schedule|diary|news|casual|other",
        },
        "kind": {
            "type": "string",
            "description": "의도 유형: factual_lookup|procedural|constraint|create|list|delete|casual|other",
        },
        # P10i (2026-04-29): target_keywords 제거. retrieval (BGE-M3 + reranker) 은
        # 자연어 발화 그대로 받음 — 키워드 분리는 trace 표시용일 뿐 retrieval 영향 0.
        # LLM 호출 prompt 단축 + 응답 latency 절감. trace 는 발화 자체로 표시.
        "target_repository_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "available_repos 카탈로그가 prompt 에 제공된 경우, 그 중 발화와 매칭되는 repo id 목록. 카탈로그 미제공 시 빈 배열.",
        },
    },
    "required": ["search", "reason"],
    "additionalProperties": False,
}

_BASE_SYSTEM_PROMPT = (
    "KMS 플랫폼의 intent 분류기입니다. 사용자 발화가 업로드된 문서·메모·일정·일기 등의 "
    "데이터 검색이 필요한지, 검색이 불필요한 일상 대화인지 판단합니다.\n"
    "- 검색 필요 (search=true): 지식 베이스·개인 문서·일정·일기에 기반한 **사실 확인 질의**\n"
    "  (업무 지식, 지인/가족/친구 정보, 내 일정, 과거 일기, 절차/규정/가격/기능 등 전부 포함)\n"
    "- 검색 불필요 (search=false): 단순 인사/감사/공감/맞장구/날씨 잡담, **감정 호소 발화** "
    "(예: '오늘 잠이 안 와', '힘들다')\n"
    "**중요**: '내', '우리', '지인/친구/가족' 같은 개인 소유 표현이 붙은 사실 질의는 "
    "반드시 search=true. 사용자가 본인 데이터를 찾는 것이므로 시스템은 도메인 밖 이라고 거절하지 않음.\n"
    "\n"
    "PR-F 정밀 추출 — 다음 3 필드도 함께 반환:\n"
    "  • domain: kms (지식·문서·업무) / schedule (일정·약속) / diary (일기·메모) / "
    "news (뉴스·시장) / casual (대화·인사·감정) / other (애매)\n"
    "  • kind: factual_lookup (사실 확인) / procedural (절차·방법) / constraint (제약·규정) / "
    "create (등록) / list (조회) / delete (삭제) / casual / other\n"
    "  • target_repository_ids: prompt 에 'AVAILABLE_REPOS' 섹션이 있는 경우 그 중 발화의 의도와 "
    "맞는 repo id 들만. 매칭 0~N개 가능. 카탈로그 미제공 시 빈 배열. **카탈로그에 없는 id 추측 금지**.\n"
    "\n"
    "JSON 만 반환. reason 은 한국어로 한 줄, 40자 이내. 모든 라벨은 위 enum 값만 사용."
)


def _build_system_prompt(
    domain_description: str | None,
    available_repos: list[dict] | None = None,
) -> str:
    """도메인 설명이 있으면 분류기가 범위를 인지하도록 프롬프트 확장.

    PR-F — available_repos 카탈로그도 함께 inject. 각 entry: {id, name, description?}.
    LLM 이 발화에 가장 맞는 repo id 들을 target_repository_ids 에 채움.
    """
    prefix = now_prefix()
    parts: list[str] = [prefix, _BASE_SYSTEM_PROMPT]
    if domain_description and domain_description.strip():
        parts.append(
            f"\n\n지식 베이스 도메인 설명:\n{domain_description.strip()}\n"
            "이 도메인과 무관한 질의는 search=false 로 분류하고 reason 에 '도메인 외' 명시."
        )
    if available_repos:
        # 카탈로그 prompt — id 가 prompt 에 노출되어야 LLM 이 선택 가능. PII 위험
        # 없는 메타만. description 은 요약 80자 제한.
        catalog_lines: list[str] = ["\n\nAVAILABLE_REPOS:"]
        for r in available_repos[:30]:  # 너무 많으면 prefill 부담 — 30개 cap
            rid = r.get("id", "")
            name = r.get("name", "")
            desc = (r.get("description") or "").strip().replace("\n", " ")
            if len(desc) > 80:
                desc = desc[:77] + "..."
            catalog_lines.append(f"- id={rid} name={name} desc={desc}")
        catalog_lines.append(
            "\n발화 의도와 매칭되는 repo id 들을 target_repository_ids 에 채움. "
            "맞는 게 없으면 빈 배열. **카탈로그에 없는 id 추측 금지**."
        )
        parts.append("\n".join(catalog_lines))
    return "".join(parts)


async def classify_intent(
    query: str,
    conversation_history: list[dict] | None = None,
    domain_description: str | None = None,
    available_repos: list[dict] | None = None,
) -> IntentResult:
    """LLM 으로 발화의 검색 필요성 판단. 실패 시 보수적으로 search=True 반환 (정보 누락 방지).

    동일 (query, 최근 3턴, domain, repo 카탈로그) 조합은 Redis 캐시 (2시간 TTL)
    에서 반환해 LLM 호출 (~280ms) 생략.

    PR-F — available_repos 가 주어지면 LLM 이 *그 카탈로그 안에서* 발화와 매칭되는
    repo id 들을 IntentResult.target_repository_ids 에 채움. 호출자 (engine
    grounding) 가 SearchRequest.repository_ids 로 자동 타겟팅에 활용.
    """
    from src.common.llm.base import LLMRequest, LLMTask
    from src.common.llm.router import llm_router

    # 1. 캐시 hit 시 즉시 반환
    cache_key = _make_intent_cache_key(
        query, conversation_history, domain_description, available_repos
    )
    cached = await _get_intent_cache(cache_key)
    if cached is not None:
        log.debug("intent_cache_hit", query_preview=query[:40])
        # latency_ms 는 원본 계산값 유지 (cache 히트라도 clock 측정값 대신 "원본 소요" 의미 유지)
        return cached

    # 대화 맥락은 최근 3턴만 사용 (prefill 토큰 최소화)
    history_text = ""
    if conversation_history:
        recent = conversation_history[-3:]
        parts = []
        for t in recent:
            role = t.get("role", "user")
            content = t.get("content", "")
            label = "상담사" if role == "assistant" else "고객"
            parts.append(f"{label}: {content}")
        history_text = "이전 대화:\n" + "\n".join(parts) + "\n\n"

    user_prompt = f"{history_text}현재 발화: {query}"

    system_prompt = _build_system_prompt(domain_description, available_repos)
    start = time.monotonic()
    try:
        resp = await asyncio.wait_for(
            llm_router.route(
                task=LLMTask.RAG_GENERATION,  # 기존 Gemma 4 라우팅 재사용
                request=LLMRequest(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    # PR-F — 새 필드 4개 (domain/kind/target_keywords/target_repository_ids)
                    # 추가로 응답 길이 증가. 256 으로 상향. 카탈로그 없으면 실제 사용은
                    # 100 토큰 안쪽이지만 truncation 위험 차단 우선.
                    max_tokens=256,
                    temperature=0.0,
                    guided_json=_INTENT_SCHEMA,
                ),
            ),
            timeout=_CLASSIFY_TIMEOUT_S,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        try:
            data = json.loads(resp.text)
            # PR-F — available_repos 카탈로그가 있을 때만 target_repository_ids 신뢰
            # (카탈로그 없으면 LLM 이 임의 id 추측할 위험 — 빈 배열 강제).
            allowed_ids: set[str] = set()
            if available_repos:
                allowed_ids = {str(r.get("id", "")) for r in available_repos if r.get("id")}
            raw_repo_ids = data.get("target_repository_ids") or []
            if not isinstance(raw_repo_ids, list):
                raw_repo_ids = []
            filtered_repo_ids = [
                str(rid) for rid in raw_repo_ids
                if available_repos and str(rid) in allowed_ids
            ]
            # P10i: target_keywords 제거 — retrieval 영향 없음. backward-compat
            # 위해 필드 유지하되 항상 빈 list (옛 caller 가 읽어도 비어있어 안전).
            result = IntentResult(
                search=bool(data.get("search", True)),
                reason=str(data.get("reason", ""))[:200],
                latency_ms=latency_ms,
                model_used=resp.model,
                domain=(str(data["domain"]).strip().lower() if data.get("domain") else None),
                kind=(str(data["kind"]).strip().lower() if data.get("kind") else None),
                target_keywords=[],
                target_repository_ids=filtered_repo_ids,
            )
            # 성공 결과만 캐시 저장 (에러/타임아웃 케이스는 재시도 기회 유지)
            await _set_intent_cache(cache_key, result)
            return result
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("intent_json_parse_failed", error=str(exc), text_preview=resp.text[:100])
            return IntentResult(
                search=True,
                reason="(분류기 JSON 파싱 실패 — 안전하게 검색 진행)",
                latency_ms=latency_ms,
                model_used=resp.model,
            )
    except asyncio.TimeoutError:
        log.warning("intent_classify_timeout", timeout_s=_CLASSIFY_TIMEOUT_S, query_preview=query[:60])
        return IntentResult(
            search=True,
            reason=f"(분류기 타임아웃 {_CLASSIFY_TIMEOUT_S}s — 안전하게 검색 진행)",
            latency_ms=int((time.monotonic() - start) * 1000),
            model_used="",
        )
    except Exception as exc:
        log.warning("intent_classify_failed", error=str(exc))
        return IntentResult(
            search=True,
            reason=f"(분류기 오류 — 안전하게 검색 진행: {type(exc).__name__})",
            latency_ms=int((time.monotonic() - start) * 1000),
            model_used="",
        )


async def log_intent_decision(
    db: Any,  # AsyncSession
    query: str,
    conversation_history: list[dict] | None,
    result: IntentResult,
    tenant_id: UUID | None,
) -> None:
    """분류 결과를 intent_logs 테이블에 누적. 실패해도 본 요청은 깨지지 않음."""
    from src.core.models.intent_log import IntentLog

    try:
        row = IntentLog(
            tenant_id=tenant_id,
            query=query,
            conversation_history=conversation_history,
            search_decision=result.search,
            reason=result.reason,
            latency_ms=result.latency_ms,
            model_used=result.model_used,
        )
        db.add(row)
        await db.commit()
    except Exception:
        log.warning("intent_log_insert_failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
