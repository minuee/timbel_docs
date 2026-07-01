"""LLM 공통 유틸리티 — thinking 제거, JSON 추출 등."""

from __future__ import annotations

import json
import re


def strip_thinking(text: str) -> str:
    """LLM 출력에서 thinking/사고 과정을 제거한다.

    처리 패턴:
    1. <think>...</think> 태그 (Qwen 기본)
    2. <think>... (닫는 태그 없이 잘린 경우)
    3. "Thinking Process:" 텍스트 (태그 없이 출력)
    """
    # 1. <think>...</think>
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    # 2. 잘린 <think>
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL)
    # 3. "Thinking Process:" 텍스트
    if "Thinking Process:" in text or "Thinking process:" in text:
        for marker in ("[", "{", "```"):
            idx = text.find(marker)
            if idx > 0:
                text = text[idx:]
                break
        else:
            parts = text.split("\n\n")
            for i in range(len(parts) - 1, -1, -1):
                if parts[i].strip() and not parts[i].strip().startswith("Thinking"):
                    text = "\n\n".join(parts[i:])
                    break

    return text.strip()


def extract_json_array(text: str) -> list[dict]:
    """텍스트에서 JSON 배열을 추출한다."""
    cleaned = strip_thinking(text)

    # 코드블럭 안의 JSON
    if "```" in cleaned:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]

    # 직접 [ 로 시작하지 않으면 찾기
    if cleaned and cleaned[0] != "[":
        start = cleaned.find("[")
        if start >= 0:
            end = cleaned.rfind("]")
            if end > start:
                cleaned = cleaned[start : end + 1]

    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    return []


def extract_json_object(text: str) -> dict:
    """텍스트에서 JSON 객체를 추출한다."""
    cleaned = strip_thinking(text)

    if "```" in cleaned:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]

    if cleaned and cleaned[0] != "{":
        start = cleaned.find("{")
        if start >= 0:
            end = cleaned.rfind("}")
            if end > start:
                cleaned = cleaned[start : end + 1]

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    return {}
