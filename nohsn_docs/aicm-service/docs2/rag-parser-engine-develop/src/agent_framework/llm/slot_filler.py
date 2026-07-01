from __future__ import annotations

import json
import re
from typing import Any, Protocol

from src.agent_framework.llm.json_parse import extract_json
from src.agent_framework.runtime.schema import SlotDef
from src.agent_framework.runtime.time_context import prepend_time
from src.common.logging import get_logger

log = get_logger(__name__)


class LLMClient(Protocol):
    async def complete(
        self,
        system: str,
        user: str | list[dict],
        *,
        response_format: str | None = None,
    ) -> str: ...


_SYSTEM = (
    "너는 slot 추출기다. 아래 메시지에서 필요한 slot 들의 값을 JSON 으로 반환하라. "
    "값이 분명하지 않으면 null. JSON 객체 하나만 출력, 다른 말 금지.\n"
    "\n"
    "## datetime / date slot — 시각·날짜 정규화\n"
    "datetime slot 은 **날짜와 시각이 모두 확정된 경우에만** 값을 채운다. "
    "시각 표기 인정: 'HH:MM' / 'N시' / 한글 숫자 (한/두/세/네/다섯/여섯/일곱/"
    "여덟/아홉/열/열한/열두) + '시' / 한자 숫자 (일/이/.../십이) + '시' / "
    "'정오'(=12:00) / '자정'(=00:00). 분 표기 '반'(=:30) 또는 'N분'.\n"
    "한글 숫자 시각 ISO 정규화: 한시=01:00, 두시=02:00, ..., 열두시=12:00. "
    "'오후' 또는 '저녁'+시간 → +12 (단 오후 열두시 = 12:00 그대로). '오전'+시간 = 그대로.\n"
    "datetime 출력은 ISO 8601 (예: 2026-04-29T14:00:00).\n"
    "'내일 저녁/아침/오후' 처럼 시간대 단어만 있고 정확한 시각이 없으면 null. "
    "'이른 아침/늦은 밤' 같은 모호 표현도 null.\n"
    "\n"
    "## date slot — 상대 날짜\n"
    "date slot 은 ISO date (YYYY-MM-DD) 로만 출력. 시스템 prompt 의 '현재 시각' "
    "이 기준일.\n"
    "상대 날짜 정규화 — 기준일 기준 산술:\n"
    "  - '오늘'/'금일' = 기준일\n"
    "  - '어제'/'전날' = 기준일 -1\n"
    "  - '그저께'/'그제' = 기준일 -2\n"
    "  - '내일'/'명일' = 기준일 +1\n"
    "  - '모레' = 기준일 +2\n"
    "  - 'N일 전'/'N일 후' = 기준일 ∓N\n"
    "  - '이번주 N요일' = 같은 주의 N요일 (월=시작). '지난주/다음주 N요일' 도.\n"
    "  - 'N월 N일' (연도 생략) = 기준일 연도 (이미 지난 날이면 다음 해도 가능 — 문맥)\n"
    "  - 주 단위 표현 (P11-17 회귀):\n"
    "    * '이번주'/'금주'/'이번 주' (요일 명시 X) = 기준일 (현재 주의 대표일).\n"
    "    * '지난주'/'저번주'/'지난 주'/'저번 주' (요일 명시 X) = 기준일이 속한 주의\n"
    "      *직전 주 월요일* 의 ISO date (예: 기준일 2026-04-29 수 → 2026-04-20).\n"
    "    * '다음주'/'담주' (요일 명시 X) = 기준일이 속한 주의 *다음 주 월요일*.\n"
    "    * '저번주 일주일 내내' / '지난주 내내' / '이번주 내내' 같이 *전체 기간* 을\n"
    "      가리키는 표현은 단일 date 로 환원 — 위 규칙대로 해당 주의 *대표일* 사용.\n"
    "  - 단순 '주말'·'평일' 처럼 요일 모호 표현은 null.\n"
    "값이 모호하면 null.\n"
    "\n"
    "## time slot — 시각만 (날짜 없음)\n"
    "이름이 ``time`` 인 slot 또는 description 에 'HH:MM' 명시된 slot 은 **24시간제**\n"
    "ISO time 'HH:MM' (예: '08:00', '21:30') 로 정규화. 발화 안 시각 표현은\n"
    "위 datetime 변환 룰 (오전/오후, 한글 숫자, 정오/자정) 그대로 적용한 뒤\n"
    "*날짜 없이 HH:MM* 만 출력.\n"
    "예시:\n"
    "  '오전 8시' → '08:00'\n"
    "  '오후 9시' → '21:00'\n"
    "  '저녁 아홉시 반' → '21:30'\n"
    "  '정오' → '12:00'\n"
    "  '자정' → '00:00'\n"
    "  '20:30' → '20:30'\n"
    "값이 모호 (시간대 단어만, 정확한 시각 X) 면 null.\n"
    "\n"
    "## recurrence_kind slot — 반복 주기 분류\n"
    "이름이 ``recurrence_kind`` 인 slot 은 4종 enum 으로 정규화:\n"
    "  - 'daily' — '매일/하루마다/일일' 류\n"
    "  - 'weekly' — '매주/주마다/주간' 류\n"
    "  - 'every_n_days' — '격일/이틀마다/N일마다' 류\n"
    "  - 'single' — '한 번만/단발/오늘만/내일만' 또는 특정 단일 날짜 명시.\n"
    "발화에 단서 없으면 null.\n"
    "\n"
    "## weekday slot — 요일 정규화\n"
    "이름이 ``weekday`` 인 slot 은 영문 3-letter 소문자 ('mon'/'tue'/'wed'/'thu'/'fri'/'sat'/'sun')\n"
    "또는 풀네임 ('monday') 로 출력. '월요일' → 'mon', '월' → 'mon', 'Monday' → 'mon'.\n"
    "값이 모호하면 null.\n"
    "\n"
    "## every_n slot — 정수\n"
    "이름이 ``every_n`` 인 slot 은 정수. '격일' → 2, '3일마다' → 3, '5일마다' → 5.\n"
    "값이 모호하면 null.\n"
    "\n"
    "## number / amount slot — 한국어 수사 정규화\n"
    "number 또는 이름이 amount/price/cost/금액 으로 끝나는 slot 은 **반드시 정수**로 출력 "
    "(원 단위, 단위 제거).\n"
    "한국어 수사 곱셈 규칙:\n"
    "  - 만(萬) = 10000, 천 = 1000, 백 = 100, 십 = 10, 억 = 100000000\n"
    "  - 단위 앞 숫자 곱셈 후 합산. 단위 앞 숫자 생략 시 1로 간주 (만오천 = 1*10000 + 5*1000 = 15000).\n"
    "예시:\n"
    "  '만오천원' → 15000\n"
    "  '만삼천원' → 13000\n"
    "  '오만원' → 50000\n"
    "  '십이만오천원' → 125000\n"
    "  '백만원' → 1000000\n"
    "  '1만3천원' → 13000\n"
    "  '1억2천만원' → 120000000\n"
    "  '13,000원'·'13000' → 13000\n"
    "  '13.5만원' → 135000\n"
    "쉼표·공백·'원'·'₩'·'KRW' 제거 후 정수.\n"
    "\n"
    "## 회상·참조·주제 유지 표현 해소 (history 가 주어졌을 때)\n"
    "사용자가 '방금/아까/조금 전/최근/방금 기록한 거/그거' 같은 회상·참조 표현을 "
    "쓰면 history 를 보고 해당 turn 의 사실에서 slot 값을 추론한다.\n"
    "\n"
    "★ **주제 생략 발화** (P11-19, 사용자 보고 회귀):\n"
    "현재 발화에 *주어/대상이 빠져 있고* 직전 turn 에서 다룬 대상이 명백한 경우\n"
    "(예: 직전 turn = '5월 4일 송어횟집 모임 등록' / 현재 turn = '시간을 오후 2시로\n"
    "해줘') 그 *대상명* 을 history 에서 추출해 slot 으로 채운다. 사용자 의도는\n"
    "*같은 대상 정보 변경* 이지 새 대상 등록 X.\n"
    "  - 직전 turn 의 user 발화 또는 assistant 응답에서 핵심 명사 (제목/종목명/약\n"
    "    이름 등) 를 추출해 title / medication_name / 종목 slot 등에 채움.\n"
    "  - 발화에 시각/시간 변경 의도 (예: '시간을 X로', '오후 X시로 해줘') 가 명백\n"
    "    하면 변경 의도로 해석 — slot 값은 *직전 대상명* 을 그대로 가져온다.\n"
    "  - 직전 turn 에 명백한 단일 대상 X 면 강제로 채우지 말고 null.\n"
    "\n"
    "★ **메일 → 일정 변환 (cross-turn 추출)**:\n"
    "직전 assistant 응답이 *메일 정리 결과* (inbox.summary 출력 또는 본문에 메일\n"
    "제목·시각·장소가 명시된 응답) 이고 사용자가 '그 메일 일정 등록해줘' / '웨비나\n"
    "메일 참고해서 일정 만들어' 라고 하면 → assistant 응답 본문에서 다음을 추출:\n"
    "  - title: 메일 제목 또는 응답 안 명시된 행사명 (50자 이내)\n"
    "  - when: 메일에 명시된 datetime → ISO 8601 (예: '4월 29일 오후 3시' →\n"
    "    '2026-04-29T15:00:00')\n"
    "  - where: 메일 안 명시된 장소 ('온라인' / '본사 회의실' 등). 없으면 null.\n"
    "현재 발화에 직접 datetime 추가됐으면 발화 우선, history 추출은 fallback.\n"
    "\n"
    "예) period_start/period_end 가 필요한 조회 skill 에서 '방금 기록한 거' 라면 "
    "history 의 직전 log/save 발화들의 날짜 중 최소를 period_start, 최대를 "
    "period_end 로. history 에 직접 단서 없으면 null.\n"
    "결정의 근거가 history 에만 있을 때도 메시지가 모호하면 강제로 채우지 말고 null.\n"
    "\n"
    "## period_start / period_end — 주·월·년 범위 해소 (P11-17)\n"
    "조회 skill 에서 사용자가 *주/월/년 범위* 를 말하면 period_start 와 period_end "
    "를 *둘 다* 채운다. 한쪽만 채우면 단일 날짜 조회로 오해되어 결과가 0건.\n"
    "기준일 = 시스템 prompt 의 '현재 시각' 의 date 부.\n"
    "  - '이번주'/'금주'/'이번 주' = period_start: 현재 주의 월요일 (ISO date), "
    "period_end: 현재 주의 일요일 (월요일+6일).\n"
    "  - '지난주'/'저번주'/'지난 주'/'저번 주' = period_start: 직전 주 월요일, "
    "period_end: 직전 주 일요일.\n"
    "  - '다음주'/'담주' = period_start: 다음 주 월요일, period_end: 다음 주 일요일.\n"
    "  - '이번달'/'금월'/'이번 달' = period_start: 현재 월 1일, "
    "period_end: 현재 월 말일.\n"
    "  - '지난달'/'저번달'/'지난 달' = period_start: 직전 월 1일, "
    "period_end: 직전 월 말일.\n"
    "  - '올해'/'금년' = period_start: 현재 연도 01-01, "
    "period_end: 현재 연도 12-31.\n"
    "  - '작년'/'지난해' = period_start: 직전 연도 01-01, "
    "period_end: 직전 연도 12-31.\n"
    "  - 'N월' (단일 월) = period_start: <기준일 연도>-N-01, "
    "period_end: <기준일 연도>-N-말일.\n"
    "  - 'N월 N일' 단일 날짜 → period_start 와 period_end 모두 그 날짜 ISO.\n"
    "  - '오늘'/'금일' → period_start = period_end = 기준일.\n"
    "  - '어제' → period_start = period_end = 기준일 -1.\n"
    "  - '최근 N일' → period_start: 기준일 -(N-1), period_end: 기준일.\n"
    "  - 모호 ('얼마나', '대충') → 둘 다 null.\n"
    "원칙: 사용자가 의문문으로 *기간 합계/조회* 를 묻는 경우, period_start 와 "
    "period_end 는 항상 *짝* 으로 채운다. 한 쪽만 채우면 buggy.\n"
    "\n"
    "## 다중 인스턴스 — multi_item 슬롯\n"
    "메시지에 같은 슬롯 세트의 인스턴스가 2개 이상이면 (예: '어제 칼국수 만오천, "
    "오늘 돼지국밥 만삼천'), JSON 출력에 `\"__items\": [{...}, {...}]` 키로 배열 "
    "반환. 각 항목은 단일 인스턴스의 slot 매핑. 단일 인스턴스이면 평소대로 객체.\n"
    "(2+ 인스턴스 판단 기준: 동일 슬롯이 다른 값을 갖도록 짝지어진 절·구·문장.)"
)


