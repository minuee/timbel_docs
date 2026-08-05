# 다크모드 대응: 하드코딩 색상 → 테마 변수 전환 가이드

> 다른 레포지토리에서 동일 작업을 진행하는 Claude/개발자에게 전달하는 핸드오프 문서.
> 출처 작업: `asst-web-portal` 리뉴얼 공지 상세 화면 다크모드 글자색 수정.

---

## 1. 문제 (증상)

- 다크모드에서 **같은 화면인데 어떤 페이지는 글자가 흰색으로 잘 보이고, 어떤 페이지는 회색으로 흐릿**하게 보임.
- 원인: 흐리게 보이는 쪽이 CSS 색상을 **hex 리터럴로 하드코딩**(`color: #374151` 등)해서, 다크모드로 전환돼도 색이 안 바뀜.
- 잘 보이는 쪽은 `var(--color-g80)` 같은 **테마 변수**를 써서 다크모드에서 자동으로 밝은색으로 뒤집힘.

**실제 예:** 공지 상세 본문 `.notice-content { color: #374151 }`(고정 진회색) → 다크 카드 배경 위에서 대비 낮아 회색으로 보임.

---

## 2. 이 프로젝트의 다크모드 원리 (핵심 — 먼저 이해할 것)

- 색 팔레트를 CSS 변수로 정의하고, **`html.dark` 셀렉터에서 같은 변수들을 다크 값으로 재매핑**하는 방식.
- 위치: `src/styles/global.scss`
  - `:root { --color-g80: #303133; ... }` ← 라이트 값
  - `html.dark { --color-g80: #e5eaf3; ... }` ← 다크 값(명도 반전)
- 따라서:
  - 색을 **`var(--color-*)` 로 쓰면** → 다크모드에서 자동 전환 ✅
  - 색을 **hex 리터럴로 쓰면** → 라이트 값 고정, 다크에서 안 바뀜(반쪽 다크) ❌
- **해결 = 하드코딩 hex를 대응하는 `--color-*` 변수로 교체.** (별도 다크 CSS 안 짜도 됨)

> ⚠️ 다른 레포에 이 `--color-*` 팔레트 + `html.dark` 재매핑 블록이 **없다면** 먼저 그 토큰 시스템부터 이식해야 함. 있으면 아래 매핑표대로 교체만 하면 끝.

---

## 3. 변수 매핑표 (global.scss 기준 · 라이트 / 다크)

### Neutral scale
| 변수 | 라이트 | 다크 | 용도 |
|---|---|---|---|
| `--color-g80` | `#303133` | `#e5eaf3` | 가장 진한 텍스트 / 제목 |
| `--color-g70` | `#4a4c4f` | `#cfd3dc` | 본문 텍스트 |
| `--color-g60` | `#606266` | `#cfd3dc` | regular 텍스트 |
| `--color-g50` | `#7a7e85` | `#a3a6ad` | 보조 라벨 |
| `--color-g40` | `#909399` | `#a3a6ad` | secondary / placeholder / 시간 |
| `--color-g35` | `#a8abb2` | `#8d9095` | 옅은 보조 |
| `--color-g20` | `#c0c4cc` | `#6c6e72` | 진한 보더 |
| `--color-g15` / `g12` | `#dcdfe6` | `#4c4d4f` | 보더 |
| `--color-g10` | `#e4e7ed` | `#414243` | 보더(light) |
| `--color-g5` | `#ebeef5` | `#363637` | 보더(lighter) / 옅은 배경 |
| `--color-g05` | `#f5f7fa` | `#262727` | 옅은 회색 표면 배경 |

### Surface / System
| 변수 | 라이트 | 다크 | 용도 |
|---|---|---|---|
| `--color-white` | `#ffffff` | `#1d1e1f` | **카드/패널 표면** (텍스트용 아님) |
| `--color-background` | `#fafafa` | `#141414` | 페이지 배경 |
| `--color-danger` | `#f56c6c` | (동일) | 위험/긴급 텍스트·점 |
| `--color-danger-15` | `danger 15%` | (자동) | 위험 배지 배경 tint |
| `--color-primary` | EP primary | (EP 다크 자동) | 강조/링크/활성 보더 |

> `--color-primary-10/15`, `--color-danger-10/15`, `--color-success-*`, `--color-warning-*` 등 **투명도 tint 토큰**도 있음(배지/hover 배경에 유용).

---

## 4. 교체 규칙 (hex를 만나면 이 변수로)

| 쓰임새 | 권장 변수 |
|---|---|
| 제목/가장 진한 텍스트 | `--color-g80` |
| 본문 텍스트 | `--color-g70` (또는 `--color-g60`) |
| 보조 라벨 | `--color-g50` |
| placeholder / 시간 / 힌트 | `--color-g40` |
| 카드/패널 배경 | `--color-white` |
| 옅은 표면 배경 | `--color-g05` |
| 일반 보더 | `--color-g10` (또는 `g15`) |
| 옅은 구분선 | `--color-g5` |
| 위험/긴급 텍스트·아이콘 | `--color-danger` |
| 위험 배지 배경 | `--color-danger-15` |
| 강조/링크/활성 보더 | `--color-primary` |

> 흰 텍스트를 항상 흰색으로 고정해야 하는 자리(예: primary 버튼 위 글자)는 `#fff` **리터럴 유지**가 맞음. (`--color-white`는 다크에서 어두운 표면색으로 뒤집히므로 텍스트에 쓰면 안 됨)

---

## 5. 작업 절차

1. 대상 파일에서 하드코딩 색 찾기:
   ```bash
   grep -nE "#[0-9a-fA-F]{3,6}" <파일경로>
   ```
2. 각 hex를 §4 규칙대로 `var(--color-*)`로 교체.
3. 교체 후 재확인 — 남은 hex가 있으면 의도된 것(예: primary 버튼 위 `#fff`)인지 판단.
4. **라이트/다크 둘 다** 실제 화면에서 육안 확인.

---

## 6. 실제 적용 예시 (이번 작업)

**파일:** `src/view/advisor-renual/notice/index.vue` (상담사 공지 상세)

| 위치 | before | after |
|---|---|---|
| 본문 글자(핵심) | `#374151` | `var(--color-g70)` |
| 미확인 요약 | `#6b7280` | `var(--color-g50)` |
| 카드 보더 | `#e5e7eb` | `var(--color-g10)` |
| 열림 보더 | `#c7d2fe` | `var(--color-primary)` |
| 긴급 배지 배경/글자 | `#fee2e2` / `#ef4444` | `var(--color-danger-15)` / `var(--color-danger)` |
| 일반 배지 배경/글자 | `#f1f5f9` / `#64748b` | `var(--color-g05)` / `var(--color-g50)` |
| new 점 | `#ef4444` | `var(--color-danger)` |
| 시간 | `#9ca3af` | `var(--color-g40)` |
| 본문 구분선 | `#f1f5f9` | `var(--color-g5)` |
| 전체보기 링크 | `#6366f1` | `var(--color-primary)` |
| 힌트 | `#94a3b8` | `var(--color-g40)` |

**결과:** `html.dark`에서 팔레트가 뒤집히며 본문 글자가 진회색 → 밝은색으로 자동 전환 → 관리자 페이지와 동일하게 잘 보임.

**참고 (정상 케이스):** 관리자 공지 `src/view/advisor-renual/admin/notice/index.vue`는 처음부터 `var(--color-gXX)`를 써서 다크 대응이 돼 있었음. 이걸 레퍼런스로 삼으면 됨.
