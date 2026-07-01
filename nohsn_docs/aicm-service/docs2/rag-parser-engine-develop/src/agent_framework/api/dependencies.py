"""FastAPI DI — AgentEngine 싱글턴 빌더.

import-time 에 vLLM/Redis 에 연결하지 않는다. 싱글턴은 `_build_engine()` 첫
호출 시점에 만들어지며, 테스트에서는 `app.dependency_overrides` 로 이 함수를
바꿔치기해 실제 외부 의존성 없이 chat 엔드포인트를 검증한다.

env flag `AGENT_SKILLS_SOURCE` (Stage A):
- "fs"  (기본) — 파일시스템 YAML 로드 (하위호환)
- "kms" — KMS documents 테이블에서 로드 (seed_agent_skills 로 적재된 것)
"""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from fastapi import Depends, HTTPException

from src.agent_framework.agent.tool_calling_loop import ToolCallingLoop
from src.agent_framework.classifier.draft_composer import DraftComposer
from src.agent_framework.conversation.ack_generator import AckGenerator
from src.agent_framework.core.skill_registry import SkillRegistry
from src.agent_framework.llm.fallback_router import FallbackRouter
from src.agent_framework.llm.intent_classifier import MultiLabelIntentClassifier
from src.agent_framework.llm.response_generator import ResponseGenerator
from src.agent_framework.llm.slot_filler import SlotFiller
from src.agent_framework.llm.vllm_adapter import VLLMAdapter
from src.agent_framework.runtime.engine import SKILLS_DIR, AgentEngine
from src.agent_framework.runtime.loader import load_all_skills
from src.agent_framework.runtime.session_store import SessionStore
from src.agent_framework.tools.availability import (
    schedule_availability,
    schedule_suggest_slots,
)
from src.agent_framework.tools import (
    calendar_mock,
    delivery_store,
    diary_store,
    expense_store,
    inbox_query,
    inventory_store,
    kms_save_research,
    lifestyle_stubs,
    mail_compose,
    mail_search,
    mail_send,
    memo_store,
    news_search,
    news_store,
    payment_store,
    reminder_store,
    reservation_store,
    schedule_store,
    stock_analyze,
    stock_data,
    stock_watch,
    weather_mock,
    weather_real,
    web_fetch,
    web_search,
)
from src.agent_framework.tools import kms_inventory, kms_meta
from src.agent_framework.tools.kms_rag import KMSRagTool
from src.agent_framework.tools.kms_sop import KMSSopTool
from src.agent_framework.tools.registry import ToolRegistry
from src.agent_framework.tools.scope_resolver import (
    TOOL_DEFAULT_SCOPES as _TOOL_DEFAULT_SCOPES,
)
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


# Stage B-Core-3: SkillRegistry 용 공유 async DB engine. import 시점이 아닌
# _build_engine() 첫 호출에 한 번만 생성되어 모듈 라이프타임 동안 재사용.
# 매 턴 새 커넥션 풀을 만들지 않도록.
_DB_ENGINE_SINGLETON: AsyncEngine | None = None


def _get_or_create_db_engine() -> AsyncEngine:
    """SkillRegistry 가 쓰는 AsyncEngine 싱글턴. lazy init."""
    global _DB_ENGINE_SINGLETON
    if _DB_ENGINE_SINGLETON is None:
        _DB_ENGINE_SINGLETON = create_async_engine(settings.DATABASE_URL)
    return _DB_ENGINE_SINGLETON


# Phase 3: kms_inventory.get_summary tool — ToolRegistry 어댑터.
# tool 본체(`kms_inventory.get_summary`) 는 sync SQLAlchemy Connection 을 받지만
# registry 호출 규약은 ``async (args:dict) → dict`` 이므로 wrapper 가 sync engine
# 을 만들어 to_thread 로 실행한다.
async def _kms_inventory_adapter(args: dict) -> dict:
    from sqlalchemy import create_engine

    sync_url = (
        settings.DATABASE_URL
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg", "postgresql")
    )

    def _run() -> dict:
        eng = create_engine(sync_url)
        conn = eng.connect()
        try:
            return kms_inventory.get_summary(
                db_conn=conn,
                tenant_id=args.get("tenant_id"),
                repository_id=args.get("repository_id"),
                personal_tenant_id=args.get("personal_tenant_id"),
            )
        finally:
            conn.close()
            eng.dispose()

    return await asyncio.to_thread(_run)


