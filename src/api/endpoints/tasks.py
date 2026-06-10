from fastapi import APIRouter, HTTPException, Body, Depends
from typing import List, Dict, Any
import uuid
from sqlalchemy.orm import Session
from src.services.task_service import create_task, get_task, list_tasks
from src.core.logging import logger
from src.database.config.database import get_db
from src.core.auth import accessible_case_ids, assert_case_access, assert_task_access, get_current_user
from src.database.models.models import User

router = APIRouter()

@router.get("/")
async def get_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Get all tasks"""
    logger.info("[TASKS] Bắt đầu get_tasks")
    try:
        tasks = list_tasks()
        allowed_ids = accessible_case_ids(db, current_user)
        if allowed_ids is not None:
            tasks = [task for task in tasks if task.get("case_id") in allowed_ids]
        return tasks
    except Exception as e:
        logger.error(f"[TASKS] Lỗi get_tasks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
def create_task_api(
    data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filename = data.get("filename")
    case_id = data.get("case_id")
    logger.info(f"[TASKS] Bắt đầu create_task_api | filename={filename} | case_id={case_id}")
    if not filename:
        logger.error("[TASKS] Thiếu filename khi tạo task")
        raise HTTPException(status_code=400, detail="Missing filename")
    if case_id:
        assert_case_access(db, current_user, int(case_id), "write")
    task = create_task(filename, case_id=case_id, db=db, user_id=current_user.id)
    if not task:
        logger.error("[TASKS] Lỗi tạo task mới")
        raise HTTPException(status_code=500, detail="Failed to create task")
    logger.info(f"[TASKS] Đã tạo task mới | task_id={task['id']}")
    return {"task_id": task["id"], "status": "success", "result": task}

@router.get("/{task_id}")
def get_task_api(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    logger.info(f"[TASKS] Bắt đầu get_task_api | task_id={task_id}")
    task = get_task(task_id, db=db)
    if not task:
        logger.error(f"[TASKS] Không tìm thấy task | task_id={task_id}")
        raise HTTPException(status_code=404, detail="Task not found")
    assert_task_access(db, current_user, task_id, "read")
    logger.info(f"[TASKS] Đã lấy task | task_id={task_id}")
    return {"task_id": task["id"], "status": task["status"], "result": task}

def _task_result_response(task_id: str, db: Session, current_user: User):
    task = get_task(task_id, db=db)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    assert_task_access(db, current_user, task_id, "read")
    return {"task_id": task["id"], "status": task["status"], "result": task}

@router.get("/results/{task_id}")
def get_task_result(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _task_result_response(task_id, db, current_user)

@router.get("/tasks/results/{task_id}")
def get_task_result_legacy(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _task_result_response(task_id, db, current_user)
