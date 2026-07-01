"""PR-Z11A — 미러링된 이메일 LLM 분류기.

원칙 (자비스 패턴 / feedback_llm_driven_everywhere):
- rule/regex/키워드 리스트 *금지*. 단일 LLM 호출로 content + sender domain
  상관관계 + header trust 를 통합 판단.
- 카테고리 enum 강제 X — Gemma 가 자유 어휘로 답해도 ``_normalize_category``
  가 가까운 카테고리로 매핑.
- HTML-only 메일 (실 검증 케이스 — AliExpress / Synology) 처리: body_text 가
  비면 body_html → BeautifulSoup → text 변환 후 prompt 에 inject.
- LLM 미주입/실패/JSON 파싱 실패 시 graceful fallback: ``category="uncertain"``,
  ``trust_score=0.5``, ``reason="(LLM 분류 실패)"``.

분류 결과는 ``email_processing_log.classification`` 컬럼 (JSONB) 에 그대로 저장.
액션 호출 (schedule.create / todo / reminder) 은 *여기서 X* — 사용자 confirm
단계에서 frontend 가 호출. 분류기는 *분류 + entities 추출* 만.

테스트: ``tests/integration/mail/test_classifier.py``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.common.llm.base import LLMRequest, LLMTask
from src.common.logging import get_logger

log = get_logger(__name__)


# KST = UTC+9 (Korea Standard Time). zoneinfo 가 없는 환경 대비 고정 offset.
_KST = timezone(timedelta(hours=9))


def _now_kst() -> datetime:
    """현재 KST 시각 — testing 시 monkeypatch 가능 hook."""
    return datetime.now(_KST)


# ---------------------------------------------------------------------------
# 카테고리 — *가이드용* enum. LLM 자유 어휘 답을 _normalize_category 가 매핑.
# ---------------------------------------------------------------------------

CATEGORY_GUIDE: dict[str, str] = {
    "meeting_request": "응답 필요한 미팅 제안 — 일정 조율 / 참석 확인 요청",
    "work_directive": "업무 지시·할일 — 마감일 있는 task 부여",
    "conference_info": "컨퍼런스·웨비나·세미나 안내 (참석 결정 필요한 비-광고 정보)",
    "advertisement": "광고·프로모션·마케팅 (B2C/B2B 모두 포함)",
    "newsletter": "뉴스레터·구독 정기 발송 — 정보 전달 목적",
    "personal": "개인 메일 — 친구·가족·1:1 사적 대화",
    "billing": "결제·청구·영수증·세금계산서·이용 명세",
    "notification": "시스템 알림 — 비밀번호 재설정·로그인 알림·서비스 공지",
    "uncertain": "분류 불가 — reason 필드 필수",
}

_CATEGORY_KEYS: set[str] = set(CATEGORY_GUIDE.keys())


def _normalize_category(raw: str | None) -> str:
    """LLM 자유 어휘 답 → guide enum 매핑.

    - exact match (대소문자 무시) 우선
    - 공통 어휘 변형 (meeting / mtg / 미팅 / 회의 / 일정) 패턴
    - fallback: ``uncertain``
    """
    if not raw:
        return "uncertain"
    s = str(raw).strip().lower().replace(" ", "_").replace("-", "_")

    # exact / 부분 일치
    if s in _CATEGORY_KEYS:
        return s
    for key in _CATEGORY_KEYS:
        if key in s or s in key:
            return key

    # 한국어/영어 의미 매핑 — *예시 enum* 가이드용. 새 어휘는 LLM prompt 보강으로 흡수.
    semantic_groups: dict[str, tuple[str, ...]] = {
        "meeting_request": ("meeting", "mtg", "미팅", "회의", "일정요청", "schedule_request", "calendar_invite", "invite"),
        "work_directive": ("task", "todo", "할일", "지시", "directive", "assignment", "업무"),
        "conference_info": ("conference", "webinar", "seminar", "컨퍼런스", "세미나", "웨비나", "event"),
        "advertisement": ("ad", "promo", "promotion", "광고", "프로모션", "sale", "할인", "marketing"),
        "newsletter": ("newsletter", "digest", "subscription", "뉴스레터", "구독"),
        "personal": ("personal", "private", "개인"),
        "billing": ("invoice", "receipt", "billing", "payment", "결제", "청구", "영수증", "세금계산서"),
        "notification": ("notification", "alert", "notice", "알림", "공지", "verification", "otp", "password_reset"),
    }
    for key, tokens in semantic_groups.items():
        if any(tok in s for tok in tokens):
            return key

    return "uncertain"


# ---------------------------------------------------------------------------
# Body extraction helper — HTML-only fallback
# ---------------------------------------------------------------------------


def _html_to_text(html: str) -> str:
    """HTML → text. BeautifulSoup4 가 deps 에 있음 (pyproject.toml).
    실패 시 stdlib html.parser fallback (alpha 환경 대비).
    """
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # script / style 제거 (의미 없는 토큰 다량 — LLM 토큰 낭비)
        for tag in soup(["script", "style", "noscript"]):
            tag.extract()
        text = soup.get_text(separator="\n")
        # 공백/연속 개행 정리
        lines = [ln.strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln)
    except Exception as e:  # noqa: BLE001
        log.debug("bs4_html_parse_failed_fallback_stdlib", error=str(e))
        # stdlib fallback — 매우 단순한 태그 stripping
        try:
            from html.parser import HTMLParser

            class _Stripper(HTMLParser):
                def __init__(self) -> None:
                    super().__init__()
                    self.parts: list[str] = []
                    self._skip_depth = 0

                def handle_starttag(self, tag: str, attrs: Any) -> None:
                    if tag.lower() in {"script", "style", "noscript"}:
                        self._skip_depth += 1

                def handle_endtag(self, tag: str) -> None:
                    if tag.lower() in {"script", "style", "noscript"} and self._skip_depth > 0:
                        self._skip_depth -= 1

                def handle_data(self, data: str) -> None:
                    if self._skip_depth == 0 and data.strip():
                        self.parts.append(data.strip())

            sp = _Stripper()
            sp.feed(html)
            return "\n".join(sp.parts)
        except Exception:  # noqa: BLE001
            return html  # 최후 — raw 그대로


# ---------------------------------------------------------------------------
# ISO summary builder — frontend 목록용 한 줄 표기
# ---------------------------------------------------------------------------


def _format_iso_human(iso: str) -> str:
    """LLM 이 박은 ISO 문자열을 사람이 읽기 쉽게 — 'YYYY-MM-DD HH:MM' / 'YYYY-MM-DD'.

    timezone offset (+09:00) 은 별도로 ' KST' 라벨을 뒤에 붙이므로 여기선 제거.
    파싱 실패 시 입력 그대로 반환 (정보 손실 방지).
    """
    s = (iso or "").strip()
    if not s:
        return ""
    # date-only ('YYYY-MM-DD') — 그대로 반환
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    # ISO 8601 datetime — 다양한 형태 허용 ('Z', '+09:00', 무 offset, 's' 유무).
    candidate = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # 'YYYY-MM-DDTHH:MM' 같은 짧은 형태도 허용
        try:
            dt = datetime.strptime(candidate[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            return s
    # KST 변환 — 입력에 tz 가 있으면 KST 로 환산, 없으면 그대로 (KST 가정).
    if dt.tzinfo is not None:
        dt = dt.astimezone(_KST)
    return dt.strftime("%Y-%m-%d %H:%M")


def _build_iso_summary(entities: dict[str, Any]) -> str:
    """frontend 목록용 한 줄 요약 — '(YYYY-MM-DD HH:MM KST, 장소)'.

    우선순위:
    1. datetime_iso 가 있으면 시각 + 'KST' + 장소 결합.
    2. 없으면 events[0].when_iso 시도.
    3. 둘 다 없으면 subject_summary 그대로.
    4. recurrence 가 있으면 시각 뒤에 '(매주 화요일)' 처럼 부기.
    """
    dt_iso = str(entities.get("datetime_iso") or "").strip()
    if not dt_iso:
        events = entities.get("events") or []
        if isinstance(events, list) and events:
            first = events[0]
            if isinstance(first, dict):
                dt_iso = str(first.get("when_iso") or "").strip()

    location = str(entities.get("location") or "").strip()
    recurrence = str(entities.get("recurrence") or "").strip()

    if not dt_iso:
        # 시각 정보가 전혀 없으면 subject_summary 그대로 (frontend 가 빈 문자열 → fallback).
        return str(entities.get("subject_summary") or "").strip()

    human = _format_iso_human(dt_iso)
    parts: list[str] = []
    if human:
        # date-only 면 'KST' 라벨 생략 (시간이 없으니 무의미).
        if len(human) == 10:
            parts.append(human)
        else:
            parts.append(f"{human} KST")
    if location:
        parts.append(location)
    summary = ", ".join(parts)
    if recurrence:
        summary = f"{summary} ({recurrence})" if summary else f"({recurrence})"
    return f"({summary})" if summary else ""


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


@dataclass
class ClassificationResult:
    """LLM 분류 결과 — JSONB 로 저장될 dict 변환용 데이터 클래스."""

    category: str
    subcategory_reason: str
    trust_score: float
    trust_factors: list[str]
    priority: str
    extracted_entities: dict[str, Any]
    needs_user_attention: bool
    needs_meeting_prep: bool
    raw_llm_text: str | None = None  # 디버깅용 원문 — 옵션

    def to_dict(self) -> dict[str, Any]:
        d = {
            "category": self.category,
            "subcategory_reason": self.subcategory_reason,
            "trust_score": self.trust_score,
            "trust_factors": self.trust_factors,
            "priority": self.priority,
            "extracted_entities": self.extracted_entities,
            "needs_user_attention": self.needs_user_attention,
            "needs_meeting_prep": self.needs_meeting_prep,
        }
        if self.raw_llm_text is not None:
            d["_raw_llm"] = self.raw_llm_text[:1000]
        return d


_PROMPT_TEMPLATE = """당신은 사용자의 받은편지함을 분류하는 비서다.

