"""Agent 세션 상태 저장소 (Redis).

v1 설계: 매 `put()` 마다 TTL 재설정 → idle timeout 효과.
활성 대화는 계속 연장, 30분+ idle 시 자동 삭제.

값 타입 계약 (values in slots/history/identity MUST be JSON-native):
  - str / int / float / bool / None / list / dict 만 허용
  - datetime 등은 ISO 문자열로 먼저 변환 후 저장
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

import redis.asyncio as aioredis


_SESSION_PREFIX = "agent:session:"

# v1 idle timeout: 30분 (1800초). 이전 기본값 24h 는 너무 길어서 막힌 세션이
# 오래 남아 다음 방문 시 혼란. `settings.AGENT_SESSION_TTL_S` 로 override.
DEFAULT_SESSION_TTL_S = 60 * 30


@dataclass
class SessionState:
    session_id: str
    skill_id: str | None
    current_state: str | None
    slots: dict[str, Any]
    history: list[dict[str, Any]]    # [{role, content, ts}]
    tenant_id: str
    identity: dict[str, Any] | None
    # Stage B-1: account 자동 생성 후 session 에 바인드되는 식별자.
    # 기존 session JSON (필드 없음) 을 deserialize 할 때 KeyError 방지 위해
    # 기본값 None. Stage B-2+ 에서 schedule/diary/news scope key 로 사용 예정.
    account_id: str | None = None
    personal_tenant_id: str | None = None
    # Wave V2 (KMS-Plus, 2026-04-25) — 세션 동안 활성화된 SkillV2 이름.
    # 다음 턴에서 auto_loader 가 None 을 돌려주면 이 sticky skill 로 fallback —
    # 짧은 응답(예: "네", "최대한 많이") 만으로는 LLM 매칭이 어려워 페르소나가
    # 끊기던 문제를 수습. auto_loader 가 다른 skill 을 매칭하면 그걸로 override.
    activated_skill_v2_name: str | None = None
    # Wave 6 (D 코스, 2026-04-26) — Adaptive Behavior 의 ledger.
    # clarification_history: [{turn_idx, asked, answered, applied_skill, applied_slot, confidence, ts}]
    # slot_ledger: {skill_name: {slot_name: {value, source_turn, confidence, ts}}}
    # topic_thread: [{turn_idx, topic, entities, persona_state, ts}]
    # 기존 session JSON 호환 위해 default_factory 로 빈 collection 자동 초기화.
    clarification_history: list[dict[str, Any]] = field(default_factory=list)
    slot_ledger: dict[str, dict[str, Any]] = field(default_factory=dict)
    topic_thread: list[dict[str, Any]] = field(default_factory=list)

    # PR-C (KMS-Plus, 2026-04-27) — tenant_id 3단 fallback 단일 source.
    # account_bind_failed (varchar(32) phone column 에 UUID 36자 INSERT 실패) 시
    # personal_tenant_id 가 None 으로 남는데, grounding (G2) / tool 호출 (PR-C)
    # 모두 동일 fallback 체인을 봐야 'personal_tenant_id 누락' 으로 인한
    # 일정 저장 실패가 다시 발생하지 않는다.
    #
    # 결정 자체에 keyword/regex 분기 없음 — 단순 None 가드만.
    @property
    def effective_personal_tenant_id(self) -> str | None:
        """grounding/tool 양쪽이 공유하는 tenant_id 결정.

        체인: ``personal_tenant_id`` → ``tenant_id``.
        엔진의 ``_activated_tenant_id`` 가 별도로 우선 적용되는 경로
        (G2 grounding) 는 호출 전 계산되어 합산되므로, 여기서는 세션 스코프에서
        결정 가능한 두 단계만 다룬다.
        """
        if self.personal_tenant_id:
            return self.personal_tenant_id
        if self.tenant_id:
            return self.tenant_id
        return None


class SessionStore:
    def __init__(
        self,
        client: aioredis.Redis,
        ttl_s: int = DEFAULT_SESSION_TTL_S,
    ):
        self.client = client
        self.ttl_s = ttl_s

    def _key(self, session_id: str) -> str:
        return _SESSION_PREFIX + session_id

    async def get(self, session_id: str) -> SessionState | None:
        raw = await self.client.get(self._key(session_id))
        if not raw:
            return None
        data = json.loads(raw)
        # Wave 6 — D 코스 신 필드 default 보정 (옛 세션 호환)
        data.setdefault("clarification_history", [])
        data.setdefault("slot_ledger", {})
        data.setdefault("topic_thread", [])
        # 알 수 없는 키 (미래 버전 → 옛 코드) 는 무시 — 안전장치
        valid_fields = {f for f in SessionState.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in valid_fields}
        return SessionState(**clean)

    async def put(self, state: SessionState) -> None:
        data = json.dumps(asdict(state), ensure_ascii=False)
        # ex= 매 write 마다 TTL 재설정 → active session 자동 연장
        await self.client.set(self._key(state.session_id), data, ex=self.ttl_s)

    async def delete(self, session_id: str) -> None:
        await self.client.delete(self._key(session_id))
