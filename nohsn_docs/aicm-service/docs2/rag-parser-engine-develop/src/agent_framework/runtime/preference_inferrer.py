"""PR-M — User preference inference (자비스 패턴).

사용자의 *최근 활동 history* (schedule, diary 등) 를 LLM 으로 정제해 *선호
패턴* 을 추출. plan_orchestrator 가 generate_plan 호출 시 user_preference
입력으로 inject → plan 이 *사용자 일상 맥락* 알고 자연스러운 제안 생성.

예: 사용자가 주말마다 "드라이브 일정" 등록 → preference.weekend_pattern =
"드라이브". "내일 시간 비어있어" 발화에 "내일 비어있는 시간 있어요. 평소
주말 드라이브 자주 다니시던데, 드라이브 일정 만들어 드릴까요?" proactive
제안 가능.

캐시: Redis 1-day TTL (key = ``aicm:agent:preference:{account_id}``).

원칙 (사용자 강조):
- LLM 적극 활용 — pattern 추출 rule/regex 금지. 발화 다양성·표현 변형 LLM
  일반화.
- 사례 yaml 금지 — 패턴 코어. 입력 history 리스트 → LLM → dict 한 번 호출.
"""
from __future__ import annotations

import json
from typing import Any

from src.common.logging import get_logger

log = get_logger(__name__)


_CACHE_TTL_SEC = 86400  # 1 day
_CACHE_KEY_PREFIX = "aicm:agent:preference:"
_HISTORY_LIMIT = 30  # 최근 30 건 schedule + 30 건 diary


def _cache_key(account_id: str) -> str:
    return f"{_CACHE_KEY_PREFIX}{account_id}"


class PreferenceInferrer:
    """사용자 활동 history → LLM → preference dict.

    의존성: redis, llm_client (response_format=json_object 지원), schedule_store
    list_all, diary_store list_items (선택).
    """

    def __init__(self, redis_client: Any, llm_client: Any) -> None:
        self.redis = redis_client
        self.llm = llm_client

    async def get_or_infer(
        self,
        *,
        account_id: str | None,
        tenant_id: str | None,
        phone: str | None = None,
    ) -> dict[str, Any]:
        """캐시 hit 시 그대로 반환. miss 시 history 수집 + LLM 추론 + 캐시.

        AGENT_DATA_STORE 모드에 따라 schedule_store/diary_store 가 phone (redis)
        또는 tenant_id (kms) 를 요구. 둘 다 받아 양쪽 모드 지원.

        실패 / LLM 미주입 / history 없음 → ``{}`` (plan 은 그냥 진행).
        """
        if not account_id or self.llm is None:
            return {}
        if not tenant_id and not phone:
            return {}
        # 1. cache lookup
        try:
            cached = await self.redis.get(_cache_key(account_id))
            if cached:
                if isinstance(cached, bytes):
                    cached = cached.decode("utf-8")
                return json.loads(cached)
        except Exception as e:  # noqa: BLE001
            log.debug("preference_cache_get_failed", error=str(e))

        # 2. history 수집
        history = await self._collect_history(tenant_id=tenant_id, phone=phone)
        if not history:
            return {}

        # 3. LLM 추론
        pref = await self._llm_infer(history)
        if not pref:
            return {}

        # 4. cache 저장
        try:
            await self.redis.set(
                _cache_key(account_id),
                json.dumps(pref, ensure_ascii=False),
                ex=_CACHE_TTL_SEC,
            )
        except Exception as e:  # noqa: BLE001
            log.debug("preference_cache_set_failed", error=str(e))
        log.info(
            "preference_inferred",
            account_id=account_id,
            weekend_pattern=pref.get("weekend_pattern"),
            routine=pref.get("routine"),
        )
        return pref

    async def invalidate(self, account_id: str) -> None:
        """history 변동 (새 schedule/diary 등록) 시 호출 — 다음 turn 재추론."""
        try:
            await self.redis.delete(_cache_key(account_id))
        except Exception as e:  # noqa: BLE001
            log.debug("preference_cache_invalidate_failed", error=str(e))

    async def _collect_history(
        self, *, tenant_id: str | None, phone: str | None
    ) -> dict[str, list]:
        """schedule + diary 최근 N 건 수집.

        AGENT_DATA_STORE=redis (default) → phone 키. =kms → tenant_id.
        둘 다 시도해 비어있으면 다른 mode 도 fallback. 실패는 빈 dict.
        """
        out: dict[str, list] = {"schedules": [], "diaries": []}
        # schedule_store args: redis 모드는 phone, kms 모드는 tenant_id
        sched_args_candidates = []
        if phone:
            sched_args_candidates.append({"phone": phone})
        if tenant_id:
            sched_args_candidates.append({"tenant_id": tenant_id})
        for args in sched_args_candidates:
            try:
                from src.agent_framework.tools import schedule_store
                sched = await schedule_store.list_all(args)
                items = sched.get("items") or []
                if items:
                    out["schedules"] = items[-_HISTORY_LIMIT:]
                    break
            except Exception as e:  # noqa: BLE001
                log.debug(
                    "preference_collect_schedule_failed",
                    args=str(args)[:80],
                    error=str(e),
                )
        for args in sched_args_candidates:  # diary uses same key shape
            try:
                from src.agent_framework.tools import diary_store
                diary_args = (
                    {"phone": args.get("phone")}
                    if args.get("phone")
                    else {"tenant_id": args.get("tenant_id")}
                )
                diary = await diary_store.list_items(diary_args)
                items = diary.get("items") or []
                if items:
                    out["diaries"] = items[-_HISTORY_LIMIT:]
                    break
            except Exception as e:  # noqa: BLE001
                log.debug("preference_collect_diary_failed", error=str(e))
        return out

    async def _llm_infer(self, history: dict[str, list]) -> dict[str, Any]:
        """history → LLM JSON dict. 실패는 빈 dict."""
        if not history.get("schedules") and not history.get("diaries"):
            return {}
        system = (
            "당신은 사용자의 최근 일정·일기 history 를 보고 *반복 선호 패턴* 을 \n"
            "추출하는 분석가다. 한 줄 JSON 으로만 답한다.\n\n"
            "출력 schema (다른 텍스트 X):\n"
            "{\n"
            "  \"weekend_pattern\": \"주말에 자주 하는 활동 (없으면 빈 문자열)\",\n"
            "  \"weekday_pattern\": \"평일 저녁에 자주 하는 활동\",\n"
            "  \"routine\": \"일상에 반복되는 단어/주제 (예: 헬스장, 카페, 미팅)\",\n"
            "  \"common_locations\": [\"자주 등장하는 장소 max 3\"],\n"
            "  \"summary\": \"한국어 한 줄 요약 — proactive 제안에 그대로 사용 가능\"\n"
            "}\n\n"
            "원칙:\n"
            "- 표현 변형 일반화 (예: '드라이브', '운전', '차로 어디 갔다' = 같은 패턴)\n"
            "- 단발성 1~2 회 등장은 패턴 X. 3 회 이상 또는 명확한 반복만.\n"
            "- 추출 근거 부족하면 해당 필드 빈 문자열/빈 배열.\n"
            "- summary 는 사용자가 들으면 자연스러운 한 문장."
        )
        user = json.dumps(history, ensure_ascii=False, indent=2)
        try:
            raw = await self.llm.complete(
                system, user, response_format="json_object"
            )
            _stripped = (raw or "").strip()
            if _stripped.startswith("```"):
                _nl = _stripped.find("\n")
                if _nl > 0:
                    _stripped = _stripped[_nl + 1 :]
            if _stripped.endswith("```"):
                _stripped = _stripped[:-3].rstrip()
            data = json.loads(_stripped)
            if not isinstance(data, dict):
                return {}
            return data
        except Exception as e:  # noqa: BLE001
            log.warning(
                "preference_llm_infer_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            return {}
