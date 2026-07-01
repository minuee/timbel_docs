"""각 mock tool 의 OpenAI function calling schema.

LLM 이 이 스키마 보고 tool_call 생성 → tool_calling_loop 가 레지스트리로 실행.

Schema 디자인 원칙:
- description 은 LLM 에게 보여질 것 — 언제 쓰는지 명확히
- required 는 꼭 필요한 것만 (선택 파라미터 많으면 LLM 이 허둥댐)
- parameters.type 은 OpenAI spec 엄격 준수 (string/number/boolean/object/array)
"""
from __future__ import annotations


# 각 entry: (tool_name, spec dict)
# spec 은 OpenAI Chat Completions API 의 tools[].function 포맷
_SCHEMAS: list[dict] = [
    # ── schedule ─────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "schedule.create",
            "description": "사용자 개인 일정을 등록. 약속·회의·반복 이벤트 등 시간 기반 일정.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "사용자 식별용 전화번호"},
                    "title": {"type": "string", "description": "일정 제목 (예: '팀 미팅')"},
                    "when": {"type": "string", "description": "ISO 8601 날짜/시간 (예: 2026-04-25T15:00)"},
                    "recurrence": {"type": ["string", "null"], "description": "RRULE (예: FREQ=WEEKLY;BYDAY=MO). 단발이면 null"},
                },
                "required": ["phone", "title", "when"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule.list",
            "description": "사용자의 등록된 일정 목록 조회. '내 일정 뭐 있어' 같은 질문에.",
            "parameters": {
                "type": "object",
                "properties": {"phone": {"type": "string"}},
                "required": ["phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule.delete",
            "description": "특정 일정 삭제.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string"},
                    "id": {"type": "string", "description": "schedule.list 응답에서 얻은 일정 UUID"},
                },
                "required": ["phone", "id"],
            },
        },
    },

    # ── diary ────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "diary.save",
            "description": "개인 일기 저장. 오늘의 기분/생각/사건 기록.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string"},
                    "entry_text": {"type": "string", "description": "일기 본문"},
                    "emotion": {
                        "type": ["string", "null"],
                        "enum": ["기쁨", "슬픔", "분노", "평온", "불안", None],
                        "description": "주된 감정. 모호하면 null",
                    },
                    "date": {"type": ["string", "null"], "description": "YYYY-MM-DD (기본: 오늘)"},
                },
                "required": ["phone", "entry_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diary.search",
            "description": "과거 일기 검색. 키워드·감정 필터 지원.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string"},
                    "query": {"type": "string", "description": "검색 키워드 (공백 허용)"},
                    "emotion": {
                        "type": ["string", "null"],
                        "enum": ["기쁨", "슬픔", "분노", "평온", "불안", None],
                    },
                    "top_k": {"type": "number", "description": "최대 결과 수 (default 5)"},
                },
                "required": ["phone"],
            },
        },
    },

    # ── news ─────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "news.add_subscription",
            "description": "사용자가 구독할 뉴스 주제 추가.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string"},
                    "topic": {"type": "string", "description": "주제 (예: 'AI 스타트업')"},
                },
                "required": ["phone", "topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news.remove_subscription",
            "description": "구독 주제 해제.",
            "parameters": {
                "type": "object",
                "properties": {"phone": {"type": "string"}, "topic": {"type": "string"}},
                "required": ["phone", "topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news.list_subscriptions",
            "description": "사용자의 구독 주제 목록.",
            "parameters": {
                "type": "object",
                "properties": {"phone": {"type": "string"}},
                "required": ["phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news.list_recent_reports",
            "description": "최근 전송된 뉴스 브리핑 조회.",
            "parameters": {
                "type": "object",
                "properties": {"phone": {"type": "string"}},
                "required": ["phone"],
            },
        },
    },

    # ── reminder ────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "reminder.schedule",
            "description": "미래 시각에 SMS·알림 전송 예약.",
            "parameters": {
                "type": "object",
                "properties": {
                    "at": {"type": "string", "description": "ISO 8601 datetime"},
                    "channel": {"type": "string", "enum": ["sms", "email", "push"], "description": "전송 채널"},
                    "phone": {"type": "string"},
                    "template": {"type": ["string", "null"], "description": "미리 준비된 템플릿 이름 (선택)"},
                    "tenant_id": {"type": "string", "description": "KMS 모드일 때 required (tenant scope)"},
                },
                "required": ["at", "channel", "phone"],
            },
        },
    },

    # ── kms_rag (문서 검색) ─────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "kms_rag.search",
            "description": "업로드된 문서·지식베이스 검색. 지인 정보/사실 확인/개인 자료 조회.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "자연어 검색 쿼리"},
                    "top_k": {"type": "number", "description": "default 3"},
                    "tenant_id": {"type": "string", "description": "사용자 식별자 (tenant scope)"},
                },
                "required": ["query", "tenant_id"],
            },
        },
    },
]


def all_schemas() -> list[dict]:
    """전체 tool 스키마 리스트 (LLM 호출 시 tools= 에 그대로 전달)."""
    return list(_SCHEMAS)


def tool_name_set() -> set[str]:
    return {s["function"]["name"] for s in _SCHEMAS}
