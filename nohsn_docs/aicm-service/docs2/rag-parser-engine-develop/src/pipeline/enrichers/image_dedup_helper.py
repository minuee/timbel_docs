"""이미지 dedup helper — vision LLM 호출 cost 절감 *전용*.

같은 PDF 안에서 같은 위치 (bbox) + 같은 이미지 bytes (md5) 인 image block 을
그룹핑해서, 그룹당 vision LLM 호출 1 회만 발생하도록 한다. 결과 (description /
image_type / is_decorative / caption / summary / ocr_text / ...) 를 그룹 전체에
broadcast 한다.

**중요 (사용자 절칙)**:
- *제외 결정 X* — dedup 은 LLM 호출 cost 절감자 *전용*. 노이즈 결정은
  noise_filter 에서 LLM 의 is_decorative 판단으로만 발생.
- bbox 라운딩만으론 false positive 위험 (같은 위치 다른 콘텐츠) → image
  bytes md5 일치 필수. 미스매치면 그룹 분리해서 각자 LLM 호출.
- image_index / page_number / bbox 는 *각자 보존*. metadata 의 분석 결과
  필드만 broadcast.

D17 (2026-05-08) 신규 — GPT-5 G2 반영.
"""

from __future__ import annotations

import hashlib

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType

log = get_logger(__name__)


# broadcast 대상 metadata 필드 (image_index / page_number / bbox 제외)
_BROADCAST_META_FIELDS: frozenset[str] = frozenset({
    "image_type",
    "is_decorative",
    "should_index",
    "decorative_rationale",
    "caption",
    "summary",
    "ocr_text",
    "visible_entities",
    "relation_to_neighbor",
})

_BBOX_ROUND_PX = 1
_SIZE_BUCKET_PX = 8  # 너비/높이를 8px 버킷으로 양자화 (PDF crop 변동 흡수)


def _compute_bbox_signature(block: BlockObject) -> tuple | None:
    """bbox + 크기 버킷 signature. 위치·크기가 비슷한 image 식별."""
    try:
        sl = block.source_location
        bbox = getattr(sl, "bbox", None) or []
        if not bbox or len(bbox) < 4:
            return None
        x0, y0, x1, y1 = bbox[:4]
        w = max(0.0, x1 - x0)
        h = max(0.0, y1 - y0)
        return (
            round(float(x0), _BBOX_ROUND_PX),
            round(float(y0), _BBOX_ROUND_PX),
            round(float(x1), _BBOX_ROUND_PX),
            round(float(y1), _BBOX_ROUND_PX),
            int(w / _SIZE_BUCKET_PX),
            int(h / _SIZE_BUCKET_PX),
        )
    except Exception:
        return None


def _compute_image_md5(image_path: str) -> str | None:
    """image bytes 의 md5. dedup signature 검증용 (false positive 방어)."""
    try:
        with open(image_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()  # noqa: S324 (non-security use)
    except Exception as exc:
        log.debug("image_md5_failed", path=image_path, error=str(exc))
        return None


async def dedup_image_calls(
    blocks: list[BlockObject],
    describer,
    document_title: str = "",
) -> list[BlockObject]:
    """image block 의 vision LLM 호출을 dedup 으로 효율화.

    절차:
    1. IMAGE block 만 추출.
    2. (bbox signature, image_md5) 쌍으로 그룹핑. md5 미스매치면 같은 bbox
       라도 그룹 분리 (false positive 방어).
    3. 그룹별 *대표 1장* 만 describer.describe_blocks 호출.
    4. 그룹 내 다른 image block 들에 분석 결과 메타 broadcast.

    Parameters
    ----------
    blocks : list[BlockObject]
        전체 block 목록 (IMAGE 외 타입 그대로 통과).
    describer : ImageDescriber
        실제 vision LLM 호출 객체. describe_blocks(blocks, document_title) 시그니처.
    document_title : str
        vision prompt 컨텍스트.

    Returns
    -------
    list[BlockObject]
        분석된 block 목록 (제자리 수정 + 동일 list 반환).
    """
    image_blocks = [b for b in blocks if b.block_type == BlockType.IMAGE and b.image_path]
    if not image_blocks:
        return blocks

    # 그룹핑: key = (bbox_signature, image_md5)
    groups: dict[tuple, list[BlockObject]] = {}
    for b in image_blocks:
        sig = _compute_bbox_signature(b)
        md5 = _compute_image_md5(b.image_path) if b.image_path else None
        if sig is None or md5 is None:
            # signature 없으면 단독 그룹 (자기 자신 LLM 호출)
            key = ("solo", str(b.id))
        else:
            key = (sig, md5)
        groups.setdefault(key, []).append(b)

    log.info(
        "image_dedup_grouped",
        image_total=len(image_blocks),
        group_count=len(groups),
        savings=len(image_blocks) - len(groups),
    )

    # 그룹 정보를 dedup metadata 에 미리 저장 (broadcast 와 무관 — 진단·DB 검증용)
    for key, group in groups.items():
        rep = group[0]
        for b in group:
            b.metadata["dedup_signature_count"] = len(group)
            b.metadata["dedup_representative_block_id"] = str(rep.id)

    # 그룹별 대표 1장만 LLM 호출 (private _analyze_image 직접 호출 — describe_blocks
    # 의 batch 루프와 skip 조건을 우회. blocks list 안에 대표 위치를 찾아 컨텍스트 inject).
    broadcast_count = 0
    for key, group in groups.items():
        rep = group[0]
        # 이미 분석된 경우 skip (재처리 안전)
        if rep.image_description and rep.metadata.get("is_decorative") is not None:
            # 이미 분석됨 → 그래도 group 내 다른 멤버에게 broadcast
            pass
        else:
            # 컨텍스트 빌드 + LLM 호출
            try:
                idx = blocks.index(rep)
            except ValueError:
                idx = 0
            context = describer._build_context(blocks, idx, document_title)
            try:
                analysis = await describer._analyze_image(rep.image_path, context)
                describer._apply_analysis(rep, analysis)
            except Exception as exc:
                log.warning(
                    "image_dedup_rep_analyze_failed",
                    block_id=str(rep.id),
                    error=str(exc),
                )
                continue

        # broadcast: 대표 결과를 그룹 멤버에 복사 (단독 그룹은 skip)
        if len(group) <= 1:
            continue
        rep_meta = rep.metadata or {}
        for b in group[1:]:
            b.image_description = rep.image_description
            if rep.ocr_text and not b.ocr_text:
                b.ocr_text = rep.ocr_text
            # broadcast 필드만 복사
            for field in _BROADCAST_META_FIELDS:
                if field in rep_meta:
                    b.metadata[field] = rep_meta[field]
            # content 재구성 (대표와 동일하게)
            b.content = rep.content
            b.compute_hash()
            broadcast_count += 1

    log.info(
        "image_dedup_broadcast_complete",
        groups=len(groups),
        broadcast_members=broadcast_count,
    )
    return blocks
