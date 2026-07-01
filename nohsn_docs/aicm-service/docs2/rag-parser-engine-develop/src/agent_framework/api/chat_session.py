"""/agent/chat — AgentEngine 을 SSE 로 스트리밍하는 엔드포인트.

Engine.turn() 이 yield 하는 dict 이벤트를 `text/event-stream` 형식으로
직렬화해 클라이언트에 푸시. 이벤트 종류: intent / state / slot_update /
tool_result / token / done.

Task 24.5 — ``ChatRequest.attachments`` 가 추가됨.  프론트가 이미지를 base64
로 인코딩해 전송하면 엔진이 멀티모달 LLM 호출 시 vision content 로 변환.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.agent_framework.api.dependencies import get_agent_engine
from src.agent_framework.runtime.engine import AgentEngine
from src.api.middleware.rate_limit import CHAT_LIMIT, limiter

router = APIRouter(prefix="/agent", tags=["agent"])


class Attachment(BaseModel):
    """채팅 메시지 첨부 (v1: 이미지만 지원).

    data_base64 는 파일 바이트의 base64 인코딩 — ``data:`` URL prefix 는 포함
    하지 않는다 (백엔드에서 `data:{mime};base64,{data_base64}` 로 재조합).
    """

    mime: str  # "image/png" | "image/jpeg" | "image/webp"
    filename: str
    data_base64: str


class ChatRequest(BaseModel):
    session_id: str
    tenant_id: str
    message: str
    attachments: list[Attachment] = Field(default_factory=list)
    # Phase 2 — voice 모드 hint. True 면 응답 본문이 TTS 친화 양식이어야 함을 알린다.
    # v1: 백엔드는 이 hint 를 세션에 기록만 (엔진이 모듈 사용 여부 결정), FE 가 마지막 후처리.
    voice_mode: bool = False


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode(
        "utf-8"
    )


@router.post("/chat")
@limiter.limit(CHAT_LIMIT)
async def chat(
    request: Request,  # slowapi 필수 — limiter 가 키 추출에 사용
    req: ChatRequest,
    engine: AgentEngine = Depends(get_agent_engine),
) -> StreamingResponse:
    async def stream():
        async for item in engine.turn(
            req.session_id,
            req.tenant_id,
            req.message,
            attachments=req.attachments or None,
        ):
            yield _sse(item["event"], item["data"])

    return StreamingResponse(stream(), media_type="text/event-stream")
