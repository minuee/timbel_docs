"""Claude 클라이언트 스텁 — Anthropic 의존성 제거됨.

기존 import 호환을 위해 유지. 실제 호출은 QwenLLMClient (OpenAI API 호환)로 라우팅됨.
"""

from src.common.llm.qwen_client import QwenLLMClient

# 기존 코드에서 ClaudeLLMClient를 import하는 곳이 있으면
# 동일한 OpenAI-compatible 클라이언트로 대체
ClaudeLLMClient = QwenLLMClient
