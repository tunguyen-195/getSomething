import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc
from src.core.logging import logger
from src.database.config.database import get_db
from src.database.models.models import Task as DBTask, Case, CaseStatus, CasePriority, User
import uuid
import json
from src.database.models.schemas import TaskResult

logger = logging.getLogger(__name__)

def create_task(filename: str, case_id: int = None, db: Session = None) -> Dict[str, Any]:
    """Create a new task and save to DB. Chỉ tạo task nếu case_id hợp lệ hoặc tự tạo case mới nếu không truyền case_id."""
    logger.debug(f"[create_task] INPUT filename={filename}, case_id={case_id}")
    close_db = False
    if db is None:
        db = next(get_db())
        close_db = True
    real_case_id = None
    user_id = None
    try:
        # Only use transaction context if we created the session
        if close_db:
            with db.begin():
                if case_id is not None:
                    case = db.query(Case).filter(Case.id == case_id).first()
                    if not case:
                        logger.error(f"Case with id {case_id} does not exist. Cannot create task.")
                        if close_db:
                            db.close()
                        return None
                    real_case_id = case.id
                    user_id = case.created_by
                else:
                    status = db.query(CaseStatus).filter(CaseStatus.status_name == "active").first()
                    priority = db.query(CasePriority).filter(CasePriority.priority_name == "high").first()
                    user = db.query(User).filter(User.username == "admin").first()
                    if not status or not priority or not user:
                        logger.error(f"Missing default: status={status}, priority={priority}, user={user}")
                        if close_db:
                            db.close()
                        return None
                    case = Case(
                        title=filename,
                        case_code=str(uuid.uuid4()),
                        description=None,
                        status_id=status.id,
                        priority_id=priority.id,
                        created_by=user.id
                    )
                    db.add(case)
                    db.flush()
                    real_case_id = case.id
                    user_id = user.id
                task_id = str(uuid.uuid4())
                db_task = DBTask(
                    id=task_id,
                    filename=filename,
                    status="pending",
                    case_id=real_case_id,
                    user_id=user_id,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                db.add(db_task)
                db.flush()
                db.refresh(db_task)
                db.commit()
        else:
            # Use db directly, no transaction context (assume caller manages transaction)
            if case_id is not None:
                case = db.query(Case).filter(Case.id == case_id).first()
                if not case:
                    logger.error(f"Case with id {case_id} does not exist. Cannot create task.")
                    return None
                real_case_id = case.id
                user_id = case.created_by
            else:
                status = db.query(CaseStatus).filter(CaseStatus.status_name == "active").first()
                priority = db.query(CasePriority).filter(CasePriority.priority_name == "high").first()
                user = db.query(User).filter(User.username == "admin").first()
                if not status or not priority or not user:
                    logger.error(f"Missing default: status={status}, priority={priority}, user={user}")
                    return None
                case = Case(
                    title=filename,
                    case_code=str(uuid.uuid4()),
                    description=None,
                    status_id=status.id,
                    priority_id=priority.id,
                    created_by=user.id
                )
                db.add(case)
                db.flush()
                real_case_id = case.id
                user_id = user.id
            task_id = str(uuid.uuid4())
            db_task = DBTask(
                id=task_id,
                filename=filename,
                status="pending",
                case_id=real_case_id,
                user_id=user_id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(db_task)
            db.flush()
            db.refresh(db_task)
            db.commit()
        logger.info(f"Created task {task_id} for file {filename}")
        logger.debug(f"[create_task] OUTPUT: {db_task.__dict__}")
        if close_db:
            db.close()
        return {
            "id": db_task.id,
            "filename": db_task.filename,
            "status": db_task.status,
            "created_at": db_task.created_at.isoformat(),
            "updated_at": db_task.updated_at.isoformat(),
            "result": db_task.result,
            "error": db_task.error,
            "case_id": db_task.case_id,
        }
    except Exception as e:
        logger.error(f"Error creating task: {str(e)}")
        db.rollback()
        if close_db:
            db.close()
        return None

def get_task(task_id: str, db: Session = None) -> Optional[Dict[str, Any]]:
    logger.debug(f"[get_task] INPUT task_id={task_id}")
    close_db = False
    if db is None:
        db = next(get_db())
        close_db = True
    try:
        db_task = db.query(DBTask).filter(DBTask.id == task_id).first()
        if not db_task:
            logger.warning(f"Task {task_id} not found")
            if close_db:
                db.close()
            return None
        result = {
            "id": db_task.id,
            "filename": db_task.filename,
            "status": db_task.status,
            "created_at": db_task.created_at.isoformat() if db_task.created_at else None,
            "updated_at": db_task.updated_at.isoformat() if db_task.updated_at else None,
            "result": db_task.result,
            "error": db_task.error,
            "case_id": db_task.case_id,
        }
        logger.debug(f"[get_task] OUTPUT: {result}")
        if close_db:
            db.close()
        return result
    except Exception as e:
        logger.error(f"Error getting task {task_id}: {str(e)}")
        if close_db:
            db.close()
        return None

def update_task(task_id: str, data: Dict[str, Any]) -> bool:
    logger.debug(f"[update_task] INPUT task_id={task_id}, data={data}")
    try:
        db: Session = next(get_db())
        db_task = db.query(DBTask).filter(DBTask.id == task_id).first()
        if not db_task:
            logger.warning(f"Task {task_id} not found")
            return False
        for k, v in data.items():
            if k == "result":
                # Validate result schema
                try:
                    validated = TaskResult(**v)
                    db_task.result = validated.dict()
                except Exception as e:
                    logger.error(f"Result schema invalid for task {task_id}: {e}")
                    return False
            elif hasattr(db_task, k):
                setattr(db_task, k, v)
        db_task.updated_at = datetime.utcnow()
        db.commit()
        logger.info(f"Updated task {task_id}")
        logger.debug(f"[update_task] OUTPUT: {db_task.__dict__}")
        return True
    except Exception as e:
        logger.error(f"Error updating task {task_id}: {str(e)}")
        return False

def delete_task(task_id: str) -> bool:
    try:
        db: Session = next(get_db())
        db_task = db.query(DBTask).filter(DBTask.id == task_id).first()
        if not db_task:
            logger.warning(f"Task {task_id} not found")
            return False
        db.delete(db_task)
        db.commit()
        logger.info(f"Deleted task {task_id}")
        return True
    except Exception as e:
        logger.error(f"Error deleting task {task_id}: {str(e)}")
        return False

def list_tasks(case_id: str = None) -> List[Dict[str, Any]]:
    logger.debug(f"[list_tasks] INPUT case_id={case_id}")
    try:
        db: Session = next(get_db())
        query = db.query(DBTask)
        if case_id:
            query = query.filter(DBTask.case_id == case_id)
        db_tasks = query.order_by(desc(DBTask.created_at)).all()
        results = [
            {
                "id": t.id,
                "filename": t.filename,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                "result": t.result,
                "error": t.error,
                "case_id": t.case_id,
            }
            for t in db_tasks
        ]
        print(f"[list_tasks] Số lượng task trả về: {len(results)}")
        print(f"[list_tasks] Dữ liệu trả về: {json.dumps(results, ensure_ascii=False, indent=2)}")
        logger.debug(f"[list_tasks] OUTPUT: {results}")
        return results
    except Exception as e:
        logger.error(f"Error listing tasks: {str(e)}")
        return [] 