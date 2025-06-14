from sqlalchemy.orm import Session
from src.database.models.models import Summary
from src.database.models.schemas import SummaryCreate
from typing import List, Optional

def create_summary(db: Session, summary: SummaryCreate) -> Summary:
    db_summary = Summary(**summary.model_dump())
    db.add(db_summary)
    db.commit()
    db.refresh(db_summary)
    return db_summary

def get_summary(db: Session, summary_id: int) -> Optional[Summary]:
    return db.query(Summary).filter(Summary.id == summary_id).first()

def list_summaries(db: Session, case_id: Optional[int] = None) -> List[Summary]:
    q = db.query(Summary)
    if case_id is not None:
        q = q.filter(Summary.case_id == case_id)
    return q.order_by(Summary.created_at.desc()).all()

def update_summary(db: Session, summary_id: int, data: dict) -> Optional[Summary]:
    summary = db.query(Summary).filter(Summary.id == summary_id).first()
    if not summary:
        return None
    for k, v in data.items():
        if hasattr(summary, k):
            setattr(summary, k, v)
    db.commit()
    db.refresh(summary)
    return summary

def delete_summary(db: Session, summary_id: int) -> bool:
    summary = db.query(Summary).filter(Summary.id == summary_id).first()
    if not summary:
        return False
    db.delete(summary)
    db.commit()
    return True 