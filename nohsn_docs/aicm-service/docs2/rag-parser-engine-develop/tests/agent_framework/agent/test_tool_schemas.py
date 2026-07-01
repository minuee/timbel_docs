from src.agent_framework.agent.tool_schemas import all_schemas, tool_name_set


def test_all_schemas_valid_openai_function_format():
    for s in all_schemas():
        assert s["type"] == "function"
        fn = s["function"]
        assert "name" in fn and "description" in fn
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params


def test_schemas_cover_mock_tools():
    names = tool_name_set()
    # v1 에 등록된 non-audit tool 은 전부 있어야 함
    for n in [
        "schedule.create", "schedule.list", "schedule.delete",
        "diary.save", "diary.search",
        "news.add_subscription", "news.remove_subscription",
        "news.list_subscriptions", "news.list_recent_reports",
        "reminder.schedule",
        "kms_rag.search",
    ]:
        assert n in names


def test_audit_tools_excluded():
    """appointment/calendar tool 은 tool-calling 에 노출되면 안 됨 (의료 감사 경로 별도)."""
    names = tool_name_set()
    for forbidden in ["calendar.book", "calendar.check_availability",
                       "calendar.list_doctors", "calendar.list_available_slots"]:
        assert forbidden not in names


def test_no_duplicate_names():
    names = [s["function"]["name"] for s in all_schemas()]
    assert len(names) == len(set(names))
