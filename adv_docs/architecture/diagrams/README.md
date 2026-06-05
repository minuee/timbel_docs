# Architecture Diagrams

> 시각화된 아키텍처 자료 보관소.
> 텍스트 설명은 상위 디렉토리의 `0X-*.md` 문서를 참조하세요.

---

## 파일 목록

| 파일 | 내용 | 형식 |
|------|------|------|
| [aicc-architecture.drawio](aicc-architecture.drawio) | AICC 전체 시스템 다이어그램 (C4 모델 기반, 17페이지) | drawio (XML) |
| [advisor-4service-architecture.svg](advisor-4service-architecture.svg) | Advisor ↔ auth/user/tenant-mgmt 4서비스 구조 + 데이터 저장소 + 흐름 번호 | SVG |
| [advisor-runtime-sequence.svg](advisor-runtime-sequence.svg) | 런타임 요청 흐름 시퀀스 (asst → user → auth, 캐시 히트 최적화) | SVG |

> SVG 2종은 [../01-multi-tenant-db.md](../01-multi-tenant-db.md) 에 임베드되어 있고, GitHub/IDE에서 바로 렌더링됩니다 (drawio와 달리 별도 뷰어 불필요).

---

## drawio 파일 보는 방법

`.drawio` 는 [draw.io](https://drawio-app.com/) 의 XML 포맷입니다. 다음 방법 중 하나로 엽니다:

### 방법 1: 웹 브라우저 (가장 간단)

[app.diagrams.net](https://app.diagrams.net/) 접속 → 메뉴 `File → Open from → Device` → drawio 파일 선택.

### 방법 2: VS Code 확장

VS Code Extensions 에서 **"Draw.io Integration"** (`hediet.vscode-drawio`) 설치 후 파일을 열면 내장 에디터로 보임. 가장 편함.

### 방법 3: 데스크톱 앱

[GitHub Releases](https://github.com/jgraph/drawio-desktop/releases) 에서 운영체제별 설치.

---

## 다이어그램 자료 갱신 규칙

1. **drawio 편집은 파일 직접 수정** — XML 기반이라 git diff 추적됨
2. **SVG는 원본 도구에서 재생성 후 교체** — 손으로 SVG XML을 고치지 말 것
3. **commit 메시지 컨벤션**: `docs: 아키텍처 다이어그램 갱신 (...)` 형식
4. **신규 다이어그램 추가 시** 이 README에 항목 추가 + 관련 본문 문서에 임베드/링크
5. **큰 구조 변경**: PR 본문에 변경 전/후 스크린샷 첨부 권장 (drawio는 GitHub 미리보기 안 됨, SVG는 됨)

---

## 자세한 설명

전체 시스템 컨텍스트의 텍스트 설명은 [../aicc-system-context.md](../aicc-system-context.md) 참조.
