# 문서 버전/이력 버그 수정 설계

작성일: 2026-06-24

## 문제 (테스터 재현)

1. **최초 업로드 시 버전 2개** — 업로드 직후 `1.0.0`으로 보이다가 파이프라인 4스텝(KMS 파싱/세그먼트/메타/임베딩) 완료 후 `1.0.1`로 바뀐다. 단일 업로드인데 버전이 2개 생긴다.
2. **편집화면 저장 시 이력 없음** — 편집화면(`/save_editor`)에서 저장해도 문서 이력에 남지 않는다. (정식 메타 편집 `/update_doc`은 이력이 정상 기록됨 — 이력 인프라 자체는 동작.)

## 근본 원인 (코드 추적 결과)

### 데이터 모델
- `aicm_documents_contents`: 버전 row. `version_name`(`1.0.0` 등), `contents`(index id 리스트), `document_id`, `created_at`.
- `aicm_documents_hist`: 이력 row. `content_id`(특정 버전 FK), `user_id`, `history`(타입), `details`. 이력 상세 화면은 이력 항목의 버전 contents와 현재 버전을 비교(diff)해 표시한다.
- 규칙: 의미있는 편집 = (새 버전 contents row) + (그 버전을 가리키는 hist row). 이력을 쓰는 곳은 **DB-계층 서비스** `DB_DocumentService.update_document`(`db/services/document/document_service.py:749`, `create_history("edited_doc")`)와 `create_document`(생성 이력) 둘뿐.

### 버그 ① 업로드 버전 2개
업로드 파이프라인(`api/endpoints/documents/chunk_endpoint.py`):
1. `_register_processing_doc`(L288): 빈 outline `{"outline": []}`로 `add_doc` → `create_document` → **버전 `1.0.0` 생성**(+생성 이력).
2. 4스텝 파이프라인.
3. `_finalize_doc`(L321): 파싱된 outline을 **리포지토리** `update_document`로 채움 → `update_content`가 `next_version_name`을 타서 **새 버전 `1.0.1` 생성**.

즉 `1.0.0`=빈 껍데기, `1.0.1`=실제 내용. finalize가 기존 `1.0.0`을 제자리(in-place)로 채우지 않고 새 버전을 만드는 것이 원인. (리포 경로라 이력도 안 남김.)

### 버그 ② 편집 저장 이력 없음
`/save_editor`(L849)는 outline을 블럭으로 변환해 **KMS `replace_blocks`만 호출**하고 aicm DB(버전·이력)를 전혀 건드리지 않는다. 따라서 버전도 이력도 안 생긴다. (`_finalize_doc`은 `/upload`에서만 호출되고 `save_editor` 경로엔 없음 → 중복 처리 우려 없음.)

## 수정 설계

### Fix ① 업로드 단일 `1.0.0` (in-place)
- `update_content`(리포)에 **`in_place: bool = False`** 파라미터 추가. `True`면 새 `DocumentsContentModel`을 만들지 않고 **기존 content row를 재사용**해 outline/index를 제자리 갱신(버전명 불변, `next_version_name` 미호출). 기존 index row는 교체.
- `update_document_contents`(서비스)·`document_repository.update_document`에 `in_place` 전달 경로 추가(기본 `False` → 기존 동작 무회귀).
- `_finalize_doc`은 `in_place=True` 경로로 기존 `1.0.0`을 채운다.
- 결과: 업로드 = 버전 `1.0.0` 하나 + 이력 1건(생성).

### Fix ② 편집 저장 버전 + 이력
- `SaveEditorRequest`에 **`editor_id: str`** 추가(FE가 편집자 전달 — 이력 user_id 용).
- `/save_editor`: KMS `replace_blocks` 성공 후, **DB-계층 서비스** `DB_DocumentService.update_document`를 편집 outline으로 호출 → 새 버전 + `create_history("edited_doc")`. 이 서비스는 KMS 재색인을 하지 않으므로 replace_blocks와 중복되지 않는다.
- `document_id`는 `rag_doc_id`와 동일(force-id 통일)하므로 암호화해 전달.
- 결과: 편집 저장 = 버전 +1 + 이력 +1("edited_doc"), 이력 상세 diff 정상.

## 무회귀 보장
- `in_place` 기본값 `False` → 기존 모든 편집/업서트 경로는 그대로 새 버전 생성.
- `save_editor`의 KMS `replace_blocks`는 유지, aicm 버전·이력 기록만 추가.
- `_finalize_doc`만 `in_place=True`로 전환.

## 검증 기준
- 업로드 후: `aicm_documents_contents` 버전 1건(`1.0.0`), `aicm_documents_hist` 1건(생성).
- 편집 저장 후: 버전 +1, hist +1(`edited_doc`, content_id=새 버전), 이력 상세 화면에 좌(구버전)/우(현재) diff 표시.
- 기존 메타 편집(`/update_doc`) 동작 무변화.
