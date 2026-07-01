"""Pipeline workers test conftest.

D46-v3: test_d35_self_check_fatal.py 가 patch.dict("sys.modules", ...) 를 사용해
src.common.metrics 가 모듈 캐시에서 제거되는 부수효과 발생. 본 conftest 는
session-scoped autouse fixture 로 src.common.metrics 를 사전 import 하여
sys.modules 에 *patch.dict 시작 전부터 존재* 하도록 보장.

이렇게 하면 patch.dict 가 종료될 때 src.common.metrics 가 *원래 존재했던
key* 로 인식되어 제거되지 않음. 후속 테스트의 re-import 시 Counter 재등록
ValueError 회피.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _preserve_metrics_module_in_sys_modules() -> None:
    """src.common.metrics 사전 import — patch.dict 의 sys.modules 부수효과 회피."""
    import src.common.metrics  # noqa: F401
