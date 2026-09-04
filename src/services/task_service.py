import copy
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.database.config.database import SessionLocal
from src.database.models.models import (
    AudioFile,
    Case,
    CaseParticipant,
    CasePriority,
    CaseStatus,
    ParticipantRole,
    Task as DBTask,
    User,
)
from src.services.investigation.contracts import sha256_canonical_json

logger = logging.getLogger(__name__)

CANONICAL_STATUSES = {
    "uploaded",
    "transcribing",
    "transcribed",
    "summarizing",
    "summarized",
    "visualizing",
    "visualized",
    "failed",
}

LEGACY_STATUS_ALIASES = {
    "pending": "uploaded",
    "processing": "transcribing",
}

RESULT_FIELD_ALIASES = {
    "transcript": "transcription",
    "context": "context_analysis",
    "visualization": "visualization_data",
}

# Summary artifacts are complete snapshots. Merging them recursively can retain
# stale internal fields when a newer public projection intentionally removes keys.
ATOMIC_RESULT_FIELDS = frozenset(
    {
        "context_analysis",
        "summary_authority",
        "summary_error",
        "summary_notice",
        "summary_preview",
        "summary_runtime",
    }
)

RESULT_FIELDS = {
    "transcription",
    "summary",
    "segments",
    "duration",
    "context_analysis",
    "visualization_data",
    "has_visualization",
    "audio_id",
    "download_url",
    "language",
    "confidence",
    "processing_time",
    "formatted_transcript",
    "transcript_file",
    "has_diarization",
    "num_speakers",
    "speed_factor",
    "diarization_method",
    "transcription_time",
    "diarization_time",
    "fast_mode",
    "caption",
    "model_name",
    "summary_model",
    "summary_type",
    "summary_variants",
    "requested_engine",
    "engine_used",
    "fallback_reason",
    "audio_sha256",
    "audio_integrity_status",
}


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    return {}


def released_investigation_run_identity(value: Any) -> tuple[str, str, str] | None:
    """Read routing identity only; this never rehydrates release authority."""

    if not isinstance(value, dict):
        return None
    if (
        value.get("schema_version") != "investigation-run-v1.0"
        or value.get("run_status") != "success"
    ):
        return None
    provenance = value.get("provenance")
    run_id = value.get("run_id")
    source_revision_id = (
        provenance.get("source_revision_id")
        if isinstance(provenance, dict)
        else None
    )
    if not isinstance(run_id, str) or not run_id.strip():
        return None
    if not isinstance(source_revision_id, str) or not source_revision_id.strip():
        return None
    return run_id, source_revision_id, sha256_canonical_json(value)


