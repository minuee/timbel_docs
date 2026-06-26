# 원본문서 뷰어 & 위치이동(책갈피/바로가기) 정리

> 지식저장소(knowledge)에서 "원본 문서"를 모달로 열고, 선택한 색션(블록)의 위치로 자동 스크롤하는 기능에 대한 분석 + 작업 기록.
> ※ 순수 "문서 뷰어/위치이동" 관련 내용만 정리 (감정·VOC 등은 제외).

---

## 1. 핵심 컴포넌트

| 역할 | 파일 |
|---|---|
| 원본 문서 모달(뷰어 본체) | `src/view/advisor/components/knowledge/DocOriginalViewerModal.vue` |
| 모달 상태 관리(open/문서ID/대상텍스트) | `src/view/advisor/components/knowledge/composables/useKnowledgeModals.ts` |
| 모달 호출(문서 상세) | `src/view/advisor/components/knowledge/DocumentDetailView.vue` |

---

## 2. 문서 렌더링 방식

원본 파일을 받아 **매직바이트로 종류를 판별**한 뒤 형식별로 다르게 렌더링한다.

| 형식 | 렌더링 | 비고 |
|---|---|---|
| **DOCX** (`PK` zip 계열) | `mammoth`로 **HTML 변환** 후 `v-html` | 변환 HTML은 모듈 캐시(`_cache`, 최대 10개 FIFO) |
| **PDF** (`%PDF`) | `pdf.js`로 **페이지별 Canvas 렌더** | Canvas라 텍스트가 DOM 요소가 아님(중요) |
| **기타** (이미지/구형 OLE/HWP 등) | 미리보기 미지원 → **자동 다운로드** | 파일명 확장자는 best-effort 추정 |

- HTTP: `KnowledgeAPI.instance.getDocumentOriginal(documentId)` — **원본 파일 바이너리만** 받는다.

---

## 3. 위치이동(바로가기)의 핵심 원리 ⭐

**백엔드가 주는 위치정보(offset/좌표/anchor/#id)는 전혀 없다.** 순수 프론트의 **텍스트 매칭**으로 동작한다.

```
[문서 상세에서 펼친 블록의 "첫 줄 텍스트"]
   ↓ extractContentFromItem()        ← DocumentDetailView.vue
[activeContent = 그냥 문자열]
   ↓ openOriginalViewer(docId, activeContent)
[모달] getDocumentOriginal(docId)    ← 원본 파일 바이너리 (위치정보 X)
   ↓ 렌더링 후 텍스트 매칭으로 해당 위치 탐색 → scrollIntoView
```

- 이동 대상 = `activeContent`(블록 첫 줄 텍스트). 좌표/페이지/offset 같은 메타데이터가 아니다.
- 즉, **"이동할 텍스트"를 렌더된 문서에서 글자로 찾아 점프**하는 방식.

### 3-1. DOCX 위치이동 — 단락 텍스트 매칭

`focusActiveContent()` (DocOriginalViewerModal.vue)

- 렌더된 HTML의 단락 요소(`p, li, td, th, h1~h6`)를 순회
- 각 단락의 `textContent`를 `normalizeText()`로 정규화 후, `activeContent`(앞 100자)와 `includes` 비교
- **첫 매칭 단락**에 하이라이트(`.kms-focus`, 황색 배경) + `scrollIntoView({ block: "center" })` 후 `break`

`normalizeText()` 정규화 처리:
- 연속 공백 → 단일 공백, 따옴표/물음표 통일, 소문자화
- **인덱서가 영문/숫자↔한글 경계에 넣는 공백 제거** (실데이터 특성 대응)

### 3-2. PDF 위치이동 — 페이지 단위 이동 (추가 구현)

PDF는 Canvas라 단락 DOM이 없어 원래 **위치이동 미지원**이었음. → **페이지 단위 이동**으로 구현.

`focusActivePdfPage()` (DocOriginalViewerModal.vue)

- `renderPdf()`에서 페이지를 그릴 때 `page.getTextContent()`로 **페이지별 텍스트를 보관**(`pdfPageTexts`), canvas에 `data-page` 부여
- `activeContent`가 포함된 **페이지**를 `normalizeText` + `includes`로 탐색 → 해당 canvas로 `scrollIntoView({ block: "start" })` + 페이지 테두리 강조(`.kms-focus-page`, 주황 outline)
- PDF 텍스트는 공백/줄바꿈이 지저분해 통째 매칭이 어려움 → **검색어 길이를 100 → 60 → 30자로 줄여가며 재시도**

---

## 4. 위치이동 호출 시점

`DocOriginalViewerModal.vue`의 watch:
- 모달 open / `documentId` 변경 → `loadDocument()` → 렌더 후 위치이동 호출
  - DOCX(html): `focusActiveContent()` / PDF: `focusActivePdfPage()` / 다운로드: 스킵
- `activeContent`만 변경(같은 문서, 다른 섹션) → DOCX는 `focusActiveContent()`, PDF는 `focusActivePdfPage()` 재호출

---

## 5. 한계 / 위치가 안 맞을 수 있는 원인

| # | 원인 | 영향 |
|---|---|---|
| 1 | 앞 **100자만** 매칭 + **첫 매칭 break** | 흔하거나 짧은 문구면 엉뚱한 단락/페이지로 갈 수 있음 |
| 2 | `normalizeText` 과도 정규화 | 인덱서가 자른 텍스트와 렌더 단락이 달라 매칭 실패 가능 |
| 3 | 비동기 렌더링 타이밍(`nextTick` 1회 의존) | 큰 문서면 DOM 완성 전 호출되어 빗나갈 여지 |
| 4 | **PDF는 페이지 단위**(상단으로만 이동) | 페이지 안 정확한 줄까진 못 감 |
| 5 | 스캔 PDF(이미지) 등 텍스트 추출 불가 | 매칭 대상 없음 → 이동 안 함(에러는 없음) |

---

## 6. 작업 이력 요약

1. **분석**: 원본문서 위치이동이 백엔드 위치정보 없이 **순수 프론트 텍스트 매칭**임을 확인. DOCX만 동작, PDF는 미지원이었음.
2. **구현(PDF)**: PDF에 **페이지 단위 위치이동** 추가 (`renderPdf` 텍스트 추출 + `focusActivePdfPage` + `.kms-focus-page` 강조). DOCX 로직은 미변경.
   - 선택지 중 "페이지 단위 이동"을 채택(줄 단위 text-layer 방식은 복잡/정확도 트레이드오프로 보류).
