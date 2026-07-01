"""파일 업로드 검증·저장 유틸리티.

보안 강화:
- Magic bytes 기반 파일 타입 검증
- 이중 확장자 공격 방지 (.pdf.exe 등)
- 임베디드 스크립트/매크로 탐지
"""

import hashlib
import mimetypes
import uuid
from pathlib import Path

from fastapi import UploadFile

from src.common.config import settings
from src.common.exceptions import AICMError, UnsupportedFormatError
from src.common.logging import get_logger

logger = get_logger(__name__)

# 지원 포맷 → MIME 매핑
SUPPORTED_FORMATS: dict[str, list[str]] = {
    "pdf": ["application/pdf"],
    "docx": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",  # 구 .doc
    ],
    "hwp": [
        "application/x-hwp",
        "application/haansofthwp",
        "application/vnd.hancom.hwp",
        "application/vnd.hancom.hwpx",
    ],
    "xlsx": [
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",  # 구 .xls
    ],
    "pptx": [
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-powerpoint",  # 구 .ppt
    ],
    "rtf": ["application/rtf", "text/rtf"],
    "csv": ["text/csv", "application/csv"],
    "html": ["text/html"],
    "txt": ["text/plain"],
    "markdown": ["text/markdown", "text/plain"],
    "image": [
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/bmp",
        "image/webp",
        "image/gif",
    ],
}

# 확장자 → 포맷 역매핑
EXTENSION_TO_FORMAT: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",  # 구 Word 포맷 → LibreOffice 경유 변환
    ".hwp": "hwp",
    ".hwpx": "hwp",  # 신 한글 포맷
    ".xlsx": "xlsx",
    ".xls": "xlsx",  # 구 Excel 포맷 → xlrd 폴백
    ".pptx": "pptx",
    ".ppt": "pptx",  # 구 PowerPoint 포맷 → LibreOffice 경유 변환
    ".html": "html",
    ".htm": "html",
    ".txt": "txt",
    ".md": "markdown",
    ".markdown": "markdown",
    ".csv": "csv",
    ".rtf": "rtf",  # LibreOffice 변환
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tiff": "image",
    ".tif": "image",
    ".bmp": "image",
    ".webp": "image",
    ".gif": "image",
}

