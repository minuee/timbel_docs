# 문서 버전/이력 버그 수정 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 으로 task 단위 실행. 체크박스(`- [ ]`)로 추적.

**Goal:** 최초 업로드가 단일 버전 `1.0.0`을 남기고(in-place), 편집화면 저장이 새 버전 + 수정 이력을 남기도록 한다.

**Architecture:** `update_content`에 `in_place` 모드를 추가해 `_finalize_doc`이 placeholder `1.0.0`을 제자리 채우게 하고(버전 미증가), `/save_editor`가 KMS replace_blocks 후 DB-계층 `update_document`(버전+이력)를 호출하게 한다.

**Tech Stack:** Python, FastAPI, SQLAlchemy. 테스트: pytest (timbel `aicm_dev_service` 컨테이너의 `/app` 복사본에서 실행 — 로컬은 의존성 미설치).

## Global Constraints
- 이모지 금지(코드/주석/커밋).
- 하드코딩 금지(키워드 enum/정답 문자열).
- 한국어 커밋 메시지(이슈/원인/수정).
- 기존 동작 무회귀: `in_place` 기본값 `False`, `save_editor`의 KMS `replace_blocks` 유지.
- 커밋 trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01HE6cPhMaMkJFVquwB5gtUW`
- 브랜치: feature 브랜치(아래 실행 시 생성), develop/main 직접 커밋 금지.

---

### Task 1: `update_content`에 `in_place` 모드 추가 (Fix ①)

**Files:**
- Modify: `db/repositories/document/document_contents_repository.py` (`update_content`, 현재 L169~352)
- Test: `tests/repositories/test_update_content_in_place.py` (신규)

**Interfaces:**
- Produces: `update_content(..., in_place: bool = False)` — `in_place=True`면 기존 content row 재사용(새 row·`next_version_name` 미생성), outline/index 제자리 갱신.

**구현 요지:**
- 시그니처에 `in_place: bool = False` 추가.
- `in_place=True`일 때: 새 `DocumentsContentModel(...)`을 만드는 대신 `db_document_contents = content`(기존 row)로 두고, 변경 필드(name/summary/ai_summary/keywords/category_id/sources/meta/editor_id/is_temporary)를 기존 row에 set. `version_name`은 건드리지 않는다.
- index: `in_place=True`면 placeholder(빈 outline 가정)이므로 `content.contents`를 새 outline으로 재생성(`get_indexes_ids(content_id=content.id, indexes=new_contents_dict)`). (기존 index가 비어있다는 placeholder 전제 — finalize 전용. 비어있지 않으면 `logger.warning` 후 진행.)
- `in_place=False`면 기존 코드 그대로(무회귀).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/repositories/test_update_content_in_place.py
from unittest.mock import MagicMock
import pytest
from db.repositories.document.document_contents_repository import DB_DocumentContentsRepository
from api.schemas.document_schemas import DocumentUpdate


def _make_repo_with_placeholder():
    repo = DB_DocumentContentsRepository.__new__(DB_DocumentContentsRepository)
    repo.db = MagicMock()
    repo.index_service = MagicMock()
    repo.attachments_service = MagicMock()
    repo.attachments_service.create_attachments_bulk.return_value = []
    # 기존 placeholder content (version 1.0.0, 빈 contents)
    content = MagicMock()
    content.id = "content_100"
    content.document_id = "doc_1"
    content.version_name = "1.0.0"
    content.name = "doc"
    content.attachments = []
    content.contents = []
    repo.get_document_content = MagicMock(return_value=content)
    repo.index_service.create_document_indexes.return_value = [{"id": "idx_1"}]
    return repo, content


def test_in_place_reuses_existing_content_no_version_bump():
    repo, content = _make_repo_with_placeholder()
    update = DocumentUpdate(contents={"outline": [{"title": "T", "blocks": ["b"]}]}, editor_id="u1")
    result, _ = repo.update_content(
        workspace_id="ws", content_id="content_100", update_data=update, in_place=True
    )
    # 같은 row 재사용 — id/version 불변, 새 row add 안 함
    assert result.id == "content_100"
    assert result.version_name == "1.0.0"
    # 새 DocumentsContentModel 을 db.add 로 추가하지 않았다(in_place)
    add_calls = [c for c in repo.db.add.call_args_list]
    assert all(getattr(c.args[0], "id", None) == "content_100" for c in add_calls) or not add_calls
```

- [ ] **Step 2: 실패 확인**

Run(컨테이너): `python -m pytest tests/repositories/test_update_content_in_place.py -q`
Expected: FAIL (`in_place` 인자 없음 → TypeError).

- [ ] **Step 3: `update_content`에 `in_place` 구현**