아래 이메일을 읽고 *JSON 한 객체* 만 반환한다 (그 외 텍스트 금지).

[기준 시각 — datetime 정규화에 반드시 사용]
- now_kst = {now_kst}  (오늘 = {today_kst}, 요일 = {weekday_kst})
- 모든 datetime 은 한국 표준시 (KST, UTC+09:00) 기준으로 해석한다.
- 메일에 timezone 이 명시 (예: PST/EST/UTC) 되어 있으면 KST 로 변환한 값을 넣는다.

판단 기준 (절대 키워드 단순 매칭 금지 — 종합 판단):
- 발신자 도메인 신뢰도: 알려진 SaaS·금융기관·정부 도메인은 trust 높음.
  발신 display_name 과 from_address 도메인이 어긋나면 trust 낮춤.
- 본인이 to 에 있는지 vs mass cc/bcc 인지 — mass 면 newsletter/advertisement 가능성.
- List-Unsubscribe 헤더가 있으면 newsletter / advertisement 강한 신호.
- DKIM/SPF 결과가 fail 이면 trust 낮춤.
- subject 와 body 의 의도 일치 — 어긋나면 trust 낮춤.
- "응답 필요한 미팅 제안" 은 본문에 *날짜/시간/장소 후보* + 본인의 응답 요청이 모두 있을 때.
  단순 컨퍼런스 안내는 conference_info.
