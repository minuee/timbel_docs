"""LLM multi-label intent classifier — 스킬 trigger 집합에서 어느 것이 발화와 매칭되는지.

Task 14.5 — 기존 ``IntentClassifierAdapter`` 의 stub (`["general_query"]` 만 반환)
을 대체. 라벨 집합을 주입받아 LLM 에 JSON 형태로 분류를 요청하고, 할루시네이션을
필터링한 뒤 실제 매칭 라벨만 리턴한다.

Stage B-Core-2 — 가변 labels 지원.
 - ``classify_multi(available_labels=...)`` 로 호출 시점에 tenant/session 별 라벨
   집합을 넘길 수 있음. None → ``self.labels`` 로 fallback (legacy).
 - ``available_labels=[]`` → LLM 호출 없이 즉시 ``["_no_skills_available"]`` 반환.
 - LLM 이 명확한 요청이지만 매칭 라벨이 없다고 판단하면 ``["unsupported"]`` 반환;
   이 sentinel 은 할루시네이션 필터를 항상 통과.

fail-safe 원칙:
 - 빈 라벨 집합 (constructor 에서, override 없음) → 즉시 빈 리스트
 - 라벨 밖 값 → 제거 (단, "unsupported" sentinel 은 예외)
 - JSON 파싱 실패 → 빈 리스트 (→ SkillRouter 에서 기본 응답 라우팅)
"""

from __future__ import annotations

import json
from typing import Protocol

from src.agent_framework.llm.json_parse import extract_json
from src.agent_framework.runtime.time_context import prepend_time
from src.common.logging import get_logger

log = get_logger(__name__)


class LLMClient(Protocol):
    async def complete(
        self, system: str, user: str, *, response_format: str | None = None
    ) -> str: ...


# 예약 sentinel 라벨 — 엔진이 전용 응답 경로로 라우팅하는 데 사용.
UNSUPPORTED_LABEL = "unsupported"
NO_SKILLS_AVAILABLE_LABEL = "_no_skills_available"
# 사용자가 "뭐 할 수 있어?/무슨 기능 있어?" 같이 서비스 능력 소개를 요청하는 경우.
# 엔진은 이 sentinel 을 받으면 현재 계정의 enabled skill 목록을 소개하는 응답을 생성.
CAPABILITY_QUERY_LABEL = "_capability_query"
# 사용자가 "이런 기능 추가해 줘/만들자" 처럼 **새 기능 정의/확장** 을 요청하는 경우.
# 엔진은 이 sentinel 을 받으면 DraftComposer 로 skill YAML draft 를 생성해
# skill_drafts 테이블에 쌓아 두고, 사용자에게 "검토 대기 중" 안내를 돌려준다.
# (Task 34-36 Phase A)
SKILL_DRAFT_REQUEST_LABEL = "_skill_draft_request"