`def update_content(self, workspace_id, content_id, update_data, processed_contents=None, attachments_obj=None, remove_attachments_ids=None, in_place: bool = False)` 로 시그니처 확장. `in_place=True` 분기에서 기존 `content` row를 재사용하고 `version_name` 미변경, 변경 필드 set, index 재생성. `in_place=False`는 기존 로직 유지.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/repositories/test_update_content_in_place.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add db/repositories/document/document_contents_repository.py tests/repositories/test_update_content_in_place.py
git commit -m "fix(version): update_content in_place 모드 추가 (placeholder 제자리 갱신)"
```

---

### Task 2: `in_place`를 서비스/리포 update_document 경로로 전달

**Files:**
- Modify: `db/services/document/document_contents_service.py` (`update_document_contents`, L138~170)
- Modify: `db/repositories/document/document_repository.py` (`update_document`, L427~468)
- Test: `tests/repositories/test_update_document_in_place.py` (신규)

**Interfaces:**
- Consumes: Task 1의 `update_content(in_place=...)`.
- Produces: `update_document_contents(..., in_place=False)`, `document_repository.update_document(..., in_place=False)`. `in_place=True`면 새 버전 미생성, `document.current_contents_id` 불변.

**구현 요지:**
- `update_document_contents`에 `in_place: bool = False` 추가 → `self.repository.update_content(..., in_place=in_place)` 로 전달.
- `document_repository.update_document`에 `in_place: bool = False` 추가 → `self.doc_contents_service.update_document_contents(..., in_place=in_place)` 로 전달. `in_place=True`면 새 content id가 기존과 같으므로 `document.current_contents_id = updated_content.get("id")`는 그대로 안전(동일 id 재대입).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/repositories/test_update_document_in_place.py
from unittest.mock import MagicMock
from db.repositories.document.document_repository import DB_DocumentRepository
from api.schemas.document_schemas import DocumentUpdate


def test_update_document_passes_in_place_to_contents_service():
    repo = DB_DocumentRepository.__new__(DB_DocumentRepository)
    repo.db = MagicMock()
    doc = MagicMock(); doc.current_contents_id = "content_100"
    repo.get_document = MagicMock(return_value=doc)
    repo.doc_contents_service = MagicMock()
    repo.doc_contents_service.get_document_content.return_value = {"id": "content_100", "is_temporary": False}
    repo.doc_contents_service.update_document_contents.return_value = ({"id": "content_100"}, None)
    update = DocumentUpdate(contents={"outline": []}, editor_id="u1")
    repo.update_document(workspace_id="ws", document_id="enc", update_data=update, in_place=True)
    kwargs = repo.doc_contents_service.update_document_contents.call_args.kwargs
    assert kwargs.get("in_place") is True
```

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest tests/repositories/test_update_document_in_place.py -q` → FAIL(`in_place` 미전달).

- [ ] **Step 3: 두 메서드에 `in_place` 전달 구현.**

- [ ] **Step 4: 통과 확인** — PASS.

- [ ] **Step 5: 커밋**

```bash
git add db/services/document/document_contents_service.py db/repositories/document/document_repository.py tests/repositories/test_update_document_in_place.py
git commit -m "fix(version): in_place 플래그를 update_document 경로로 전달"
```

---

### Task 3: `_finalize_doc`이 in_place로 placeholder 채움 (Fix ① 배선)

**Files:**
- Modify: `api/endpoints/documents/chunk_endpoint.py` (`_finalize_doc`, L307~337)
- Test: `tests/endpoints/test_finalize_in_place.py` (신규)

**Interfaces:**
- Consumes: Task 2의 `repository.update_document(in_place=True)`.

**구현 요지:**
- `_finalize_doc`의 `doc_db.repository.update_document(...)` 호출에 `in_place=True` 추가. 나머지(commit, rag_status=pending_review, 블록 메타 동기화) 동일.

- [ ] **Step 1: 실패 테스트 작성** — `_finalize_doc`이 `repository.update_document`를 `in_place=True`로 호출하는지 검증(repository를 MagicMock 패치).

```python
# tests/endpoints/test_finalize_in_place.py
from unittest.mock import MagicMock, patch
import api.endpoints.documents.chunk_endpoint as ce


def test_finalize_doc_uses_in_place(monkeypatch):
    fake_repo = MagicMock()
    fake_doc_db = MagicMock(); fake_doc_db.repository = fake_repo
    with patch.object(ce, "DB_DocumentService", return_value=fake_doc_db), \
         patch.object(ce, "DatabaseManager") as dm, \
         patch.object(ce, "DocumentService"):
        dm.return_value.get_db_by_url_core.return_value = iter([MagicMock()])
        ce._finalize_doc(workspace_id="ws", token="t", raw_doc_id="d1",
                         outline=[{"title": "T", "blocks": ["b"]}],
                         tenant_id="ten", api_key=None, user_id="u1")
    assert fake_repo.update_document.call_args.kwargs.get("in_place") is True
