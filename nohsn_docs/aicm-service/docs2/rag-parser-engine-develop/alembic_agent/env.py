"""Phase 2 T2.2 — Lucas-Agent alembic env (delegates to alembic/env_agent.py)."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

_env_agent = _root / "alembic" / "env_agent.py"
exec(compile(_env_agent.read_text(encoding="utf-8"), str(_env_agent), "exec"))