_SYSTEM_TEMPLATE = (
    "너는 intent 분류기다. 발화의 **의도 유형** 을 먼저 파악한 뒤 라벨을 선택한다.\n"
    "표면 어휘 암기가 아닌 의미·맥락 기반으로 판단하므로 "
    "아래 '원리' 와 의미가 같으면 다른 단어로 표현되어도 같은 분류가 된다.\n"
    "\n"
    "## 출력 유형 (택 1)\n"
    "\n"
    "1) 주어진 intent 라벨 집합 중 **의미상 매칭되는** 라벨(들)만 JSON 배열로 반환.\n"
    "   여러 의도가 섞여 있으면 모두 포함. 라벨 집합 밖 값 추측 금지.\n"
    "\n"
    "2) 사용자가 명확히 어떤 기능/작업을 **요청** 하고 있으나 라벨 집합에 대응이 "
    "전혀 없으면 `unsupported` 하나만 반환.\n"
    "\n"
    "3) 사용자가 **시스템 자체가 제공하는 역할·능력·기능 범위** 를 메타적으로 "
    "물으면 `_capability_query` 하나만 반환. 특정 기능을 실행/조회해 달라는 "
    "요청과 구분할 것: 전자는 '네 역할이 뭐야?' 수준의 질문, 후자는 실제 작업 요청.\n"
    "\n"
    "4) 인사·맞장구·감정 호소·자기소개 질문 등 '요청' 이 아닌 발화는 빈 리스트 `[]`.\n"
    "\n"
    "5) 사용자가 **새 기능/자동화를 만들어 달라 요청** (\"이런 기능 추가해 줄 수 있어?\", "
    "\"이거 자동으로 해주는 거 만들자\", \"...하는 기능이 있으면 좋겠다\", "
    "\"내가 기능 하나 정의해줄게\") 하면 `_skill_draft_request` 하나만 반환.\n"
    "   - 기존 기능을 사용하려는 요청과 구분: 전자는 \"없는 기능을 만들어 달라\", "
    "후자는 \"있는 기능을 써달라\".\n"
    "\n"
    "## 라벨 선택 원리\n"
    "\n"
    "- **의도 유형별 구분**:\n"
    "  · 상태 조회 — 현재 상태/시간/종류/가격/목록을 물음 → 해당 *_hours, *_treatment, list_* 류\n"
    "  · 상태 변경 — 새로 만들거나 취소·변경·해지 요청 → create/book/add/remove 류\n"
    "  · 회상 조회 — 과거 기록·로그 탐색 → recall_* 류\n"
    "  · 기록 — 사용자의 감정·상태·사건을 지금 저장 → log_* 류\n"
    "  · 자원·재고 조회 (status/용량/변동) — 적재된 **데이터 자원**의 status 분포·"
    "용량·최근 변동 등 통계적 메타 질의 → `kms_inventory_query`. "
    "'용량 얼마야?', '최근 추가된 거?', 'pending 몇 개?' 같이 **status·시간 변동·"
    "사이즈** 가 핵심 어휘.\n"
    "  · 자기 인벤토리 자기 소개 (카테고리 합산 + 블록 수 + 색인 수) — 사용자가 "
    "자기 워크스페이스에 **무엇이 얼마나 등록되어 있는지** 자기 소개적으로 묻거나, "
    "검색 인덱스의 **블록·청크 단위 갯수** 를 묻는 경우 → `ask_my_data_inventory`. "
    "'지금 너가 참고하는 지식이 몇 개야?', '등록된 문서 몇 개야?', "
    "'내 워크스페이스에 뭐 있어?', '지식 등록된 거 몇 개?', '활성 스킬 무엇?', "
    "'블록 몇 개야?', '검색 가능한 청크 몇 개?', '지금 참고하는 지식 문서의 "
    "블럭수가 어떻게 되지?' 처럼 **본인의 자료 보유 전반** 을 묻는다. "
    "**검색·조회 결과 (kms_rag.search) 가 아니라 *전체 인벤토리 메타* 라는 점이 핵심**.\n"
    "  · 시스템 메타 — 시스템의 역할 자체 질의 → `_capability_query`\n"
    "\n"
    "- **list_* vs create/log 구분 (가장 흔한 오분류)**:\n"
    "  · **의문형·부정형으로 '현재 상태' 를 묻는 발화** → list_* (조회)\n"
    "      예) '있나/없나/되어 있어?/뭐뭐 있어?/갈 일 있어?/약속 잡혀 있지?'\n"
    "      부정형 질문 ('병원 갈 일 없나?') 도 조회이지 등록이 **절대 아님**.\n"
    "  · **특정 시간·주제를 동반한 선언/명령** → create/log 류 (상태 변경)\n"
    "      예) '내일 3시 회의 잡아줘/등록해줘/추가해줘/저장해줘/박아둬'\n"
    "  · 같은 어휘라도 **문장 말미의 종결** 이 판단 근거. '-해줘/-등록/-추가' = 명령, '-있나/-없냐/-잡혀있어?' = 질문.\n"
    "\n"
    "- **동사의 목적어로 모호성 해소**: '기록한다/저장한다' 는 그 자체로 어느 라벨도 결정하지 못한다.\n"
    "  · 목적어가 감정·하루·기분·느낌 같은 **경험** → 일기 계열\n"
    "  · 목적어가 약속·회의·일정·미팅 같은 **시간 이벤트** → 일정 계열\n"
    "\n"
    "- **★ 식비·지출 도메인 — 행위 분기 (P11-19d, 사용자 보고 회귀)**:\n"
    "  expense (식비/지출/가계부) 도메인 발화는 *행위 동사* 로 4가지 라벨 분기.\n"
    "  같은 '식비' 명사라도 동사가 *기록·등록·저장* 이면 log_expense, *조회·합계·\n"
    "  얼마* 면 expense_query, *삭제·지워·빼·제외·없애* 면 expense_delete.\n"
    "  · log_expense — '어제 점심 만오천원', '오늘 35000원 썼어'.\n"
    "  · expense_query — '이번주 식비 얼마야', '이번달 총 지출', '얼마 썼어'.\n"
    "  · expense_delete — '27만원 두 건 빼줘', '인베스트먼트 비용 삭제해줘',\n"
    "    '중복된 점심비 지워', '그 항목 잘못됐어 빼고 다시 계산해줘'.\n"
    "  · expense_analyzer — 분석·요약 ('식비 카테고리별 분석').\n"
    "  '삭제/지워/빼/제외/없애/빼고/제거' 같은 동사가 발화에 있으면 *절대*\n"
    "  log_expense 로 분류 X — expense_delete 우선. 사용자 보고 (2026-04-30) 회귀\n"
    "  직접 원인: '삭제해줘' 발화가 log_expense 로 잡혀 expense_logger 가\n"
    "  expense.create 를 호출, 의도와 정반대로 *신규 항목* 추가됨.\n"
    "\n"
    "- **★ 도메인 + 행위 vs 도메인 + 정보 구분 (P11-19)**:\n"
    "  같은 도메인 명사 (주식·식비·일정 등) 라도 *행위 의도* 와 *정보 조회 의도*\n"
    "  는 다른 라벨로 분류. 이 구분이 plan 라우터의 정확도 직접 결정 요인.\n"
    "  · *행위*: 시스템에 *조작·기록·등록·실행* 시키는 발화 → 도메인 행위 intent.\n"
    "    예) '삼성전자 현재가 알려줘' (특정 종목 시세 조회) = stock_quote.\n"
    "        '삼성전자 53주 샀어' = stock_register.\n"
    "        '23만원 되면 알려줘' = stock_watch.\n"
    "    ★ 거래 의향 (매수/매도) — 실시간 주문 미지원 → *관심 종목 등록* 으로\n"
    "    대체 분류. '종목명 + 거래 동사 (매수/사자/담아/들어가/진입/추매/물타기/\n"
    "    매도/팔자/익절/손절 등 — 이에 한정 X) + (금액|수량)?' 패턴은 stock_watch\n"
    "    로 분류 (tool=stock.add_watch). '카카오 20만원치 매수해줘' / '삼성전자 사자' /\n"
    "    '엔비디아 50만원 담아' / '테슬라 들어가자' / 'NVDA 한 주' = stock_watch.\n"
    "    매도 발화 ('절반 팔자', '익절하자') 도 stock_watch (note='매도 의향').\n"
    "    절대 unsupported 로 분류 X — 시스템이 *관심 등록* 으로 처리한다.\n"
    "    ★★ 시제 가드 (stock_register vs stock_watch 충돌 방지):\n"
    "    · 과거 체결 보고 ('샀어/팔았어/매수했어/매도했어/담았어/털었어') = stock_register.\n"
    "    · 미래·명령·의향 ('사자/매수해줘/담아/들어가자/추매/익절/손절') = stock_watch.\n"
    "    단, 네거티브 (비금융 맥락) 는 제외: '사자 사진/사자성어' (동물·고사),\n"
    "    '테슬라 방 들어가자/단톡방/카카오톡 들어가자' (채팅방·메신저),\n"
    "    '비트코인 담아' (코인 — stock X), '삼성전자 사장 누구야' (인물),\n"
    "    '테슬라 모델3 사자/아이폰 사자/그래픽카드 사자' (제품). 종목명 확신 안 되면\n"
    "    *unsupported X*, 오히려 stock_watch 로 분류해 도구가 Clarify 하도록 위임.\n"
    "        '어제 점심 만오천원' = log_expense.\n"
    "        '내일 3시 회의 등록' = create_schedule.\n"
    "        '메모에 X 남겨줘' / '아 맞다 내일 보고서 제출 2시 마감' / "
    "'이거 까먹지 않게 적어둬' = memo_capture.\n"
    "        '내 메모 보여줘' / '진행 중인 할 일' = memo_list.\n"
    "        '그 메모 완료 처리' = memo_complete.\n"
    "        'X 한테 메일 보내줘' / '회신 보내줘' / '그 초안 발송' / "
    "'그 메일로 발송해줘' = mail_send.\n"
    "        '윤종후 보낸 메일 찾아줘' / '계약서 메일 검색' = mail_query (mail.search).\n"
    "    ★ schedule vs memo: '회의/약속/만남/미팅' 같이 *대면* 또는 *시각 명확*\n"
    "    이벤트는 create_schedule. '제출/완료/까먹지/마감/할일/메모/적어둬' 같이\n"
    "    *기한 있는 할일* 또는 *기록* 의도면 memo_capture. 발화에 '메모' 단어가\n"
    "    있으면 *항상* memo_capture.\n"
    "    ★ mail_send vs mail_query: '보내줘/발송/회신/답장' = mail_send (행위).\n"
    "    '찾아줘/검색/리스트' = mail_query (조회).\n"
    "  · *정보 조회*: 제도·시간·방법·뜻·배경 같은 *지식 안내* 답변을 기대 → \n"
    "    `info_lookup` (없으면 `knowledge_query`).\n"
    "    예) '주식 거래 시간 알려줘' = info_lookup (시세 X, 시간 정보).\n"
    "        '주식 매매 수수료는 어떻게 돼' = info_lookup.\n"
    "        'T+2 결제가 뭔 뜻이야' = info_lookup.\n"
    "        '신용카드 한도가 뭐야' = info_lookup.\n"
    "  · 판단 기준 (LLM 일반화 — 키워드 X):\n"
    "    1) 발화에 *특정 인스턴스* (특정 종목명/장소/사람/날짜) + 조작 동사 → 행위.\n"
    "    2) 발화에 *일반 명사* (주식/거래/매매/제도) + 정보 verb (알려줘/뭐야/\n"
    "       어떻게 되) → 정보 조회.\n"
    "    3) 사용자가 *답으로 받고 싶은 것* 이 *데이터 변경 결과* 면 행위, *사실 안내* 면 정보.\n"
    "  · 모호하면 두 라벨 모두 반환 (multi-label OK) — 라우터 단에서 LLM 재판단.\n"
    "\n"
    "- **화자 의도로 모호성 해소**: 의료·서비스 도메인에서 '예약'·'가다' 동사 방향:\n"
    "  · 시스템에 **위임** ('예약해줘/잡아줘') → 예약 intent\n"
    "  · 본인 의사 **선언** ('~ 갈게요/할게요') → 일정 등록 intent (본인 캘린더 저장)\n"
    "\n"
    "- **복합 질의**: 같은 대상에 대해 두 속성을 동시에 물으면 두 라벨 모두 반환.\n"
    "  예) 특정 인물의 근무 요일 = 인물 정보 + 시간 정보.\n"
    "\n"
    "- **형태 힌트**:\n"
    "  · 공손한 의문형·가정형·높임체도 **요청** 이면 분류 대상 (단순 인사 아님).\n"
    "  · 기능 범위를 복수형·목록 뉘앙스로 묻는 형태는 `_capability_query`.\n"
    "  · '너 누구야?/이름 뭐야?' 같은 **신원** 질의는 시스템 능력이 아니라 일상 대화 → `[]`.\n"
    "\n"
    "- **대화 이력 활용**: 직전 턴이 제공되면 반드시 참고.\n"
    "  · 대명사·지시어('그거/그걸/그때/거기') 는 직전 내용으로 해소\n"
    "  · 생략된 목적어(\"취소해줘\" → 직전에 예약한 대상) 도 참조 해소\n"
    "  · 'yes/아니/네/좋아/응' 같은 승낙·거절은 직전 assistant 가 무엇을 물었는지 보고 판단\n"
    "  · 참조 해소해서 의도가 '예약 취소' 로 확정되면 해당 intent 반환 (unsupported 로 도망 금지)\n"
    "\n"
    '출력 형식: {"intents": ["..."]}'
)