# 2026-05-06: kms_inventory.list_documents — 실제 row 목록 (summary 와 별도).
async def _kms_inventory_list_adapter(args: dict) -> dict:
    from sqlalchemy import create_engine

    sync_url = (
        settings.DATABASE_URL
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg", "postgresql")
    )

    def _run() -> dict:
        eng = create_engine(sync_url)
        conn = eng.connect()
        try:
            return kms_inventory.list_documents(
                db_conn=conn,
                tenant_id=args.get("tenant_id"),
                personal_tenant_id=args.get("personal_tenant_id"),
                repository_id=args.get("repository_id"),
                status=args.get("status"),
                limit=int(args.get("limit") or 20),
            )
        finally:
            conn.close()
            eng.dispose()

    return await asyncio.to_thread(_run)


# F7 (KMS-Plus): kms_meta.get_my_inventory tool — self-introspective 인벤토리.
# read_only · tenant 스코프. kms_inventory_adapter 와 동일 sync→async 래퍼 패턴.
async def _kms_meta_adapter(args: dict) -> dict:
    from sqlalchemy import create_engine

    sync_url = (
        settings.DATABASE_URL
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg", "postgresql")
    )

    def _run() -> dict:
        eng = create_engine(sync_url)
        conn = eng.connect()
        try:
            return kms_meta.get_my_inventory(
                db_conn=conn,
                tenant_id=args.get("tenant_id"),
                personal_tenant_id=args.get("personal_tenant_id"),
            )
        finally:
            conn.close()
            eng.dispose()

    return await asyncio.to_thread(_run)


def _load_skills_from_configured_source():
    """env flag 에 따라 fs 또는 kms 에서 스킬 로드.

    Returns dict[str, Skill] — fs loader 와 동일 시그니처.
    """
    source = os.environ.get("AGENT_SKILLS_SOURCE", "fs").lower()
    if source == "kms":
        from sqlalchemy.ext.asyncio import create_async_engine

        from src.agent_framework.runtime.kms_skill_loader import (
            load_all_skills_from_kms,
        )

        async def _load():
            eng = create_async_engine(settings.DATABASE_URL)
            try:
                return await load_all_skills_from_kms(eng)
            finally:
                await eng.dispose()

        try:
            # _build_engine 은 sync — 새 event loop 로 실행
            return asyncio.run(_load())
        except RuntimeError:
            # 이미 running loop (FastAPI lifespan 등) 에서 호출된 경우 fallback.
            # create_async_engine 이 가벼워 재시도 가능.
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_load())
            finally:
                loop.close()
    # fs (기본)
    return load_all_skills(SKILLS_DIR)


def _build_guard_and_inv_store() -> tuple[object, object]:
    """Phase 8 (KMS-Plus) — ExecutionPolicyGuard + ToolInvocationStore.

    AgentEngine 은 async 환경이지만 tool_invocation_store 는 sync SQLAlchemy
    Connection 을 사용. settings.DATABASE_URL 을 sync 변환해 별도 engine 을
    만들고, store 는 그 engine 의 connection 을 공유한다.

    DB 연결이 실패해도 (테스트 환경 등) 전체 빌드를 막지 않도록 try/except
    로 감싸 None 반환 — engine 은 guard 없이 동작 (tool_loop 가 직접 실행).
    """
    try:
        from sqlalchemy import create_engine

        from src.agent_framework.runtime.execution_policy_guard import (
            ExecutionPolicyGuard,
        )
        from src.agent_framework.storage.tool_invocation_store import (
            ToolInvocationStore,
        )

        sync_url = (
            settings.DATABASE_URL.replace("+asyncpg", "").replace(
                "postgresql+asyncpg", "postgresql"
            )
        )
        sync_eng = create_engine(sync_url, pool_pre_ping=True, pool_size=2)
        # store 는 connection 객체를 자체 보유. engine 은 모듈 라이프타임 유지.
        sync_conn = sync_eng.connect()
        inv_store = ToolInvocationStore(sync_conn)
        guard = ExecutionPolicyGuard(inv_store=inv_store)
        log.info("agent_engine_guard_wired", store=type(inv_store).__name__)
        return guard, inv_store
    except Exception as exc:
        log.warning("agent_engine_guard_wire_failed", error=str(exc))
        return None, None