- 사용자가 *받는 사람* 인 청구서는 billing — 광고성 결제 유도는 advertisement.

[Datetime 정규화 규칙 — 매우 엄격히 준수]
1. 출력 ISO 8601 포맷: "YYYY-MM-DDTHH:MM:SS+09:00" (초가 없으면 :00, KST offset 필수).
2. 본문에 *날짜만 있고 시간 표기가 전혀 없을 때*:
   - datetime_iso 는 빈 문자열 "" (시간 추측 금지).
   - 단, 컨퍼런스/웨비나처럼 "종일 행사" 가 명백한 경우만 "YYYY-MM-DD" (date-only) 로.
3. 상대 표현은 now_kst 를 기준으로 해석:
   - "오늘", "내일", "모레", "다음주 화요일", "이번 주 금요일", "다음 달 첫째 주" 등.
   - "다음주" = 이번주 다음 월~일. "이번 주 X요일" = 이번 주 X요일 (지났으면 다음 주 X요일).
4. 한글 시각 표기 정규화:
   - "오전" = 0~12, "오후" = 12~23. "오후 두시" = 14:00. "오후 12시" = 12:00. "오전 12시" = 00:00.
   - "정오" = 12:00. "자정" = 00:00. "한낮" = 12:00.
   - "X시 반" = X:30. "X시 X분" 그대로. "X시 정각" = X:00.
   - 한자/한글 숫자: "두시" = 2시, "세시" = 3시 ... "열시" = 10시, "열한시" = 11시, "열두시" = 12시.
