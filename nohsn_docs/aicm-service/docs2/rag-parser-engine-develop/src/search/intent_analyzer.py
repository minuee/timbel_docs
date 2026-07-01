"""쿼리 의도 분석기 — 검색 전 쿼리를 분석하여 검색 범위를 자동 축소.

5000개 문서에서 "이더넷 커넥터"를 검색하면 여러 문서가 섞이는 문제를 해결.
LLM이 쿼리를 분석하여:
1. 어떤 분야/주제인지 (전자, 금융, 공정, 소프트웨어...)
2. 어떤 유형의 답변이 필요한지 (수치 조회, 절차 설명, 비교, 목록)
3. 시간 범위가 있는지 ("최근", "지난달", "2024년")
4. 특정 문서를 가리키는지 ("매뉴얼에서", "보고서에", "단가표에서")
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from src.common.logging import get_logger

log = get_logger(__name__)


class QueryIntent(BaseModel):
    """쿼리 의도 분석 결과."""

    original_query: str
    domain: str = ""  # electronics, finance, manufacturing, software, general
    answer_type: str = ""  # lookup, procedure, comparison, list, explanation
    time_filter: str = ""  # recent, last_month, 2024, "" (없음)
    document_hint: str = ""  # "매뉴얼", "단가표", "보고서" 등 문서 유형 힌트
    suggested_block_types: list[str] = Field(default_factory=list)
    confidence: float = 0.0  # 의도 파악 신뢰도

    # 검색에 직접 적용할 필터
    suggested_repository_ids: list[str] = Field(default_factory=list)
    suggested_category_ids: list[str] = Field(default_factory=list)


class IntentAnalyzer:
    """쿼리 의도 분석기.

    규칙 기반 분석(~1ms)을 기본으로, 신뢰도가 낮으면 LLM 분석(~500ms)을 추가.
    모든 분석은 선택적이며, 실패해도 검색에 영향을 주지 않는다.
    """

    def __init__(
        self,
        llm_client: object | None = None,
        repositories: list[dict] | None = None,
    ) -> None:
        """IntentAnalyzer를 초기화한다.

        Args:
            llm_client: LLM 클라이언트 (없으면 규칙 기반만 사용)
            repositories: 저장소 목록 [{"id": "...", "name": "...", "description": "..."}]
        """
        self._llm = llm_client
        self._repos = repositories or []

    async def analyze(self, query: str) -> QueryIntent:
        """쿼리 의도를 분석한다.

        Args:
            query: 사용자 검색 쿼리

        Returns:
            QueryIntent: 분석된 의도 정보
        """
        intent = QueryIntent(original_query=query)

        # 1. 규칙 기반 분석 (빠르고 LLM 없이도 동작)
        self._rule_based_analysis(query, intent)

        # 2. LLM 기반 분석 (있으면 추가)
        if self._llm and intent.confidence < 0.7:
            await self._llm_analysis(query, intent)

        log.debug(
            "intent_analysis_completed",
            query=query[:100],
            domain=intent.domain,
            answer_type=intent.answer_type,
            time_filter=intent.time_filter,
            document_hint=intent.document_hint,
            confidence=intent.confidence,
            suggested_repos=len(intent.suggested_repository_ids),
        )

        return intent

    def _rule_based_analysis(self, query: str, intent: QueryIntent) -> None:
        """규칙 기반 의도 분석.

        키워드 매칭으로 문서 유형 힌트, 답변 유형, 시간 필터, 도메인, 저장소를 추론한다.
        """
        q = query.lower()

        # 문서 유형 힌트
        doc_hints: dict[str, list[str]] = {
            "매뉴얼": ["매뉴얼", "manual", "사용법", "설명서", "가이드"],
            "단가표": ["가격", "단가", "얼마", "비용", "price", "cost"],
            "사양서": ["스펙", "spec", "사양", "pin", "핀", "레지스터", "register", "gpio"],
            "보고서": ["보고서", "report", "분석", "결과"],
            "공정": ["공정", "process", "순서", "절차", "step"],
        }
        for doc_type, keywords in doc_hints.items():
            if any(kw in q for kw in keywords):
                intent.document_hint = doc_type
                intent.confidence = max(intent.confidence, 0.5)
                break

        # 답변 유형
        if any(kw in q for kw in ["얼마", "가격", "비용", "수치", "몇"]):
            intent.answer_type = "lookup"
            intent.suggested_block_types.append("table")
        elif any(kw in q for kw in ["방법", "어떻게", "절차", "순서", "steps"]):
            intent.answer_type = "procedure"
            intent.suggested_block_types.append("numbered_list")
        elif any(kw in q for kw in ["비교", "차이", "vs", "대비"]):
            intent.answer_type = "comparison"
            intent.suggested_block_types.append("table")
        elif any(kw in q for kw in ["목록", "리스트", "종류", "어떤"]):
            intent.answer_type = "list"
        else:
            intent.answer_type = "explanation"

        # 시간 필터
        if any(kw in q for kw in ["최근", "최신", "latest", "recent"]):
            intent.time_filter = "recent"
        elif any(kw in q for kw in ["지난달", "저번달", "last month"]):
            intent.time_filter = "last_month"
        year_match = re.search(r"20[0-9]{2}년?", q)
        if year_match:
            intent.time_filter = year_match.group().replace("년", "")

        # 도메인 추론
        domain_keywords: dict[str, list[str]] = {
            "electronics": [
                "커넥터", "이더넷", "ethernet", "pcb", "회로", "반도체", "칩",
                "gpio", "spi", "i2c", "uart", "전압", "전류", "저항",
            ],
            "finance": [
                "대출", "금리", "이자", "계좌", "보험", "투자", "펀드",
                "주식", "채권", "배당", "수익률",
            ],
            "manufacturing": [
                "공정", "smt", "조립", "검사", "품질", "불량", "라인",
                "생산", "설비", "금형", "용접",
            ],
            "software": [
                "api", "코드", "배포", "서버", "데이터베이스", "docker",
                "kubernetes", "sdk", "라이브러리",
            ],
        }
        for domain, keywords in domain_keywords.items():
            if any(kw in q for kw in keywords):
                intent.domain = domain
                intent.confidence = max(intent.confidence, 0.4)
                break
        if not intent.domain:
            intent.domain = "general"

        # 저장소 매칭 (저장소 이름/설명과 쿼리 키워드 매칭)
        for repo in self._repos:
            repo_name = (
                repo.get("name", "") + " " + repo.get("description", "")
            ).lower()
            query_words = set(re.findall(r"[가-힣]{2,}|[a-zA-Z]{3,}", q))
            repo_words = set(re.findall(r"[가-힣]{2,}|[a-zA-Z]{3,}", repo_name))
            overlap = query_words & repo_words
            if overlap:
                intent.suggested_repository_ids.append(repo["id"])
                intent.confidence = max(intent.confidence, 0.6)

    async def _llm_analysis(self, query: str, intent: QueryIntent) -> None:
        """LLM 기반 의도 분석 (규칙으로 부족할 때).

        규칙 기반 분석 신뢰도가 0.7 미만일 때만 호출된다.
        LLM 호출이 실패해도 규칙 기반 결과를 유지한다.
        """
        repo_list = ", ".join(f"{r.get('name', '?')}" for r in self._repos[:10])

        prompt = f"""사용자 검색 쿼리를 분석하세요.

