from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.database.models.models import Task as DBTask

from .schemas import AnalysisGraphV2, EntityItem


def _result_dict(task: DBTask) -> dict[str, Any]:
    if isinstance(task.result, dict):
        return copy.deepcopy(task.result)
    if isinstance(task.result, str):
        try:
            parsed = json.loads(task.result)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _write_graph(task: DBTask, graph: AnalysisGraphV2) -> None:
    result = _result_dict(task)
    result["visualization_data"] = graph.to_storage_dict()
    result["has_visualization"] = True
    task.result = result
    flag_modified(task, "result")


def _load_graph(task: DBTask) -> AnalysisGraphV2:
    result = _result_dict(task)
    graph_data = result.get("visualization_data")
    if not isinstance(graph_data, dict) or graph_data.get("schema_version") != "analysis_intelligence.v2":
        raise HTTPException(status_code=404, detail="Analysis graph not found")
    return AnalysisGraphV2(**graph_data)


def _lock_task(db: Session, task_id: str) -> DBTask:
    task = db.query(DBTask).filter(DBTask.id == task_id).with_for_update().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def save_graph(db: Session, task_id: str, graph: AnalysisGraphV2) -> AnalysisGraphV2:
    task = _lock_task(db, task_id)
    _write_graph(task, graph)
    return graph


def _revision_guard(graph: AnalysisGraphV2, expected_revision: int | None) -> None:
    if expected_revision is not None and expected_revision != graph.graph_revision:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Analysis graph revision conflict",
                "current_revision": graph.graph_revision,
                "graph": graph.to_storage_dict(),
            },
        )


def _all_item_lists(graph_data: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return [
        graph_data.setdefault("entities", []),
        graph_data.setdefault("relations", []),
        graph_data.setdefault("events", []),
        graph_data.setdefault("claims", []),
        graph_data.setdefault("facts", []),
        graph_data.setdefault("risk_flags", []),
        graph_data.setdefault("slots", []),
    ]


def review_item(
    db: Session,
    task_id: str,
    item_id: str,
    review_status: str,
    user_id: int,
    expected_revision: int | None,
    review_note: str | None = None,
) -> AnalysisGraphV2:
    task = _lock_task(db, task_id)
    graph = _load_graph(task)
    _revision_guard(graph, expected_revision)
    data = graph.to_storage_dict()
    found = False
    for items in _all_item_lists(data):
        for item in items:
            if item.get("id") == item_id:
                item["review_status"] = review_status
                item["reviewed_by"] = user_id
                item["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                if review_note is not None:
                    item["review_note"] = review_note
                found = True
    if not found:
        raise HTTPException(status_code=404, detail="Analysis item not found")
    data["graph_revision"] = graph.graph_revision + 1
    updated = AnalysisGraphV2(**data)
    _write_graph(task, updated)
    return updated


def update_entity(
    db: Session,
    task_id: str,
    entity_id: str,
    patch: dict[str, Any],
    user_id: int,
    expected_revision: int | None,
) -> AnalysisGraphV2:
    task = _lock_task(db, task_id)
    graph = _load_graph(task)
    _revision_guard(graph, expected_revision)
    data = graph.to_storage_dict()
    found = False
    for entity in data.setdefault("entities", []):
        if entity.get("id") != entity_id:
            continue
        found = True
        if "original_label" not in entity or not entity.get("original_label"):
            entity["original_label"] = entity.get("label")
        if "original_type" not in entity or not entity.get("original_type"):
            entity["original_type"] = entity.get("type")
        for key in ("label", "type", "aliases"):
            if key in patch:
                entity[key] = patch[key]
        entity["reviewed_by"] = user_id
        entity["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        if patch.get("review_note") is not None:
            entity["review_note"] = patch["review_note"]
    if not found:
        raise HTTPException(status_code=404, detail="Entity not found")
    data["graph_revision"] = graph.graph_revision + 1
    updated = AnalysisGraphV2(**data)
    _write_graph(task, updated)
    return updated


def merge_entities(
    db: Session,
    task_id: str,
    source_entity_ids: list[str],
    user_id: int,
    expected_revision: int | None,
    target_label: str | None = None,
    target_type: str | None = None,
) -> AnalysisGraphV2:
    if len(source_entity_ids) < 2:
        raise HTTPException(status_code=400, detail="At least two source entities are required")
    task = _lock_task(db, task_id)
    graph = _load_graph(task)
    _revision_guard(graph, expected_revision)
    data = graph.to_storage_dict()
    target_id = source_entity_ids[0]
    seen = set(source_entity_ids)
    found = set()
    now = datetime.now(timezone.utc).isoformat()
    for entity in data.setdefault("entities", []):
        entity_id = entity.get("id")
        if entity_id not in seen:
            continue
        found.add(entity_id)
        if entity_id == target_id:
            entity["source_item_ids"] = sorted(set(entity.get("source_item_ids") or []) | seen)
            if target_label:
                entity.setdefault("original_label", entity.get("label"))
                entity["label"] = target_label
            if target_type:
                entity.setdefault("original_type", entity.get("type"))
                entity["type"] = target_type
            entity["reviewed_by"] = user_id
            entity["reviewed_at"] = now
        else:
            entity["review_status"] = "rejected"
            entity["reviewed_by"] = user_id
            entity["reviewed_at"] = now
            entity["review_note"] = "Merged into another entity"
    if found != seen:
        raise HTTPException(status_code=404, detail="One or more entities were not found")
    for relation in data.setdefault("relations", []):
        if relation.get("source_entity_id") in seen:
            relation["source_entity_id"] = target_id
        if relation.get("target_entity_id") in seen:
            relation["target_entity_id"] = target_id
        if relation.get("source_entity_id") == relation.get("target_entity_id"):
            relation["review_status"] = "rejected"
            relation["reviewed_by"] = user_id
            relation["reviewed_at"] = now
            relation["review_note"] = "Hidden after entity merge produced a self-loop"
    data["graph_revision"] = graph.graph_revision + 1
    updated = AnalysisGraphV2(**data)
    _write_graph(task, updated)
    return updated


def split_entity(
    db: Session,
    task_id: str,
    entity_id: str,
    replacement_entities: list[dict[str, Any]],
    user_id: int,
    expected_revision: int | None,
) -> AnalysisGraphV2:
    if not replacement_entities:
        raise HTTPException(status_code=400, detail="replacement entities are required")
    task = _lock_task(db, task_id)
    graph = _load_graph(task)
    _revision_guard(graph, expected_revision)
    data = graph.to_storage_dict()
    found = False
    now = datetime.now(timezone.utc).isoformat()
    for entity in data.setdefault("entities", []):
        if entity.get("id") == entity_id:
            found = True
            entity["review_status"] = "rejected"
            entity["reviewed_by"] = user_id
            entity["reviewed_at"] = now
            entity["review_note"] = "Split into replacement entities"
    if not found:
        raise HTTPException(status_code=404, detail="Entity not found")

    for replacement in replacement_entities:
        replacement["source_item_ids"] = sorted(set(replacement.get("source_item_ids") or []) | {entity_id})
        replacement.setdefault("reviewed_by", user_id)
        replacement.setdefault("reviewed_at", now)
        data.setdefault("entities", []).append(EntityItem(**replacement).model_dump(mode="json"))

    data["graph_revision"] = graph.graph_revision + 1
    updated = AnalysisGraphV2(**data)
    _write_graph(task, updated)
    return updated
