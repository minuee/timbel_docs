"""Multi-Intent Splitter — deterministic candidate + LLM 게이트 (D22, 2026-05-08).

## 배경

GPT-5.5 자문 (2026-05-01): gemma-4-31b 의 multi-intent 인식 약함. 단일 LLM 분류
의존하면 "통신비 50000원 기록하고 알람 리스트도 보여줘" 같이 명백한 다중 발화
도 단일 intent 로 잡혀 두 번째 의도 처리 누락. multi_intent 카테고리 PASS rate
42% 직접 원인.

## D22 (2026-05-08) — over-split 결함 수정

D20 진단: KRX agent (1225300f) 04→06 UTC +63% latency. 직접 원인:
``_CONNECTIVES`` 의 ``"하고 "`` 가 *동사 어간 + 고* (정통하고, 이해하고, 응용하고)
에 substring 매칭 → user_message (혹은 plan_pending_resume 합성문) 4 분절 →
4× utterance LLM + 4× kms_rag.search dispatch + 12-step plan.

해결 (GPT-5 phase0 GO_WITH_CHANGES → v2 GO):
1. **persona/system preface strip** — 합성문 패턴 제거 후 진짜 user 텍스트만 splitter 입력.
2. **word-boundary 강화** — connective 매칭 시 양측 공백/구두점/문장경계 검사.
   substring 매치 → boundary 매치. 동사 어간 conjugation false-split 차단.
3. **max_segments cap=2 default** — env ``MULTI_INTENT_MAX_SEGMENTS`` 로 즉시 롤백.
   LLM-3 escalation (utterance_classifier 가 high-confidence 3+ intent 보고 시).
4. **identical-text collapse** — 분절 후 normalized 동일 segment 단일로 합침.

의미 판단은 모두 LLM (utterance_classifier). splitter 는 *후보 경계 제안* 만.

## 해결

deterministic splitter (코드) + LLM 분류 (utterance_classifier) ensemble.

1. deterministic 단계: persona strip + 한국어 connective 양측 boundary 매칭으로
   문장 분절 후보 제안.
2. 분절된 각 절을 utterance_classifier 에 별도로 보내 단일 분류.
3. LLM 결과의 confidence + (verb, domain) 다양성으로 multi-intent 확정 / collapse.
4. 분절이 1건이면 단일 intent 로 처리 (기존 동작).

## 사용자 메모리 정합

``feedback_pattern_over_case_enumeration`` + ``feedback_no_hardcoding_first_principle``
— 이 모듈은 *connective lexicon* 의 *위치 식별* 만 (boundary 검사). 의미 분류는
모두 LLM 수행. 동사 어간 vs 명령형 종결 휴리스틱은 *제거* — LLM 게이트 가 처리.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from src.common.logging import get_logger

log = get_logger(__name__)


# 연결 표현 — 한국어 발화에서 *별도 행위* 를 잇는 연결어.
# 분절은 *의미* 가 아니라 *문장 구조* 결정 — 각 절의 의도 분류는 LLM.
# D22: trailing 공백/개행은 boundary 검사로 대체 — 순수 token 형태로 보관.
#
# 두 카테고리 분리 (GPT-5 phase1 사후 verdict — separator handling 보정):
# - VERB_ENDING: 동사 종결형 (하고/해주고/해주시고) — left 절에 결합해야 의미 보존.
# - SEPARATOR: 순수 separator (그리고/후에/다음에/다음으로/또/또한/같이) —
#   left 절에 붙이지 않음. 분절 경계로만 사용.
_CONNECTIVES_VERB_ENDING = (
    "하고",
    "해주고",
    "해주시고",
)
_CONNECTIVES_SEPARATOR = (
    "그리고",
    "후에",
    "다음에",
    "다음으로",
    "또",
    "또한",
    "같이",
)
_CONNECTIVES_RAW = _CONNECTIVES_VERB_ENDING + _CONNECTIVES_SEPARATOR

# 명령형 종결 + 연결 (예: "해줘 그리고") — 토큰 시퀀스. 좌측 boundary 무시.
_CONNECTIVES_PHRASES = (
    "해줘 그리고",
    "해줘. 그리고",
    "해줘, 그리고",
    "해주세요 그리고",
    "해주세요. 그리고",
    "도 그리고",
)


def _max_segments() -> int:
    """env override 로 즉시 롤백 가능. default 2 — D22 cap.

    GPT-5 phase0 v2 verdict: env 노출 필수 (하드코딩 금지).
    LLM-3 escalation 은 utterance_classifier 가 high-confidence 시 처리.
    """
    try:
        return max(1, int(os.environ.get("MULTI_INTENT_MAX_SEGMENTS", "2")))
    except (TypeError, ValueError):
        return 2


# 분절 후 각 절의 *최소* 길이 (너무 짧은 fragment 는 노이즈).
_MIN_SEGMENT_LEN = 4


# Persona / system preface 마커 — engine.py:1497 plan_pending_resume 합성문 +
# agent persona 텍스트 패턴. 마커 발견 시 *마지막 사용자 답변 부분* 만 추출.
_PERSONA_MARKERS = (
    "사용자 답변:",
    "원래 발화:",
    "어시스턴트 질문:",
    "[페르소나]",
    "[추가 지시]",
    "[system]",
    "User:",
    "Assistant:",
)


@dataclass
class Segment:
    """분절 결과 한 절."""

    text: str
    span: tuple[int, int]  # 원본 문자열 내 (start, end) — 디버깅용


def _normalize(s: str) -> str:
    """공백 정규화 (\\n → 공백, multiple → single)."""
    if not s:
        return ""
    s = s.replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_persona_preface(utterance: str) -> tuple[str, bool]:
    """D22 — 합성문/페르소나 preface 를 제거하고 *진짜 user 텍스트* 만 반환.

    engine.py:1497 plan_pending_resume 합성문 ("원래 발화: ... 사용자 답변: ...")
    + agent persona 텍스트 패턴 ("[페르소나]\\n...") 을 입력으로 받아도
    splitter 가 user 발화만 보도록 strip.

    전략:
    - "사용자 답변:" 마커가 있으면 그 이후 텍스트만 사용 (합성문 패턴).
    - 다른 marker 가 있으면 *마지막 marker 이후* 텍스트 사용 (보수).
    - marker 미발견 + 빈 줄로 구분된 다단 텍스트면 *마지막 빈 줄 이후* 사용.
    - 위 전부 미적용 시 입력 그대로 반환.

    Returns: (stripped_text, was_stripped)
    """
    if not utterance:
        return utterance, False

    # 1) 가장 명확한 "사용자 답변:" 마커 — engine.py 합성문 패턴
    idx = utterance.rfind("사용자 답변:")
    if idx >= 0:
        after = utterance[idx + len("사용자 답변:"):].strip()
        if after:
            return after, True

    # 1b) "User:" 마지막 블록 — Assistant 마지막보다 우선 (GPT-5 phase1 verdict).
    user_idx = utterance.rfind("User:")
    if user_idx >= 0:
        after = utterance[user_idx + len("User:"):].strip()
        # User: 이후 다음 "Assistant:" 까지만 추출 (multi-turn 합성문)
        next_assistant = after.find("Assistant:")
        if next_assistant >= 0:
            after = after[:next_assistant].strip()
        if after:
            return after, True

    # 2) 다른 marker — 마지막 발견 위치 이후 사용 (보수)
    last_marker_end = -1
    last_marker = ""
    for marker in _PERSONA_MARKERS:
        if marker in ("사용자 답변:", "User:"):
            continue
        # Assistant: 마커는 user 발화 가능성 낮음 — strip 의 종결 신호로만 활용.
        if marker == "Assistant:":
            continue
        i = utterance.rfind(marker)
        if i > last_marker_end:
            last_marker_end = i + len(marker)
            last_marker = marker
    if last_marker_end >= 0:
        after = utterance[last_marker_end:].strip()
        # marker 다음 줄로 시작되는 경우 첫 줄만 (persona 본문 차단)
        # — "[페르소나]\n금융 제도에 정통하고..." 같은 경우 그 본문은 user 가 아님.
        # 보수: marker 이후 *빈 줄* 까지만 사용. 빈 줄 없으면 marker 이후 fully strip.
        if after:
            # marker 가 [페르소나]/[추가 지시]/[system] 류 — *제거* (블록 자체가 system).
            if last_marker.startswith("[") and last_marker.endswith("]"):
                # 블록 본문은 user 가 아님 — 다음 빈 줄까지 skip 후 fallback.
                lines = after.split("\n")
                # 첫 빈 줄 까지를 system 본문 으로 간주 → 그 이후 사용
                bound = -1
                for li, ln in enumerate(lines):
                    if not ln.strip():
                        bound = li
                        break
                if bound >= 0 and bound + 1 < len(lines):
                    rest = "\n".join(lines[bound + 1:]).strip()
                    if rest:
                        return rest, True
                # 다음 블록 없음 — system 본문만 있는 경우 — 빈 문자열 반환 회피.
                # 이 경우 입력에 user 텍스트 자체가 없는 비정상 — 원본 유지.
                return utterance, False
            # User: / Assistant: 류 — marker 이후 텍스트 자체가 답변
            return after, True

    # 3) marker 미발견 + 빈 줄 다단 텍스트
    if "\n\n" in utterance:
        parts = utterance.split("\n\n")
        last = parts[-1].strip()
        if last and last != utterance.strip():
            return last, True

    return utterance, False


def _is_boundary_left(text: str, idx: int) -> bool:
    """connective 매칭 시 좌측 boundary 검사.

    문장 시작 / 공백 / 구두점 직후 면 boundary. 동사 어간 conjugation
    (예: "정통하고", "이해하고") 의 "하고" 는 *어간 음절* 직후라 boundary X.
    """
    if idx <= 0:
        return True
    prev = text[idx - 1]
    return prev in " \t\n.,!?;:()\"'‘’“”"


def _is_boundary_right(text: str, end_idx: int) -> bool:
    """connective 매칭 후 우측 boundary 검사. 끝 / 공백 / 구두점."""
    if end_idx >= len(text):
        return True
    nxt = text[end_idx]
    return nxt in " \t\n.,!?;:()\"'‘’“”"


def _find_next_connective(
    text: str,
    *,
    start: int,
) -> tuple[int, int, str]:
    """첫 boundary-valid connective 위치 반환.

    Returns: (match_start, match_end, matched_token). 미발견 시 (-1, -1, "").
    """
    best_start = -1
    best_end = -1
    best_token = ""

    # 길이 우선 (긴 phrase 먼저). 양측 boundary 통과 시만 채택.
    candidates: list[str] = list(_CONNECTIVES_PHRASES) + list(_CONNECTIVES_RAW)
    candidates.sort(key=len, reverse=True)

    for tok in candidates:
        i = start
        while True:
            j = text.find(tok, i)
            if j < 0:
                break
            j_end = j + len(tok)
            # phrase 인 경우 *좌측 boundary* 는 강제하지 않음 — 명령형 종결 직후
            # 이미 boundary 가 자연스러움. 단어 token 인 경우 양측 검사.
            phrase = tok in _CONNECTIVES_PHRASES
            left_ok = True if phrase else _is_boundary_left(text, j)
            right_ok = _is_boundary_right(text, j_end)
            if left_ok and right_ok:
                if best_start < 0 or j < best_start:
                    best_start = j
                    best_end = j_end
                    best_token = tok
                break  # 더 이른 위치 찾았음 — 다음 candidate 비교
            i = j + 1
    return best_start, best_end, best_token


def split_utterance(utterance: str) -> list[Segment]:
    """발화를 절 단위로 분절. 단일이면 길이 1 list 반환.

    D22 변경: persona strip + word-boundary 강화 + max_segments cap (env) +
    identical collapse. 의미 판단은 utterance_classifier LLM 책임 — splitter 는
    *후보 경계 제안* 까지만.
    """
    if not utterance:
        return [Segment(text="", span=(0, 0))]

    # D22 §1A — persona/system preface strip.
    stripped, was_stripped = _strip_persona_preface(utterance)
    if was_stripped:
        log.info(
            "splitter_strip_applied",
            original_len=len(utterance),
            stripped_len=len(stripped),
        )

    norm = _normalize(stripped)
    if len(norm) < _MIN_SEGMENT_LEN * 2:
        return [Segment(text=norm, span=(0, len(norm)))]

    max_segs = _max_segments()

    segments: list[Segment] = []
    cursor = 0  # in norm

    # max_segs - 1 개 connective 까지만 매칭 — 마지막 절은 잔여 텍스트.
    while len(segments) < max_segs - 1:
        ms, me, tok = _find_next_connective(norm, start=cursor)
        if ms < 0:
            break
        # connective 앞에 *충분한 길이* 의 절 있어야 함
        left_text = norm[cursor:ms].strip()
        if len(left_text) < _MIN_SEGMENT_LEN:
            # 너무 짧음 — 매칭 무시하고 더 뒤에서 검색
            cursor = me
            continue

        # GPT-5 phase1 사후 verdict — separator handling 보정.
        # 1) verb-ending (하고/해주고/해주시고) — 동사 종결이 left 의 의미. 결합.
        # 2) separator (그리고/또/또한/같이/후에/다음에/다음으로) — left 에 붙이지 않음.
        #    분절 경계로만 사용. left_text 만 segment.
        # 3) phrase (해줘 그리고 등) — 첫 단어 (해줘/해주세요/도) 만 left 에 결합.
        if tok in _CONNECTIVES_VERB_ENDING:
            # 동사 종결 — left 절의 *의미적 끝* — 공백 한 칸 후 결합 (자연스러움).
            # 단 left_text 의 마지막 글자가 한국어 음절이면 공백 X (예: "기록" + "하고").
            # 음절 직후 공백을 넣으면 "기록 하고" 로 부자연 — 그대로 붙임.
            seg_text = (left_text + tok).strip()
            # span end = connective end — text/span 정합.
            seg_span_end = me
        elif tok in _CONNECTIVES_SEPARATOR:
            # 순수 separator — left 절에 결합 X. left_text 그대로 segment.
            seg_text = left_text
            # span end = ms (left 절의 끝). connective 자체는 segment 에 포함 X.
            seg_span_end = ms
        else:
            # phrase (해줘 그리고 등) — 첫 단어 (해줘/해주세요/도) 만 left 에 결합.
            first_word = tok.split()[0].rstrip(".,")
            if first_word:
                seg_text = (left_text + " " + first_word).strip()
                seg_span_end = ms + len(first_word)
            else:
                seg_text = left_text
                seg_span_end = ms
        segments.append(Segment(
            text=seg_text,
            span=(cursor, seg_span_end),
        ))
        cursor = me
        # 연속 공백/구두점 skip
        while cursor < len(norm) and norm[cursor] in " \t.,":
            cursor += 1

    # 마지막 절 (잔여)
    # GPT-5 phase1 사후 verdict — final span 정합. text 가 strip 된 만큼
    # span 도 leading whitespace skip + trailing whitespace 제외해 정합.
    final_raw = norm[cursor:]
    final = final_raw.strip()
    if len(final) >= _MIN_SEGMENT_LEN:
        # final 의 norm 내 시작/끝 위치 계산 (whitespace 제외).
        leading_ws = len(final_raw) - len(final_raw.lstrip())
        trailing_ws = len(final_raw) - len(final_raw.rstrip())
        final_start = cursor + leading_ws
        final_end = len(norm) - trailing_ws
        segments.append(Segment(
            text=final,
            span=(final_start, final_end),
        ))
    elif segments and final:
        # 너무 짧은 마지막 — 직전 절에 합침
        last = segments[-1]
        segments[-1] = Segment(
            text=(last.text + " " + final).strip(),
            span=(last.span[0], last.span[1] + len(final) + 1),
        )

    if not segments:
        segments = [Segment(text=norm, span=(0, len(norm)))]

    # D22 §1A — identical-text collapse (normalized 동일 segment 합침).
    if len(segments) >= 2:
        unique_norms: list[str] = []
        unique_segs: list[Segment] = []
        for s in segments:
            n = _normalize(s.text).lower()
            if n not in unique_norms:
                unique_norms.append(n)
                unique_segs.append(s)
        if len(unique_segs) < len(segments):
            log.info(
                "splitter_identical_collapsed",
                before=len(segments),
                after=len(unique_segs),
            )
            segments = unique_segs

    # GPT-5 phase1 verdict — PII 로그 마스킹. 원문 텍스트 leak 차단.
    # 길이 + sha1 8자 hash 만 노출 (디버그 가능성 유지).
    import hashlib as _hashlib
    log.debug(
        "multi_intent_split",
        original_len=len(norm),
        segment_count=len(segments),
        max_segments=max_segs,
        segment_lens=[len(s.text) for s in segments],
        segment_hashes=[
            _hashlib.sha1(s.text.encode("utf-8", errors="replace")).hexdigest()[:8]
            for s in segments
        ],
    )
    return segments