# datetime slot 이 "시각 없이 시간대 단어만" 갖고 있는지 검사하기 위한 패턴.
# 아래 둘 다 참이면 vague → slot 미확정으로 간주.
#  1) 문자열에 HH:MM / HH시 같은 구체적 시각 표시가 **없다**
#  2) "저녁/아침/오후/오전/밤/새벽/점심/정오" 같은 시간대 단어가 있다
# 시각 표시 — latin digit + 한글/한자 숫자 시각 + 정오/자정 + 분 표기.
# 2026-04-28 사용자 신고 + GPT-5.5 검토:
#   - "오후 두시" 한글 숫자 추가
#   - "정오"/"자정" 정확 시각
#   - sino-Korean 시 (일시/이시/.../십이시)
#   - "반"/"N분" 분 표기 (옵션)
_NATIVE_HOUR = r"(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열한|열두|열)"
_SINO_HOUR = r"(?:십이|십일|일|이|삼|사|오|육|칠|팔|구|십)"
_HOUR_NUMERAL = r"(?:" + _NATIVE_HOUR + r"|" + _SINO_HOUR + r")"
_EXACT_TIME = r"(?:정오|자정)"
_MIN_SUFFIX = r"(?:\s*(?:반|\d{1,2}\s*분))?"
_TIME_HHMM_RE = re.compile(
    r"(?:\bT\d{1,2}:\d{2}\b|\d{1,2}:\d{2}"
    + r"|\d{1,2}\s*시" + _MIN_SUFFIX
    + r"|" + _HOUR_NUMERAL + r"\s*시" + _MIN_SUFFIX
    + r"|" + _EXACT_TIME + r")"
)
_VAGUE_TIMEOFDAY_RE = re.compile(
    r"(저녁|아침|오후|오전|밤|새벽|점심|정오|이른|늦은)"
)


