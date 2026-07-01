# `/api/docs/update_doc` PATCH 메서드 동작 프로세스

## 개요

`/api/docs/update_doc` 엔드포인트는 문서를 수정하는 API입니다. 이 API는 **버전 관리 시스템**처럼 동작하여 기존 문서 내용을 보존하면서 새로운 버전을 생성합니다.

## 핵심 사항

### ❌ 문서 ID는 변경되지 않습니다

- **`document_id`는 절대 변경되지 않습니다**
- 문서의 고유 식별자는 유지됩니다
- 문서를 수정해도 동일한 `document_id`를 사용합니다

### ✅ 새로운 버전(Content)이 생성됩니다

- 기존 `DocumentsContentModel` 레코드는 **수정되지 않고 보존**됩니다
- 새로운 `DocumentsContentModel` 레코드가 생성됩니다
- 새로운 버전명(`version_name`)이 자동으로 생성됩니다 (예: v1.0 → v1.1)
- `DocumentsModel.current_contents_id`가 새로운 content의 ID로 업데이트됩니다

## 동작 프로세스

### 1단계: API 엔드포인트 수신

```
PATCH /api/docs/update_doc?workspace_id=xxx&document_id=yyy
```

**요청 본문:**
```json
{
  "name": "수정된 문서 제목",
  "contents": {...},
  "summary": "수정된 요약",
  "editor_id": "user_123",
  ...
}
```

### 2단계: 워크스페이스 검증

```python
workspace_service.check_workspace(workspace_id=workspace_id)
```

- 워크스페이스 존재 여부 확인
- 인증 토큰 검증

### 3단계: 기존 문서 조회 및 섹션 ID 수집

```python
# services/document_service.py
legacy_doc_sections_ids = doc_service.legacy_sections_ids(
    workspace_id=workspace_id,
    document_id=document_id
)
```

- 문서의 모든 섹션(section) ID를 수집
- 이후 검색 엔진 업데이트에 사용

### 4단계: 기존 문서 내용 가져오기 및 전처리

```python
# db/services/document/document_service.py
legacy_contents = self.get_document(workspace_id=workspace_id, document_id=document_id)
contents = copy.deepcopy(legacy_contents["contents"])
blocks_map = {b["id"]: b["content"] for b in legacy_contents["blocks_map"]}
```

**전처리 과정:**
- 기존 문서의 `contents`와 `blocks_map`을 복사
- `clean_and_replace` 함수로 내용 정리:
  - outline의 `id` 필드 제거
  - `sect_xxx` 형식의 섹션 ID를 실제 HTML content로 치환
  - 새로운 버전 생성을 위한 데이터 준비

### 5단계: 문서 업데이트 (새 버전 생성)

```python
# db/repositories/document/document_repository.py
document = self.get_document(workspace_id=workspace_id, document_id=document_id)
content = self.doc_contents_service.get_document_content(
    workspace_id=workspace_id,
    content_id=document.current_contents_id
)

updated_content = self.doc_contents_service.update_document_contents(
    workspace_id=workspace_id,
    content_id=content.get("id"),
    document=update_data,
    processed_contents=processed_contents
)

document.current_contents_id = updated_content.get("id")
```

**중요한 점:**
- 기존 `content`는 **수정되지 않음**
- 새로운 `DocumentsContentModel` 인스턴스가 생성됨
- `document.current_contents_id`만 새로운 content ID로 업데이트됨

### 6단계: 새 Content 생성 (버전 관리)

```python
# db/repositories/document/document_contents_repository.py
db_document_contents = DocumentsContentModel(
    workspace_id=workspace_id,
    document_id=content.document_id,  # 동일한 document_id 사용
    version_name=next_version_name(content.version_name, content.created_at),  # 새 버전명
    name=new_name,
    summary=new_summary,
    ...
)

self.db.add(db_document_contents)
```

**버전명 생성:**
- `next_version_name()` 함수로 자동 생성
- 예: "v1.0" → "v1.1", "v1.1" → "v1.2"
- 날짜 기반 버전 관리

### 7단계: 인덱스 및 섹션 생성

```python
if isinstance(new_contents, dict):
    db_document_contents.contents = self.get_indexes_ids(
        workspace_id=workspace_id,
        content_id=db_document_contents.id,
        indexes=processed_contents
    )
```

