"""Heading path propagator — block 의 source_location.heading_path 자동 추출.

D17 (2026-05-08) 신규 — P1 step 6. GPT-5 M4 (신뢰도 게이팅) 반영.

audit Phase 0.5 진단: KRX 127 블럭 모두 heading_path = []. 필드는 schema 에
있고 search 가 소비할 준비가 됐는데, ingest 가 0 회 채움. heading boundary
부정확 (audit C9) 까지 결합되면 단순 stack push 는 잘못된 path 를 inject.

**전략 (GPT-5 M4)**:
1. heading_1/2/3 block 의 *신뢰도 점수* 계산 — 폰트크기 + bold + 번호체계.
2. score >= threshold (default 0.6) 인 heading 만 stack push.
3. score 미달 heading 은 무시 (과거 stack 유지) → false path 주입 방지.
4. 각 non-heading block 에 source_location.heading_path = stack 복사.

**사용자 절칙 *하드코딩 금지***: 키워드 enum 같은 *내용 기반 분류* 금지.
번호체계 (1./1.1/Ⅰ.) 는 *형식 식별 패턴* 으로 정규식만 사용 — 도메인 어휘 X.
"""

from __future__ import annotations

import re

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType

log = get_logger(__name__)


# 헤딩 신뢰도 임계 (env override 가능)
_DEFAULT_CONFIDENCE_THRESHOLD = 0.6

# 번호체계 패턴 — *형식* 식별만 (어휘 X). 사용자 절칙 *하드코딩 금지* 부합.
# - "1." / "1.1" / "1.1.1"
# - "Ⅰ." / "II." / "Ⅲ-1" / "Ⅲ.1"
# - "가." / "나." / "다." (한국어 차례)
# - "Chapter 1" / "제1장" / "제1절" (형식 prefix)
_NUMBERING_PATTERN = re.compile(
    r"^\s*(?:"
    r"\d+(?:\.\d+){0,3}\.?\s+"  # 1. / 1.1 / 1.2.3
    r"|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+(?:\s*[.)]|\s*-\s*\d+)\s*"  # Ⅰ. / Ⅱ) / Ⅲ-1
    r"|[IVX]+(?:\s*[.)]|\s*-\s*\d+)\s*"  # I. / II. / III-1
    r"|[가-힣]\s*[.)]\s*"  # 가. / 나)
    r"|제\s*\d+\s*[장절편]\s*"  # 제1장 / 제2절
    r"|Chapter\s+\d+\s*"  # Chapter 1 (영문)
    r"|§\s*\d+(?:\.\d+)?\s*"  # § 1 / § 1.1
    r")"
)

# 마크다운 heading 접두("#"~"######" + 공백) — 번호체계 매칭·heading_path 저장 전 제거.
# 세그멘터가 heading content 를 "### 9. 환매수수료" 형태로 저장하면 "### " 접두가 번호
# 정규식(^\s*\d) 을 막아 confidence 에서 +0.4(번호) 가 누락 → heading push 실패 →
# heading_path 미전파(propagated=0) 가 된다. 매칭 전 접두를 제거해 번호체계를 인식시킨다.
_MD_HEADING_PREFIX = re.compile(r"^#{1,6}\s*")


_HEADING_TYPES = (BlockType.HEADING_1, BlockType.HEADING_2, BlockType.HEADING_3)


def _heading_level(block_type: BlockType) -> int:
    """heading_1=1, heading_2=2, heading_3=3, 그 외 0."""
    if block_type == BlockType.HEADING_1:
        return 1
    if block_type == BlockType.HEADING_2:
        return 2
    if block_type == BlockType.HEADING_3:
        return 3
    return 0