5. 반복 표현 (recurrence):
   - "매주 화요일", "매월 첫째 주 금요일", "매일 오전 9시" 등 → recurrence 필드에 RRULE 또는 자유 텍스트 명시.
   - 예: "FREQ=WEEKLY;BYDAY=TU" 또는 "매주 화요일 14:00 KST".
   - 첫 발생일 (가장 가까운 미래) 은 datetime_iso 에도 함께.
6. 다중 이벤트 (events 배열):
   - 한 메일에 *발표일·등록 마감일·사전 점검일* 같은 둘 이상의 datetime 이 있으면 events 배열에 모두 담는다.
   - kind 후보 (소문자 영문): "event" (행사 본 일정), "deadline" (마감), "registration_deadline",
     "preparation" (사전 준비/리허설), "reminder", "checkin", "broadcast", "announcement".
   - 가장 핵심 일정의 datetime_iso 도 별도로 채운다 (events[0] 와 일치 가능).
   - events 가 비어있으면 [] 로.

가이드 카테고리 (자유 어휘 가능 — 가까운 의미면 OK):
{category_guide}

반환 JSON 형식 (반드시 이 키 모두):
{{
  "category": "<위 카테고리 중 하나 또는 가까운 자유 어휘>",
  "subcategory_reason": "<한 줄 — 왜 그 카테고리인지>",
  "trust_score": <0.0 ~ 1.0 float>,
  "trust_factors": ["<신뢰도에 영향 준 신호 한 줄씩>", ...],
  "priority": "<high | normal | low>",
  "extracted_entities": {{
    "datetime_iso": "<YYYY-MM-DDTHH:MM:SS+09:00 또는 YYYY-MM-DD 또는 빈 문자열>",
    "datetime_natural": "<원 표현 예: 내일 오후 3시 / 빈 문자열>",
    "deadline_iso": "<마감일이 본 일정과 다를 때만, ISO 8601 KST / 빈 문자열>",
    "recurrence": "<RRULE 또는 자유 텍스트 / 빈 문자열>",
    "events": [
      {{"kind": "<event|deadline|registration_deadline|preparation|reminder|...>",
        "when_iso": "<ISO 8601 KST>",
        "when_natural": "<원 표현>"}}
    ],
    "timezone": "Asia/Seoul",
    "location": "<장소 또는 빈 문자열 — 온라인이면 'online' 또는 URL>",
    "attendees": ["<참석자 또는 빈 배열>"],
    "action_required": "<응답 / 확인 / 무대응>",
    "subject_summary": "<한 줄 요약>"
  }},
  "needs_user_attention": <true | false — 사용자 직접 확인 필요>,
  "needs_meeting_prep": <true | false — 미팅 준비 자료 필요>
}}

이메일:
─────────────
From: {from_address}
From-Domain: {from_domain}
Display-Name: {display_name}
To: {to_address}
Subject: {subject}
Date: {date}

[Headers (key signals)]
{headers_block}

[Body]
{body}
─────────────