def _is_vague_when(value: Any) -> bool:
    """datetime slot 값이 '시간대만 있고 구체 시각이 없는' 상태인지.

    SlotFiller 가 LLM 으로 추출한 값을 돌려주기 **전에** 한 번 더 확인.
    string 타입이 아닌 경우 (dict / datetime instance) 는 vague 여부 판단이
    모호하니 False (통과) — LLM/downstream 이 처리.
    """
    if not isinstance(value, str):
        return False
    if not value.strip():
        return True  # 빈 문자열은 vague
    has_explicit_time = bool(_TIME_HHMM_RE.search(value))
    has_vague_word = bool(_VAGUE_TIMEOFDAY_RE.search(value))
    return has_vague_word and not has_explicit_time


class SlotFiller:
    def __init__(self, llm_client: LLMClient, max_retries: int = 1):
        self.llm = llm_client
        self.max_retries = max_retries

    async def fill(
        self,
        user_message: str,
        slot_defs: list[SlotDef],
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """slot 추출.

        반환:
        - 단일 인스턴스: ``{slot_name: value, ...}``
        - 다중 인스턴스: ``{"__items": [{slot_name: value, ...}, ...]}``
          호출자(engine) 가 ``__items`` 키 존재 여부로 fan-out 분기.

        history (옵션): 이전 turn 의 user/assistant 발화. "방금 기록한 거",
        "그거", "아까 말한" 같은 회상·참조 표현이 발생하면 history 를 보고
        분석가가 period_start/period_end / 참조 식별을 추론. 호출자가 sess.history
        를 그대로 넘길 수 있다. 마지막 6턴까지만 prompt 에 포함.
        """
        schema_desc = [
            {"name": s.name, "type": s.type, "values": s.values} for s in slot_defs
        ]
        history_section = ""
        if history:
            recent = history[-6:]
            lines = []
            for m in recent:
                role = m.get("role", "")
                content = (m.get("content", "") or "").strip()
                if not content:
                    continue
                role_label = "사용자" if role == "user" else (
                    "어시스턴트" if role == "assistant" else role
                )
                lines.append(f"{role_label}: {content}")
            if lines:
                history_section = "## 직전 대화 (참조·회상 표현 해소용)\n" + "\n".join(lines) + "\n\n"
        user = (
            f"{history_section}"
            f"메시지: \"{user_message}\"\n"
            f"필요한 slots: {json.dumps(schema_desc, ensure_ascii=False)}\n"
            f"JSON 만 출력. 다중 인스턴스면 __items 배열."
        )
        # must_be_specific=true 인 datetime slot 이 있을 때, 사용자 메시지에
        # 구체 시각(HH:MM / N시 / T-시간) 표시가 있는지 사전 확인. LLM 이
        # "내일" 만 보고 06:00 같은 default 를 채워 보내도, user_message 에
        # 시각 표시가 없으면 ask_user_clarify 가 발동되도록 강제 reject.
        # 2026-04-28 사용자 신고: "대표님하고 미팅" 발화에 시간 명시 없는데
        # 자동 등록되던 버그.
        strict_datetime_slots = {
            s.name for s in slot_defs
            if s.type == "datetime" and getattr(s, "must_be_specific", False)
        }
        user_message_has_explicit_time = bool(_TIME_HHMM_RE.search(user_message))

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            raw = await self.llm.complete(
                prepend_time(_SYSTEM), user, response_format="json_object"
            )
            try:
                parsed = extract_json(raw)
                if isinstance(parsed, dict):
                    datetime_slot_names = {
                        s.name for s in slot_defs if s.type == "datetime"
                    }

                    def _post_process_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
                        # 1) datetime slot 의 LLM 결과가 vague 단어만 갖고 있으면 null.
                        for sname in datetime_slot_names:
                            v = bundle.get(sname)
                            if v is not None and _is_vague_when(v):
                                log.info(
                                    "slot_filler_vague_datetime_rejected",
                                    slot=sname,
                                    value_preview=str(v)[:40],
                                )
                                bundle[sname] = None
                        # 2) must_be_specific 슬롯 — user_message 자체에 시각이 없으면
                        # LLM 의 default 추측(예: 06:00) 을 거부.
                        if not user_message_has_explicit_time:
                            for sname in strict_datetime_slots:
                                if bundle.get(sname) is not None:
                                    log.info(
                                        "slot_filler_strict_datetime_rejected",
                                        slot=sname,
                                        user_message_preview=user_message[:60],
                                        llm_value=str(bundle.get(sname))[:40],
                                    )
                                    bundle[sname] = None
                        return bundle

                    # multi-item 분기 — LLM 이 __items 배열로 돌려줬으면 각 bundle
                    # post-process 후 그대로 return. engine fan-out 이 N 회 save 실행.
                    items = parsed.get("__items")
                    if isinstance(items, list) and items:
                        cleaned = [
                            _post_process_bundle(dict(it))
                            for it in items
                            if isinstance(it, dict)
                        ]
                        log.info(
                            "slot_filler_multi_item_detected",
                            count=len(cleaned),
                            user_message_preview=user_message[:80],
                        )
                        return {"__items": cleaned}

                    return _post_process_bundle(parsed)
                raise ValueError("not a dict")
            except Exception as e:
                last_err = e
                log.warning("slot_filler bad json", attempt=attempt, error=str(e))
        raise RuntimeError(f"slot filler failed after retries: {last_err}")