def _released_visualization_authority(value: Any) -> Dict[str, Any] | None:
    """Extract hash-bound semantic registries from the stored released run."""

    identity = released_investigation_run_identity(value)
    if identity is None or not isinstance(value, dict):
        return None
    ledger = value.get("ledger")
    projections = value.get("projections")
    if not isinstance(ledger, dict) or not isinstance(projections, dict):
        return None
    analysis = projections.get("analysis")
    summary = projections.get("summary")
    if not isinstance(analysis, dict) or not isinstance(summary, dict):
        return None

    released_refs = analysis.get("released_claim_refs")
    source_refs = analysis.get("source_attributed_claim_refs") or []
    fact_refs = analysis.get("fact_claim_refs") or []
    if not isinstance(released_refs, list) or not all(
        isinstance(ref, str) and ref.strip() for ref in released_refs
    ):
        return None
    if not all(isinstance(ref, str) and ref.strip() for ref in source_refs):
        return None
    if not all(isinstance(ref, str) and ref.strip() for ref in fact_refs):
        return None
    released_set = set(released_refs)
    source_set = set(source_refs)
    fact_set = set(fact_refs)
    if (
        len(released_set) != len(released_refs)
        or source_set & fact_set
        or source_set | fact_set != released_set
    ):
        return None

    claims = ledger.get("claims")
    evidence = ledger.get("evidence")
    concepts = ledger.get("concepts") or []
    if not isinstance(claims, list) or not isinstance(evidence, list):
        return None
    claim_by_id = {
        item.get("claim_id"): item
        for item in claims
        if isinstance(item, dict)
        and isinstance(item.get("claim_id"), str)
        and item.get("claim_id")
    }
    if not released_set.issubset(claim_by_id):
        return None

    narrative = summary.get("narrative")
    if not isinstance(narrative, dict):
        return None
    sentences = narrative.get("overview")
    if not isinstance(sentences, list):
        return None
    all_sentences = list(sentences)
    groups = narrative.get("thematic_groups") or []
    if not isinstance(groups, list):
        return None
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("sentences"), list):
            return None
        all_sentences.extend(group["sentences"])
    sentence_texts: Dict[str, List[str]] = {ref: [] for ref in released_refs}
    for sentence in all_sentences:
        if not isinstance(sentence, dict):
            return None
        text = sentence.get("text")
        claim_refs = sentence.get("claim_refs")
        if not isinstance(text, str) or not text.strip() or not isinstance(
            claim_refs, list
        ):
            return None
        for claim_ref in claim_refs:
            if claim_ref in sentence_texts:
                sentence_texts[claim_ref].append(text)
    if any(len(values) != 1 for values in sentence_texts.values()):
        return None

    expected_claims: Dict[str, Dict[str, str]] = {}
    for claim_ref in released_refs:
        claim = claim_by_id[claim_ref]
        claim_type = claim.get("claim_type")
        if not isinstance(claim_type, str) or not claim_type.strip():
            return None
        expected_claims[claim_ref] = {
            "label": sentence_texts[claim_ref][0],
            "type": claim_type,
            "epistemic_type": (
                "source_attributed" if claim_ref in source_set else "fact"
            ),
        }

    expected_evidence: Dict[str, Dict[str, Any]] = {}
    evidence_fields = (
        "evidence_id",
        "segment_id",
        "quote_exact",
        "quote_sha256",
        "source_sha256",
        "start_seconds",
        "end_seconds",
        "speaker_id",
    )
    for item in evidence:
        if not isinstance(item, dict):
            return None
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            return None
        payload = {
            field: item[field]
            for field in evidence_fields
            if field in item and item[field] is not None
        }
        payload["source_revision_id"] = identity[1]
        if evidence_id in expected_evidence or payload.get("evidence_id") != evidence_id:
            return None
        expected_evidence[evidence_id] = payload

    expected_concepts: Dict[str, Dict[str, Any]] = {}
    if not isinstance(concepts, list):
        return None
    for item in concepts:
        if not isinstance(item, dict):
            return None
        concept_id = item.get("concept_id")
        concept_type = item.get("concept_type")
        surface = item.get("surface")
        if not all(
            isinstance(part, str) and part.strip()
            for part in (concept_id, concept_type, surface)
        ):
            return None
        expected_concepts[concept_id] = {
            "type": concept_type,
            "value": surface,
            "role": item.get("role"),
        }
    return {
        "identity": identity,
        "claims": expected_claims,
        "evidence": expected_evidence,
        "concepts": expected_concepts,
    }