JSON:"""


class EmailClassifier:
    """LLM 1콜 이메일 분류기.

    ``llm`` 인자: ``LLMRouter`` 또는 ``BaseLLMClient`` 또는 stub callable.
        - ``llm.route(task=..., request=LLMRequest)`` 우선
        - ``llm.generate(LLMRequest)`` fallback
        - 둘 다 없으면 graceful uncertain fallback

    원칙: 호출 1회 — fail-soft. 분류기 실패가 KMS 저장이나 polling loop 를 막지 않음.
    """

    def __init__(self, llm: Any = None, *, max_body_chars: int = 4000) -> None:
        self.llm = llm
        self.max_body_chars = max_body_chars

    async def classify(self, fetched_email: Any) -> ClassificationResult:
        """단일 이메일 분류 — async. 항상 ClassificationResult 반환 (예외 X)."""
        prompt = self._build_prompt(fetched_email)
        try:
            raw_text = await self._invoke_llm(prompt)
        except Exception as exc:  # noqa: BLE001
            log.warning("email_classifier_llm_failed", error=str(exc))
            return self._fallback("(LLM 분류 실패: " + type(exc).__name__ + ")")

        if not raw_text:
            return self._fallback("(LLM 빈 응답)")

        parsed = self._parse_json(raw_text)
        if parsed is None:
            log.warning("email_classifier_parse_failed", raw=raw_text[:300])
            return self._fallback("(LLM JSON 파싱 실패)", raw_text=raw_text)

        return self._coerce_result(parsed, raw_text=raw_text)

    # ───────────────── prompt build ─────────────────

    def _build_prompt(self, email: Any) -> str:
        body_text = self._extract_body(email)
        if len(body_text) > self.max_body_chars:
            body_text = body_text[: self.max_body_chars] + "\n…(truncated)"

        from_addr = (getattr(email, "from_address", None) or "").strip()
        from_domain = (getattr(email, "from_domain", None) or "").strip()
        display_name = ""
        if "<" in from_addr:
            # "Name <addr@dom>" 형식
            display_name = from_addr.split("<", 1)[0].strip().strip('"')
        to_addr = getattr(email, "to_address", None) or ""
        subject = getattr(email, "subject", None) or "(제목 없음)"
        date = getattr(email, "date_iso", None) or ""

        headers = getattr(email, "headers", {}) or {}
        # 분류에 *유의미한 헤더만* — 토큰 낭비 방지.
        relevant_keys = (
            "List-Unsubscribe",
            "Authentication-Results",
            "Received-SPF",
            "DKIM-Signature",
            "X-Spam-Score",
            "X-Spam-Status",
            "Message-ID",
            "In-Reply-To",
            "Reply-To",
            "Cc",
            "Bcc",
            "Precedence",
            "X-Mailer",
        )
        header_lines: list[str] = []
        # case-insensitive lookup (서버마다 헤더 케이스 다양)
        lower_map = {k.lower(): (k, v) for k, v in headers.items()}
        for rk in relevant_keys:
            tup = lower_map.get(rk.lower())
            if tup is not None:
                _, v = tup
                v_str = str(v)[:200]  # 한 헤더 200자 cap
                header_lines.append(f"{rk}: {v_str}")
        headers_block = "\n".join(header_lines) if header_lines else "(no relevant headers)"

        category_guide_lines = "\n".join(
            f"- {k}: {v}" for k, v in CATEGORY_GUIDE.items()
        )

        # KST 기준 시각 — LLM 의 상대 표현 ("내일", "다음주 화요일") 정규화 컨텍스트.
        now_kst = _now_kst()
        weekday_ko = ("월", "화", "수", "목", "금", "토", "일")[now_kst.weekday()]

        return _PROMPT_TEMPLATE.format(
            category_guide=category_guide_lines,
            now_kst=now_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
            today_kst=now_kst.strftime("%Y-%m-%d"),
            weekday_kst=f"{weekday_ko}요일",
            from_address=from_addr or "(unknown)",
            from_domain=from_domain or "(unknown)",
            display_name=display_name or "(unknown)",
            to_address=to_addr or "(unknown)",
            subject=subject,
            date=date or "(unknown)",
            headers_block=headers_block,
            body=body_text or "(empty body)",
        )

    def _extract_body(self, email: Any) -> str:
        """body_text 우선. 비면 body_html → text 변환."""
        body_text = (getattr(email, "body_text", None) or "").strip()
        if body_text:
            return body_text
        body_html = getattr(email, "body_html", None)
        if body_html:
            return _html_to_text(body_html).strip()
        return ""

    # ───────────────── llm invoke ─────────────────

    async def _invoke_llm(self, prompt: str) -> str:
        if self.llm is None:
            raise RuntimeError("no llm injected")

        request = LLMRequest(
            prompt=prompt,
            max_tokens=600,
            temperature=0.1,  # 분류 — 결정론적 가깝게
            response_format="json",
        )

        # 1) LLMRouter style: .route(task=..., request=...)
        route = getattr(self.llm, "route", None)
        if callable(route):
            response = await route(task=LLMTask.METADATA_EXTRACTION, request=request)
            return getattr(response, "text", "") or ""

        # 2) BaseLLMClient style: .generate(request)
        generate = getattr(self.llm, "generate", None)
        if callable(generate):
            response = await generate(request)
            return getattr(response, "text", "") or ""

        # 3) plain async callable (테스트 stub)
        if callable(self.llm):
            result = await self.llm(prompt)
            if isinstance(result, str):
                return result
            return getattr(result, "text", "") or ""

        raise RuntimeError("llm has no compatible interface (route/generate/__call__)")

    # ───────────────── parse / coerce ─────────────────

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        """LLM 응답에서 JSON 객체 추출. ```json``` fence / 앞뒤 잡담 허용."""
        text = raw.strip()
        # ```json ... ``` 또는 ``` ... ``` fence 제거
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            # 첫 줄이 'json' 라벨이면 제거
            if text.lower().startswith("json\n"):
                text = text[5:]
            elif text.lower().startswith("json"):
                text = text[4:].lstrip()

        # 첫 { ~ 마지막 } 범위만 (앞뒤 잡담 컷)
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0 or end <= start:
            return None
        candidate = text[start : end + 1]
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None

    @staticmethod
    def _coerce_trust(value: Any) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.5
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v

    @staticmethod
    def _coerce_priority(value: Any) -> str:
        s = str(value or "").strip().lower()
        if s in {"high", "normal", "low"}:
            return s
        if s in {"urgent", "critical", "p0", "p1"}:
            return "high"
        if s in {"medium", "med", "p2"}:
            return "normal"
        if s in {"none", "ignore", "p3", "p4"}:
            return "low"
        return "normal"

    def _coerce_result(
        self, parsed: dict[str, Any], *, raw_text: str | None = None
    ) -> ClassificationResult:
        category = _normalize_category(parsed.get("category"))
        entities = parsed.get("extracted_entities") or {}
        if not isinstance(entities, dict):
            entities = {}

        trust_factors_raw = parsed.get("trust_factors") or []
        if not isinstance(trust_factors_raw, list):
            trust_factors_raw = [str(trust_factors_raw)]
        trust_factors = [str(x) for x in trust_factors_raw][:8]

        # events 배열 정규화 — 각 항목 dict 구조 강제. 잘못된 항목은 drop.
        events_raw = entities.get("events")
        events_out: list[dict[str, str]] = []
        if isinstance(events_raw, list):
            for ev in events_raw:
                if not isinstance(ev, dict):
                    continue
                kind = str(ev.get("kind") or "").strip().lower()[:64]
                when_iso = str(ev.get("when_iso") or "").strip()[:64]
                when_natural = str(ev.get("when_natural") or "").strip()[:200]
                if not (kind or when_iso or when_natural):
                    continue
                events_out.append(
                    {
                        "kind": kind or "event",
                        "when_iso": when_iso,
                        "when_natural": when_natural,
                    }
                )

        # entities 표준 키 보장 — 누락 시 기본값. v2: ISO/recurrence/events/deadline 추가.
        entities_out = {
            "datetime_iso": str(entities.get("datetime_iso") or ""),
            "datetime_natural": str(entities.get("datetime_natural") or ""),
            "deadline_iso": str(entities.get("deadline_iso") or ""),
            "recurrence": str(entities.get("recurrence") or ""),
            "events": events_out,
            "timezone": str(entities.get("timezone") or "Asia/Seoul"),
            "location": str(entities.get("location") or ""),
            "attendees": (
                [str(a) for a in entities.get("attendees", [])]
                if isinstance(entities.get("attendees"), list)
                else []
            ),
            "action_required": str(entities.get("action_required") or "확인"),
            "subject_summary": str(entities.get("subject_summary") or ""),
        }
        # frontend 목록용 요약 — "(2026-04-29 15:00 KST, 온라인 웨비나)" 형식.
        entities_out["entity_summary_iso"] = _build_iso_summary(entities_out)

        return ClassificationResult(
            category=category,
            subcategory_reason=str(parsed.get("subcategory_reason") or "")[:500],
            trust_score=self._coerce_trust(parsed.get("trust_score")),
            trust_factors=trust_factors,
            priority=self._coerce_priority(parsed.get("priority")),
            extracted_entities=entities_out,
            needs_user_attention=bool(parsed.get("needs_user_attention", False)),
            needs_meeting_prep=bool(parsed.get("needs_meeting_prep", False)),
            raw_llm_text=raw_text,
        )

    @staticmethod
    def _fallback(reason: str, *, raw_text: str | None = None) -> ClassificationResult:
        return ClassificationResult(
            category="uncertain",
            subcategory_reason=reason,
            trust_score=0.5,
            trust_factors=[reason],
            priority="normal",
            extracted_entities={
                "datetime_iso": "",
                "datetime_natural": "",
                "deadline_iso": "",
                "recurrence": "",
                "events": [],
                "timezone": "Asia/Seoul",
                "location": "",
                "attendees": [],
                "action_required": "확인",
                "subject_summary": "",
                "entity_summary_iso": "",
            },
            needs_user_attention=True,  # 분류 실패 시 사용자가 직접 확인하도록
            needs_meeting_prep=False,
            raw_llm_text=raw_text,
        )
