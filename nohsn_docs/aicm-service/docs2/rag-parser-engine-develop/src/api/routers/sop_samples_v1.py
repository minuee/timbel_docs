"""SOP sample 라우터 — 19 카테고리 권장 양식 가이드 + 다운로드 노출.

2026-05-07: 사용자 요청 — `FEATURE_SOP_RAG` default OFF 유지 (작은 SOP 적합).
사용자가 *어떤 형태가 좋은지* 응용할 수 있도록 sample 19 개를 UI 에서 노출.

엔드포인트:
- GET /api/v1/sop-samples/categories — 19 카테고리 메타 list (label/desc/line/byte)
- GET /api/v1/sop-samples/{category} — markdown 본문 (text/plain)
- GET /api/v1/sop-samples/{category}/download — markdown attachment

보안:
- category whitelist Literal (path traversal 차단).
- 인증 X (공개 자료 — README/공개 가이드 동급).
- nosniff + Cache-Control 헤더 부착.

성능:
- 모듈 import 시 lazy-load + per-file try/except (부팅 차단 X).
- 캐시 hit 시 파일 I/O 없음.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sop-samples", tags=["sop-samples"])

_SAMPLES_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "agent_framework"
    / "agent_templates"
    / "sop_samples"
)

# 19 카테고리 (label / description). label 기준 한글 sort 는 응답 시 수행.
_CATEGORY_META: Dict[str, tuple[str, str]] = {
    "restaurant_cafe": ("식당/카페", "레스토랑·카페·베이커리·패스트푸드·테이크아웃"),
    "retail": ("리테일/잡화", "일반 소매 매장"),
    "beauty_skincare": ("뷰티/스킨케어", "화장품·피부관리"),
    "clothing_fashion": ("의류/패션", "옷가게·악세사리"),
    "culture_arts": ("문화/예술", "공연·전시·문화센터"),
    "education": ("교육/학원", "학원·교육 서비스"),
    "finance": ("금융", "보험·증권·은행 상담"),
    "hair_nail": ("헤어/네일", "미용실·네일샵"),
    "health_medical": ("헬스/의료", "병원·헬스장·필라테스"),
    "home_interior": ("홈/인테리어", "가구·인테리어·생활용품"),
    "it_electronics": ("IT/전자", "전자제품·디지털"),
    "kids_baby": ("키즈/유아", "유아용품·키즈카페"),
    "leisure_sports": ("레저/스포츠", "스포츠·레저"),
    "lodging": ("숙박", "호텔·펜션·게스트하우스"),
    "pet": ("반려동물", "동물병원·펫샵"),
    "plants_flowers": ("화초/플라워", "화원·꽃집"),
    "travel_agency": ("여행", "여행사·관광"),
    "wedding_dating": ("웨딩/소개", "웨딩홀·결혼정보"),
    "other": ("기타", "기타 업종"),
}

# id → {text, line_count, byte_size, label, description}
_CACHE: Dict[str, dict] = {}


def _load_cache() -> None:
    """모듈 import 시 1회 실행. per-file try/except — 부팅 차단 X."""
    if _CACHE:
        return
    if not _SAMPLES_DIR.exists():
        logger.warning(
            "sop_samples directory missing: %s — sample 라우터는 빈 응답.",
            _SAMPLES_DIR,
        )
        return
    for cat_id, (label, desc) in _CATEGORY_META.items():
        path = _SAMPLES_DIR / f"{cat_id}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("sop sample missing: %s", path)
            continue
        except Exception as exc:  # noqa: BLE001 — robust startup
            logger.warning("sop sample load fail %s: %s", path, exc)
            continue
        _CACHE[cat_id] = {
            "text": text,
            "line_count": text.count("\n") + (0 if text.endswith("\n") else 1),
            "byte_size": len(text.encode("utf-8")),
            "label": label,
            "description": desc,
        }
    logger.info("sop_samples loaded: %d/%d", len(_CACHE), len(_CATEGORY_META))


_load_cache()


@router.get("/categories")
async def list_categories() -> dict:
    """19 카테고리 메타 list — label 한글 기준 sort."""
    items = [
        {
            "id": cat_id,
            "label": entry["label"],
            "description": entry["description"],
            "line_count": entry["line_count"],
            "byte_size": entry["byte_size"],
        }
        for cat_id, entry in _CACHE.items()
    ]
    items.sort(key=lambda x: x["label"])
    return {"items": items}


@router.get("/{category}", response_class=PlainTextResponse)
async def get_sample(category: str) -> Response:
    """sample SOP markdown 본문 반환."""
    if category not in _CATEGORY_META:
        raise HTTPException(status_code=404, detail="category not found")
    entry = _CACHE.get(category)
    if entry is None:
        raise HTTPException(status_code=404, detail="sample not loaded")
    return PlainTextResponse(
        content=entry["text"],
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{category}/download")
async def download_sample(category: str) -> Response:
    """attachment 다운로드. browser 가 파일로 저장."""
    if category not in _CATEGORY_META:
        raise HTTPException(status_code=404, detail="category not found")
    entry = _CACHE.get(category)
    if entry is None:
        raise HTTPException(status_code=404, detail="sample not loaded")
    return Response(
        content=entry["text"],
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{category}_sop_sample.md"',
            "Cache-Control": "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )
