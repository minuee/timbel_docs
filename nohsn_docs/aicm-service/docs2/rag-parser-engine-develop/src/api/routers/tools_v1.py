"""Tool 카탈로그 endpoint — admin 의 agent 빌더 UI 가 사용.

가용 tool 리스트 + 카테고리 분류 + 짧은 설명 + 구현 여부.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


class ToolInfo(BaseModel):
    name: str            # e.g. "schedule.create"
    description: str     # 한 줄 설명
    category: str        # 검색/일정/메일/...
    is_implemented: bool # False = stub, True = 실제 동작
    # intent visibility (Phase 1.5A)
    triggered_by_intents: list[str] = []   # 이 도구가 호출되는 intent 라벨들
    example_utterances: list[str] = []     # 사용자 발화 예시 (한국어)


_CATALOG: list[ToolInfo] = [
    # 검색 / 자료
    ToolInfo(
        name="kms_rag.search",
        description="내부 KMS 문서 검색 (BGE-M3 reranker)",
        category="검색 / 자료",
        is_implemented=True,
        triggered_by_intents=["info_lookup", "_capability_query"],
        example_utterances=[
            "회사 휴가 규정 알려줘",
            "주식 매도 대금 입금일",
            "산재보험 처리 절차가 어떻게 돼?",
        ],
    ),
    ToolInfo(
        name="web.search",
        description="웹 검색 (Naver/Brave)",
        category="검색 / 자료",
        is_implemented=True,
        triggered_by_intents=["info_lookup", "external_search"],
        example_utterances=[
            "검색해줘",
            "{주제} 정보 찾아",
            "최신 뉴스 검색",
        ],
    ),
    ToolInfo(
        name="web.fetch",
        description="URL 본문 fetch + parse",
        category="검색 / 자료",
        is_implemented=True,
        triggered_by_intents=["external_search", "info_lookup"],
        example_utterances=[
            "이 링크 내용 요약해줘",
            "해당 페이지 긁어와",
        ],
    ),

    # 일정
    ToolInfo(
        name="schedule.create",
        description="일정 등록",
        category="일정",
        is_implemented=True,
        triggered_by_intents=["schedule_create", "schedule_personal", "schedule_appointment"],
        example_utterances=[
            "내일 2시 약속 등록해줘",
            "다음주 화요일 진료 예약 잡아줘",
            "오늘 오후 일정 추가해줘",
        ],
    ),
    ToolInfo(
        name="schedule.list",
        description="일정 조회 (날짜 범위)",
        category="일정",
        is_implemented=True,
        triggered_by_intents=["schedule_query", "schedule_personal"],
        example_utterances=[
            "내일 일정 어떻게 되나?",
            "오늘 약속 알려줘",
            "이번주 일정 확인",
        ],
    ),
    ToolInfo(
        name="schedule.delete",
        description="단건 일정 삭제",
        category="일정",
        is_implemented=True,
        triggered_by_intents=["schedule_delete", "schedule_cancel"],
        example_utterances=[
            "내일 2시 약속 취소해줘",
            "그 일정 지워",
        ],
    ),
    ToolInfo(
        name="schedule.delete_duplicates",
        description="중복 일정 일괄 정리",
        category="일정",
        is_implemented=True,
        triggered_by_intents=["schedule_cleanup", "schedule_delete"],
        example_utterances=[
            "중복 일정 정리해줘",
            "겹치는 약속 삭제해",
        ],
    ),

    # 메일
    ToolInfo(
        name="mail.search",
        description="메일 검색 (수신함)",
        category="메일",
        is_implemented=True,
        triggered_by_intents=["mail_search", "mail_query"],
        example_utterances=[
            "어제 받은 메일 검색",
            "{사람} 한테서 온 메일",
            "지난주 메일 찾아줘",
        ],
    ),
    ToolInfo(
        name="mail.send",
        description="SMTP 메일 발송",
        category="메일",
        is_implemented=True,
        triggered_by_intents=["mail_compose", "mail_send"],
        example_utterances=[
            "{사람} 한테 메일 보내줘",
            "이메일 작성해서 보내",
        ],
    ),
    ToolInfo(
        name="mail.compose",
        description="메일 초안 작성 (LLM 보조)",
        category="메일",
        is_implemented=True,
        triggered_by_intents=["mail_compose", "mail_draft"],
        example_utterances=[
            "메일 초안 작성해줘",
            "{주제}로 이메일 써줘",
        ],
    ),

    # 메모 / 일기
    ToolInfo(
        name="memo.save",
        description="메모 저장 + 지식 등록",
        category="메모 / 일기",
        is_implemented=True,
        triggered_by_intents=["memo_capture"],
        example_utterances=[
            "메모해줘 — {내용}",
            "{내용} 적어둬",
            "노트에 적어",
        ],
    ),
    ToolInfo(
        name="diary.save",
        description="일기 저장",
        category="메모 / 일기",
        is_implemented=True,
        triggered_by_intents=["diary_write", "memo_capture"],
        example_utterances=[
            "오늘 일기 써줘",
            "일기 저장해",
        ],
    ),

    # 알림
    ToolInfo(
        name="sms.send",
        description="SMS 발송 (외부 게이트웨이)",
        category="알림",
        is_implemented=False,
        triggered_by_intents=["sms_send", "notification_send"],
        example_utterances=[
            "{사람} 한테 문자 보내줘",
            "SMS로 알려줘",
        ],
    ),

    # 가계부
    ToolInfo(
        name="expense.add",
        description="가계부 등록",
        category="가계부",
        is_implemented=True,
        triggered_by_intents=["expense_log"],
        example_utterances=[
            "{금액}원 가계부 등록",
            "{식당}에서 {금액} 썼어",
        ],
    ),
    ToolInfo(
        name="expense.list",
        description="가계부 조회",
        category="가계부",
        is_implemented=True,
        triggered_by_intents=["expense_query"],
        example_utterances=[
            "이번달 지출 알려줘",
            "식비 얼마나 썼어?",
        ],
    ),

    # 문서 생성
    ToolInfo(
        name="doc.draft",
        description="문서 자동 초안 (gemma-4)",
        category="문서 생성",
        is_implemented=True,
        triggered_by_intents=["doc_draft", "doc_create"],
        example_utterances=[
            "{주제} 문서 초안 만들어줘",
            "보고서 작성해",
        ],
    ),
    ToolInfo(
        name="doc.summarize",
        description="문서 요약",
        category="문서 생성",
        is_implemented=True,
        triggered_by_intents=["doc_summarize", "info_lookup"],
        example_utterances=[
            "이 문서 요약해줘",
            "내용 정리해",
        ],
    ),

    # 외부 정보
    ToolInfo(
        name="weather.lookup",
        description="날씨 조회 (Open-Meteo)",
        category="외부 정보",
        is_implemented=True,
        triggered_by_intents=["weather_query"],
        example_utterances=[
            "내일 서울 날씨",
            "오늘 비 와?",
        ],
    ),
    ToolInfo(
        name="news.search",
        description="뉴스 검색 (RSS)",
        category="외부 정보",
        is_implemented=True,
        triggered_by_intents=["news_query"],
        example_utterances=[
            "오늘 뉴스 알려줘",
            "최신 IT 뉴스 찾아줘",
        ],
    ),
    ToolInfo(
        name="stock.predict",
        description="주식 가격 예측 (미구현)",
        category="외부 정보",
        is_implemented=False,
        triggered_by_intents=["stock_query", "stock_analysis"],
        example_utterances=[
            "삼성전자 주가 예측",
            "이 종목 분석해줘",
        ],
    ),

    # 예약 (Phase 1.5C P0)
    ToolInfo(
        name="reservation.create",
        description="예약 생성 (식당/미용실/병원/숙박/펫)",
        category="예약",
        is_implemented=True,
        triggered_by_intents=["reservation_create", "reservation_book"],
        example_utterances=[
            "내일 7시 2명 예약",
            "토요일 점심 4명 자리 잡아줘",
            "다음주 화요일 미용 예약 잡아줘",
        ],
    ),
    ToolInfo(
        name="reservation.cancel",
        description="예약 취소 (id 기반, broad mutation 차단)",
        category="예약",
        is_implemented=True,
        triggered_by_intents=["reservation_cancel"],
        example_utterances=[
            "예약 취소할게요",
            "그 예약 지워줘",
            "갑자기 못 가게 됐어요",
        ],
    ),
    ToolInfo(
        name="reservation.check_availability",
        description="예약 슬롯 가용성 yes/no (raw 정보 비노출)",
        category="예약",
        is_implemented=True,
        triggered_by_intents=["reservation_check_availability"],
        example_utterances=[
            "당일 예약 되나요?",
            "내일 6시에 자리 있어요?",
            "이번주 토요일 가능한가요?",
        ],
    ),
    ToolInfo(
        name="reservation.reschedule",
        description="예약 일정 변경 (id + 새 시각)",
        category="예약",
        is_implemented=True,
        triggered_by_intents=["reservation_reschedule"],
        example_utterances=[
            "예약 시간 바꿀 수 있을까요?",
            "다른 날로 옮겨줘",
            "한 시간만 미뤄도 돼요?",
        ],
    ),

    # 결제 (Phase 1.5C P0)
    ToolInfo(
        name="payment.refund",
        description="결제 환불 요청 (추상 layer — 실 PG 후속 PR)",
        category="결제",
        is_implemented=True,
        triggered_by_intents=["payment_refund"],
        example_utterances=[
            "환불 해주세요",
            "주문 취소하고 환불 요청",
            "결제 금액 돌려주세요",
        ],
    ),

    # 재고 (Phase 1.5C P0)
    ToolInfo(
        name="inventory.check",
        description="재고 조회 (read-only)",
        category="재고",
        is_implemented=True,
        triggered_by_intents=["inventory_check"],
        example_utterances=[
            "이 상품 재고 있어요?",
            "원하는 색상 있나요?",
            "품절이에요? 언제 들어와요?",
        ],
    ),

    # 배송 (Phase 1.5C P0)
    ToolInfo(
        name="delivery.track",
        description="배송 조회 (추상 layer — 실 carrier 후속 PR)",
        category="배송",
        is_implemented=True,
        triggered_by_intents=["delivery_track"],
        example_utterances=[
            "택배 어디까지 왔어요?",
            "배송 조회해줘",
            "송장번호로 확인해줘",
        ],
    ),
]


@router.get("/catalog", response_model=list[ToolInfo])
async def list_tool_catalog() -> list[ToolInfo]:
    """가용 tool 리스트. agent 빌더 UI 가 호출."""
    return _CATALOG