# Magic bytes (파일 시그니처) 매핑
MAGIC_BYTES: dict[str, list[bytes]] = {
    "pdf": [b"%PDF"],
    # docx/xlsx/pptx 는 ZIP(PK) 기반; 구형 .doc/.xls/.ppt 는 OLE2(Compound Doc)
    "docx": [b"PK\x03\x04", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    "xlsx": [b"PK\x03\x04", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    "pptx": [b"PK\x03\x04", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    "hwp": [b"\xd0\xcf\x11\xe0", b"HWP Document File", b"PK\x03\x04"],  # hwpx 는 ZIP
    "rtf": [b"{\\rtf"],
    "csv": [],  # 텍스트 기반
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "tiff": [b"II\x2a\x00", b"MM\x00\x2a"],
    "tif": [b"II\x2a\x00", b"MM\x00\x2a"],
    "bmp": [b"BM"],
    "webp": [b"RIFF"],  # RIFF....WEBP
    "gif": [b"GIF87a", b"GIF89a"],
    "html": [b"<!DOCTYPE", b"<html", b"<!doctype", b"<HTML"],
    "htm": [b"<!DOCTYPE", b"<html", b"<!doctype", b"<HTML"],
}

# 위험한 실행 파일 확장자
DANGEROUS_EXTENSIONS: set[str] = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".pif",
    ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".ps1",
    ".psm1", ".psd1", ".sh", ".bash", ".csh", ".ksh",
    ".app", ".action", ".command", ".workflow",
    ".dll", ".sys", ".drv", ".ocx",
    ".jar", ".class", ".pyc", ".pyo",
}

# 스크립트/매크로 시그니처 패턴 (바이트 기반)
_SCRIPT_SIGNATURES: list[bytes] = [
    b"<script",
    b"<SCRIPT",
    b"javascript:",
    b"vbscript:",
    b"eval(",
    b"exec(",
    b"\\x00MZ",  # PE 실행파일
    b"MZ\x90\x00",  # PE 실행파일
]

# VBA 매크로 시그니처
_MACRO_SIGNATURES: list[bytes] = [
    b"vbaProject.bin",
    b"VBA",
    b"\\Macros\\",
    b"Sub AutoOpen",
    b"Sub Workbook_Open",
    b"Sub Document_Open",
]


class FileTooLargeError(AICMError):
    """업로드 파일 크기 초과."""

    def __init__(self, size_mb: float, max_mb: int) -> None:
        super().__init__(
            code="FILE_TOO_LARGE",
            message=f"파일 크기({size_mb:.1f}MB)가 최대 허용 크기({max_mb}MB)를 초과합니다.",
            details={"size_mb": size_mb, "max_mb": max_mb},
        )


class MaliciousFileError(AICMError):
    """악성 파일 탐지."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            code="MALICIOUS_FILE_DETECTED",
            message=f"보안 검증 실패: {reason}",
            details={"reason": reason},
        )


class DoubleExtensionError(AICMError):
    """이중 확장자 공격 탐지."""

    def __init__(self, filename: str) -> None:
        super().__init__(
            code="DOUBLE_EXTENSION_ATTACK",
            message=f"이중 확장자가 감지되었습니다: {filename}",
            details={"filename": filename},
        )


class MagicBytesMismatchError(AICMError):
    """Magic bytes 불일치."""

    def __init__(self, expected_format: str) -> None:
        super().__init__(
            code="MAGIC_BYTES_MISMATCH",
            message=f"파일 내용이 선언된 포맷({expected_format})과 일치하지 않습니다.",
            details={"expected_format": expected_format},
        )


def detect_format(filename: str, content_type: str | None = None) -> str:
    """파일명과 Content-Type으로 문서 포맷을 감지한다.

    Args:
        filename: 원본 파일명
        content_type: HTTP Content-Type 헤더 값

    Returns:
        포맷 문자열 (pdf, docx, hwp 등)

    Raises:
        UnsupportedFormatError: 지원하지 않는 포맷
    """
    ext = Path(filename).suffix.lower()
    if ext in EXTENSION_TO_FORMAT:
        return EXTENSION_TO_FORMAT[ext]

    # Content-Type 기반 매칭
    if content_type:
        for fmt, mime_list in SUPPORTED_FORMATS.items():
            if content_type in mime_list:
                return fmt

    # mimetypes 추론
    guessed_type, _ = mimetypes.guess_type(filename)
    if guessed_type:
        for fmt, mime_list in SUPPORTED_FORMATS.items():
            if guessed_type in mime_list:
                return fmt

    raise UnsupportedFormatError(ext or content_type or "unknown")


def validate_double_extension(filename: str) -> None:
    """이중 확장자 공격을 탐지한다.

    예: report.pdf.exe, document.docx.bat

    Args:
        filename: 원본 파일명

    Raises:
        DoubleExtensionError: 이중 확장자 감지
    """
    # 파일명에서 모든 확장자 추출
    name = filename
    extensions: list[str] = []
    while True:
        path = Path(name)
        ext = path.suffix.lower()
        if not ext:
            break
        extensions.append(ext)
        name = path.stem

    if len(extensions) < 2:
        return

    # 확장자 중 하나라도 위험 확장자이면 거부
    for ext in extensions:
        if ext in DANGEROUS_EXTENSIONS:
            raise DoubleExtensionError(filename)

    # 최종 확장자가 지원 포맷이 아니면 거부
    if extensions[0] not in EXTENSION_TO_FORMAT:
        raise DoubleExtensionError(filename)


def validate_magic_bytes(content: bytes, expected_format: str) -> None:
    """파일 내용의 magic bytes가 선언된 포맷과 일치하는지 검증한다.

    Args:
        content: 파일 내용 바이트
        expected_format: 감지된 포맷

    Raises:
        MagicBytesMismatchError: magic bytes 불일치
    """
    # 텍스트 기반 포맷은 magic bytes 검증 스킵
    if expected_format in ("txt", "markdown"):
        return

    # 매핑된 magic bytes 가져오기
    # image 포맷은 개별 확장자로 확인
    expected_magics: list[bytes] = []
    if expected_format == "image":
        # 여러 이미지 포맷의 magic bytes를 모두 허용
        for fmt in ("png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"):
            expected_magics.extend(MAGIC_BYTES.get(fmt, []))
    else:
        expected_magics = MAGIC_BYTES.get(expected_format, [])

    if not expected_magics:
        return  # 알려진 magic bytes 없으면 스킵

    # 파일 시작 부분 확인 (최대 16바이트)
    header = content[:16]
    for magic in expected_magics:
        if header.startswith(magic) or magic in header:
            return

    raise MagicBytesMismatchError(expected_format)


def scan_for_malicious_content(content: bytes, filename: str) -> None:
    """파일 내용에서 악성 스크립트나 매크로를 탐지한다.

    Args:
        content: 파일 내용 바이트
        filename: 원본 파일명

    Raises:
        MaliciousFileError: 악성 콘텐츠 탐지
    """
    ext = Path(filename).suffix.lower()

    # 문서 파일에서 스크립트 시그니처 검사 (HTML은 제외)
    if ext not in (".html", ".htm"):
        for sig in _SCRIPT_SIGNATURES:
            if sig in content:
                logger.warning(
                    "malicious_content_detected",
                    filename=filename,
                    signature=sig.decode("utf-8", errors="replace"),
                )
                raise MaliciousFileError(
                    f"파일에 임베디드 스크립트가 감지되었습니다: {filename}"
                )

    # Office 문서에서 VBA 매크로 검사
    if ext in (".docx", ".xlsx", ".doc", ".xls"):
        for sig in _MACRO_SIGNATURES:
            if sig in content:
                logger.warning(
                    "macro_detected",
                    filename=filename,
                    signature=sig.decode("utf-8", errors="replace"),
                )
                raise MaliciousFileError(
                    f"파일에 VBA 매크로가 감지되었습니다: {filename}"
                )

    # PE 실행파일 시그니처 검사 (모든 파일)
    if content[:2] == b"MZ":
        raise MaliciousFileError(
            f"파일이 실행 파일(PE) 형식입니다: {filename}"
        )

    # ELF 실행파일 시그니처 검사
    if content[:4] == b"\x7fELF":
        raise MaliciousFileError(
            f"파일이 실행 파일(ELF) 형식입니다: {filename}"
        )


async def validate_file_security(file: UploadFile) -> bytes:
    """파일 보안 검증을 통합 수행한다.

    1. 이중 확장자 검사
    2. Magic bytes 검증
    3. 악성 콘텐츠 스캔

    Args:
        file: FastAPI UploadFile

    Returns:
        파일 내용 바이트

    Raises:
        DoubleExtensionError: 이중 확장자 탐지
        MagicBytesMismatchError: magic bytes 불일치
        MaliciousFileError: 악성 콘텐츠 탐지
    """
    filename = file.filename or "unknown"

    # 1. 이중 확장자 검사
    validate_double_extension(filename)

    # 2. 파일 내용 읽기
    content = await file.read()
    await file.seek(0)

    # 3. 포맷 감지 및 magic bytes 검증
    try:
        detected_format = detect_format(filename, file.content_type)
        validate_magic_bytes(content, detected_format)
    except UnsupportedFormatError:
        pass  # 포맷 감지 실패는 여기서 처리하지 않음

    # 4. 악성 콘텐츠 스캔
    scan_for_malicious_content(content, filename)

    logger.info(
        "file_security_validated",
        filename=filename,
        size_bytes=len(content),
    )
    return content


async def validate_file_size(file: UploadFile, max_mb: int | None = None) -> int:
    """파일 크기 검증. 스트림을 끝까지 읽어 크기를 확인하고 처음으로 되감는다.

    Args:
        file: FastAPI UploadFile
        max_mb: 최대 허용 크기(MB). None이면 설정값 사용.

    Returns:
        파일 바이트 크기

    Raises:
        FileTooLargeError: 크기 초과
    """
    max_mb = max_mb or settings.MAX_UPLOAD_SIZE_MB

    # 파일 크기 확인 (SpooledTemporaryFile 에선 seek 필요)
    contents = await file.read()
    size_bytes = len(contents)
    await file.seek(0)

    size_mb = size_bytes / (1024 * 1024)
    if size_mb > max_mb:
        raise FileTooLargeError(size_mb=size_mb, max_mb=max_mb)

    return size_bytes


async def compute_file_sha256(file: UploadFile) -> str:
    """업로드 파일 바이트의 SHA-256(hex)을 계산하고 스트림을 처음으로 되감는다.

    동일 내용 문서 중복 적재(dedup) 판별용. 스트림을 끝까지 읽으므로 호출 후 seek(0)으로
    복원하여 후속 save_upload 가 정상 동작하도록 한다.
    """
    contents = await file.read()
    digest = hashlib.sha256(contents).hexdigest()
    await file.seek(0)
    return digest


async def save_upload(
    file: UploadFile,
    tenant_id: uuid.UUID,
    repository_id: uuid.UUID,
) -> str:
    """업로드 파일을 디스크에 저장한다.

    저장 경로: {UPLOAD_DIR}/{tenant_id}/{repository_id}/{uuid}_{filename}

    Args:
        file: FastAPI UploadFile
        tenant_id: 테넌트 UUID
        repository_id: 저장소 UUID

    Returns:
        저장된 파일의 절대 경로
    """
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / str(repository_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 안전한 파일명 생성 (원본 파일명에서 위험 문자 제거)
    original_name = file.filename or "unknown"
    safe_name = "".join(
        c for c in original_name if c.isalnum() or c in (".", "-", "_")
    )
    safe_filename = f"{uuid.uuid4().hex}_{safe_name}"
    file_path = upload_dir / safe_filename

    contents = await file.read()
    file_path.write_bytes(contents)
    await file.seek(0)

    logger.info(
        "file_saved",
        path=str(file_path),
        size_bytes=len(contents),
        tenant_id=str(tenant_id),
        repository_id=str(repository_id),
    )
    return str(file_path)