def extract_visualization_payload(
    value: Any,
    *,
    expected_run_id: str | None = None,
    expected_source_revision_id: str | None = None,
    expected_release_subject_sha256: str | None = None,
    expected_released_run: Any = None,
) -> Any:
    """Return an artifact only when it matches the active released run identity."""

    if not isinstance(value, dict):
        return None
    if "visualization_data" in value:
        return extract_visualization_payload(
            value["visualization_data"],
            expected_run_id=expected_run_id,
            expected_source_revision_id=expected_source_revision_id,
            expected_release_subject_sha256=expected_release_subject_sha256,
            expected_released_run=expected_released_run,
        )
    if "data" in value and (
        "visualization_type" in value
        or value.get("status") in {"visualization_ready", "visualized", "success"}
        or "task_id" in value
    ):
        return extract_visualization_payload(
            value["data"],
            expected_run_id=expected_run_id,
            expected_source_revision_id=expected_source_revision_id,
            expected_release_subject_sha256=expected_release_subject_sha256,
            expected_released_run=expected_released_run,
        )
    if "result" in value and value.get("status") == "success":
        return extract_visualization_payload(
            value["result"],
            expected_run_id=expected_run_id,
            expected_source_revision_id=expected_source_revision_id,
            expected_release_subject_sha256=expected_release_subject_sha256,
            expected_released_run=expected_released_run,
        )
    if (
        not expected_run_id
        or not expected_source_revision_id
        or not expected_release_subject_sha256
    ):
        return None
    try:
        from src.services.visualization import InvestigationVisualization

        artifact = InvestigationVisualization.model_validate(value)
    except (ImportError, TypeError, ValueError):
        return None
    if (
        artifact.run_id != expected_run_id
        or artifact.source_revision_id != expected_source_revision_id
        or artifact.release_subject_sha256 != expected_release_subject_sha256
    ):
        return None
    if expected_released_run is not None:
        authority = _released_visualization_authority(expected_released_run)
        if authority is None or authority["identity"] != (
            expected_run_id,
            expected_source_revision_id,
            expected_release_subject_sha256,
        ):
            return None
        expected_claims = authority["claims"]
        claim_nodes = {node.id: node for node in artifact.nodes if node.kind == "claim"}
        if set(claim_nodes) != set(expected_claims):
            return None
        for claim_ref, expected in expected_claims.items():
            node = claim_nodes[claim_ref]
            if (
                node.claim_refs != [claim_ref]
                or node.label != expected["label"]
                or node.type != expected["type"]
                or node.epistemic_type != expected["epistemic_type"]
            ):
                return None

        artifact_claim_refs = {
            claim_ref
            for item in [*artifact.nodes, *artifact.edges, *artifact.extracted_entities]
            for claim_ref in item.claim_refs
        }
        artifact_claim_refs.update(item.claim_ref for item in artifact.timeline)
        artifact_claim_refs.update(item.claim_ref for item in artifact.main_events)
        if not artifact_claim_refs.issubset(expected_claims):
            return None

        expected_evidence = authority["evidence"]
        all_evidence = [
            evidence
            for item in [
                *artifact.nodes,
                *artifact.edges,
                *artifact.timeline,
                *artifact.main_events,
                *artifact.extracted_entities,
            ]
            for evidence in item.evidence
        ]
        if any(
            expected_evidence.get(evidence.evidence_id)
            != evidence.model_dump(mode="json", exclude_none=True)
            for evidence in all_evidence
        ):
            return None

        expected_concepts = authority["concepts"]
        concept_nodes = [node for node in artifact.nodes if node.kind == "concept"]
        for node in concept_nodes:
            expected = expected_concepts.get(node.id)
            if expected is None or (
                node.type != expected["type"]
                or node.label != expected["value"]
                or node.role != expected["role"]
            ):
                return None
        for entity in artifact.extracted_entities:
            expected = expected_concepts.get(entity.id)
            if expected is None or (
                entity.type != expected["type"]
                or entity.value != expected["value"]
                or entity.context != expected["role"]
            ):
                return None

        for item in artifact.timeline:
            expected = expected_claims[item.claim_ref]
            if (
                item.event != expected["label"]
                or item.epistemic_type != expected["epistemic_type"]
            ):
                return None
        for item in artifact.main_events:
            expected = expected_claims[item.claim_ref]
            if (
                item.event != expected["label"]
                or item.type != expected["type"]
                or item.epistemic_type != expected["epistemic_type"]
            ):
                return None
    return artifact.model_dump(mode="json", exclude_none=True)


def extract_active_visualization_payload(result: Any) -> Any:
    """Project the visualization visible for the current stored release identity."""

    if not isinstance(result, dict):
        return None
    identity = released_investigation_run_identity(
        result.get("released_investigation_run")
    )
    if identity is None:
        return None
    return extract_visualization_payload(
        result.get("visualization_data"),
        expected_run_id=identity[0],
        expected_source_revision_id=identity[1],
        expected_release_subject_sha256=identity[2],
        expected_released_run=result.get("released_investigation_run"),
    )


