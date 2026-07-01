"""Phase 2 T2.2 — Lucas-KMS alembic env (delegates to alembic/env_kms.py).

본 파일은 ``alembic.kms.ini`` 의 ``script_location = alembic_kms`` 가 지정한
디렉토리의 env.py. 실제 로직은 ``alembic/env_kms.py`` 에 위치하며 본 파일은
*위임* 만 수행 — 코드 중복 회피.
"""

import os
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path 에 추가
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

# alembic/env_kms.py 를 모듈로 import 하면 자동 실행 (alembic env 패턴).
# env_kms.py 의 top-level 코드가 context.is_offline_mode() 분기를 처리.
_env_kms = _root / "alembic" / "env_kms.py"
exec(compile(_env_kms.read_text(encoding="utf-8"), str(_env_kms), "exec"))
