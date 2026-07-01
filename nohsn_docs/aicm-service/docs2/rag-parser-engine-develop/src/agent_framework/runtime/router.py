from src.agent_framework.runtime.schema import Skill


# PR-H — 의도 라벨 명명 컨벤션. *동사_* prefix 가 붙은 의도는 사용자의 *명확한 행동*
# 신호 (등록·조회·삭제·로그 등). 같은 detected_intents 안에 동사형과 명사형(daily_briefing
# 같은 generic) 이 함께 매칭되면 동사형이 우선. R4 회귀의 직접 원인 — "내일 약속 등록"
# 발화가 [daily_briefing, create_schedule] 둘 다 매칭됐는데 알파벳 정렬 첫 매칭 (daily_*)
# 이 우선되어 schedule_personal 의 create_schedule 가 무시됐다.
_VERB_PREFIXES: tuple[str, ...] = (
    "create_", "list_", "delete_", "update_",
    "log_", "recall_", "set_", "register_",
    "remove_", "subscribe_", "unsubscribe_",
    "report_", "file_", "book_", "find_",
    "lookup_", "search_", "inquire_",
    "ask_", "check_", "configure_",
    "approve_", "escalate_", "schedule_", "cancel_",
)


def _is_verb_intent(intent: str) -> bool:
    return intent.startswith(_VERB_PREFIXES)


class SkillRouter:
    def __init__(self, skills: dict[str, Skill]):
        # 결정적 매칭을 위해 정렬된 skill id 기준
        self._skills = dict(sorted(skills.items()))

    def route(self, detected_intents: list[str]) -> str | None:
        """PR-H — 매칭 우선순위:
        1. *동사형* (create_/list_/delete_/log_/...) intent 매칭 skill — 사용자
           행동 의도가 명확.
        2. *명사형* (daily_briefing 같은 generic) intent 매칭 skill — 행동 의도가
           모호한 fallback.
        3. detected_intents 순서가 같은 priority 안에서 우선 (intent classifier
           가 가장 적합한 의도를 첫 위치에 두기를 기대).
        4. 모두 실패 시 None.
        """
        # detected_intents 순서를 우선시 (classifier 가 의미적 정렬한 결과로 가정).
        # intent → skill_id 매칭은 (intent_index, is_verb) 기준 정렬.
        priority_high: list[tuple[int, str]] = []  # 동사형
        priority_low: list[tuple[int, str]] = []   # 명사형

        for skill_id, skill in self._skills.items():
            if skill.trigger_type != "intent":
                continue
            for t in skill.triggers:
                if t.intent not in detected_intents:
                    continue
                idx = detected_intents.index(t.intent)
                if _is_verb_intent(t.intent):
                    priority_high.append((idx, skill_id))
                else:
                    priority_low.append((idx, skill_id))
                break  # 한 skill 의 첫 매칭 trigger 만 — 중복 push 방지

        if priority_high:
            priority_high.sort()  # idx 작은 것 우선
            return priority_high[0][1]
        if priority_low:
            priority_low.sort()
            return priority_low[0][1]
        return None
