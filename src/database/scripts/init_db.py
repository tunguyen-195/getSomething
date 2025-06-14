from sqlalchemy.orm import Session
from ..models.models import (
    UserRole, CaseStatus, CasePriority, ParticipantRole,
    Language, AudioStatus, Sentiment, ActivityType, User, Case
)
from ..config.database import SessionLocal
import bcrypt

def init_db():
    db = SessionLocal()
    try:
        # Create initial user roles
        if db.query(UserRole).count() == 0:
            user_roles = [
                UserRole(
                    role_name="admin",
                    description="System administrator",
                    permissions={"all": True}
                ),
                UserRole(
                    role_name="user",
                    description="Regular user",
                    permissions={"read": True, "write": True}
                )
            ]
            db.add_all(user_roles)

        # Create initial case statuses
        if db.query(CaseStatus).count() == 0:
            case_statuses = [
                CaseStatus(status_name="active", description="Case is currently active"),
                CaseStatus(status_name="closed", description="Case has been closed"),
                CaseStatus(status_name="pending", description="Case is pending review")
            ]
            db.add_all(case_statuses)

        # Create initial case priorities
        if db.query(CasePriority).count() == 0:
            case_priorities = [
                CasePriority(priority_name="high", description="High priority", weight=3),
                CasePriority(priority_name="medium", description="Medium priority", weight=2),
                CasePriority(priority_name="low", description="Low priority", weight=1)
            ]
            db.add_all(case_priorities)

        # Create initial participant roles
        if db.query(ParticipantRole).count() == 0:
            participant_roles = [
                ParticipantRole(
                    role_name="owner",
                    description="Case owner",
                    permissions={"all": True}
                ),
                ParticipantRole(
                    role_name="member",
                    description="Case member",
                    permissions={"read": True, "write": True}
                ),
                ParticipantRole(
                    role_name="viewer",
                    description="Case viewer",
                    permissions={"read": True}
                )
            ]
            db.add_all(participant_roles)

        # Create initial languages
        if db.query(Language).count() == 0:
            languages = [
                Language(language_code="vi", language_name="Vietnamese"),
                Language(language_code="en", language_name="English")
            ]
            db.add_all(languages)

        # Create initial audio statuses
        if db.query(AudioStatus).count() == 0:
            audio_statuses = [
                AudioStatus(status_name="pending", description="Audio file is pending processing"),
                AudioStatus(status_name="processing", description="Audio file is being processed"),
                AudioStatus(status_name="completed", description="Audio file processing is completed"),
                AudioStatus(status_name="failed", description="Audio file processing failed")
            ]
            db.add_all(audio_statuses)

        # Create initial sentiments
        if db.query(Sentiment).count() == 0:
            sentiments = [
                Sentiment(sentiment_name="positive", description="Positive sentiment"),
                Sentiment(sentiment_name="negative", description="Negative sentiment"),
                Sentiment(sentiment_name="neutral", description="Neutral sentiment")
            ]
            db.add_all(sentiments)

        # Create initial activity types
        if db.query(ActivityType).count() == 0:
            activity_types = [
                ActivityType(type_name="create", description="Create action"),
                ActivityType(type_name="update", description="Update action"),
                ActivityType(type_name="delete", description="Delete action"),
                ActivityType(type_name="view", description="View action")
            ]
            db.add_all(activity_types)

        # Create initial users
        if db.query(User).count() == 0:
            password_hash = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
            admin_user = User(
                username="admin",
                email="admin@example.com",
                password_hash=password_hash,
                full_name="Admin User",
                is_active=True,
                role_id=1
            )
            db.add(admin_user)
            db.commit()

        # Create initial cases
        if db.query(Case).count() == 0:
            admin_user = db.query(User).filter_by(username="admin").first()
            case = Case(
                case_code="TEST1",
                title="Test Case 1",
                description="Sample test case",
                status_id=1,
                priority_id=1,
                created_by=admin_user.id if admin_user else None
            )
            db.add(case)
            db.commit()

        db.commit()
        print("Database initialized successfully!")
    except Exception as e:
        db.rollback()
        print(f"Error initializing database: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    init_db() 