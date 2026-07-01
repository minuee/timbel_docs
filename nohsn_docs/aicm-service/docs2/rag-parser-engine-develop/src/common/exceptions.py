"""AICM 공통 예외 정의."""


class AICMError(Exception):
    """AICM 기본 예외."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AICMError):
    """리소스를 찾을 수 없음."""

    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            code=f"{resource.upper()}_NOT_FOUND",
            message=f"{resource}를 찾을 수 없습니다: {resource_id}",
            details={"resource": resource, "id": resource_id},
        )


class TenantIsolationError(AICMError):
    """테넌트 격리 위반."""

    def __init__(self) -> None:
        super().__init__(
            code="TENANT_ISOLATION_VIOLATION",
            message="테넌트 격리 정책을 위반하는 접근입니다.",
        )


class UnsupportedFormatError(AICMError):
    """지원하지 않는 문서 포맷."""

    def __init__(self, format_name: str) -> None:
        super().__init__(
            code="UNSUPPORTED_FORMAT",
            message=f"지원하지 않는 문서 포맷입니다: {format_name}",
            details={"format": format_name},
        )


class PipelineError(AICMError):
    """파이프라인 처리 오류."""

    def __init__(self, stage: str, message: str, details: dict | None = None) -> None:
        super().__init__(
            code=f"PIPELINE_{stage.upper()}_ERROR",
            message=message,
            details={"stage": stage, **(details or {})},
        )


class LLMRoutingError(AICMError):
    """LLM 라우팅 실패 (양쪽 모두 실패)."""

    def __init__(self, task: str, errors: dict) -> None:
        super().__init__(
            code="LLM_ROUTING_FAILED",
            message=f"LLM 라우팅 실패: {task}. 모든 프로바이더가 응답하지 않습니다.",
            details={"task": task, "errors": errors},
        )


class RateLimitExceededError(AICMError):
    """API 호출 제한 초과."""

    def __init__(self, key_id: str, limit: int) -> None:
        super().__init__(
            code="RATE_LIMIT_EXCEEDED",
            message=f"API 호출 제한을 초과했습니다. 한도: {limit} req/min",
            details={"key_id": key_id, "limit": limit},
        )


class LicenseLimitExceededError(AICMError):
    """라이선스 한도 초과."""

    def __init__(self, resource: str, current: int, limit: int, tier: str) -> None:
        super().__init__(
            code="LICENSE_LIMIT_EXCEEDED",
            message=f"라이선스 한도를 초과했습니다. {resource}: {current}/{limit} (티어: {tier})",
            details={
                "resource": resource,
                "current": current,
                "limit": limit,
                "tier": tier,
            },
        )
