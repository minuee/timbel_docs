"""agent_framework classifier package — LLM 기반 문서/쿼리 분류 모듈.

Stage B-Core-4 (KMS-Plus): 업로드된 문서의 도메인/카테고리/태그를
정밀 프롬프트로 LLM 에 한 번 물어보고, processing_meta.auto_classification
으로 영구 저장.
"""
from src.agent_framework.classifier.document_classifier import DocumentClassifier

__all__ = ["DocumentClassifier"]
