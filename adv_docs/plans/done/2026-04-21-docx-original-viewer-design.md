# DOCX 원본 문서 뷰어 설계

## 목표

검색 결과에서 문서 상세 보기(DocumentDetailView) 아이콘 클릭 시, 원본 DOCX 파일을 모달로 렌더링하고 현재 펼쳐진 블록 위치를 하이라이트+스크롤한다.

---

## 배경 및 제약

- `GET /documents/{doc_id}/original` API가 DOCX를 `application/octet-stream`으로 반환
- 블록 데이터에 `section_title: null`, `heading_path: []` — 제목 기반 포커스 불가
- 블록 데이터에 `content`, `start_char_offset`, `end_char_offset` 존재 → content 텍스트로 포커스
- 파일 크기 ~24KB → 네트워크 + 변환 ~500ms 이내 예상

---

## 아키텍처

```
DocumentDetailView (open_in_new 아이콘 클릭)
    │
    ├── emit("openOriginalViewer", { document_id, activeContent })
    │
knowledge/index.vue (핸들러)
    │
    ├── 캐시 조회 (docHtmlCache: Map<document_id, htmlString>)
    │       ├── HIT  → 캐시 HTML 사용
    │       └── MISS → GET /documents/{doc_id}/original
    │                   → mammoth.convertToHtml(blob)
    │                   → 캐시 저장 (LRU, 최대 10개)
    │
DocOriginalViewerModal.vue
    ├── 로딩 스피너 (캐시 MISS 시)
    ├── mammoth HTML 렌더링
    └── content 텍스트 검색 → <mark> 하이라이트 + scrollIntoView
```

---

## 캐싱 전략

- **저장소**: `Map<string, string>` (document_id → HTML 문자열)
- **위치**: `knowledge/index.vue` 또는 composable (`useDocHtmlCache`)
- **초기화 시점**: 페이지 새로고침 시 자동 소멸 (세션 기반)
- **크기 제한**: 최대 10개, 초과 시 가장 오래된 항목(FIFO) 제거
- **포커스 로직**: 캐시 대상 아님 — 매 호출마다 새로 실행

---

## 포커스 로직

1. 모달 HTML 렌더 완료 후 실행
2. `activeContent` (블록 content 첫 줄 또는 핵심 문장) 으로 텍스트 노드 탐색
3. 일치 텍스트를 `<mark class="kms-highlight">` 로 감싸기
4. `scrollIntoView({ behavior: 'smooth', block: 'center' })`
5. 미일치 시: 모달 상단 유지 (에러 없이 graceful 처리)

---

## 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `asst-web/src/view/advisor/components/knowledge/DocumentDetailView.vue` | 현재 펼쳐진 블록 content 추적, 아이콘 클릭 시 emit |
| `asst-web/src/view/advisor/components/knowledge/index.vue` | openOriginalViewer 핸들러, docHtmlCache Map, LRU 10개 제한 |
| `asst-web/src/view/advisor/components/knowledge/DocOriginalViewerModal.vue` | 신규 — mammoth 렌더링 + 포커스 로직 |
| `asst-web/package.json` | mammoth 패키지 추가 |

---

## UX 플로우

```
1. 검색 결과 카드 클릭 → DocumentDetailView 열림
2. 섹션 펼침 (ContentCollapse) → activeContent 업데이트
3. open_in_new 아이콘 클릭
4. [캐시 MISS] 로딩 스피너 → API → mammoth → 캐시 저장
   [캐시 HIT]  즉시 HTML 표시
5. 블록 content 텍스트 하이라이트 + 스크롤
```

---

**작성일**: 2026-04-21  
**작성자**: Claude Code (Sonnet 4.6)