- 새로운 content ID로 인덱스(index) 및 섹션(section) 생성
- 문서 구조(outline) 재구성

### 8단계: 히스토리 기록

```python
self.history_service.create_history(history=DocumentHistory(
    workspace_id=workspace_id,
    document_id=document_id,
    content_id=updated.get("id"),
    user_id=update_data.editor_id,
    history="edited_doc",
    details="내용 수정"
))
```

- 문서 수정 이력을 기록
- 누가, 언제 수정했는지 추적 가능

### 9단계: 검색 엔진 업데이트

```python
search_engine_client.update_document(
    token=token,
    workspace_id=workspace_id,
    section_ids=legacy_doc_sections_ids,
    approved='staging'
)
```

- Elasticsearch 등 검색 엔진에 변경사항 반영
- 기존 섹션들을 staging 상태로 업데이트

### 10단계: 응답 반환

```python
return self.fill_detail_dict(workspace_id=workspace_id, content_id=updated.get("id"))
```

- 새로 생성된 버전의 상세 정보를 반환
- `fill_detail_dict`로 완전한 문서 정보 구성

## 데이터베이스 변화

### Before (수정 전)

**aicm_documents 테이블:**
```
id: document_abc123
current_contents_id: contents_v1_0
effective_contents_id: null
```

**aicm_documents_contents 테이블:**
```
id: contents_v1_0
document_id: document_abc123
version_name: v1.0
name: "원본 문서"
...
```

### After (수정 후)

**aicm_documents 테이블:**
```
id: document_abc123  ← 변경되지 않음!
current_contents_id: contents_v1_1  ← 새 content ID로 업데이트
effective_contents_id: null
```

**aicm_documents_contents 테이블:**
```
id: contents_v1_0  ← 기존 레코드 보존 (수정 안 됨)
document_id: document_abc123
version_name: v1.0
name: "원본 문서"
...

id: contents_v1_1  ← 새 레코드 생성
document_id: document_abc123  ← 동일한 document_id
version_name: v1.1  ← 새 버전명
name: "수정된 문서"
...
```

## 요약

### 변경되는 것

1. ✅ **새로운 `DocumentsContentModel` 레코드 생성**
2. ✅ **`DocumentsModel.current_contents_id` 업데이트**
3. ✅ **새로운 버전명(`version_name`) 생성**
4. ✅ **새로운 인덱스/섹션 생성**
5. ✅ **히스토리 기록 생성**
6. ✅ **검색 엔진 업데이트**

### 변경되지 않는 것

1. ❌ **`document_id` (문서의 고유 ID)**
2. ❌ **기존 `DocumentsContentModel` 레코드들 (모든 버전 보존)**
3. ❌ **`DocumentsModel.id`**
4. ❌ **`DocumentsModel.created_at`**

## 버전 관리 방식

이 시스템은 **불변성(Immutability)** 원칙을 따릅니다:

- 기존 데이터는 절대 수정하지 않음
- 변경사항은 새로운 레코드로 기록
- 모든 버전이 보존되어 이력 추적 가능
- `current_contents_id`로 현재 활성 버전 관리

## 예시

### 요청

```bash
PATCH /api/docs/update_doc?workspace_id=ws_123&document_id=doc_abc
```

```json
{
  "name": "업데이트된 문서 제목",
  "summary": "새로운 요약",
  "editor_id": "user_456"
}
```

### 결과

- `document_id`: `doc_abc` (변경 없음)
- 기존 버전: `v1.0` (보존됨)
- 새 버전: `v1.1` (생성됨)
- `current_contents_id`: 새 버전의 content ID로 업데이트

### 응답

새로 생성된 버전(`v1.1`)의 상세 정보가 반환됩니다:

```json
{
  "id": "encrypted_doc_abc",
  "version_name": "v1.1",
  "name": "업데이트된 문서 제목",
  "summary": "새로운 요약",
  ...
}
```

## 관련 파일

- API 엔드포인트: `api/endpoints/documents/documents_endpoint.py` (161-187줄)
- 서비스 레이어: `services/document_service.py` (166-229줄)
- DB 서비스 레이어: `db/services/document/document_service.py` (288-337줄)
- Repository 레이어: `db/repositories/document/document_repository.py` (288-320줄)
- Content Repository: `db/repositories/document/document_contents_repository.py` (184-300줄)
- 버전명 유틸: `utils/version_name_utils.py`