```

- [ ] **Step 2: 실패 확인** → FAIL(`in_place` 없음).
- [ ] **Step 3: `_finalize_doc`에 `in_place=True` 추가.**
- [ ] **Step 4: 통과 확인** → PASS.
- [ ] **Step 5: 커밋**

```bash
git add api/endpoints/documents/chunk_endpoint.py tests/endpoints/test_finalize_in_place.py
git commit -m "fix(version): 최초 업로드 finalize를 in_place로 → 단일 1.0.0 (이슈: 업로드 시 버전 2개)"
```

---

### Task 4: 편집화면 저장이 버전 + 이력 기록 (Fix ②)

**Files:**
- Modify: `api/endpoints/documents/chunk_endpoint.py` (`SaveEditorRequest` L843, `save_editor` L849~898)
- Test: `tests/endpoints/test_save_editor_history.py` (신규)

**Interfaces:**
- Consumes: 기존 DB-계층 `DB_DocumentService.update_document`(버전+`create_history("edited_doc")`, KMS 재색인 안 함).

**구현 요지:**
- `SaveEditorRequest`에 `editor_id: str` 추가(FE가 편집자 전달).
- `save_editor`: `rag_client.replace_blocks(...)` 성공 후, 새 DB 세션으로 `DB_DocumentService(db).update_document(workspace_id, document_id=encrypt_str(rag_doc_id), update_data=DocumentUpdate(contents={"outline": body.outline}, editor_id=body.editor_id))` 호출 → 새 버전 + 이력. best-effort 실패 로깅(KMS 저장은 이미 됨). `rag_doc_id == aicm document_id`(force-id 통일) 이용, `encrypt_str` 로 암호화 전달.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/endpoints/test_save_editor_history.py
import asyncio
from unittest.mock import MagicMock, patch
import api.endpoints.documents.chunk_endpoint as ce
from api.endpoints.documents.chunk_endpoint import SaveEditorRequest


def test_save_editor_records_version_and_history():
    body = SaveEditorRequest(workspace_id="ws", rag_doc_id="d1",
                             outline=[{"title": "T", "blocks": ["b"]}], editor_id="u1")
    fake_doc_db = MagicMock()
    rag_client = MagicMock(); rag_client.replace_blocks.return_value = {"ok": True}
    with patch.object(ce, "_outline_to_blocks", return_value=[{"id": "b"}]), \
         patch.object(ce, "build_rag_client", return_value=rag_client), \
         patch.object(ce, "DB_DocumentService", return_value=fake_doc_db), \
         patch.object(ce, "DatabaseManager") as dm, \
         patch("api.endpoints.documents.chunk_endpoint.WorkspaceRagConfigService") as cfg, \
         patch("utils.cipher_utils.encrypt_str", return_value="enc_d1"):
        dm.return_value.get_db_by_url_core.return_value = iter([MagicMock()])
        cfg.return_value.get_rag_config.return_value = MagicMock(tenant_id="ten", repository_id="repo")
        cfg.return_value.get_api_key.return_value = "key"
        asyncio.get_event_loop().run_until_complete(ce.save_editor(body, token="t"))
    # 편집 저장이 DB-계층 update_document(버전+이력)를 호출했는가
    assert fake_doc_db.update_document.called
    kwargs = fake_doc_db.update_document.call_args.kwargs
    assert kwargs["update_data"].editor_id == "u1"
```

- [ ] **Step 2: 실패 확인** → FAIL(save_editor가 update_document 미호출 / editor_id 필드 없음).
- [ ] **Step 3: `SaveEditorRequest.editor_id` 추가 + `save_editor`에 버전+이력 호출 구현.**
- [ ] **Step 4: 통과 확인** → PASS.
- [ ] **Step 5: 커밋**

```bash
git add api/endpoints/documents/chunk_endpoint.py tests/endpoints/test_save_editor_history.py
git commit -m "fix(history): 편집화면 저장 시 버전+수정이력 기록 (이슈: 편집 저장이 이력에 안 남음)"
```

---

## E2E 검증 (전체 task 후, timbel)
- 새 문서 업로드 → 4스텝 완료 → `aicm_documents_contents` 버전 **1건(1.0.0)**, `aicm_documents_hist` **1건(생성)**.
- 편집화면에서 한 블럭 수정 후 저장 → 버전 **+1**, hist **+1(`edited_doc`)**, 이력 상세 화면 좌/우 diff 표시.
- 기존 메타 편집(`/update_doc`) 정상(버전+이력 무변화).