쿼리: "{query}"
사용 가능한 저장소: {repo_list}

JSON으로 반환:
{{"domain": "분야", "answer_type": "lookup/procedure/comparison/list/explanation", "document_hint": "문서유형 힌트 또는 빈 문자열", "suggested_repos": ["관련 저장소명"]}}"""

        try:
            if hasattr(self._llm, "chat"):
                resp = await self._llm.chat.completions.create(
                    model=settings.VLLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200,
                    temperature=0.1,
                )
                import json

                text = resp.choices[0].message.content or ""
                # JSON 부분만 추출
                json_match = re.search(r"\{.*\}", text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    if parsed.get("domain"):
                        intent.domain = parsed["domain"]
                    if parsed.get("answer_type"):
                        intent.answer_type = parsed["answer_type"]
                    if parsed.get("document_hint"):
                        intent.document_hint = parsed["document_hint"]
                    if parsed.get("suggested_repos"):
                        # 저장소명 → ID 변환
                        repo_name_map = {
                            r.get("name", "").lower(): r.get("id", "")
                            for r in self._repos
                        }
                        for repo_name in parsed["suggested_repos"]:
                            repo_id = repo_name_map.get(repo_name.lower(), "")
                            if repo_id and repo_id not in intent.suggested_repository_ids:
                                intent.suggested_repository_ids.append(repo_id)
                    intent.confidence = max(intent.confidence, 0.8)
        except Exception:
            log.debug("llm_intent_analysis_failed", exc_info=True)
            # LLM 실패 시 규칙 기반 결과만 사용
