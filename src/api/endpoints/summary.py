from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from src.database.config.database import get_db
from src.database.models.models import Summary as DBSummary, Case, AudioFile
from src.database.models.schemas import SummaryCreate, SummaryOut
from src.services.summary_service import (
    create_summary, get_summary, list_summaries, update_summary, delete_summary
)

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