# 대화 이력을 classifier 에 노출할 최대 턴 수. user+assistant 번갈아 들어오므로
# 6 = 약 3 상호작용. 너무 크면 prefill 비용 증가.
_HISTORY_WINDOW = 6


class MultiLabelIntentClassifier:
    """스킬 trigger intent 집합에 대한 multi-label 분류기."""

    def __init__(self, llm_client: LLMClient, labels: list[str]):
        self.llm = llm_client
        self.labels = list(labels)  # 복사본, 불변성

    async def classify_multi(
        self,
        user_message: str,
        history: list[dict] | None = None,
        *,
        available_labels: list[str] | None = None,
    ) -> list[str]:
        # available_labels 가 명시적으로 빈 리스트 → sentinel 즉시 반환 (LLM 호출 없음).
        if available_labels is not None and len(available_labels) == 0:
            return [NO_SKILLS_AVAILABLE_LABEL]

        # candidate 결정: override > constructor labels
        candidates: list[str] = (
            list(available_labels) if available_labels is not None else self.labels
        )

        # constructor 빈 labels + override 미지정 → 레거시 조용 모드 (빈 리스트).
        if not candidates:
            return []

        # 대화 이력 — 참조 해소용. history 를 **발화보다 먼저** 배치해서
        # LLM 이 현재 발화를 읽기 전에 맥락을 먼저 흡수하게 함.
        history_section = ""
        if history:
            last = history[-_HISTORY_WINDOW:]
            if last:
                lines = []
                for m in last:
                    role = m.get("role", "")
                    content = (m.get("content", "") or "").strip()
                    if not content:
                        continue
                    role_label = "사용자" if role == "user" else (
                        "어시스턴트" if role == "assistant" else role
                    )
                    lines.append(f"{role_label}: {content}")
                if lines:
                    history_section = "## 직전 대화 이력\n" + "\n".join(lines) + "\n\n"

        user_prompt = (
            f"{history_section}"
            f"## 사용 가능한 intent 라벨\n{candidates}\n\n"
            f'## 분류할 현재 사용자 발화\n"{user_message}"\n\n'
            f"JSON 만 출력."
        )

        raw: str | None = None
        try:
            raw = await self.llm.complete(
                prepend_time(_SYSTEM_TEMPLATE),
                user_prompt,
                response_format="json_object",
            )
            data = extract_json(raw)
            detected = data.get("intents", [])
            if not isinstance(detected, list):
                return []
            # 할루시네이션 제거: candidate 집합 내에 있는 것만 통과.
            # 단, sentinel 라벨(unsupported / _capability_query) 은 항상 통과.
            allowed = set(candidates)
            passthrough_sentinels = {
                UNSUPPORTED_LABEL,
                CAPABILITY_QUERY_LABEL,
                SKILL_DRAFT_REQUEST_LABEL,
            }
            return [
                x for x in detected if x in allowed or x in passthrough_sentinels
            ]
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            log.warning("intent classifier bad json", error=str(e), raw=raw)
            return []  # fail-safe → 스킬 라우팅 불가 → 기본 응답
