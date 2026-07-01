"""ActivationService — 상태 전이 + 감사 + 원자 트랜잭션."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import text
from .state import ActivationState, assert_transition, InvalidTransition


_DOC_TYPES = {"document", "crawl_digest", "agent_news_report", "stock_snapshot"}


class UnknownArtifactType(ValueError):
    pass


class ArtifactNotFound(LookupError):
    pass


def _json(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


class ActivationService:
    def __init__(self, db_session, *, dependency_discover=None, overlap_analyzer=None):
        """
        :param db_session: SQLAlchemy session (sync).
        :param dependency_discover: optional DependencyDiscover. None 이면 skill_draft
            의 dependency 후크를 skip (graceful degrade).
        :param overlap_analyzer: optional KnowledgeOverlapAnalyzer. None 이면
            document 활성화의 overlap 후크를 skip.
        """
        self.db = db_session
        self.dependency_discover = dependency_discover
        self.overlap_analyzer = overlap_analyzer

    def _load(self, artifact_type: str, artifact_id: str) -> dict:
        if artifact_type in _DOC_TYPES:
            row = self.db.execute(
                text(
                    "SELECT id, status, processing_meta FROM documents "
                    "WHERE id=CAST(:id AS uuid) FOR UPDATE"
                ),
                {"id": artifact_id},
            ).mappings().first()
        elif artifact_type == "skill_draft":
            row = self.db.execute(
                text(
                    "SELECT id, status_v2 AS status, processing_meta FROM skill_drafts "
                    "WHERE id=CAST(:id AS uuid) FOR UPDATE"
                ),
                {"id": artifact_id},
            ).mappings().first()
        elif artifact_type == "cc_pair":
            row = self.db.execute(
                text(
                    "SELECT id, status, processing_meta FROM connector_credential_pairs "
                    "WHERE id=:id FOR UPDATE"
                ),
                {"id": artifact_id},
            ).mappings().first()
        else:
            raise UnknownArtifactType(artifact_type)
        if row is None:
            raise ArtifactNotFound(f"{artifact_type}:{artifact_id}")
        return dict(row)

    def _update_status(self, artifact_type: str, artifact_id: str,
                       new_status: ActivationState, activation_patch: dict) -> None:
        patch_sql = (
            "processing_meta = jsonb_set("
            "COALESCE(processing_meta,'{}'::jsonb), '{activation}', "
            "COALESCE(processing_meta->'activation','{}'::jsonb) || CAST(:patch AS jsonb), "
            "true)"
        )
        if artifact_type in _DOC_TYPES:
            self.db.execute(
                text(
                    f"UPDATE documents SET status=:s, {patch_sql}, updated_at=NOW() "
                    f"WHERE id=CAST(:id AS uuid)"
                ),
                {"s": new_status.value, "patch": _json(activation_patch), "id": artifact_id},
            )
        elif artifact_type == "skill_draft":
            self.db.execute(
                text(
                    f"UPDATE skill_drafts SET status_v2=:s, {patch_sql} "
                    f"WHERE id=CAST(:id AS uuid)"
                ),
                {"s": new_status.value, "patch": _json(activation_patch), "id": artifact_id},
            )
        elif artifact_type == "cc_pair":
            self.db.execute(
                text(
                    f"UPDATE connector_credential_pairs SET status=:s, {patch_sql} "
                    f"WHERE id=:id"
                ),
                {"s": new_status.value, "patch": _json(activation_patch), "id": artifact_id},
            )

    def approve(self, artifact_type: str, artifact_id: str, *,
                user_id: str, action: str = "add",
                target_doc_ids: list[str] | None = None,
                execution_policy: dict | None = None,
                note: str | None = None) -> dict:
        row = self._load(artifact_type, artifact_id)
        src = ActivationState(row["status"])
        if src == ActivationState.active:
            return {"status": "active", "idempotent": True}
        assert_transition(src, ActivationState.active)

        meta = row["processing_meta"] or {}
        existing = meta.get("activation") or {}
        patch = {
            "approved_by": existing.get("approved_by") or user_id,
            "approved_at": existing.get("approved_at") or datetime.now(timezone.utc).isoformat(),
            "approved_action": action,
            "auto_approved": False,
        }
        if note:
            patch["approve_note"] = note
        if execution_policy:
            patch["execution_policy"] = execution_policy

        # skill_draft 활성화 시 DependencyDiscover 자동 호출.
        # — side_effect_level / consequential / required_connectors 를
        # processing_meta.activation.dependencies 에 기록해 이후 ExecutionPolicyGuard
        # 가 참조 가능. discover 미주입 / 분석 실패 시 graceful degrade (skip).
        if (
            artifact_type == "skill_draft"
            and self.dependency_discover is not None
        ):
            dep_payload = self._run_dependency_discover(artifact_id, meta)
            if dep_payload is not None:
                patch["dependencies"] = dep_payload

        # document 활성화 시 KnowledgeOverlapAnalyzer 자동 호출.
        # — duplicate / supersedes / conflicts 결정을 processing_meta.activation.overlap
        # 에 기록. 호출자가 supersede 액션을 명시 (`action`/`target_doc_ids`) 하지 않은
        # 케이스에서도 후속 운영 결정 (예: 자동 archiver) 이 참고할 수 있다.
        # analyzer 미주입 / 분석 실패 / 요약 메타 부재 시 graceful degrade (skip).
        if (
            artifact_type in _DOC_TYPES
            and self.overlap_analyzer is not None
        ):
            overlap_payload = self._run_overlap_analyzer(artifact_id, meta)
            if overlap_payload is not None:
                patch["overlap"] = overlap_payload

        self._update_status(artifact_type, artifact_id, ActivationState.active, patch)

        archived: list[str] = []
        if action in ("replace", "merge") and target_doc_ids:
            for tid in target_doc_ids:
                self._archive_doc(tid, superseded_by=artifact_id, user_id=user_id)
                archived.append(tid)
            self._update_status(artifact_type, artifact_id, ActivationState.active,
                                {"supersedes": target_doc_ids})

        self.db.commit()
        return {"status": "active", "supersedes": target_doc_ids or [], "archived": archived}

    def reject(self, artifact_type: str, artifact_id: str, *,
               user_id: str, reason: str) -> dict:
        row = self._load(artifact_type, artifact_id)
        src = ActivationState(row["status"])
        assert_transition(src, ActivationState.rejected)
        self._update_status(artifact_type, artifact_id, ActivationState.rejected, {
            "rejected_by": user_id,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "rejected_reason": reason,
        })
        self.db.commit()
        return {"status": "rejected"}

    def defer(self, artifact_type: str, artifact_id: str, *,
              user_id: str, note: str) -> dict:
        row = self._load(artifact_type, artifact_id)
        src = ActivationState(row["status"])
        if src != ActivationState.pending_review:
            raise InvalidTransition(src, ActivationState.pending_review)
        self._update_status(artifact_type, artifact_id, ActivationState.pending_review, {
            "deferred_by": user_id,
            "deferred_at": datetime.now(timezone.utc).isoformat(),
            "defer_note": note,
        })
        self.db.commit()
        return {"status": "pending_review", "note": note}

    def deactivate(self, artifact_type: str, artifact_id: str, *,
                   user_id: str, reason: str) -> dict:
        row = self._load(artifact_type, artifact_id)
        src = ActivationState(row["status"])
        assert_transition(src, ActivationState.archived)
        self._update_status(artifact_type, artifact_id, ActivationState.archived, {
            "deactivated_by": user_id,
            "deactivated_at": datetime.now(timezone.utc).isoformat(),
            "deactivated_reason": reason,
        })
        self.db.commit()
        return {"status": "archived"}

    def reactivate(self, artifact_type: str, artifact_id: str, *, user_id: str) -> dict:
        row = self._load(artifact_type, artifact_id)
        src = ActivationState(row["status"])
        assert_transition(src, ActivationState.active)
        self._update_status(artifact_type, artifact_id, ActivationState.active, {
            "reactivated_by": user_id,
            "reactivated_at": datetime.now(timezone.utc).isoformat(),
        })
        self.db.commit()
        return {"status": "active"}

    def verify(self, artifact_type: str, artifact_id: str, *,
               user_id: str, note: str | None = None) -> dict:
        from .trust_score import compute_trust_score

        row = self._load(artifact_type, artifact_id)
        meta = row["processing_meta"] or {}
        if artifact_type in _DOC_TYPES:
            created_row = self.db.execute(
                text("SELECT created_at FROM documents WHERE id=CAST(:id AS uuid)"),
                {"id": artifact_id},
            ).mappings().first()
        elif artifact_type == "skill_draft":
            created_row = self.db.execute(
                text("SELECT created_at FROM skill_drafts WHERE id=CAST(:id AS uuid)"),
                {"id": artifact_id},
            ).mappings().first()
        else:
            created_row = self.db.execute(
                text("SELECT created_at FROM connector_credential_pairs WHERE id=:id"),
                {"id": artifact_id},
            ).mappings().first()
        created_at = created_row["created_at"]
        now = datetime.now(timezone.utc)
        score = compute_trust_score(
            created_at=created_at,
            verified_at=now,
            hit_count_30d=(meta.get("activation", {}).get("hit_count_30d") or 0),
            supersede_count=len(meta.get("activation", {}).get("supersedes") or []),
            now=now,
        )
        patch = {
            "verified_by": user_id,
            "verified_at": now.isoformat(),
            "trust_score": score,
        }
        if note:
            patch["verify_note"] = note
        src = ActivationState(row["status"])
        self._update_status(artifact_type, artifact_id, src, patch)
        self.db.commit()
        return {"verified_at": now.isoformat(), "trust_score": score}

    def _run_dependency_discover(self, draft_id: str, meta: dict) -> dict | None:
        """skill_draft 의 yaml 을 로드해 DependencyDiscover 를 동기 실행.

        DependencyDiscover.analyze 는 async — 활성화 경로는 sync 라서 asyncio.run
        으로 한 번 감싼다 (단, 이미 실행 중인 루프가 있으면 skip).
        실패는 모두 swallow → activation 자체는 막지 않는다.
        """
        import asyncio
        try:
            row = self.db.execute(
                text(
                    "SELECT draft_yaml FROM skill_drafts WHERE id=CAST(:id AS uuid)"
                ),
                {"id": draft_id},
            ).mappings().first()
            if row is None or not row.get("draft_yaml"):
                return None
            yaml_text = row["draft_yaml"]
            try:
                import yaml as _yaml
                skill_yaml = _yaml.safe_load(yaml_text) or {}
            except Exception:
                # yaml 파싱 실패 — discover 만 skip (activation 은 진행).
                return {"error": "yaml_parse_failed"}
            tenant_id = (meta.get("tenant_id") or "t_default") if isinstance(meta, dict) else "t_default"
            try:
                loop = asyncio.get_running_loop()
                # 이미 루프 안 — async 컨텍스트에서 호출하지 않는 것이 원칙.
                # 여기서는 fall-back 으로 분석을 task 로 떠넘기지 않고 skip.
                return {"error": "running_loop_unsupported"}
            except RuntimeError:
                pass
            report = asyncio.run(self.dependency_discover.analyze(
                skill_yaml=skill_yaml, tenant_id=tenant_id,
            ))
            return report.to_dict()
        except Exception as e:
            return {"error": f"discover_failed: {type(e).__name__}: {e}"}

    def _run_overlap_analyzer(self, doc_id: str, meta: dict) -> dict | None:
        """document 의 요약을 사용해 overlap 분석을 동기 실행.

        요약은 processing_meta.summary 에서 우선, 없으면 documents.title 로 fallback.
        tenant_id 는 documents 행 자체에서 로드 (meta 와 별개로 신뢰값).
        실패는 모두 swallow → activation 자체는 진행.
        """
        import asyncio
        try:
            row = self.db.execute(
                text(
                    "SELECT title, tenant_id::text AS tenant_id FROM documents "
                    "WHERE id=CAST(:id AS uuid)"
                ),
                {"id": doc_id},
            ).mappings().first()
            if row is None:
                return None
            tenant_id = row.get("tenant_id") or "t_default"
            summary = (meta or {}).get("summary") or row.get("title") or ""
            if not summary:
                return {"error": "no_summary_or_title"}
            try:
                asyncio.get_running_loop()
                # 활성화 경로는 sync — 실행 중 루프가 있으면 충돌 회피로 skip.
                return {"error": "running_loop_unsupported"}
            except RuntimeError:
                pass
            report = asyncio.run(self.overlap_analyzer.analyze(
                tenant_id=tenant_id, new_doc_id=doc_id, new_summary=summary,
            ))
            return report.to_dict()
        except Exception as e:
            return {"error": f"overlap_failed: {type(e).__name__}: {e}"}

    def _archive_doc(self, doc_id: str, *, superseded_by: str, user_id: str) -> None:
        self.db.execute(text("""
            UPDATE documents
               SET status='archived',
                   processing_meta = jsonb_set(
                     COALESCE(processing_meta,'{}'::jsonb), '{activation}',
                     COALESCE(processing_meta->'activation','{}'::jsonb) || CAST(:p AS jsonb),
                     true),
                   updated_at=NOW()
             WHERE id=CAST(:id AS uuid) AND status='active'
        """), {"id": doc_id, "p": _json({
            "superseded_by": superseded_by,
            "superseded_at": datetime.now(timezone.utc).isoformat(),
            "superseded_authorized_by": user_id,
        })})
