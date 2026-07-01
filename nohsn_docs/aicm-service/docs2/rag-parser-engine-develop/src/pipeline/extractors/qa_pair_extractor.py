"""Q&A pair extractor — 문서 본문에서 질문-답변 쌍 추출 (LLM 기반).

rule/regex 사용 절대 금지. LLM 정밀 prompt 로 일반화 — 변형된 질문 형태
("결제일은?", "결제는 언제 됩니까", "결제 시점이 궁금해요" 모두 같은 의도)
도 같이 묶이도록 한다.

LLM client 인터페이스 가정: async generate(LLMRequest) -> LLMResponse
또는 router.route(task, request). 호환을 위해 callable 어떤 것이든
`generate(prompt: str) -> str` 시그니처면 동작하는 어댑터 형태로 사용.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.common.logging import get_logger

log = get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "qa_pair.txt"


@dataclass(frozen=True)
class QAPair:
    """추출된 질문-답변 쌍.

    Attributes:
        question: 정규화된 질문 (LLM 이 자연스러운 형태로 다듬음).
        answer:   정규화된 답변 (본문 인용 + 핵심 요약, 환각 금지).
        source_block_id: 추출된 블록 식별자 (있을 경우).
        confidence: 0.0~1.0 LLM 자체 평가. 낮으면 후속에서 필터.
    """

    question: str
    answer: str
    source_block_id: str | None
    confidence: float


def _load_prompt_template() -> str:
    """프롬프트 파일을 한 번만 로드. 디스크 의존성 단일 책임."""
    return _PROMPT_PATH.read_text(encoding="utf-8")


class QAPairExtractor:
    """LLM 으로 본문에서 Q&A 쌍을 일반화 추출.

    rule/regex 일체 사용하지 않는다. 변형 질문 (어순/조사/축약 등) 은
    프롬프트 단일 원칙 ("같은 의도면 1개로 통합") 에 위임한다.
    """

    def __init__(self, llm_client, max_pairs: int = 20, min_confidence: float = 0.0):
        """
        Args:
            llm_client: `generate(prompt: str) -> str` 또는 LLMRequest 호환 객체.
            max_pairs: 한 본문당 추출 상한 (LLM 폭주 방어).
            min_confidence: 이 미만은 결과에서 제외. 0.0 = 모두 통과.
        """
        self.llm = llm_client
        self.max_pairs = max_pairs
        self.min_confidence = min_confidence
        self._prompt_template = _load_prompt_template()

    async def extract(
        self, *, text: str, block_id: str | None = None
    ) -> list[QAPair]:
        """본문 텍스트에서 Q&A 쌍 추출.

        실패/파싱 에러 시 빈 리스트 반환 (try/except — 파이프라인 안정성).
        """
        if not text or not text.strip():
            return []

        prompt = self._prompt_template.replace("{text}", text)

        try:
            raw = await self._call_llm(prompt)
        except Exception as exc:  # noqa: BLE001
            log.warning("qa_pair_llm_call_failed", error=str(exc))
            return []

        pairs = self._parse_response(raw, source_block_id=block_id)

        # 신뢰도 필터 + 상한 적용
        filtered = [p for p in pairs if p.confidence >= self.min_confidence]
        return filtered[: self.max_pairs]

    async def _call_llm(self, prompt: str) -> str:
        """LLM 호출 어댑터.

        다양한 client 시그니처를 지원:
          1. callable async (prompt) -> str
          2. .generate(prompt: str) -> str (코루틴)
          3. .generate(LLMRequest-like) -> 객체 with .text
        """
        # Case 1: 직접 호출 가능한 async callable — 가장 우선 (mock + plain async fn)
        # AsyncMock 도 callable. 직접 await 했을 때 str 나오면 그대로 반환.
        import inspect
        if callable(self.llm):
            try:
                maybe = self.llm(prompt)
                if inspect.isawaitable(maybe):
                    direct = await maybe
                    if isinstance(direct, str):
                        return direct
                    text = getattr(direct, "text", None)
                    if isinstance(text, str):
                        return text
            except (TypeError, AttributeError):
                pass  # generate 경로 시도

        gen = getattr(self.llm, "generate", None)
        if gen is None or not callable(gen):
            raise RuntimeError("llm_client has no usable generate() method")

        # Case 2/3: 시도 — string 우선, 실패 시 LLMRequest 형태
        try:
            result = await gen(prompt)  # type: ignore[misc]
        except TypeError:
            from src.common.llm.base import LLMRequest

            result = await gen(
                LLMRequest(prompt=prompt, response_format="json", max_tokens=2000)
            )

        if isinstance(result, str):
            return result
        text = getattr(result, "text", None)
        if text is None:
            raise RuntimeError("LLM response missing .text attribute")
        return text

    def _parse_response(
        self, raw: str, *, source_block_id: str | None
    ) -> list[QAPair]:
        """LLM JSON 응답 → QAPair 리스트.

        펜스/잡음 들어와도 첫 JSON object 만 추출 시도.
        """
        cleaned = self._strip_json_envelope(raw)
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            log.warning(
                "qa_pair_json_decode_failed", error=str(exc), preview=cleaned[:120]
            )
            return []

        pairs_raw = obj.get("pairs", [])
        if not isinstance(pairs_raw, list):
            return []

        out: list[QAPair] = []
        for item in pairs_raw:
            if not isinstance(item, dict):
                continue
            q = (item.get("question") or "").strip()
            a = (item.get("answer") or "").strip()
            if not q or not a:
                continue
            try:
                conf = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            conf = max(0.0, min(1.0, conf))
            out.append(
                QAPair(
                    question=q,
                    answer=a,
                    source_block_id=source_block_id,
                    confidence=conf,
                )
            )
        return out

    @staticmethod
    def _strip_json_envelope(raw: str) -> str:
        """```json ...``` 펜스나 앞뒤 자연어 제거. 첫 '{' ~ 마지막 '}' 슬라이스."""
        s = raw.strip()
        if s.startswith("```"):
            # ```json\n...\n``` 케이스
            first_nl = s.find("\n")
            if first_nl != -1:
                s = s[first_nl + 1 :]
            if s.endswith("```"):
                s = s[: -3]
            s = s.strip()
        start = s.find("{")
        end = s.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return s
        return s[start : end + 1]
