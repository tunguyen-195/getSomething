from fastapi import APIRouter, HTTPException, Depends, Body
from sqlalchemy.orm import Session
from typing import List, Optional
from src.database.config.database import get_db
from src.database.models.models import Summary as DBSummary, Case, AudioFile, User
from src.database.models.schemas import SummaryCreate, SummaryOut
from src.services.summary_service import (
    create_summary, get_summary, list_summaries, update_summary, delete_summary
)
from src.services.task_service import update_task, get_task
import requests
import os
from src.speech_to_text.transcriber import Transcriber, OllamaProcessor
import logging
from src.core.auth import (
    accessible_case_ids,
    assert_case_access,
    assert_task_access,
    check_rate_limit,
    get_current_user,
    is_admin,
)
from src.core.config import settings

router = APIRouter()


def _assert_global_summary_admin(current_user: User) -> None:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _assert_summary_access(db: Session, current_user: User, summary: DBSummary, action: str) -> None:
    if summary.case_id is None:
        _assert_global_summary_admin(current_user)
        return
    assert_case_access(db, current_user, summary.case_id, action)


def _assert_summary_target(db: Session, current_user: User, case_id: int | None, action: str) -> None:
    if case_id is None:
        _assert_global_summary_admin(current_user)
        return
    assert_case_access(db, current_user, case_id, action)

@router.get("/", response_model=List[SummaryOut])
def get_all_summaries(
    case_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if case_id is not None:
        assert_case_access(db, current_user, case_id, "read")
        return list_summaries(db, case_id=case_id)
    if is_admin(current_user):
        return list_summaries(db)
    allowed_ids = accessible_case_ids(db, current_user) or set()
    if not allowed_ids:
        return []
    return (
        db.query(DBSummary)
        .filter(DBSummary.case_id.in_(allowed_ids))
        .order_by(DBSummary.created_at.desc())
        .all()
    )

@router.get("/{summary_id}", response_model=SummaryOut)
def get_one_summary(summary_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    summary = get_summary(db, summary_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    _assert_summary_access(db, current_user, summary, "read")
    return summary

@router.post("/", response_model=SummaryOut)
def create_one_summary(summary: SummaryCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _assert_summary_target(db, current_user, summary.case_id, "write")
    return create_summary(db, summary)

@router.patch("/{summary_id}", response_model=SummaryOut)
def update_one_summary(summary_id: int, data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    existing = get_summary(db, summary_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Summary not found")
    _assert_summary_access(db, current_user, existing, "write")
    target_case_id = data.get("case_id", existing.case_id)
    _assert_summary_target(db, current_user, target_case_id, "write")
    summary = update_summary(db, summary_id, data)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary

@router.delete("/{summary_id}")
def delete_one_summary(summary_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    summary = get_summary(db, summary_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    _assert_summary_access(db, current_user, summary, "delete")
    ok = delete_summary(db, summary_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"detail": "Summary deleted"}

@router.post("/analyze")
def analyze_summary(summary: str = Body(..., embed=True), task_id: str = Body(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Phân tích summary bằng rule/memory bank nội bộ (OllamaProcessor.analyze_context).
    Nếu truyền task_id, sẽ tự động lưu context_analysis vào trường result của task tương ứng.
    """
    import logging
    logger = logging.getLogger("summary_analyze")
    logger.info(f"[SUMMARY_ANALYZE] Bắt đầu analyze_summary | summary_len={len(summary) if summary else 0} | task_id={task_id}")
    check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    task = None
    if task_id:
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "process")
    try:
        processor = OllamaProcessor()
        context_analysis = processor.analyze_context(summary)
        logger.info(
            f"[SUMMARY_ANALYZE] OllamaProcessor.analyze_context keys: "
            f"{list(context_analysis.keys()) if isinstance(context_analysis, dict) else 'non-dict'}"
        )
        if context_analysis:
            if task:
                result_data = task.get("result") or {}
                result_data["context_analysis"] = context_analysis
                update_task(task_id, {"result": result_data})
            return {"context_analysis": context_analysis}
    except Exception as e:
        logger.error(f"[SUMMARY_ANALYZE] OllamaProcessor.analyze_context failed: {e}", exc_info=True)
    return {"error": "Phân tích thất bại với rule/memory bank nội bộ"}

@router.post("/visualize")
def visualize_summary(summary: str = Body(..., embed=True), current_user: User = Depends(get_current_user)):
    """
    Trực quan hóa hội thoại: trả về nodes, edges, timeline, entity_types, main_events cho frontend.
    """
    logger = logging.getLogger("summary_visualize")
    logger.info(f"[SUMMARY_VISUALIZE] Bắt đầu visualize_summary | summary_len={len(summary) if summary else 0}")
    check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    try:
        from src.services.analysis_intelligence.service import generate_text_graph

        result = generate_text_graph(
            summary,
            source_kind="summary_text",
            source_method="legacy_summary_derived",
        ).to_storage_dict()
        logger.info(
            f"[SUMMARY_VISUALIZE] visualize_context keys: "
            f"{list(result.keys()) if isinstance(result, dict) else 'non-dict'}"
        )
        return result
    except Exception as e:
        logger.error(f"[SUMMARY_VISUALIZE] visualize_context failed: {e}", exc_info=True)
        return {"error": str(e)}