def _compute_heading_confidence(block: BlockObject) -> float:
    """heading block 의 신뢰도 점수 (0.0~1.0).

    score 합산:
    - 폰트 크기: metadata.font_size > 본문 평균 (1.2x 이상이면 +0.3~0.4)
    - bold: metadata.is_bold (또는 properties.bold) → +0.3
    - 번호체계 매칭: 정규식 → +0.4
    - block_type=heading_* 자체 (세그멘터의 명시적 형식 분류 — 권위 있는 구조 신호) → +0.4
    - 짧은 길이 (≤40자) 보너스 → +0.2

    metadata 가 빈약한 PDF (pdfplumber path) 에선 번호체계 + heading 타입만으로도
    0.6 이상 도달 가능. score 0.6 이상이면 stack push.
    """
    if block.block_type not in _HEADING_TYPES:
        return 0.0

    score = 0.0
    meta = block.metadata or {}
    props = block.properties or {}
    content = (block.content or "").strip()
    if not content:
        return 0.0

    # 1) 폰트 크기 (metadata.font_size 또는 metadata.font_size_ratio)
    font_size = meta.get("font_size") or meta.get("font_size_ratio")
    try:
        if font_size is not None:
            fs = float(font_size)
            # font_size_ratio 면 그대로 사용, font_size 면 14pt 기준 정규화
            ratio = fs if fs <= 5.0 else (fs / 14.0)
            if ratio >= 1.4:
                score += 0.4
            elif ratio >= 1.2:
                score += 0.3
            elif ratio >= 1.0:
                score += 0.1
    except (TypeError, ValueError):
        pass

    # 2) bold
    if meta.get("is_bold") or props.get("bold") or props.get("is_bold"):
        score += 0.3

    # 3) 번호체계 (가장 보편적인 시그널). 마크다운 heading 접두("### ")는 *번호 매칭 직전에만*
    #    제거한다. 아래 5)의 길이 보너스는 원본 first_line 기준을 유지 — 접두 제거가 길이 판정
    #    (≤30자)을 바꿔 borderline heading 을 과검출하지 않도록(코드리뷰 #1).
    first_line = content.split("\n", 1)[0]
    if _NUMBERING_PATTERN.match(_MD_HEADING_PREFIX.sub("", first_line)):
        score += 0.4

    # 4) block_type=heading 자체 — *세그멘터의 명시적 형식 분류 결과* (권위 있는 구조 신호).
    #    heading_2/3(섹션)은 번호 없어도(예: "### 투자위험등급") 세그멘터가 확정했으면
    #    신뢰해 +0.4 → 짧은 제목과 합쳐 임계 통과. 단 heading_1 은 보통 *문서 제목*
    #    (document_title 과 중복)이라 +0.2 만 — 번호/폰트 없으면 push 안 돼 heading_path
    #    에 문서 제목이 섞여 section_title 이 중복("제목 > 섹션")되는 것을 막는다.
    if block.block_type in (BlockType.HEADING_2, BlockType.HEADING_3):
        score += 0.4
    else:
        score += 0.2

    # 5) 짧은 길이 보너스 (heading 은 보통 짧은 제목 — 40자 이하면 +0.2). 명시 heading
    #    타입(+0.4)과 합쳐 번호 없는 짧은 제목도 임계(0.6)를 통과시킨다. 긴 단락(오분류/
    #    본문 흡수)은 이 보너스 없이 0.4 에 머물러 push 안 됨(과검출 억제).
    if len(first_line) <= 40:
        score += 0.2

    return min(1.0, score)


