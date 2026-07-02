# 어드바이저 출처 하이라이트 가이드

> 2026-06-30 배포. rag_assist SSE `sources` 이벤트 변경사항.

## 변경 요약

`sources` 배열의 각 출처 항목에 `highlightable` 필드가 추가되었습니다.

```json
{
  "ref_num": 1,
  "document_id": "be0ddf95-...",
  "chunk_id": "a0f4b6e1-...",
  "document_title": "하나코리아증권자투자신탁_주식_종류A_간이투자설명서.docx",
  "section_title": null,
  "content": "...",
  "score": 0.731,
  "token_count": 51,
  "page_info": null,
  "source_location": { ... },
  "highlightable": false
}
```

## highlightable 판정 기준

| 조건 | 설명 |
|------|------|
| `generated != true` | LLM이 합성한 요약 블록이 아닐 것 |
| `file_url` 존재 | 원본 문서 접근 경로가 있을 것 |
| `char_offset` 또는 `page_number` 존재 | 원문 내 위치를 특정할 수 있을 것 |

3가지 조건을 **모두** 만족하면 `true`, 하나라도 빠지면 `false`.

## 프론트 처리 방안

### highlightable: true

기존과 동일하게 원문 하이라이트 처리.

- **텍스트 블록** (paragraph, heading, qna): `content` 텍스트를 원문에서 찾아 강조. `start_char_offset`/`end_char_offset`이 있으면 정밀 위치 지정 가능.
- **이미지 블록**: `page_number` + `source_location.bbox`로 해당 영역 표시. 이미지 원본은 `metadata.image_path` 참조.
- **표 블록**: `page_number` + `source_location.bbox`로 해당 영역 표시. 마크다운 변환된 content는 원문 텍스트와 다를 수 있으므로 영역 기반 강조 권장.

### highlightable: false

원문 위치 강조가 불가능한 출처. 예시:

- 문서 전체 요약 블록 (LLM이 합성한 텍스트, 원문에 없음)
- 위치 정보가 없는 블록 (마크다운 원본 등 페이지 개념 없는 문서)

**권장 처리**: 출처 클릭 시 "원문 위치 강조 미지원" 안내 표시, 또는 문서 원본보기만 제공 (위치 강조 없이).

## 블록 타입별 예상 결과

| 원본 포맷 | 블록 타입 | highlightable | 위치 확보 방식 |
|-----------|----------|:---:|------|
| PDF/HWP | 텍스트 | true | char_offset (정밀) |
| PDF/HWP | 이미지 | true | page + bbox (영역) |
| PDF/HWP | 표 | true | page + bbox (영역) |
| DOCX (복잡) | 텍스트 | true | char_offset |
| Markdown | 텍스트/QNA | true | char_offset |
| 모든 포맷 | 문서 요약 (합성) | **false** | 위치 없음 |

## 기존 API와의 호환성

- `highlightable` 필드는 **추가**된 것이므로, 기존 프론트 코드에 영향 없음.
- 기존에 `source_location` 전체가 null인지 체크하던 로직이 있다면, `highlightable` 필드로 대체 가능.
