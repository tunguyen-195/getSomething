from fastapi import APIRouter, HTTPException, Depends, Body
from sqlalchemy.orm import Session
from typing import List, Optional
from src.database.config.database import get_db
from src.database.models.models import Summary as DBSummary, Case, AudioFile
from src.database.models.schemas import SummaryCreate, SummaryOut
from src.services.summary_service import (
    create_summary, get_summary, list_summaries, update_summary, delete_summary
)
from src.services.task_service import update_task, get_task
import requests
import os
from src.speech_to_text.transcriber import Transcriber, OllamaProcessor
import logging

router = APIRouter()

@router.get("/", response_model=List[SummaryOut])
def get_all_summaries(case_id: Optional[int] = None, db: Session = Depends(get_db)):
    return list_summaries(db, case_id=case_id)

@router.get("/{summary_id}", response_model=SummaryOut)
def get_one_summary(summary_id: int, db: Session = Depends(get_db)):
    summary = get_summary(db, summary_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary

@router.post("/", response_model=SummaryOut)
def create_one_summary(summary: SummaryCreate, db: Session = Depends(get_db)):
    return create_summary(db, summary)

@router.patch("/{summary_id}", response_model=SummaryOut)
def update_one_summary(summary_id: int, data: dict, db: Session = Depends(get_db)):
    summary = update_summary(db, summary_id, data)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary

@router.delete("/{summary_id}")
def delete_one_summary(summary_id: int, db: Session = Depends(get_db)):
    ok = delete_summary(db, summary_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"detail": "Summary deleted"}

@router.post("/analyze")
def analyze_summary(summary: str = Body(..., embed=True), task_id: str = Body(None), db: Session = Depends(get_db)):
    """
    Phân tích summary bằng rule/memory bank nội bộ (OllamaProcessor.analyze_context).
    Nếu truyền task_id, sẽ tự động lưu context_analysis vào trường result của task tương ứng.
    """
    import logging
    logger = logging.getLogger("summary_analyze")
    logger.info(f"[SUMMARY_ANALYZE] Bắt đầu analyze_summary | summary_len={len(summary) if summary else 0} | task_id={task_id}")
    try:
        processor = OllamaProcessor()
        context_analysis = processor.analyze_context(summary)
        logger.info(f"[SUMMARY_ANALYZE] OllamaProcessor.analyze_context result: {context_analysis}")
        if context_analysis:
            if task_id:
                task = get_task(task_id)
                if task:
                    result_data = task.get("result") or {}
                    result_data["context_analysis"] = context_analysis
                    update_task(task_id, {"result": result_data})
            return {"context_analysis": context_analysis}
    except Exception as e:
        logger.error(f"[SUMMARY_ANALYZE] OllamaProcessor.analyze_context failed: {e}", exc_info=True)
    return {"error": "Phân tích thất bại với rule/memory bank nội bộ"}

@router.post("/visualize")
def visualize_summary(summary: str = Body(..., embed=True)):
    """
    Trực quan hóa hội thoại: trả về nodes, edges, timeline, entity_types, main_events cho frontend.
    """
    logger = logging.getLogger("summary_visualize")
    logger.info(f"[SUMMARY_VISUALIZE] Bắt đầu visualize_summary | summary_len={len(summary) if summary else 0}")
    try:
        processor = OllamaProcessor()
        result = processor.visualize_context(summary)
        logger.info(f"[SUMMARY_VISUALIZE] OllamaProcessor.visualize_context result: {result}")
        return result
    except Exception as e:
        logger.error(f"[SUMMARY_VISUALIZE] visualize_context failed: {e}", exc_info=True)
        return {"error": str(e)} 