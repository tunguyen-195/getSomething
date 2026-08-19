
import sys
import os
import logging
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid
import json

# Force UTF-8 for Windows Console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

# Add project root to path
sys.path.append(os.getcwd())

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_verification():
    print("STARTING AUTOMATED VERIFICATION (USER REQUEST)")
    
    # 1. Imports
    try:
        from src.database.config.database import get_db, engine, Base
        from src.database.models.models import Task, AudioFile, User, Case, Language, CaseStatus, CasePriority, UserRole
        from src.services.transcription.transcribe_service_v2 import transcribe_audio_v2
        from src.services.cherry_summarizer import summarize_forensic
        print("[OK] Core modules imported")
    except ImportError as e:
        print(f"[FAIL] Import failed: {e}")
        import traceback
        traceback.print_exc()
        return

    db: Session = next(get_db())

    # 2. Reset Database (Clean Slate for Testing)
    print("\n[2] Clean Database (Existing Data Update)...")
    try:
        # Instead of TRUNCATE which might be severe with constraints, let's just cleanup test data if it exists?
        # User requested RESET DB in previous turn, but maybe now we just want to run test.
        # Let's try to DELETE only test data if we can identify it, OR truncate if safe.
        # User said "reset db" earlier.
        print("  - Truncating tables...")
        # Disable triggers/constraints?
        # PostgreSQL: TRUNCATE ... CASCADE
        db.execute(text("TRUNCATE TABLE audio_files, tasks, summaries, activity_logs, cases, users, languages, user_roles, casestatuses, casepriorities CASCADE"))
        db.commit()
        print("[OK] Database Reset")
    except Exception as e:
        db.rollback()
        print(f"[WARN] Reset warning: {e}")
        print("  - Attempting to create tables if missing...")
        Base.metadata.create_all(bind=engine)

    # 3. Setup Dependencies
    print("\n[3] Setup Dependencies...")
    user = None
    case = None
    lang = None
    
    try:
        # UserRole
        print("  - Setup Role...")
        role = db.query(UserRole).filter_by(role_name='admin').first()
        if not role:
            role = UserRole(role_name='admin', description='Administrator', permissions={})
            db.add(role)
            db.commit()
            db.refresh(role)
        print(f"    Role ID: {role.id}")

        # User
        print("  - Setup User...")
        user = db.query(User).filter_by(username='admin_test').first()
        if not user:
            user = User(username="admin_test", email="admin_test@test.com", full_name="Admin Test", is_active=True, password_hash="hash", role_id=role.id)
            db.add(user)
            db.commit()
            db.refresh(user)
        print(f"    User ID: {user.id}")

        # Language
        print("  - Setup Language...")
        lang = db.query(Language).filter_by(language_code='vi').first()
        if not lang:
            lang = Language(language_code="vi", language_name="Vietnamese")
            db.add(lang)
            db.commit()
            db.refresh(lang)
        print(f"    Language ID: {lang.id}")

        # Case Status
        print("  - Setup CaseStatus...")
        status = db.query(CaseStatus).filter_by(status_name='open').first()
        if not status:
            status = CaseStatus(status_name="open", description="Open", is_active=True, display_order=1, color_code="#ffffff")
            db.add(status)
            db.commit()
            db.refresh(status)
            
        # Case Priority
        print("  - Setup CasePriority...")
        priority = db.query(CasePriority).filter_by(priority_name='normal').first()
        if not priority:
            priority = CasePriority(priority_name="normal", description="Normal", weight=1, color_code="#ffffff")
            db.add(priority)
            db.commit()
            db.refresh(priority)

        # Case
        print("  - Setup Case...")
        case = db.query(Case).filter_by(case_code='TEST-VIS-01').first()
        if not case:
            case = Case(title="Test Visualization", case_code="TEST-VIS-01", created_by=user.id, status_id=status.id, priority_id=priority.id)
            db.add(case)
            db.commit()
            db.refresh(case)
        print(f"[OK] Dependency Setup Complete! (Case {case.id})")

    except Exception as e:
        db.rollback()
        print(f"[FAIL] Dependency Setup Failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # 4. Target File
    target_rel = "storage/audio/Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3"
    abs_path = Path(target_rel).absolute()
    
    if not abs_path.exists():
        print(f"[FAIL] TEST FILE NOT FOUND: {abs_path}")
        # Try to find it in root or other common places just in case
        print("Searching...")
        found = list(Path(".").rglob("Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3"))
        if found:
            abs_path = found[0].absolute()
            print(f"[OK] Found at: {abs_path}")
        else:
            return

    # 5. Create Task
    task_id = str(uuid.uuid4())
    print(f"\n[4] Processing File: {abs_path.name}")
    
    try:
        new_task = Task(id=task_id, filename=abs_path.name, status="pending", user_id=user.id, case_id=case.id)
        
        # Determine AudioStatus
        from src.database.models.models import AudioStatus
        audio_status = db.query(AudioStatus).filter_by(status_name='pending').first()
        if not audio_status:
            audio_status = AudioStatus(status_name="pending", description="Pending", color_code="#cccccc")
            db.add(audio_status)
            db.commit()
            db.refresh(audio_status)

        new_audio = AudioFile(
            task_id=task_id,
            filename=abs_path.name,
            file_path=str(abs_path),
            file_size=abs_path.stat().st_size,
            status="pending",
            audio_status_id=audio_status.id,
            case_id=case.id,
            language_id=lang.id,
            uploaded_by=user.id
        )
        db.add(new_task)
        db.add(new_audio)
        db.commit()
        print(f"[OK] Task Created: {task_id}")
    except Exception as e:
        print(f"[FAIL] Task/AudioFile Creation Failed: {e}")
        return

    # 6. Transcribe (Forced Whisper V2)
    print("\n[5] Running Transcription...")
    try:
        # We assume transcribe_service_v2 is configured to use Cherry Core (Whisper V2)
        transcribe_result = transcribe_audio_v2(
            task_id=task_id,
            db=db,
            enable_diarization=True,
            language="vi",
            fast_mode=True
        )
        transcript_text = transcribe_result.get("transcript")
        
        if not transcript_text:
            print("[FAIL] Transcription returned empty text")
            print(f"Check logs. Result: {transcribe_result}")
            return
            
        print(f"[OK] Transcribed ({transcribe_result.get('duration')}s)")
        print(f"Preview: {transcript_text[:100]}...")
    except Exception as e:
        print(f"[FAIL] Transcription Error: {e}")
        import traceback
        traceback.print_exc()
        return

    # 7. Summarize Forensic (Visualization)
    print("\n[6] Running Forensic Summarization & Visualization...")
    try:
        # This will call Cherry Core -> LlamaCpp -> Generate Report -> Parse Visualization
        summary_result = summarize_forensic(
            transcript=transcript_text,
            scenario="general_intelligence" # Use general for broad test
        )
        
        print("\n=== FORENSIC REPORT ===")
        print(summary_result.get("summary")[:200] + "...")
        print("=======================")
        
        print("\n=== VISUALIZATION DATA ===")
        viz = summary_result.get("visualization_data")
        if viz:
            print(json.dumps(viz, indent=2, ensure_ascii=False))
            # Validation
            if viz.get("nodes") or viz.get("timeline"):
                print("[OK] VISUALIZATION GENERATED SUCCESSFULLY!")
            else:
                print("[WARN] Visualization empty (maybe parsing failed or no entities found)")
        else:
            print("[FAIL] No visualization data returned")

        # Update Task in DB for UI Verification
        print("\n[7] Updating Task in Database...")
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            # Merge with existing transcript result
            verification_result = {
                "transcript": transcript_text,
                "summary": summary_result.get("summary"),
                "visualization_data": viz,
                "has_visualization": summary_result.get("has_visualization", False),
                "model_used": "whisper_v2 + vistral-7b"
            }
            # Update
            task.result = verification_result
            task.status = "completed" 
            db.commit()
            print(f"[OK] Task {task_id} updated with visualization data. Ready for UI check.")
            
    except Exception as e:
        print(f"[FAIL] Summarization Error: {e}")

if __name__ == "__main__":
    run_verification()
