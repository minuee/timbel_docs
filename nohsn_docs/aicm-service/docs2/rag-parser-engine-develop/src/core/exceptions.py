"""Core 서비스 전용 예외 정의."""

from src.common.exceptions import AICMError


class TenantNotFoundError(AICMError):
    """테넌트를 찾을 수 없음."""

    def __init__(self, tenant_id: str) -> None:
        super().__init__(
            code="TENANT_NOT_FOUND",
            message=f"테넌트를 찾을 수 없습니다: {tenant_id}",
            details={"tenant_id": tenant_id},
        )


class TenantInactiveError(AICMError):
    """비활성 테넌트 접근 시도."""

    def __init__(self, tenant_id: str) -> None:
        super().__init__(
            code="TENANT_INACTIVE",
            message=f"비활성 상태의 테넌트입니다: {tenant_id}",
            details={"tenant_id": tenant_id},
        )


class RepositoryNotFoundError(AICMError):
    """저장소를 찾을 수 없음."""

    def __init__(self, repository_id: str) -> None:
        super().__init__(
            code="REPOSITORY_NOT_FOUND",
            message=f"저장소를 찾을 수 없습니다: {repository_id}",
            details={"repository_id": repository_id},
        )


class CategoryNotFoundError(AICMError):
    """카테고리를 찾을 수 없음."""

    def __init__(self, category_id: str) -> None:
        super().__init__(
            code="CATEGORY_NOT_FOUND",
            message=f"카테고리를 찾을 수 없습니다: {category_id}",
            details={"category_id": category_id},
        )


class DocumentTypeNotFoundError(AICMError):
    """문서타입을 찾을 수 없음."""

    def __init__(self, document_type_id: str) -> None:
        super().__init__(
            code="DOCUMENT_TYPE_NOT_FOUND",
            message=f"문서타입을 찾을 수 없습니다: {document_type_id}",
            details={"document_type_id": document_type_id},
        )


class DocumentNotFoundError(AICMError):
    """문서를 찾을 수 없음."""

    def __init__(self, document_id: str) -> None:
        super().__init__(
            code="DOCUMENT_NOT_FOUND",
            message=f"문서를 찾을 수 없습니다: {document_id}",
            details={"document_id": document_id},
        )


class UserNotFoundError(AICMError):
    """사용자를 찾을 수 없음."""

    def __init__(self, user_id: str) -> None:
        super().__init__(
            code="USER_NOT_FOUND",
            message=f"사용자를 찾을 수 없습니다: {user_id}",
            details={"user_id": user_id},
        )


class InsufficientPermissionError(AICMError):
    """권한 부족."""

    def __init__(self, required_role: str, current_role: str) -> None:
        super().__init__(
            code="INSUFFICIENT_PERMISSION",
            message=f"권한이 부족합니다. 필요 역할: {required_role}, 현재 역할: {current_role}",
            details={"required_role": required_role, "current_role": current_role},
        )


class DuplicateSlugError(AICMError):
    """테넌트 slug 중복."""

    def __init__(self, slug: str) -> None:
        super().__init__(
            code="DUPLICATE_SLUG",
            message=f"이미 사용 중인 slug입니다: {slug}",
            details={"slug": slug},
        )


class DuplicateNameError(AICMError):
    """리소스 이름 중복."""

    def __init__(self, resource: str, name: str) -> None:
        super().__init__(
            code="DUPLICATE_NAME",
            message=f"이미 사용 중인 {resource} 이름입니다: {name}",
            details={"resource": resource, "name": name},
        )


class InvalidDocumentStatusTransitionError(AICMError):
    """허용되지 않는 문서 상태 전이."""

    def __init__(self, current_status: str, target_status: str) -> None:
        super().__init__(
            code="INVALID_STATUS_TRANSITION",
            message=f"허용되지 않는 상태 전이입니다: {current_status} → {target_status}",
            details={"current_status": current_status, "target_status": target_status},
        )


class AuthenticationError(AICMError):
    """인증 실패."""

    def __init__(self, message: str = "인증에 실패했습니다.") -> None:
        super().__init__(
            code="AUTHENTICATION_FAILED",
            message=message,
        )


class APIKeyInvalidError(AICMError):
    """유효하지 않은 API 키."""

    def __init__(self) -> None:
        super().__init__(
            code="API_KEY_INVALID",
            message="유효하지 않은 API 키입니다.",
        )


class CategoryCircularReferenceError(AICMError):
    """카테고리 순환 참조."""

    def __init__(self, category_id: str) -> None:
        super().__init__(
            code="CATEGORY_CIRCULAR_REFERENCE",
            message=f"카테고리 순환 참조가 감지되었습니다: {category_id}",
            details={"category_id": category_id},
        )
