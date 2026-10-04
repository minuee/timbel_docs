"""Presigned URL transfers for the /v1/merge job pipeline.

recog holds no storage credentials. Every object access goes through a
presigned URL that master-api issues, so the standard library is enough:
the signature already lives in the query string and we never sign anything.

See newDocs/MERGE_API_SPEC.md section 2.3.
"""

from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_TIMEOUT_SEC = 300
CHUNK_BYTES = 1024 * 1024

#: Metadata header that master-api must include in the PUT signature.
#: Its value decides the download filename (Content-Disposition) later, so we
#: forward the caller-supplied string verbatim -- any reshaping breaks the
#: signature. See spec section 4.1.
ORIGINALNAME_HEADER = "x-amz-meta-originalname"


class TransferError(RuntimeError):
    """A presigned transfer failed.

    ``code`` carries the spec error code (E41xx) so the job can surface it
    to master-api without re-deriving the cause.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error_body(exc: urllib.error.HTTPError) -> str:
    """Best-effort read of an S3/MinIO XML error body."""
    try:
        return exc.read(4096).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - diagnostics only
        return ""


def _is_expired(status: int, body: str) -> bool:
    """S3 and MinIO both answer an outdated signature with 403 + 'expired'."""
    if status != 403:
        return False
    lowered = body.lower()
    return "expired" in lowered


def download(url: str, dest_path: str | Path, *, timeout: float = DEFAULT_TIMEOUT_SEC) -> int:
    """GET a presigned URL into ``dest_path``. Returns the byte count written."""
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with open(dest_path, "wb") as handle:
                shutil.copyfileobj(response, handle, CHUNK_BYTES)
    except urllib.error.HTTPError as exc:
        body = _error_body(exc)
        code = "E4102" if _is_expired(exc.code, body) else "E4101"
        raise TransferError(code, f"download failed (HTTP {exc.code}): {body[:200]}") from exc
    except urllib.error.URLError as exc:
        raise TransferError("E4101", f"download failed: {exc.reason}") from exc
    except OSError as exc:
        raise TransferError("E4101", f"download failed: {exc}") from exc

    return Path(dest_path).stat().st_size


def upload(
    url: str,
    src_path: str | Path,
    *,
    originalname: str,
    content_type: str = "application/octet-stream",
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> int:
    """PUT ``src_path`` to a presigned URL. Returns the byte count sent.

    ``originalname`` is sent unmodified as the metadata header; master-api must
    have included that exact value when signing the URL.
    """
    size = Path(src_path).stat().st_size
    with open(src_path, "rb") as handle:
        request = urllib.request.Request(url, data=handle, method="PUT")
        request.add_header("Content-Type", content_type)
        request.add_header("Content-Length", str(size))
        request.add_header(ORIGINALNAME_HEADER, originalname)
        try:
            with urllib.request.urlopen(request, timeout=timeout):
                pass
        except urllib.error.HTTPError as exc:
            body = _error_body(exc)
            code = "E4102" if _is_expired(exc.code, body) else "E4105"
            raise TransferError(code, f"upload failed (HTTP {exc.code}): {body[:200]}") from exc
        except urllib.error.URLError as exc:
            raise TransferError("E4105", f"upload failed: {exc.reason}") from exc
        except OSError as exc:
            raise TransferError("E4105", f"upload failed: {exc}") from exc

    return size
