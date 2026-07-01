from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_reformulate_prompt_handles_exclusion():
    """REFORMULATE_PROMPT는 'X 말고' 같은 제외(부정) 표현을 복원하도록 지시해야 한다.

    멀티턴 부정 발화('한국투자 말고 아까 그거')에서 제외 대상을 검색어에서 빼고
    실제 가리키는 대상으로 재작성하게 하는 지시가 프롬프트에 있어야 한다.
    """
    src = _read("src/search/llm_query_rewriter.py")
    assert "REFORMULATE_PROMPT" in src
    assert "말고" in src
    assert "제외" in src