# D26 (2026-05-08) — 등록 도구 → default scope 매핑을 *resolver SoT* 에서 재사용.
# 본 함수는 catalog/UI 메타용 dict 만 산출 — runtime enforcement 는 engine 이
# 직접 scope_resolver.resolve_tool_scope() 호출.
def _default_scopes_for_registered_tools() -> dict[str, str]:
    """현재 등록 도구의 default_scope manifest dict.

    resolver._TOOL_DEFAULT_SCOPES 가 *유일한* SoT. 본 함수는 resolver 의 sub-set
    을 등록 도구 이름 기준으로 추출.

    fallback 정책 — *없음* (강제 정합). resolver 에 미등록인 도구가
    `_REGISTERED_TOOL_NAMES` 에 들어가면 KeyError. drift 검출 unit test
    (`test_registered_tools_are_subset_of_resolver_defaults`) 가 사전 차단.
    """
    return {name: _TOOL_DEFAULT_SCOPES[name] for name in _REGISTERED_TOOL_NAMES}


# 등록 도구 이름 — ToolRegistry 의 `tools` dict 의 key 와 *반드시 일치*. drift
# 시 unit test fail. 새 도구 추가 시 본 set 와 ToolRegistry tools dict 를 함께
# 갱신하고 resolver 에도 default scope 명시할 것.
_REGISTERED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "calendar.check_availability",
        "calendar.book",
        "calendar.list_doctors",
        "calendar.list_available_slots",
        "schedule.create",
        "schedule.list",
        "schedule.delete",
        "schedule.delete_duplicates",
        "schedule.delete_all",
        "schedule.update",
        "schedule.availability",
        "schedule.suggest_slots",
        "reservation.create",
        "reservation.cancel",
        "reservation.check_availability",
        "reservation.reschedule",
        "payment.refund",
        "inventory.check",
        "delivery.track",
        "memo.create",
        "memo.list",
        "memo.update",
        "memo.delete",
        "memo.complete",
        "mail.send",
        "mail.search",
        "mail.compose",
        "diary.save",
        "diary.search",
        "expense.create",
        "expense.list",
        "expense.sum_by_category",
        "expense.delete",
        "expense.update",
        "inbox.summary",
        "reminder.schedule",
        "reminder.list",
        "reminder.cancel",
        "news.add_subscription",
        "news.remove_subscription",
        "news.list_subscriptions",
        "news.fetch_and_summarize",
        "news.list_recent_reports",
        "kms_rag.search",
        "kms_sop.search",
        "kms_inventory.get_summary",
        "kms_inventory.list_documents",
        "kms_meta.get_my_inventory",
        "weather.lookup",
        "news.search",
        "web.search",
        "web.fetch",
        "kms.save_research",
        "stock.quote",
        "stock.predict",
        "stock.market_movers",
        "stock.analyze",
        "stock.add_watch",
        "stock.list_watch",
        "stock.update_watch",
        "stock.delete_watch",
        "restaurant.search",
        "movie.lookup",
        "movie.boxoffice",
        "fx.rate",
        "transit.status",
        "flight.price",
        "concert.schedule",
        "menu.recommend",
        "streaming.lookup",
        "air.quality",
    }
)


