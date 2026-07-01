"""GPT-5.5 사전 검증 — Lucas-KMS 분리 spec.

사용자 절칙: model='gpt-5.5'. spec 의 architecture / phase plan / risk 항목을
GPT-5.5 적대 리뷰. PASS / FAIL_WITH_NOTES / GO_WITH_CHANGES 판정.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from openai import OpenAI


SPEC_PATH = Path(__file__).resolve().parents[2] / "docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md"
OUT_PATH = Path(__file__).resolve().parents[2] / "Doc/research/2026-05-19-lucas-kms-spec.gpt55.txt"


def main() -> int:
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    system_msg = (
        "You are GPT-5.5 acting as an adversarial spec reviewer for a "
        "Python monorepo separation project. Read the design spec for "
        "splitting a KMS-only product out of an integrated AI platform. "
        "Find logical gaps, broken invariants, hidden coupling, RLS/auth "
        "risks, migration hazards, missing test coverage, and edge cases. "
        "Be specific: cite line ranges. Verdict: PASS / GO_WITH_CHANGES / "
        "FAIL_WITH_NOTES. Korean OK."
    )
    user_msg = (
        "다음은 Lucas-KMS 분리 배포 spec 입니다. 적대적으로 검토하여 "
        "결함/누락/위험을 모두 식별하고, 최종 verdict (PASS / "
        "GO_WITH_CHANGES / FAIL_WITH_NOTES) 와 함께 보고하세요. "
        "특히 다음을 집중 검토:\n"
        "1) lucas-kms 가 lucas-agent 를 0 import 가능한지 (런타임 호출 "
        "경로 누락 없는지)\n"
        "2) Alembic migration 이 분리 후에도 안전한지\n"
        "3) RLS / tenant 격리가 패키지 분할 시 깨지지 않는지\n"
        "4) Phase 1-4 의 순서/의존성 문제\n"
        "5) Frontend V1 patch 작업량 과소평가 여부\n"
        "6) 외부 vLLM endpoint 운영 정책의 누락\n"
        "7) Risk 섹션의 mitigation 충분성\n"
        "8) Success Criteria 의 측정 가능성\n\n"
        "--- spec 시작 ---\n\n"
        f"{spec_text}\n\n"
        "--- spec 끝 ---\n\n"
        "verdict 와 보강 권고를 한국어로 보고."
    )

    resp = client.chat.completions.create(
        model="gpt-5.5",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    )
    text = resp.choices[0].message.content or ""
    OUT_PATH.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
