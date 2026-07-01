"""Utterance Classifier — verb × domain 2축 분류 (P11-19d, 2026-04-30).

## 배경

기존 ``intent_classifier`` 는 96+ 라벨 single-label 분류 → verb 식별 정확도 낮음.
사용자 보고 회귀 (2026-04-30): "27만원 삭제해줘" 가 ``log_expense`` 로 잘못
분류 → expense_logger V1 state machine 가로챔 → 정반대로 expense.create 호출.

## 해결

verb (6 enum) × domain (10 enum) 으로 분리. 각 LLM 호출의 decision space 축소.
GPT-5.5 자문 (2026-04-30) 권장 — 96라벨 단일 분류보다 견고.

verb:
- ``log``      — 새 항목 등록·기록 ("어제 점심 만오천원")
- ``query``    — 조회·합계·리스트 ("이번달 식비 얼마?", "내 알람 보여줘")
- ``delete``   — 삭제·해제·취소 ("27만원 두 건 빼줘", "그 알람 멈춰")
- ``update``   — 수정·변경 ("시간을 오후 2시로", "수량을 530주로")
- ``info``     — 지식·정보 조회 ("주식 거래 시간", "T+2 가 뭐야")
- ``smalltalk``— 인사·자유 대화 ("안녕", "고마워")
- ``cancel``   — 취소 (delete 와 다름 — 진행중 작업 중단)
- ``unknown``  — 결정 불가

domain:
- ``expense``    — 식비·지출·가계부
- ``schedule``   — 일정·약속·미팅
- ``reminder``   — 알람·복약 알림
- ``mail``       — 메일함
- ``stock``      — 주식 (시세·등록·모니터링·분석)
- ``kms``        — KMS 자료·문서·블록 메타
- ``contact``    — 연락처·인물 (후속 PR)
- ``task``       — 할 일·todo (후속 PR)
- ``settings``   — 설정·페르소나
- ``none``       — 위 어디에도 안 속함

## (verb, domain) → canonical 카테고리 매핑

plan_router 의 결정적 매핑 테이블이 변환 책임. 비직교 조합은 fallback.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.common.logging import get_logger

log = get_logger(__name__)


VERBS = (
    "log", "query", "delete", "update", "info", "smalltalk", "cancel", "unknown",
)
DOMAINS = (
    "expense", "schedule", "reminder", "mail", "stock", "kms",
    "contact", "task", "settings", "none",
)


@dataclass
class IntentSlot:
    """단일 의도 슬롯 — 다중 인텐트의 각 항목."""

    verb: str
    domain: str
    confidence: float
    reasoning: str = ""


@dataclass
class UtteranceCategory:
    """utterance_classifier 결과.

    P11-19h (2026-05-01) — 다중·애매 인텐트 지원:
    - intents: 식별된 의도 배열 (단일·다중)
    - primary: intents[0] (호환 — 옛 verb/domain 단일 사용 호출자)
    - is_ambiguous: 의도 결정 불가 → ask_user_clarify 필요
    - clarification_question: ambiguous 시 사용자에게 던질 질문
    """

    verb: str  # primary verb (호환)
    domain: str  # primary domain (호환)
    confidence: float
    reasoning: str = ""
    intents: list[IntentSlot] = field(default_factory=list)
    is_ambiguous: bool = False
    clarification_question: str | None = None


_SYSTEM_PROMPT = (
    "당신은 한국어 챗봇의 사용자 발화를 *행위(verb)* 와 *도메인(domain)* 두 축으로 "
    "분류하는 분류기입니다. 발화에 *복수* 의도가 있으면 모두 분리. *애매* 하면 "
    "사용자에게 물을 질문 생성. JSON 한 객체로 응답.\n"
    "\n"
    "## 출력 형식 (P11-19h — 다중·애매 인텐트 지원)\n"
    "\n"
    "```json\n"
    "{\n"
    '  "intents": [\n'
    '    {"verb": "<...>", "domain": "<...>", "confidence": 0.0~1.0, "reasoning": "..."},\n'
    '    ...\n'
    "  ],\n"
    '  "is_ambiguous": true|false,\n'
    '  "clarification_question": "사용자에게 물을 한 줄 질문 (is_ambiguous=true 일 때만, 아니면 null)"\n'
    "}\n"
    "```\n"
    "\n"
    "- intents 는 *식별된 의도 배열* — 단일이면 길이 1, 다중이면 사용자가 발화에서\n"
    "  명시한 *각 distinct 행위* 를 분리해 추가.\n"
    "- ★★ **다중 인텐트 적극 식별**: '그리고/하고/+/도/같이' 같은 *연결 표현* 또는\n"
    "  서로 다른 도메인 명사 (회의/지출/알람/메일 등) 가 한 발화에 *둘 이상* 있으면\n"
    "  반드시 intents 배열에 *각각* 분리해 추가. 절대 단일로 합치지 말 것.\n"
    "- 다중 예 1: '내일 회의 등록하고 어제 점심 만오천원 기록해줘' →\n"
    "  intents=[{verb:'log',domain:'schedule'},{verb:'log',domain:'expense'}]\n"
    "- 다중 예 2: '오늘 메일 요약하고 이번주 일정도 보여줘' →\n"
    "  intents=[{verb:'query',domain:'mail'},{verb:'query',domain:'schedule'}]\n"
    "- 다중 예 3: '삼성전자 시세 알려주고 매일 8시 알람 만들어' →\n"
    "  intents=[{verb:'query',domain:'stock'},{verb:'log',domain:'reminder'}]\n"
    "- 단일이면 단일. 작위적으로 split 하지 말 것 — 한 행위에 여러 인자만 있는\n"
    "  발화 ('어제 점심 만오천원 식비로') 는 *단일* (verb=log, domain=expense) 하나.\n"
    "- *애매 (모호)* 인텐트: 발화만으로는 verb 또는 domain 결정 불가, 또는 같은\n"
    "  발화가 여러 도메인 후보 가능하면 is_ambiguous=true + clarification_question.\n"
    "  - 예: '그거 빼줘' (직전 컨텍스트 없으면 애매) → is_ambiguous=true,\n"
    "    clarification_question='어떤 항목을 빼시겠어요? 일정 / 지출 / 알람 중 어느 것인지 알려 주세요.'\n"
    "  - 예: '정리해줘' 단독 → is_ambiguous=true,\n"
    "    clarification_question='무엇을 정리해 드릴까요? 일정·지출·메일 중 어느 것인지 말씀해 주세요.'\n"
    "  - 단, 직전 history 로 컨텍스트가 명확하면 ambiguous 아님 (예: 직전 turn 가\n"
    "    expense 등록 후 사용자가 '그거 빼줘' → expense delete 로 결정).\n"
    "- *모든 confidence 가 ≤0.5* 이면 is_ambiguous=true (보수적 안전망).\n"
    "\n"
    "## 호환 형식 (legacy — 예전 단일 출력)\n"
    "\n"
    "단일 의도면 다음과 같이 출력해도 OK:\n"
    "```\n"
    '{"verb": "<...>", "domain": "<...>", "confidence": ..., "reasoning": "..."}\n'
    "```\n"
    "이 경우 자동으로 intents=[{verb,domain,confidence,reasoning}] 단일 항목으로 변환.\n"
    "\n"
    "## verb (8 종)\n"
    "- log: *새 항목 등록·기록·저장*. 사용자가 시스템에 *새 데이터를 추가* 하려는 의도.\n"
    "  예: '어제 점심 만오천원 썼어', '5월 4일 송어횟집 모임 등록', '매일 8시 알람 만들어'\n"
    "- query: *조회·합계·리스트·검색*. 시스템에 *기록된 데이터를 보여달라*.\n"
    "  예: '이번달 식비 얼마?', '내 알람 보여줘', '오늘 일정 알려줘'\n"
    "- delete: *삭제·제거·해제·없애·빼·제외*. 시스템에 *기존 데이터를 없애달라*.\n"
    "  예: '27만원 두 건 빼줘', '인베스트먼트 비용 삭제해줘', '그 일정 지워'\n"
    "- update: *수정·변경*. 시스템의 *기존 데이터를 다른 값으로 변경*.\n"
    "  예: '시간을 오후 2시로 해줘', '수량을 530주로 바꿔', '일정 수정'\n"
    "- info: *지식 조회·설명*. 시스템 *외부 사실/제도/방법/뜻* 을 묻는 발화.\n"
    "  예: '주식 거래 시간 알려줘', 'T+2 가 뭐야', 'CMA 계좌 개설 방법'\n"
    "- smalltalk: 인사·감사·자유 대화. 도구 호출 불필요.\n"
    "  예: '안녕', '고마워', '잘자'\n"
    "- cancel: *진행중 작업 중단·일시정지*. delete (영구 삭제) 와 다름.\n"
    "  예: '알람 멈춰줘', '잠깐 안 받을래', '진행 취소'\n"
    "- unknown: 위 어디에도 명확히 안 들어감.\n"
    "\n"
    "## domain (10 종)\n"
    "- expense: 식비/지출/가계부/돈 사용 기록.\n"
    "- schedule: 일정/약속/미팅/이벤트 시간대 기록.\n"
    "- reminder: *반복·시각 알람*/리마인더/복약 알림. (일정과 구분 — 알람은 *반복*\n"
    "  되거나 *지정 시각에 알려줌*. 일정은 사람과의 약속.)\n"
    "- mail: 메일함/이메일 처리.\n"
    "- stock: 주식 (시세/보유/모니터링/분석).\n"
    "- kms: KMS 자료/문서/블록/저장소 메타.\n"
    "- contact: 연락처/인물 정보. (후속)\n"
    "- task: 할 일/todo. (후속)\n"
    "- settings: 시스템 설정·페르소나.\n"
    "- none: 위 어디에도 안 속함 (info verb 와 자주 결합 — 일반 정보).\n"
    "\n"
    "## 판단 원칙\n"
    "- verb 는 *문장의 주 동사* + *사용자가 답으로 받고 싶은 결과* 로 결정.\n"
    "  - 결과가 *데이터 변경* 이면 log/delete/update.\n"
    "  - 결과가 *현재 상태/사실 표시* 면 query 또는 info.\n"
    "  - 변경 vs 조회가 모호하면 발화 안 동사 형태 (-해줘/-등록/-기록 = 변경 / -알려줘/-얼마/-있어 = 조회).\n"
    "- delete 와 cancel 의 동의어 — 의미 일반화 (키워드 enum 아님):\n"
    "  · 사용자가 *기존 데이터를 없애려는 의도* 면 모두 delete:\n"
    "    '삭제/지워/없애/빼/제외/제거/취소/정리' 등 — 형태 다양해도 의미가 *제거*.\n"
    "  · 단, '정리해줘' 가 *나열·보여주기* 의도일 때도 있음 ('이번주 일정 정리해줘'\n"
    "    가 '보여줘' 면 query, '없애줘' 면 delete). 모호하면 query 가 안전 default.\n"
    "  · '취소' 는 schedule/expense 도메인에선 delete, reminder 에선 cancel\n"
    "    (진행중 알람 일시정지). 명확히 구분.\n"
    "- 부정형·예외 표현 주의:\n"
    "  - '병원 갈 일 *없나*?' → 일정 query 이지 delete 아님.\n"
    "  - '식비 *없애*줘' → expense delete (실제 삭제).\n"
    "- 직전 turn 컨텍스트 활용:\n"
    "  - 사용자가 '응' / '다시 계산해줘' 하면 직전 봇 약속 (예: '제외하겠습니다') 의\n"
    "    실행 요청 → 그 약속의 verb (보통 delete) 로 분류.\n"
    "  - history 에 직전 등록 내역 ('편의점 8천원 기록') 이 있고 사용자가 '방금/그거\n"
    "    삭제' 하면 그 객체의 도메인 그대로 + verb=delete.\n"
    "- domain 은 *주요 명사* + *다루는 객체 종류*. 명사가 일반 ('주식 거래 시간') 이면\n"
    "  info verb + none/stock domain. 특정 인스턴스 ('삼성전자 53주') 면 stock domain + log/update.\n"
    "- 일정 vs 알람 (사용자 보고 회귀): 발화에 *반복 단서* (매일/매주/격일) 또는\n"
    "  '알람/알림/리마인더/복약' 같은 명사 → reminder. *특정 1회성 약속* (5월 4일\n"
    "  3시 회의) → schedule.\n"
    "- ★ 주식 가격 알람 (P11-19m, 사용자 보고 회귀): 발화에 *종목명 (한글/영문)\n"
    "  + 가격 (원/달러/% 등) + 조건 동사 (떨어지면/되면/찍으면/오르면/빠지면)* 가\n"
    "  *함께* 있으면 verb=log + domain=*stock* (절대 reminder X). 비록 '알람/알림'\n"
    "  단어가 들어가도 *주식 가격 모니터링* 의도면 stock.\n"
    "  - '카카오 55000원 떨어지면 알람' → verb=log, domain=stock\n"
    "  - '삼성전자 23만원 되면 알려줘' → verb=log, domain=stock\n"
    "  - 'NVDA 1000 찍으면 톡 줘' → verb=log, domain=stock\n"
    "  - '네이버 -5% 빠지면 깨워줘' → verb=log, domain=stock\n"
    "  종목명 없는 *순수 시각 알람* (매일 8시 혈압약) 만 reminder.\n"
    "- ★ 주식 거래 의향 (D71, 2026-05-11 — 사용자 보고 G30 회귀): 종목명 +\n"
    "  거래 동사 + (금액|수량)? 패턴은 verb=log, domain=stock 으로 분류. 시스템은\n"
    "  실시간 주문 미지원이며 *관심 종목 등록* (stock.add_watch) 으로 처리한다.\n"
    "  거래 동사 예 (이에 한정 X — LLM 일반화): 매수/사자/담아/담아봐/들어가/\n"
    "  들어가자/진입/추매/물타기/매도/팔자/익절/손절/털자.\n"
    "  - '카카오 20만원치 매수해줘' → verb=log, domain=stock\n"
    "  - '삼성전자 사자' → verb=log, domain=stock\n"
    "  - '엔비디아 50만원 담아' → verb=log, domain=stock\n"
    "  - '테슬라 들어가자' → verb=log, domain=stock\n"
    "  - 'NVDA 한 주 사자' → verb=log, domain=stock\n"
    "  - '카카오 절반 팔자' → verb=log, domain=stock (매도 의향)\n"
    "  네거티브 (비금융 맥락 — verb/domain 다르게):\n"
    "  - '사자 사진 보내줘' → smalltalk/none (동물 사자)\n"
    "  - '사자성어 추천' → info/none\n"
    "  - '테슬라 단톡방 들어가자' / '카카오톡 들어가자' → smalltalk/none (채팅·메신저)\n"
    "  - '비트코인 담아' / '이더리움 사자' → info/none (코인 — stock 도메인 X)\n"
    "  - '삼성전자 사장 누구야' → info/none (인물 정보)\n"
    "  - '테슬라 모델3 사자' / '아이폰 사자' / '그래픽카드 사자' → log/none (제품 구매)\n"
    "  ★ 시제 가드 (과거 vs 의향) — 둘 다 domain=stock 이지만 어휘 차이 보존:\n"
    "  - '삼성전자 53주 샀어' = verb=log, domain=stock (과거 체결 보고 — stock_register)\n"
    "  - '삼성전자 사자' = verb=log, domain=stock (의향 — stock_watch)\n"
    "  utterance_classifier 단계에선 verb/domain 만 결정. 세부 라벨 분기는\n"
    "  intent_classifier 와 plan 단계에서 처리하므로 두 케이스 모두 log/stock.\n"
    "  종목명 (한글 회사명 / 영문 티커) 이 명확히 식별돼야 stock. 모호하면 confidence ≤0.5.\n"
    "- 모호하면 confidence 낮게 (≤0.5) 표시. unknown 도 가능.\n"
    "\n"
    "## 출력 schema 엄수\n"
    "- verb / domain 은 위 enum 값 정확히 그대로. 다른 단어 X.\n"
    "- JSON 한 객체만. 다른 텍스트 / 마크다운 / 코드블록 절대 X.\n"
)


class UtteranceClassifier:
    """verb × domain 2축 분류기."""

    def __init__(self, llm_client: Any):
        self.llm = llm_client

    async def classify(
        self,
        user_message: str,
        history: list[dict] | None = None,
    ) -> UtteranceCategory | None:
        """발화 분류. LLM 미주입 / 실패 시 None.

        P11-19j (GPT-5.5 자문) — multi-intent splitter 적용:
        1) deterministic splitter 로 발화 분절 시도
        2) 분절 1건 → 단일 LLM 분류 (기존)
        3) 분절 2+ → 각 절 별도 분류 + intents 배열 합성
        """
        if self.llm is None:
            return None
        if not user_message or not user_message.strip():
            return UtteranceCategory(
                verb="smalltalk", domain="none", confidence=0.0,
                reasoning="empty utterance",
            )

        # P11-19j — deterministic splitter 우선 시도.
        try:
            from src.agent_framework.llm.multi_intent_splitter import split_utterance

            segments = split_utterance(user_message)
        except Exception as e:  # noqa: BLE001
            log.debug("splitter_failed", error=str(e))
            segments = []

        # D22 (2026-05-08) — LLM 게이트. splitter 는 후보 제안만, LLM 결과의
        # confidence + (verb, domain) 다양성으로 multi-intent 확정. over-split 차단.
        # env override:
        # - MULTI_INTENT_MIN_CONFIDENCE (default 0.5) — 평균 confidence 이상이어야 multi 확정
        # - MULTI_INTENT_HIGH_CONFIDENCE (default 0.8) — 3+ 절 escalation 임계값
        import os as _os
        try:
            _MIN_CONF = float(_os.environ.get("MULTI_INTENT_MIN_CONFIDENCE", "0.5"))
        except (TypeError, ValueError):
            _MIN_CONF = 0.5
        try:
            _HIGH_CONF = float(_os.environ.get("MULTI_INTENT_HIGH_CONFIDENCE", "0.8"))
        except (TypeError, ValueError):
            _HIGH_CONF = 0.8

        if len(segments) >= 2:
            # 다중 절 — 각 절 별도 분류 후 LLM 게이트 적용.
            log.info(
                "multi_intent_splitter_active",
                segment_count=len(segments),
            )
            sub_results = []
            for seg in segments:
                sub = await self._classify_one(seg.text, history)
                if sub is not None and sub.intents:
                    sub_results.append(sub)
            if len(sub_results) >= 2:
                # 각 절의 primary intent 합성.
                merged_intents: list[IntentSlot] = []
                for r in sub_results:
                    if r.intents:
                        merged_intents.append(r.intents[0])
                if not merged_intents:
                    merged_intents = sub_results[0].intents
                primary = merged_intents[0]

                # D22 LLM 게이트:
                # 1) 평균 confidence < _MIN_CONF — over-split 으로 간주, single collapse
                avg_conf = (
                    sum(i.confidence for i in merged_intents) / len(merged_intents)
                    if merged_intents else 0.0
                )
                # 2) (verb, domain) 다양성 — 모두 동일이면 single collapse
                unique_keys = {(i.verb, i.domain) for i in merged_intents}

                multi_confirmed = (
                    avg_conf >= _MIN_CONF and len(unique_keys) >= 2
                )

                if multi_confirmed:
                    # 3+ 절은 high-confidence escalation 만 허용 (cap=2 default).
                    # 모든 절이 _HIGH_CONF 이상이면 그대로 사용. 아니면 confidence
                    # desc 정렬 후 top-2 만 (GPT-5 phase1 verdict — 가장 강한 의도 보존).
                    if len(merged_intents) >= 3 and not all(
                        i.confidence >= _HIGH_CONF for i in merged_intents
                    ):
                        merged_intents = sorted(
                            merged_intents,
                            key=lambda i: i.confidence,
                            reverse=True,
                        )[:2]
                        # primary 도 top-1 으로 갱신
                        primary = merged_intents[0]
                        log.info(
                            "multi_intent_cap_to_2",
                            kept=2,
                            original=len(sub_results),
                            avg_conf=round(avg_conf, 2),
                        )
                    elif len(merged_intents) >= 3:
                        log.info(
                            "multi_intent_high_confidence_escalation",
                            count=len(merged_intents),
                            avg_conf=round(avg_conf, 2),
                        )
                    log.info(
                        "multi_intent_llm_gate_pass",
                        count=len(merged_intents),
                        avg_conf=round(avg_conf, 2),
                        diversity=len(unique_keys),
                    )
                    return UtteranceCategory(
                        verb=primary.verb,
                        domain=primary.domain,
                        confidence=primary.confidence,
                        reasoning=(
                            f"splitter-merged from {len(merged_intents)} segments "
                            f"(avg_conf={avg_conf:.2f}, diversity={len(unique_keys)})"
                        ),
                        intents=merged_intents,
                        is_ambiguous=False,
                        clarification_question=None,
                    )
                # collapse 사유 로그
                log.info(
                    "splitter_collapsed_to_single",
                    avg_conf=round(avg_conf, 2),
                    diversity=len(unique_keys),
                    reason=(
                        "low_confidence" if avg_conf < _MIN_CONF
                        else "single_verb_domain"
                    ),
                )

        # 단일 분류 (기존 동작) — splitter 결과 무관하게 *원문 그대로* LLM 에 보냄.
        # 진짜 multi-intent 는 LLM 의 intents 배열로 올라옴 (single-classify 가 multi 잡음).
        return await self._classify_one(user_message, history)

    async def _classify_one(
        self,
        user_message: str,
        history: list[dict] | None = None,
    ) -> UtteranceCategory | None:
        """단일 발화 분류 — 내부 helper. 이전 classify() 본문."""
        if not user_message or not user_message.strip():
            return UtteranceCategory(
                verb="smalltalk", domain="none", confidence=0.0,
                reasoning="empty utterance",
            )

        user_payload = {
            "user_message": user_message.strip(),
            "history": (history or [])[-6:],
        }
        user = json.dumps(user_payload, ensure_ascii=False)
        # P11-19f — system prompt 에 현재 시각 prepend. 발화 안 시간 표현 의미
        # 분기 (예: '오늘 점심' = log_expense + spent_at=오늘) 에 기준점 필요.
        from src.agent_framework.runtime.time_context import prepend_time

        try:
            raw = await self.llm.complete(
                prepend_time(_SYSTEM_PROMPT), user, response_format="json_object"
            )
        except Exception as e:  # noqa: BLE001
            log.warning("utterance_classifier_call_failed", error=str(e))
            return None

        try:
            stripped = (raw or "").strip()
            if stripped.startswith("```"):
                nl = stripped.find("\n")
                if nl > 0:
                    stripped = stripped[nl + 1:]
            if stripped.endswith("```"):
                stripped = stripped[:-3].rstrip()
            data = json.loads(stripped)

            # 다중·애매 인텐트 지원 + legacy 단일 형식 호환.
            intents_raw = data.get("intents")
            if not isinstance(intents_raw, list):
                # legacy 단일 형식 — 자동 변환.
                intents_raw = [{
                    "verb": data.get("verb"),
                    "domain": data.get("domain"),
                    "confidence": data.get("confidence", 0.0),
                    "reasoning": data.get("reasoning", ""),
                }]

            intents: list[IntentSlot] = []
            for it in intents_raw:
                if not isinstance(it, dict):
                    continue
                v = str(it.get("verb", "")).strip().lower()
                d = str(it.get("domain", "")).strip().lower()
                if v not in VERBS:
                    v = "unknown"
                if d not in DOMAINS:
                    d = "none"
                try:
                    cf = max(0.0, min(1.0, float(it.get("confidence", 0.0))))
                except (TypeError, ValueError):
                    cf = 0.0
                rsn = str(it.get("reasoning", ""))[:200]
                intents.append(IntentSlot(
                    verb=v, domain=d, confidence=cf, reasoning=rsn,
                ))
            if not intents:
                intents = [IntentSlot(
                    verb="unknown", domain="none", confidence=0.0, reasoning="",
                )]

            is_ambiguous = bool(data.get("is_ambiguous", False))
            # 보수적 안전망 — 모든 confidence ≤ 0.5 면 ambiguous.
            if not is_ambiguous and all(s.confidence <= 0.5 for s in intents):
                is_ambiguous = True
            clarification_question = data.get("clarification_question")
            if clarification_question is not None:
                clarification_question = str(clarification_question).strip() or None

            primary = intents[0]
            return UtteranceCategory(
                verb=primary.verb,
                domain=primary.domain,
                confidence=primary.confidence,
                reasoning=primary.reasoning,
                intents=intents,
                is_ambiguous=is_ambiguous,
                clarification_question=clarification_question,
            )
        except Exception as e:  # noqa: BLE001
            log.warning(
                "utterance_classifier_parse_failed",
                error=str(e),
                raw_preview=(raw[:200] if raw else "(no raw)"),
            )
            return None