@lru_cache(maxsize=1)
def _build_engine() -> AgentEngine:
    """한 번만 빌드. lru_cache 로 lazy 싱글턴.

    Redis 커넥션풀, vLLM adapter 는 여기서 초기화된다. FastAPI lifespan 이
    아닌 첫 호출 시점에 bind 되므로, 테스트에서는 이 함수를 호출하지 않도록
    dependency override 를 걸어야 한다.
    """
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    # TTL 은 env AGENT_SESSION_TTL_S 로 override 가능 (기본 30분)
    ttl_s = int(os.environ.get("AGENT_SESSION_TTL_S", "1800"))
    session_store = SessionStore(redis_client, ttl_s=ttl_s)

    tools = ToolRegistry(
        {
            "calendar.check_availability": calendar_mock.check_availability,
            "calendar.book": calendar_mock.book,
            "calendar.list_doctors": calendar_mock.list_doctors,
            "calendar.list_available_slots": calendar_mock.list_available_slots,
            "schedule.create": schedule_store.create,
            "schedule.list": schedule_store.list_all,
            "schedule.delete": schedule_store.delete,
            "schedule.delete_duplicates": schedule_store.delete_duplicates,
            "schedule.delete_all": schedule_store.delete_all,
            "schedule.update": schedule_store.update,
            "schedule.availability": schedule_availability,
            "schedule.suggest_slots": schedule_suggest_slots,
            # Phase 1.5C P0 — reservation (예약) 4 verbs.
            "reservation.create": reservation_store.create,
            "reservation.cancel": reservation_store.cancel,
            "reservation.check_availability": reservation_store.check_availability,
            "reservation.reschedule": reservation_store.reschedule,
            # Phase 1.5C P0 — payment.refund (추상 layer, 실 PG 후속 PR).
            "payment.refund": payment_store.refund,
            # Phase 1.5C P0 — inventory.check (read-only documents 조회).
            "inventory.check": inventory_store.check,
            # Phase 1.5C P0 — delivery.track (추상 layer, 실 carrier 후속 PR).
            "delivery.track": delivery_store.track,
            "memo.create": memo_store.create,
            "memo.list": memo_store.list_all,
            "memo.update": memo_store.update,
            "memo.delete": memo_store.delete,
            "memo.complete": memo_store.complete,
            "mail.send": mail_send.send,
            "mail.search": mail_search.search,
            "mail.compose": mail_compose.compose,
            "diary.save": diary_store.save,
            "diary.search": diary_store.search,
            "expense.create": expense_store.create,
            "expense.list": expense_store.list_all,
            "expense.sum_by_category": expense_store.sum_by_category,
            "expense.delete": expense_store.delete,
            "expense.update": expense_store.update,
            "inbox.summary": inbox_query.summary,
            "reminder.schedule": reminder_store.schedule,
            "reminder.list": reminder_store.list_for_user,
            "reminder.cancel": reminder_store.cancel,
            "news.add_subscription": news_store.add_subscription,
            "news.remove_subscription": news_store.remove_subscription,
            "news.list_subscriptions": news_store.list_subscriptions,
            "news.fetch_and_summarize": news_store.fetch_and_summarize,
            "news.list_recent_reports": news_store.list_recent_reports,
            "kms_rag.search": KMSRagTool(),
            # Phase 1.5B-β — SOP RAG. plan_orchestrator 통합은 Round 2 (FEATURE_SOP_RAG 게이트).
            # registry 는 등록 — Round 2 에서 호출 시 즉시 동작 (alembic 056 + sop_indexer 인덱스 전제).
            "kms_sop.search": KMSSopTool(),
            "kms_inventory.get_summary": _kms_inventory_adapter,
            "kms_inventory.list_documents": _kms_inventory_list_adapter,
            "kms_meta.get_my_inventory": _kms_meta_adapter,
            "weather.lookup": weather_real.lookup,
            "news.search": news_search.search,
            "web.search": web_search.search,
            "web.fetch": web_fetch.fetch,
            "kms.save_research": kms_save_research.save,
            "stock.quote": stock_data.quote,
            "stock.predict": lifestyle_stubs.stock_predict,
            "stock.market_movers": stock_data.market_movers,
            "stock.add_watch": stock_watch.add_watch,
            "stock.list_watch": stock_watch.list_watch,
            "stock.update_watch": stock_watch.update_watch,
            "stock.delete_watch": stock_watch.delete_watch,
            "stock.analyze": stock_analyze.analyze,
            "restaurant.search": lifestyle_stubs.restaurant_search,
            "movie.lookup": lifestyle_stubs.movie_lookup,
            "movie.boxoffice": lifestyle_stubs.movie_boxoffice,
            "fx.rate": lifestyle_stubs.fx_rate,
            "transit.status": lifestyle_stubs.transit_status,
            "flight.price": lifestyle_stubs.flight_price,
            "concert.schedule": lifestyle_stubs.concert_schedule,
            "menu.recommend": lifestyle_stubs.menu_recommend,
            "streaming.lookup": lifestyle_stubs.streaming_lookup,
            "air.quality": lifestyle_stubs.air_quality,
        },
        # PR-W — tool descriptions catalog. plan_orchestrator 가 LLM 에 노출해
        # 비슷한 이름끼리의 picked 정확도 향상 (예: news.search vs news.fetch_and_
        # summarize). 한국어 한 줄 — 도메인 + 입력 + 반환 요약.
        descriptions={
            "calendar.check_availability": "특정 시각의 진료/예약 가능 여부 조회 (clinic 데모용 mock)",
            "calendar.book": "진료/예약 시간 잡기 (clinic 데모용 mock)",
            "calendar.list_doctors": "진료의 목록 (clinic 데모용 mock)",
            "calendar.list_available_slots": "예약 가능한 슬롯 목록 (clinic 데모용 mock)",
            "schedule.create": "사용자 개인 일정 등록 (제목, 시각, 위치, 참석자)",
            "schedule.list": "사용자 등록된 일정 전체 / 기간별 조회",
            "schedule.delete": "사용자 일정 삭제 (id 단건)",
            "schedule.delete_duplicates": "중복 일정 (title+날짜+장소+참석자 동일) 일괄 정리. id 슬롯 불필요.",
            "schedule.delete_all": "모든 일정 일괄 삭제 (보수적 — '전부 다 지워' 명시 시).",
            "schedule.update": "기존 일정 수정 (id + 변경 필드)",
            "schedule.availability": "특정 시간대 가용성 yes/no 확인. args: start/end(datetime), target_user_id(uuid?). raw 일정 정보 비노출.",
            "schedule.suggest_slots": "비어있는 슬롯 무작위 N개 추천. args: start/end(datetime), duration_minutes(int?), target_user_id(uuid?), n_suggestions(int=2). guest 호출 가능.",
            "reservation.create": "★ 예약 생성 (식당/미용실/병원/숙박/펫). args: title(필수), start_at(ISO,필수), end_at(ISO,필수), attendee_count?, location?, contact?, notes?. tenant_id 자동 주입.",
            "reservation.cancel": "예약 취소. args: id(필수, document UUID), reason?. id-only enforcement — broad mutation 차단. 취소 정책 안내는 SOP RAG.",
            "reservation.check_availability": "예약 슬롯 가용성 yes/no. args: start_at(ISO,필수), end_at(ISO,필수). reservation 도메인 한정 (schedule 와 분리).",
            "reservation.reschedule": "예약 일정 변경. args: id(필수), new_start_at(ISO,필수), new_end_at(ISO,필수). 기존 row 의 start/end 만 갱신.",
            "payment.refund": "★ 결제 환불 요청 (추상 layer — 실 PG 호출 X, 후속 PR 에서 webhook 연동). args: order_id(필수), amount(원, int, 필수), reason?. status='pending' 으로 기록.",
            "inventory.check": "★ 재고 조회 (read-only). args: item_name? / sku? / item_id? 중 하나 필수. 반환: {item, current_qty, status: in_stock|low|out_of_stock, last_updated}.",
            "delivery.track": "★ 배송 조회 (추상 layer — 실 carrier API 호출 X, 후속 PR 에서 smart-택배 webhook 연동). args: tracking_number(필수), carrier?. 반환: {status, last_updated, eta?}.",
            "mail.send": "사용자 SMTP 계정으로 메일 발송. to / subject / body_text 필수. cc/bcc/in_reply_to/mail_account_label 옵션.",
            "mail.search": "메일 검색. query (제목 키워드) / sender (발신자 이름·주소) / has_attachment / since-until / mail_account_label 옵션 조합.",
            "mail.compose": "★ 메일 초안 LLM 생성 (발송 X). args: recipient(받는사람), subject_hint(제목힌트?), body_hint(본문핵심), tone(정중/친근/비즈니스/간결?), language(ko/en?). 반환: {draft:{to, subject, body_text}}. 사용자 발화 '메일 초안 작성해줘' / '{사람}한테 {주제}로 메일 써줘' 류에 사용. 실제 발송은 별도 mail.send step.",
            "memo.create": "메모/할 일 캡처. 사용자 발화 '아 맞다 내일 보고서 제출 2시 마감' 류. title + deadline_at + alarm_at 옵션.",
            "memo.list": "등록된 메모/할 일 조회. status='active'/'done' 필터 가능.",
            "memo.update": "메모 수정 (id + title/note/deadline_at/alarm_at/status)",
            "memo.delete": "메모 삭제 (id 단건)",
            "memo.complete": "메모를 완료 처리 (status='done')",
            "diary.save": "사용자 일기 한 건 저장 (날짜, 본문, 기분 태그)",
            "diary.search": "기록된 일기 검색 / 조회 (날짜·키워드)",
            "expense.create": "★ 가계부 지출 한 건 *실제 저장*. args: amount(원,int), category(식비/교통/주거/여가/의료/교육/기타), description, spent_at(ISO/자연어), payment_method(옵션). idempotency 보장.",
            "expense.list": "가계부 지출 목록 조회 (period_start/period_end 옵션 ISO 날짜).",
            "expense.sum_by_category": "★ 기간별 카테고리별 합계 + 총액. analyzer 의 핵심 도구. args: period_start/period_end (ISO). 반환: total, by_category dict, count.",
            "expense.delete": "지출 삭제 (id 단건). id (UUID) 필수 — broad mutation 방지. id 가 없으면 먼저 expense.list / expense.sum_by_category 로 id 확보 후 호출.",
            "expense.update": "★ 지출 수정. 매칭 조건 (id 또는 description/spent_at/amount) 으로 기존 row 찾아 변경 필드 (new_amount/new_category/new_description/new_spent_at) 로 patch. delete+create 2-step 대신 단일 호출로 '수정' 톤 응답. updated_count 반환.",
            "inbox.summary": "★ 사용자 메일함 처리 결과를 카테고리별 그룹으로 집계. args: since(ISO 또는 'today'/'yesterday'/'이번주'), until(ISO 또는 'now'), limit_per_category(default 5). 응답은 카테고리별 head 5건 + has_more 플래그. '오늘 메일 정리해줘' / '이번주 미팅 요청 뭐 왔어' 류 발화에 사용. 결과의 _structured_card 필드는 chat 의 SSE event=structured_block 으로 frontend 에 흘러 rich card UI 로 렌더됨.",
            "reminder.schedule": "특정 시각·반복 알림 등록 (recurrence_kind: daily|weekly|every_n_days, time HH:MM, weekday, every_n)",
            "reminder.list": "내 등록된 알람 리스트 조회 — '내 알람 보여줘', '등록한 알람 뭐있어?'",
            "reminder.cancel": "알람 일시정지/취소 — id 또는 title 매칭. action: pause|cancel",
            "news.add_subscription": "스케줄형 뉴스 브리핑 구독 추가 (매일 아침 자동 발송)",
            "news.remove_subscription": "스케줄형 뉴스 브리핑 구독 해지",
            "news.list_subscriptions": "현재 구독중인 스케줄형 뉴스 브리핑 목록",
            "news.fetch_and_summarize": "구독한 스케줄형 뉴스를 *주기 실행 시* 가져와 요약 (스케줄러 전용, 사용자 즉시 조회 X)",
            "news.list_recent_reports": "과거 발송된 스케줄형 뉴스 리포트 이력",
            "kms_rag.search": "★ 사내 KMS 문서 임베딩 검색 (BGE-M3 + reranker) — 업로드 자료 기반 질의응답. args: query(필수), top_k, *시간 필터* created_after/created_before(ISO 8601 str), *유형 필터* document_type(presentation/manual/memo/research_note/email/report/other 중 하나 또는 list), *포맷* source_type(pdf/docx/pptx 등). '작년 STT 발표 자료' 같이 발화에 시간/유형 신호가 있으면 args 에 변환해 넘길 것.",
            "kms_sop.search": "★ Agent SOP/정책 검색 (Phase 1.5B-β) — agent.sop_repo_ids 안의 절차/정책/매뉴얼 markdown chunks 만 검색. evidence 가 아닌 *instruction*. args: query(필수), agent_id(자동주입), top_k(default 5, max 20). plan_orchestrator 통합은 FEATURE_SOP_RAG 가드.",
            "kms_inventory.get_summary": "사용자 KMS 자료 인벤토리 요약 (저장소/문서 수/카테고리)",
            "kms_inventory.list_documents": "활성/대기 문서 *실제 목록* (title/status/size/updated_at). 리스트/상세 질의용",
            "kms_meta.get_my_inventory": "사용자가 등록한 모든 자료/스킬/구독 한 번에 dict 반환",
            "weather.lookup": "★ *즉시* 특정 날짜·도시 날씨 조회 (Open-Meteo 실 API). 사용자 발화 '내일 서울 날씨' 직답 용. args: date, location",
            "news.search": "★ *즉시* 카테고리별 최신 뉴스 헤드라인 조회 (RSS 실 시간). 사용자 발화 '오늘 경제 뉴스' 직답 용. args: category, query, count. (vs news.fetch_and_summarize 는 스케줄 전용이라 즉시 조회 X)",
            "web.search": "★ 일반 웹 검색 (네이버/Brave). args: query(필수), count, category(naver: blog/news/web/cafearticle). 한국어 우선. 자비스 외부 지식 습득 1단계.",
            "web.fetch": "★ URL 본문 추출 (httpx + readability). args: url(필수), max_chars(기본 5000). SSRF 방어 (localhost/사내IP/file:// 차단). 자비스 외부 지식 습득 2단계.",
            "kms.save_research": "★ agent 가 합성한 본문을 KMS 에 저장 → 다음 turn 부터 kms_rag.search 로 재검색 가능. args: title, content, source_urls, original_query. tenant_id 자동 주입. 자비스 지식 습득 패턴 핵심.",
            "stock.quote": "★ 한국 주식 (KRX) 시세 조회 — 종목명 또는 6자리 코드. args: symbol|name. 반환: close, change_pct, volume, trade_date. pykrx 무료 데이터.",
            "stock.market_movers": "★ KRX 시장 동향 — 급등 top N + 급락 top N + 거래량 top N. args: market(KOSPI|KOSDAQ|ALL), top_n(default 5).",
            "stock.add_watch": "★ 관심·보유 종목 등록. args: symbol|name(필수), qty, avg_cost, alert_high, alert_low, monitor_interval_min, note. 동일 종목 재등록 시 필드 병합.",
            "stock.list_watch": "★ 보유·관심 종목 목록 + 현재가 + 손익 동시 조회. args: 없음(자동). 반환: items(평가금액·등락률·손익률), total_pnl.",
            "stock.update_watch": "보유 종목 일부 필드 수정. args: id(필수) + 변경할 필드.",
            "stock.delete_watch": "보유·관심 종목 삭제. args: id(필수).",
            "stock.analyze": "★ 종목 종합 분석 — 시세 + RSI/MACD/Bollinger/MA + 변동성 + 5/20일 수익률 + (DART_API_KEY 있으면) 최근 공시 + (KR-FinBert 로드 가능시) 뉴스 sentiment. args: symbol|name. 매수·매도 권고 없음, 객관적 사실·신호만. 면책 1줄 포함.",
            "stock.predict": "주식 예측 — 미구현 stub (의도 보존 응답)",
            "restaurant.search": "맛집 검색 — 미구현 stub",
            "movie.lookup": "영화 정보 검색 — 미구현 stub",
            "movie.boxoffice": "박스오피스 순위 — 미구현 stub",
            "fx.rate": "환율 조회 — 미구현 stub",
            "transit.status": "교통 / 지하철 운행 상태 — 미구현 stub",
            "flight.price": "항공권 가격 검색 — 미구현 stub",
            "concert.schedule": "콘서트 일정 검색 — 미구현 stub",
            "menu.recommend": "식사 메뉴 추천 — 미구현 stub",
            "streaming.lookup": "OTT (넷플릭스 등) 신작/순위 — 미구현 stub",
            "air.quality": "미세먼지·공기질 조회 — 미구현 stub",
        },
        # Phase 2 (#153) + D26 (#201, 2026-05-08) — 도구별 default_scope manifest.
        # spec: docs/superpowers/specs/2026-05-08-d26-default-scope-manifest.md
        # 단일 소스 = scope_resolver._TOOL_DEFAULT_SCOPES.
        # ToolRegistry 의 _scopes 는 catalog/UI 메타용. validator + engine inject 는
        # 직접 resolver 호출 — 본 dict 는 catalog API 노출 일관성을 위해 동기화.
        scopes=_default_scopes_for_registered_tools(),
    )

    llm = VLLMAdapter()

    # Stage A: fs|kms 선택. trigger label 집합은 소스와 무관하게 동일 구조.
    skills = _load_skills_from_configured_source()
    log.info(
        "agent_skills_loaded",
        source=os.environ.get("AGENT_SKILLS_SOURCE", "fs").lower(),
        count=len(skills),
    )
    all_labels = sorted({t.intent for s in skills.values() for t in s.triggers})
    intent_classifier = MultiLabelIntentClassifier(llm, labels=all_labels)

    # Task 26-B: 자유형 스킬 (+ no-match) 을 담당하는 tool-calling loop.
    # VLLMAdapter 의 chat_completion_json (response_format=json_object) 을 사용.
    tool_loop = ToolCallingLoop(llm_client=llm, tool_registry=tools)

    # Stage B-Core-3: account 별 enabled 스킬 라벨 조회. 공유 DB engine 재사용.
    db_engine = _get_or_create_db_engine()
    skill_registry = SkillRegistry(engine=db_engine, all_skills=skills)

    # Task 34-36 Phase A: DraftComposer — "대화로 스킬 추가" sentinel 경로용.
    draft_composer = DraftComposer(llm_client=llm)

    # Phase 8 (KMS-Plus): execution_guard + tool_invocation_store 활성화.
    # guard 는 consequential tool 실행 직전 정책 게이트 (deny/dry_run/interrupt/run).
    # inv_store 는 tool_invocations 테이블 CRUD — 감사/cooldown/한도 계산.
    guard, inv_store = _build_guard_and_inv_store()

    # Wave D (KMS-Plus, 2026-04-25): AckGenerator wire-up.
    # KMS_ACK_MODEL_URL 미설정이면 정적 fallback 만 발화 (timeout 0ms, OK 한
    # 사용자 경험). 설정되면 E2B/E4B 짧은 모델로 <300ms ack 합성.
    # ack_generator 미주입 시 engine 은 ack 자체를 yield 하지 않으므로 운영
    # 빌드는 명시적으로 항상 인스턴스를 만들어 둔다.
    ack_generator = AckGenerator(
        base_url=os.environ.get("KMS_ACK_MODEL_URL"),
        model=os.environ.get("KMS_ACK_MODEL_NAME", "kms-ack"),
        timeout_ms=int(os.environ.get("KMS_ACK_TIMEOUT_MS", "300")),
    )

    return AgentEngine(
        session_store=session_store,
        tool_registry=tools,
        slot_filler=SlotFiller(llm),
        response_generator=ResponseGenerator(llm),
        fallback_router=FallbackRouter(llm),
        intent_classifier=intent_classifier,
        tool_loop=tool_loop,
        # Stage A: 위에서 계산한 skills 를 engine 에 재사용 (이중 로드 방지)
        skills=skills,
        skill_registry=skill_registry,
        draft_composer=draft_composer,
        db_engine=db_engine,
        execution_guard=guard,
        tool_invocation_store=inv_store,
        ack_generator=ack_generator,
    )


async def get_agent_engine() -> AgentEngine:
    return _build_engine()


def get_skill_registry(
    engine: AgentEngine = Depends(get_agent_engine),
) -> SkillRegistry:
    """Stage B-Core-5: skill enable/disable 엔드포인트 용 DI.

    AgentEngine 은 이미 skill_registry 를 보관하므로 그대로 반환.
    prod 에서는 ``_build_engine()`` 이 항상 SkillRegistry 를 주입하므로 None 은
    비정상 상태 (테스트에서 가벼운 stub 을 주입한 경우 등) — 503 으로 drop.
    """
    reg = getattr(engine, "skill_registry", None)
    if reg is None:
        raise HTTPException(503, "skill_registry not configured")
    return reg
