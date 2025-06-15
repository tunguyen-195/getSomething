from fastapi import APIRouter, HTTPException, Body, Depends
from typing import List, Dict, Any
import uuid
from sqlalchemy.orm import Session
from src.services.task_service import create_task, get_task
from src.core.logging import logger
from src.database.config.database import get_db

router = APIRouter()

@router.get("/")
async def get_tasks() -> List[Dict[str, Any]]:
    """Get all tasks"""
    try:
        tasks = list_tasks()
        return tasks
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
def create_task_api(data: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    filename = data.get("filename")
    case_id = data.get("case_id")
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    task = create_task(filename, case_id=case_id, db=db)
    if not task:
        raise HTTPException(status_code=500, detail="Failed to create task")
    return {"task_id": task["id"], "status": "success", "result": task}

@router.get("/{task_id}")
def get_task_api(task_id: str, db: Session = Depends(get_db)):
    task = get_task(task_id, db=db)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task["id"], "status": task["status"], "result": task}

@router.get("/tasks/results/{task_id}")
def get_task_result(task_id: str, db: Session = Depends(get_db)):
    task = get_task(task_id, db=db)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task["id"], "status": task["status"], "result": task} 