def _deep_merge(
    base: Dict[str, Any],
    patch: Dict[str, Any],
    *,
    bind_visualization: bool = True,
) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if key == "has_visualization":
            continue
        if key == "summary_variants" and isinstance(value, dict) and isinstance(merged.get(key), dict):
            variants = copy.deepcopy(merged[key])
            variants.update(copy.deepcopy(value))
            merged[key] = variants
        elif key in ATOMIC_RESULT_FIELDS:
            merged[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(
                merged[key],
                value,
                bind_visualization=False,
            )
        else:
            merged[key] = copy.deepcopy(value)
    if bind_visualization and (
        "visualization_data" in patch
        or "released_investigation_run" in patch
    ):
        identity = released_investigation_run_identity(
            merged.get("released_investigation_run")
        )
        merged["visualization_data"] = (
            extract_visualization_payload(
                merged.get("visualization_data"),
                expected_run_id=identity[0],
                expected_source_revision_id=identity[1],
                expected_release_subject_sha256=identity[2],
                expected_released_run=merged.get("released_investigation_run"),
            )
            if identity is not None
            else None
        )
        merged["has_visualization"] = bool(merged.get("visualization_data"))
    return merged


def canonical_status(status: str | None, result: Dict[str, Any] | None = None) -> str | None:
    if not status:
        return status
    if status in CANONICAL_STATUSES:
        return status
    if status == "completed":
        result = result or {}
        if result.get("has_visualization") or result.get("visualization_data"):
            return "visualized"
        if result.get("summary"):
            return "summarized"
        if result.get("transcription") or result.get("transcript") or result.get("text"):
            return "transcribed"
        return "transcribed"
    return LEGACY_STATUS_ALIASES.get(status, status)


def effective_task_status(task_status: str | None, audio_status: str | None = None, result: Dict[str, Any] | None = None) -> str | None:
    status = canonical_status(task_status, result)
    if status:
        return status
    return canonical_status(audio_status, result)


def _sync_audio_status(db: Session, task: DBTask, status: str | None) -> None:
    if not status:
        return
    normalized = canonical_status(status, _as_dict(task.result))
    audio_files = list(task.audio_files or [])
    if not audio_files:
        audio_files = db.query(AudioFile).filter(AudioFile.task_id == task.id).all()
    for audio in audio_files:
        audio.status = normalized
        audio.updated_at = datetime.utcnow()


def _task_to_dict(task: DBTask) -> Dict[str, Any]:
    result = _as_dict(task.result)
    audio = task.audio_files[0] if task.audio_files else None
    if audio:
        result.setdefault("audio_id", audio.id)
        result.setdefault("download_url", f"/api/v1/audio/{audio.id}/download")

    data = {
        "id": task.id,
        "filename": task.filename,
        "status": effective_task_status(task.status, audio.status if audio else None, result),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "result": result,
        "error": task.error,
        "case_id": task.case_id,
        "user_id": task.user_id,
    }
    for key, value in result.items():
        data.setdefault(key, value)
    data.setdefault("transcript", result.get("transcription"))
    return data


def _get_actor(db: Session, user_id: int | None) -> User | None:
    if user_id:
        return db.query(User).filter(User.id == user_id).first()
    return db.query(User).filter(User.username == "admin").first()


def create_task(
    filename: str,
    case_id: int | None = None,
    db: Session | None = None,
    user_id: int | None = None,
    commit: bool = True,
) -> Optional[Dict[str, Any]]:
    own_session = db is None
    db = db or SessionLocal()
    try:
        actor = _get_actor(db, user_id)
        if not actor:
            logger.error("Cannot create task without a valid actor/admin user")
            return None

        if case_id is not None:
            case = db.query(Case).filter(Case.id == case_id).first()
            if not case:
                logger.error("Case with id %s does not exist", case_id)
                return None
        else:
            status = db.query(CaseStatus).filter(CaseStatus.status_name == "active").first()
            priority = db.query(CasePriority).filter(CasePriority.priority_name == "high").first()
            if not status or not priority:
                logger.error("Missing default case status or priority")
                return None
            case = Case(
                title=filename,
                case_code=str(uuid.uuid4()),
                description=None,
                status_id=status.id,
                priority_id=priority.id,
                created_by=actor.id,
            )
            db.add(case)
            db.flush()
            owner_role = db.query(ParticipantRole).filter(ParticipantRole.role_name == "owner").first()
            if owner_role:
                db.add(
                    CaseParticipant(
                        case_id=case.id,
                        user_id=actor.id,
                        role_id=owner_role.id,
                        is_active=True,
                    )
                )

        now = datetime.utcnow()
        task = DBTask(
            id=str(uuid.uuid4()),
            filename=filename,
            status="pending",
            case_id=case.id,
            user_id=actor.id,
            created_at=now,
            updated_at=now,
            result={},
        )
        db.add(task)
        db.flush()
        if own_session or commit:
            db.commit()
            db.refresh(task)
        return _task_to_dict(task)
    except Exception:
        if own_session or commit:
            db.rollback()
        logger.exception("Error creating task")
        return None
    finally:
        if own_session:
            db.close()


def get_task(task_id: str, db: Session | None = None) -> Optional[Dict[str, Any]]:
    own_session = db is None
    db = db or SessionLocal()
    try:
        task = db.query(DBTask).filter(DBTask.id == task_id).first()
        if not task:
            return None
        return _task_to_dict(task)
    except Exception:
        logger.exception("Error getting task %s", task_id)
        return None
    finally:
        if own_session:
            db.close()


def update_task(task_id: str, data: Dict[str, Any], db: Session | None = None) -> bool:
    own_session = db is None
    db = db or SessionLocal()
    try:
        query = db.query(DBTask).filter(DBTask.id == task_id)
        if db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update()
        task = query.first()
        if not task:
            logger.warning("Task %s not found", task_id)
            return False

        result_patch: Dict[str, Any] = {}
        status_update: str | None = None
        for key, value in data.items():
            normalized_key = RESULT_FIELD_ALIASES.get(key, key)
            if normalized_key == "result":
                if not isinstance(value, dict):
                    logger.error("Task result update must be a dict")
                    return False
                result_patch = _deep_merge(
                    result_patch,
                    value,
                    bind_visualization=False,
                )
            elif hasattr(task, normalized_key):
                if normalized_key == "status":
                    status_update = value
                else:
                    setattr(task, normalized_key, value)
            elif normalized_key in RESULT_FIELDS:
                if normalized_key == "visualization_data":
                    result_patch[normalized_key] = copy.deepcopy(value)
                elif normalized_key == "has_visualization":
                    continue
                else:
                    result_patch[normalized_key] = value
            else:
                result_patch[normalized_key] = value

        if result_patch:
            current_result = _as_dict(task.result)
            # Materialize an independent snapshot for every summary type while
            # preserving the legacy top-level latest-summary projection.
            summary_type = result_patch.get("summary_type")
            if isinstance(summary_type, str) and summary_type in {
                "brief", "detailed", "investigation", "forensic"
            }:
                variant = {
                    key: copy.deepcopy(value)
                    for key, value in result_patch.items()
                    if (key.startswith("summary") and key != "summary_variants")
                    or key == "context_analysis"
                }
                existing_variants = current_result.get("summary_variants")
                merged_variants = (
                    copy.deepcopy(existing_variants)
                    if isinstance(existing_variants, dict)
                    else {}
                )
                merged_variants[summary_type] = variant
                result_patch = {**result_patch, "summary_variants": merged_variants}
            task.result = _deep_merge(current_result, result_patch)
        if status_update:
            task.status = canonical_status(status_update, _as_dict(task.result))
            if task.status != "failed" and "error" not in data:
                task.error = None
            _sync_audio_status(db, task, task.status)
        task.updated_at = datetime.utcnow()
        if own_session:
            db.commit()
        else:
            db.flush()
        return True
    except Exception:
        if own_session:
            db.rollback()
        logger.exception("Error updating task %s", task_id)
        return False
    finally:
        if own_session:
            db.close()


def delete_task(task_id: str) -> bool:
    db = SessionLocal()
    try:
        task = db.query(DBTask).filter(DBTask.id == task_id).first()
        if not task:
            return False
        db.delete(task)
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("Error deleting task %s", task_id)
        return False
    finally:
        db.close()


def list_tasks(case_id: str | None = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        query = db.query(DBTask)
        if case_id:
            query = query.filter(DBTask.case_id == case_id)
        return [_task_to_dict(task) for task in query.order_by(desc(DBTask.created_at)).all()]
    except Exception:
        logger.exception("Error listing tasks")
        return []
    finally:
        db.close()