def propagate_heading_paths(
    blocks: list[BlockObject],
    confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
) -> list[BlockObject]:
    """blocks 의 source_location.heading_path 를 자동 채움.

    Parameters
    ----------
    blocks : list[BlockObject]
        block_index 순서로 정렬되었다고 가정.
    confidence_threshold : float
        heading 신뢰도 임계 (default 0.6).

    Returns
    -------
    list[BlockObject]
        같은 list (제자리 수정).
    """
    if not blocks:
        return blocks

    # heading stack — level 1/2/3 별로 *현재 활성* heading content
    # stack[0] = h1 의 content, stack[1] = h2, stack[2] = h3
    stack: list[str | None] = [None, None, None]
    propagated_count = 0
    high_conf_heading_count = 0
    low_conf_heading_count = 0

    # GPT-5 phase 3 권고: 잘못 push 된 heading 의 *장거리 효과* 방어.
    # 같은 h2/h3 stack 항목이 N 블럭 이상 지속되면 자동 expire (TTL).
    # 또한 *page 전환* 시 h2/h3 stack reset (h1 은 보존 — 보통 h1 는 페이지 걸쳐 유지).
    last_page_seen: int | None = None
    h2_h3_age = 0
    _STACK_TTL = 50  # heading_2/3 가 50 블럭 이상 지속되면 reset (보수적)

    for block in blocks:
        # 페이지 전환 시 h2/h3 stack reset (h1 보존)
        try:
            cur_page = block.source_location.page_number
            if cur_page is not None and last_page_seen is not None and cur_page != last_page_seen:
                stack[1] = None  # h2 reset
                stack[2] = None  # h3 reset
                h2_h3_age = 0
            last_page_seen = cur_page
        except Exception:
            pass

        # h2/h3 TTL — 너무 오래 지속되면 reset (이전 잘못된 push 방어)
        if stack[1] or stack[2]:
            h2_h3_age += 1
            if h2_h3_age >= _STACK_TTL:
                stack[1] = None
                stack[2] = None
                h2_h3_age = 0

        # heading 처리: 신뢰도 높으면 stack 갱신
        level = _heading_level(block.block_type)
        if level > 0:
            confidence = _compute_heading_confidence(block)
            if confidence >= confidence_threshold:
                # 첫 줄만 heading 텍스트로 (audit C9 — heading 본문 흡수 대응).
                # 마크다운 접두("### ") 제거 → heading_path 가 "9. 환매수수료" 로 깨끗하게 저장.
                first_line = _MD_HEADING_PREFIX.sub(
                    "", (block.content or "").strip().split("\n", 1)[0]
                )[:120]
                if first_line:
                    stack[level - 1] = first_line
                    # 하위 level 은 reset
                    for j in range(level, 3):
                        stack[j] = None
                    if level >= 2:
                        h2_h3_age = 0  # 새 h2/h3 등장 → TTL 리셋
                high_conf_heading_count += 1
                # heading 자체의 path = 자기보다 상위 stack
                _set_heading_path(block, stack[: level - 1])
            else:
                low_conf_heading_count += 1
                # heading_path 빈 배열 유지 (회귀 0)
                _set_heading_path(block, [h for h in stack if h])
            continue

        # non-heading: 현재 stack 의 활성 항목 = heading_path
        path = [h for h in stack if h]
        if path:
            _set_heading_path(block, path)
            propagated_count += 1

    log.info(
        "heading_path_propagated",
        block_total=len(blocks),
        propagated=propagated_count,
        high_confidence_headings=high_conf_heading_count,
        low_confidence_headings=low_conf_heading_count,
        threshold=confidence_threshold,
    )
    return blocks


def _set_heading_path(block: BlockObject, path: list[str]) -> None:
    """block.source_location.heading_path = path (안전 set).

    D47 §B — None/empty 원소 필터.
    원인: stack[:level-1] slice 시 None 슬롯이 그대로 통과 → 영속화 후
    SourceLocation pydantic 검증이 다음 단계 (embed_worker 의 DB fallback) 에서
    실패 → load_blocks_from_cache 가 [] 반환 → 문서 영원히 'processing' stuck.
    """
    try:
        sl = block.source_location
        # SourceLocation 은 pydantic — heading_path 가 list[str] 타입.
        # None / 빈 문자열 / 비-str 은 모두 제외 → pydantic 검증 통과 보장.
        cleaned: list[str] = []
        for h in path or []:
            if h is None:
                continue
            s = str(h).strip()
            if s:
                cleaned.append(s)
        sl.heading_path = cleaned
    except Exception as exc:
        # 필드 부재 등 — log only
        log.debug("heading_path_set_failed", error=str(exc))
