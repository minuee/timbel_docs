"""Agent active context — plan_orchestrator inject 용.

Phase 1 Task 4. Agent 모델에서 추출한 *런타임 immutable 데이터*.
plan_orchestrator 가 system prompt 에 to_prompt_section() 결과 추가.

agent_id 미지정 (default chat) 시 None — 기존 동작 그대로.

058 — ``kind`` 필드 추가 (admin / role). engine 의 admin bypass 결정에 사용.
062 — ``delegate_to_agent_ids`` 필드 추가 (multi-agent, Phase 1.5B-γ).

sender-tier-consistency (2026-05-07):
    guidelines_md 안 ``## 외부 채널 게스트 (sender.tier = guest)`` 같은
    *tier-conditional 답변 doctrine* 은 binding policy block prepend 시 제거된다.
    이유:
        - 사용자 명시 (2026-05-07): "에이전트 설정을 한번 하면, 그게 채널에 묶이면
          그건 어차피 에이전트 특성을 다 상속 받아야지. 루트에 따라 다른건 말이
          안되고."
        - tier 의 의미는 *destructive 도구 호출 권한* 만. 답변 본문 (FAQ /
          매뉴얼 인용 / LLM 추론) 은 모든 tier 에서 동일 path 로 작동해야 함.
        - guidelines_md 가 정적 doctrine 으로 ``sender.tier = guest`` 같은 분기
          markdown 을 갖고 있으면 LLM 이 (실제 sender 와 무관하게) doctrine 을
          그대로 흉내 내어 *답변 분기* 를 만든다 — 이 결함을 코드 path 에서 차단.
        - 대신 binding policy block 끝에 *tier-neutral 일관 응대 가이드* 를
          한 단락 inject — "FAQ/매뉴얼 인용은 모든 tier 동일, destructive 도구는
          runtime guard 가 차단" 만 명시.
    실제 tier 가드 (destructive 호출 거절) 는 ``sender_context_guard`` /
    ``conflict_checks`` / tool validator 에서 별도 작동.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from uuid import UUID


# sender-tier-consistency (2026-05-07) — tier-conditional 답변 doctrine 헤더
# 패턴. ``## 외부 채널 게스트 (sender.tier = guest)`` / ``# 게스트 응대
# (sender.tier=verified)`` 등 변형 모두 매칭. 다음 같은 레벨의 ``#`` 헤더 또는
# 문서 끝까지 한 섹션을 통째로 제거.
_TIER_DOCTRINE_HEADER_RE = re.compile(
    r"""
    ^                       # 줄 시작
    (\#{1,6})\s*            # ``#`` ~ ``######``
    [^\n]*                  # 헤더 제목 임의 텍스트
    sender\.tier            # 핵심 토큰 — guidelines_md 안 tier doctrine 의 단일 marker
    [^\n]*                  # 헤더 제목 나머지
    $                       # 줄 끝
    """,
    re.IGNORECASE | re.VERBOSE | re.MULTILINE,
)


def _strip_tier_doctrine_sections(guidelines_md: str) -> str:
    """``## 외부 채널 게스트 (sender.tier = guest)`` 류 *tier-conditional*
    doctrine 섹션을 제거한 guidelines_md 를 반환.

    동작:
        1. ``sender.tier`` 토큰을 포함한 markdown 헤더를 모두 찾음.
        2. 각 헤더부터 *동일 또는 더 상위* 레벨 다음 헤더 (또는 문서 끝) 직전까지
           통째로 제거.
        3. doctrine 헤더가 없으면 입력 그대로 반환 (회귀 0).

    이 함수는 *문자열 처리* 만. 실제 tier 권한 검사는 ``sender_context_guard``
    가 destructive 도구 호출 시점에 별도 적용.
    """
    if not guidelines_md or "sender.tier" not in guidelines_md.lower():
        # 빠른 path — doctrine marker 없으면 strip 스킵.
        return guidelines_md
    # 헤더 위치 + 레벨 수집.
    headers: list[tuple[int, int, int]] = []  # (start_idx, end_idx_of_header_line, level)
    for m in re.finditer(r"^(\#{1,6})[^\n]*\n", guidelines_md, re.MULTILINE):
        headers.append((m.start(), m.end(), len(m.group(1))))
    # tier doctrine 헤더 식별.
    doctrine_starts: list[int] = []
    for i, (s, _e, _lvl) in enumerate(headers):
        # 헤더 라인 (줄바꿈 미포함) 만 추출해서 marker 검사.
        line_end = guidelines_md.find("\n", s)
        if line_end == -1:
            line_end = len(guidelines_md)
        line = guidelines_md[s:line_end]
        if "sender.tier" in line.lower() and line.lstrip().startswith("#"):
            doctrine_starts.append(i)
    if not doctrine_starts:
        return guidelines_md
    # 각 doctrine 섹션의 [start, end) 범위 계산.
    # 섹션 끝 = 다음 *동일 또는 상위* 레벨 헤더 시작 (또는 문서 끝).
    cuts: list[tuple[int, int]] = []
    for di in doctrine_starts:
        d_start, _d_line_end, d_level = headers[di]
        section_end = len(guidelines_md)
        for j in range(di + 1, len(headers)):
            n_start, _n_end, n_level = headers[j]
            if n_level <= d_level:
                section_end = n_start
                break
        cuts.append((d_start, section_end))
    # 뒤에서부터 잘라야 인덱스 안정.
    out = guidelines_md
    for d_start, d_end in sorted(cuts, key=lambda x: x[0], reverse=True):
        out = out[:d_start] + out[d_end:]
    # 연속 빈 줄 정리.
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


# tier-neutral 일관 응대 가이드 — binding policy block 끝에 inject.
# *답변 본문* 은 tier 무관 동일, destructive 도구만 runtime guard 가 차단.
_TIER_NEUTRAL_ANSWER_GUIDE = (
    "## 일관 응대 가이드 (sender-tier-consistency)\n"
    "- 답변 본문 (FAQ / 매뉴얼 인용 / 일반 안내 / 검색 결과 요약) 은 *모든 진입 "
    "경로 (web / channel webhook / API) 에서 동일* 하게 작성하라. 사용자가 어떤 "
    "채널로 접근했는지·로그인 상태인지로 답변 *본문* 을 분기하지 마라.\n"
    "- destructive 도구 호출 (실 주문 변경 / 메일 실 발송 / 결제 변경 / 자동이체 "
    "등록 등) 의 *권한 검증* 은 runtime 가드가 별도로 한다. 너는 발화 의도를 "
    "정확히 답하면 되며, 권한이 없는 호출은 가드가 자동 거절한다.\n"
    "- 매뉴얼·자료가 부족한 질문에도 *거절 우선* 으로 빠지지 말 것. 일반 지식 "
    "선에서 안내 + 한 줄 disclaimer (예: '정확한 안내는 사람 상담사 또는 공식 "
    "채널을 통해 확인 권장') 형식으로 답하라.\n"
)


@dataclass(frozen=True)
class AgentContext:
    agent_id: UUID
    tenant_id: UUID
    name: str
    goal: str
    guidelines_md: str
    primary_repo_ids: list[UUID]
    fallback_repo_ids: list[UUID]
    knowledge_isolation: str  # strict / priority / broad
    allowed_tools: list[str]
    done_when: str | None
    # 058 — admin (Locus 어시스턴트, 1 per tenant) vs role (하부 역할 에이전트).
    # 미지정 시 'role' (기존 동작 호환).
    kind: str = "role"
    # Phase 1.5B-γ — 이 agent 가 위임 호출 가능한 sub-agent IDs.
    # admin kind 인 경우 *비어 있으면* 자동으로 모든 role agent 가 inject 됨
    # (from_agent classmethod 가 처리). 명시적으로 채우면 그것만 사용.
    # role kind 는 비어 있으면 위임 불가.
    delegate_to_agent_ids: list[UUID] = field(default_factory=list)
    # 069 (Plan A v3, 2026-05-07) — 4-mode 웹검색.
    #   off / separate / blended / web_only.
    # default 'off' (기존 동작 호환). admin Locus 만 'separate' (alembic 069).
    web_search_mode: str = "off"
    # 080 (D70, 2026-05-11) — 봇별 *cross-domain* 키워드. intent_gate 가 매칭 시
    # T2 거절 분기. None / [] 안전 (gate 통과). 키워드는 *브랜드/서비스 고유명* 만
    # (예: "배민", "코스피") — 일반어는 false-positive 위험.
    oos_keywords: list[str] = field(default_factory=list)
    # D84 (2026-05-13) — Phase 1.5A SOP/policy repo scope. 이전: Agent DB
    # 컬럼 + AgentOut + AgentPatch 는 모두 처리하는데 AgentContext 만 매핑
    # 누락 → SOP RAG 가 사용자 명시 sop_repo_ids 를 무시하던 silent drop.
    sop_repo_ids: list[UUID] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        """admin agent 여부 — engine 이 skill state machine bypass 결정."""
        return self.kind == "admin"

    @classmethod
    def from_agent(
        cls, agent, *, all_active_role_agent_ids: list[UUID] | None = None
    ) -> "AgentContext":
        """Agent ORM model → AgentContext. agent.* 가 list/None 인 경우 안전.

        Phase 1.5B-γ:
        - admin kind 이고 ``delegate_to_agent_ids`` 가 비어 있으면 자동으로
          ``all_active_role_agent_ids`` (호출자가 주입) 으로 채움. 이는
          "admin 은 default 로 모든 role agent 위임 가능" 시맨틱 구현.
        - admin kind 인데 명시적 위임이 채워져 있으면 그대로 사용.
        - role kind 는 자동 inject 안 함 (admin 만 default delegate).
        """
        kind = getattr(agent, "kind", None) or "role"
        explicit_delegates = list(
            getattr(agent, "delegate_to_agent_ids", None) or []
        )
        if (
            kind == "admin"
            and not explicit_delegates
            and all_active_role_agent_ids is not None
        ):
            # admin default — 동일 tenant 의 모든 active role agent 자동 위임.
            # 자기 자신은 제외 (admin id 가 role 목록에 안 들어감, 그러나 안전망).
            delegates = [
                rid for rid in all_active_role_agent_ids if rid != agent.id
            ]
        else:
            delegates = explicit_delegates

        # 069 — web_search_mode 매핑. 컬럼 없는 ORM 인스턴스 (테스트 fixture)
        # 도 안전하게 'off' 폴백.
        web_mode = getattr(agent, "web_search_mode", None) or "off"
        if web_mode not in ("off", "separate", "blended", "web_only"):
            web_mode = "off"

        # 080 (D70) — oos_keywords 안전 매핑. None / 잘못된 타입 / 빈 문자열 모두
        # 빈 리스트 폴백 (gate 통과). 운영 회귀 0.
        _raw_oos = getattr(agent, "oos_keywords", None)
        if isinstance(_raw_oos, list):
            oos_kws = [str(x).strip() for x in _raw_oos if x and str(x).strip()]
        else:
            oos_kws = []

        return cls(
            agent_id=agent.id,
            tenant_id=agent.tenant_id,
            name=agent.name,
            goal=agent.goal,
            guidelines_md=agent.guidelines_md,
            primary_repo_ids=list(agent.primary_repo_ids or []),
            fallback_repo_ids=list(agent.fallback_repo_ids or []),
            knowledge_isolation=agent.knowledge_isolation or "priority",
            allowed_tools=list(agent.allowed_tools or []),
            done_when=agent.done_when,
            kind=kind,
            delegate_to_agent_ids=delegates,
            web_search_mode=web_mode,
            oos_keywords=oos_kws,
            sop_repo_ids=list(getattr(agent, "sop_repo_ids", None) or []),
        )

    def to_binding_policy_block(self, *, sop_rag_mode: bool = False) -> str:
        """OOS-policy fix (2026-05-07) — guidelines_md 를 *최우선 바인딩 정책*
        으로 추출. system prompt 의 *맨 앞* 에 prepend 해 LLM 이 다른 지시·자료
        해석 *전* 에 도메인 외 발화 정책 / 답변 격식을 우선 적용하게 한다.

        role agent:
          - guidelines_md 안의 "도메인 외 발화 정책" / "거절 응답" 섹션 무시
            현상 (KB 봇이 무관한 적금 chunk 받고 일반 응답 시도) 직접 차단.
        admin agent:
          - 자기 자신 비서 정책이라 OOS 제약 약하지만 동일 path — guidelines_md
            가 비어 있거나 특이 정책 없으면 단순 prefix 만 작용 (회귀 0).
        guidelines_md 가 비어 있으면 빈 문자열 반환 (caller 가 무시).

        R6 (2026-05-07) — ``sop_rag_mode=True`` 일 때 guidelines_md 본문 (수천
        token) 을 *정적 prepend 하지 않음*. 핵심 OOS guard 1 줄만 유지하고, 본문
        (절차/거절 정책/실패 패턴 등) 은 SopInjectLayer 가 매 turn RAG retrieve
        해서 별도 [SOP CONTEXT] block 으로 inject. system prompt 길이 ~3000 →
        ~500 token, 사용자 발화에 무관한 정책 chunk inject 회피.
        """
        gm_raw = (self.guidelines_md or "").strip()
        if not gm_raw:
            return ""
        # sender-tier-consistency (2026-05-07) — guidelines_md 안 tier-conditional
        # doctrine ("## 외부 채널 게스트 (sender.tier = guest)" 등) 을 제거.
        # tier 분기는 destructive 도구 호출 시점 runtime guard 만 사용.
        gm = _strip_tier_doctrine_sections(gm_raw)
        if not gm:
            # doctrine 만 있던 guidelines_md 였다면 — 본문이 비더라도 OOS guard +
            # tier-neutral guide 는 inject.
            gm = "(별도 정책 없음 — OOS guard + 일관 응대 가이드만 적용.)"
        kind_label = "어시스턴트 본인 (admin)" if self.is_admin else "역할 에이전트 (role)"
        # OOS guard 한 줄 — 모든 role agent 에 자동 강제. guidelines_md 안 도메인
        # 외 발화 정책이 명시 안 됐어도 LLM 이 retrieved chunk 와 발화 도메인
        # mismatch 시 안내 + disclaimer 답변을 만들도록.
        # sender-tier-consistency (2026-05-07) — "거절하라" 어조 완화. 도메인 외
        # 발화도 일반 안내 + disclaimer 방식 (tier 무관 동일 본문 path).
        # OOS-precedence fix (2026-05-07) — GPT-5 P0 권고. in-scope 우선 규칙을
        # OOS guard 보다 *먼저* 명시. baemin "배달 취소" 같은 *도메인 운영의
        # 일반 변형* 이 거절 분기로 빠지는 결함 차단. 키워드 hardcoding X —
        # "도메인 운영의 일반 변형" 이라는 generalization 으로 LLM 패턴 인식 위임.
        oos_guard = (
            "## 분류 우선순위 (in-scope 우선)\n"
            "1) 사용자 발화가 *agent.goal / 도메인 운영의 일반 변형* (조회/등록/"
            "취소/환불/지연/재배송/결제/메뉴/매장/리뷰/배달원·라이더 같은 일상 "
            "요청) 이거나 *경계가 모호* 하면 — *반드시 in-scope 으로 가정* 하고 "
            "정상 답변 분기로 처리하라. *거절 템플릿 사용 금지*. 자료가 부족해도 "
            "일반 지식 선에서 안내 + disclaimer 한 줄.\n"
            "2) 발화가 *명백한 cross-domain* (예: 배달봇에 가스누출 / 적금봇에 "
            "일정 등록 / 가스봇에 주식 시세) 일 때만 guidelines_md 의 거절 "
            "템플릿 적용.\n"
            "3) 자료가 비거나 top-score 가 낮아도 사용자 발화가 도메인 안이면 "
            "거절 X — 일반 안내 + disclaimer ('이 에이전트의 내부 자료에 직접 "
            "매칭은 없어 일반 정보로 안내드렸습니다 — 정확한 답변은 사람 "
            "상담사·공식 채널 권고') 로 마무리.\n"
            "*답변 본문 자체* 는 모든 진입 경로 (web / channel) 에서 동일."
        )
        # D65 (2026-05-12) — L3 fallback OOS guard. role agent 의 guidelines_md
        # 에 명시 OOS 정책 (## 도메인 외 발화 정책 / out-of-scope 헤더) 도 없고
        # 본문 길이가 120자 미만이면 *자동 fallback* 추가. SaaS 봇 사용자 보고
        # 결함 ("문서 검토 잘 해줘" 1줄 guideline) 같은 vague 케이스 차단.
        # admin agent 는 fallback 적용 안 함 (자기 자신 비서, OOS 약함).
        # GPT-5 보강 (2026-05-12): None 안전 가드 + 문구 회귀 회피 (병원/식당 등
        # 도메인-내 합법 *예약* 기능 오인 차단 — "개인 도구" 로 한정).
        fallback_oos = ""
        if not self.is_admin:
            gm_safe = gm or ""
            gm_lower = gm_safe.lower()
            has_oos_section = (
                "도메인 외" in gm_safe
                or "out-of-scope" in gm_lower
                or "out of scope" in gm_lower
                or "응대 도메인" in gm_safe
            )
            min_len_ok = len(gm_safe) >= 120
            if not (has_oos_section and min_len_ok):
                persona_summary = (self.goal or self.name or "전문 자문")[:50]
                persona_name = self.name or persona_summary or "해당 도메인"
                fallback_oos = (
                    "\n\n## 도메인 외 발화 정책 (자동 fallback — D65-L3)\n"
                    f"이 에이전트는 {persona_summary} 전용이다. *도메인과 무관* "
                    "한 *개인 일반 도구* 요청 (개인 일정 등록 / 개인 메모 저장 / "
                    "개인 메일 발송 / 개인 지출 기록 등) 은 정중히 거절: "
                    f"'이 상담은 {persona_name} 전용입니다. 개인 도구는 해당 "
                    "플랫폼의 기본 기능 (일반 앱) 을 이용해 주세요.' "
                    "destructive 실행 (등록/저장/발송 등 데이터 변경) 은 거절. "
                    "*정보성 설명* (절차/방법/단계/요건 요청) 과 *도메인 내 합법 "
                    "기능* (예: 병원봇의 진료 예약 같은 도메인 핵심 동작) 은 정상 안내.\n"
                )

        if sop_rag_mode:
            # R6 — 본문 prepend 제거. agent 정체성 + OOS guard + tier-neutral
            # guide 만 정적, 나머지는 SopInjectLayer 가 [SOP CONTEXT] 로 별도
            # inject.
            return (
                f"[BINDING POLICY — current agent: {self.name} ({kind_label})]\n"
                f"이 에이전트는 자신의 역할/도메인 범위 안에서만 응대한다. "
                f"세부 절차/실패 패턴은 별도 [SOP CONTEXT] 에서 받는다.\n\n"
                f"{oos_guard}\n\n"
                f"{fallback_oos}"
                f"{_TIER_NEUTRAL_ANSWER_GUIDE}"
                f"[/BINDING POLICY]"
            )
        # OOS-precedence fix (2026-05-07) — GPT-5 P0 권고. *분류 우선순위* 가
        # guidelines_md 본문 (거절 템플릿 포함) 보다 *위* 에 위치. LLM 이 in-scope
        # 우선 규칙을 먼저 본 다음 거절 템플릿을 본다 → "배달 취소" 같은 도메인
        # 운영 일반 변형은 정상 분기.
        return (
            f"[BINDING POLICY — current agent: {self.name} ({kind_label})]\n"
            f"아래 정책은 다른 모든 지시·자료보다 우선한다. 답변 작성 *전* 에 "
            f"먼저 적용하라.\n\n"
            f"{oos_guard}\n\n"
            f"## 에이전트 본문 정책 (guidelines_md)\n"
            f"{gm}\n\n"
            f"{fallback_oos}"
            f"{_TIER_NEUTRAL_ANSWER_GUIDE}"
            f"[/BINDING POLICY]"
        )

    def to_prompt_section(self) -> str:
        """plan_orchestrator system prompt 에 inject 할 텍스트.

        OOS-policy fix (2026-05-07): guidelines_md 를 [BINDING POLICY] block 로
        prepend 해 LLM 이 도메인 외 발화 정책을 *최우선* 적용하도록 한다.
        섹션 헤더 (## current agent / goal / guidelines / allowed_tools / done_when)
        구조 — LLM 이 섹션 의미 인식하기 쉽게.
        """
        tools_str = (
            ", ".join(self.allowed_tools)
            if self.allowed_tools
            else "(미지정 — 전체 카탈로그)"
        )
        kind_label = "어시스턴트 본인 (admin)" if self.is_admin else "역할 에이전트 (role)"
        body = f"""## current agent: {self.name} — {kind_label}

### goal
{self.goal}

### guidelines
{self.guidelines_md}

### allowed_tools
{tools_str}

### done_when
{self.done_when or '(미지정 — LLM 이 자율 판정)'}
"""
        binding = self.to_binding_policy_block()
        if binding:
            return binding + "\n\n" + body
        return body


__all__ = [
    "AgentContext",
    "_strip_tier_doctrine_sections",
    "_TIER_NEUTRAL_ANSWER_GUIDE",
]
