"""블럭 프리뷰 API — 문서의 파싱/블럭 결과를 프론트엔드에서 확인한다."""

import os
import re

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

router = APIRouter(tags=["preview"])


@router.get("/preview/images/{image_path:path}", summary="추출 이미지 서빙")
async def serve_image(image_path: str) -> FileResponse:
    """파이프라인에서 추출한 이미지를 서빙한다.

    image_path는 /tmp/aicm_pdf_img_*/page1_img0.png 형태의 경로.
    보안: /tmp/aicm_ 접두사만 허용.
    """
    # nginx가 선행 /를 제거할 수 있으므로 복원
    if not image_path.startswith("/"):
        image_path = "/" + image_path
    full_path = os.path.realpath(image_path)
    if not (full_path.startswith("/tmp/") or full_path.startswith("/data/")):
        raise HTTPException(status_code=403, detail="허용되지 않는 경로")
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다")

    return FileResponse(full_path, media_type="image/png")


@router.get("/documents/{doc_id}/images", summary="문서 추출 이미지 목록")
async def list_document_images(doc_id: str) -> dict:
    """MinIO intermediate에 캐시된 parsed.json에서 이미지 경로를 반환한다."""
    import json as _json

    try:
        from src.pipeline.storage.config import storage_config as scfg
        from minio import Minio

        client = Minio(
            scfg.MINIO_ENDPOINT,
            access_key=scfg.MINIO_ACCESS_KEY,
            secret_key=scfg.MINIO_SECRET_KEY,
            secure=scfg.MINIO_SECURE,
        )
        bucket = scfg.MINIO_INTERMEDIATE_BUCKET
        key = f"{doc_id}/parsed.json"

        resp = client.get_object(bucket, key)
        parsed = _json.loads(resp.read())
        resp.close()
        resp.release_conn()

        images = []
        for img in parsed.get("images", []):
            path = img.get("image_path", "")
            if path and os.path.isfile(path):
                # 경로에서 선행 /를 제거하여 URL 이중 슬래시 방지
                clean_path = path.lstrip("/")
                images.append({
                    "page_number": img.get("page_number"),
                    "image_index": img.get("image_index"),
                    "bbox": img.get("bbox"),
                    "url": f"/api/v1/preview/images/{clean_path}",
                })
        return {"success": True, "data": images}
    except Exception as exc:
        return {"success": False, "data": [], "error": str(exc)}


@router.post("/preview/analyze", summary="문서 블럭 분석 (프리뷰용)")
async def analyze_document_for_preview(
    file_path: str,
    max_pages: int = Query(10, ge=1, le=50),
) -> dict:
    """문서를 파싱하고 블럭으로 분할하여 프리뷰 데이터를 반환한다.

    프론트엔드의 블럭 프리뷰 뷰어에서 사용.
    """
    from uuid import uuid4

    from src.pipeline.models.document import ProcessingConfig
    from src.pipeline.parsers.router import detect_format, select_parser
    from src.pipeline.segmenters.fallback_segmenter import FallbackSegmenter

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

    # 파싱 — preview도 OCR로 스캔/이미지 PDF 텍스트까지 추출(품질 우선). 동기 파싱이라 대기는 동일.
    fmt = detect_format(file_path)
    parser = select_parser(fmt, file_path)
    parse_result = await parser.parse()

    # 블럭 세그멘테이션
    config = ProcessingConfig(use_block_pipeline=True, block_max_tokens=800)
    segmenter = FallbackSegmenter(config)
    doc_id = uuid4()
    blocks = await segmenter.segment(parse_result, document_id=doc_id)

    # 블럭 직렬화
    block_data = []
    for b in blocks[: max_pages * 50]:  # 페이지당 최대 50블럭
        block_data.append(
            {
                "index": b.block_index,
                "type": b.block_type.value,
                "content": b.content,
                "page": b.source_location.page_number,
                "token_count": b.token_count,
                "image_path": b.image_path,
                "table_markdown": b.table_markdown,
                "metadata": b.metadata,
            }
        )

    # 노이즈 감지
    noise_indices = []
    content_counts: dict[str, int] = {}
    for b in block_data:
        c = b["content"].strip()
        content_counts[c] = content_counts.get(c, 0) + 1

    for i, b in enumerate(block_data):
        c = b["content"].strip()
        flags = []
        if len(c) < 10 and b["type"] not in ("divider", "image"):
            flags.append("너무 짧음")
        if re.match(r"^[-\u2013\u2014\s]*\d{1,3}[-\u2013\u2014\s]*$", c):
            flags.append("페이지 번호")
        if content_counts.get(c, 0) >= 3:
            flags.append(f"반복 {content_counts[c]}회")
        if flags:
            noise_indices.append({"index": i, "flags": flags})

    return {
        "file_path": file_path,
        "format": fmt.value,
        "pages": len(parse_result.pages),
        "total_blocks": len(block_data),
        "blocks": block_data,
        "noise_suspects": noise_indices,
        "metadata": parse_result.metadata,
    }


@router.post("/preview/analyze-file", summary="파일 업로드 → 블럭 분석 (프리뷰용)")
async def analyze_uploaded_file_for_preview(
    file: UploadFile,
    max_pages: int = Query(10, ge=1, le=50),
) -> dict:
    """업로드된 파일을 임시 저장 후 파싱하여 블럭 프리뷰를 반환한다."""
    import tempfile
    import shutil

    suffix = os.path.splitext(file.filename or "doc.txt")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="/tmp") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        result = await analyze_document_for_preview(file_path=tmp_path, max_pages=max_pages)
        result["file_path"] = file.filename or "uploaded_file"

        import base64
        for block in result.get("blocks", []):
            img_path = block.get("image_path")
            if img_path and os.path.isfile(img_path):
                try:
                    with open(img_path, "rb") as f:
                        img_data = base64.b64encode(f.read()).decode("ascii")
                    ext = os.path.splitext(img_path)[1].lstrip(".") or "png"
                    block["image_data_url"] = f"data:image/{ext};base64,{img_data}"
                except Exception:
                    pass

        return result
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
