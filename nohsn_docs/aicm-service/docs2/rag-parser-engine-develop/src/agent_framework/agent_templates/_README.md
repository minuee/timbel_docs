# Agent 템플릿 카탈로그

19 업종 카테고리별 기본 agent 정의 — *super-admin 자산*.

## 사용

tenant 관리자는 admin panel `/admin/agents/new` 진입 시 19 카테고리 그리드에서
선택 -> 자동 복제 -> tenant 안에서 customize.

## 작성 규칙

각 yaml 의 `category_id` 는 `_meta.yaml` 의 categories 목록과 매핑.

## 변경 이력

새 카테고리 추가 / 기존 템플릿 수정 시 — 이 디렉터리 안에서만 작업.
복제 후 tenant 가 customize 한 agent 는 영향 X (별도 row).
