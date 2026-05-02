import os
import logging

from src.core.config import settings
from src.database.config.database import Base, engine, SessionLocal
from src.database.models.models import (
    ActivityType,
    AudioStatus,
    CasePriority,
    CaseStatus,
    Language,
    ParticipantRole,
    Sentiment,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)


def _get_or_create(db, model, defaults=None, **filters):
    obj = db.query(model).filter_by(**filters).first()
    if obj:
        return obj
    obj = model(**filters, **(defaults or {}))
    db.add(obj)
    db.flush()
    return obj


def init_db():
    """Create schema and seed required lookup data idempotently."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin_role = _get_or_create(
            db,
            UserRole,
            role_name="admin",
            defaults={
                "description": "System administrator",
                "permissions": {"all": True},
            },
        )
        _get_or_create(
            db,
            UserRole,
            role_name="user",
            defaults={
                "description": "Regular user",
                "permissions": {"read": True, "write": True},
            },
        )

        for role_name, description, permissions in [
            ("owner", "Case owner", {"all": True}),
            ("member", "Case member", {"read": True, "write": True, "process": True}),
            ("viewer", "Case viewer", {"read": True}),
        ]:
            _get_or_create(
                db,
                ParticipantRole,
                role_name=role_name,
                defaults={
                    "description": description,
                    "permissions": permissions,
                    "is_system": True,
                },
            )

        for status_name, description, display_order, color_code in [
            ("active", "Case is active", 1, "#43a047"),
            ("pending", "Case is pending", 2, "#f9a825"),
            ("closed", "Case is closed", 3, "#757575"),
            ("archived", "Case is archived", 4, "#607d8b"),
        ]:
            _get_or_create(
                db,
                CaseStatus,
                status_name=status_name,
                defaults={
                    "description": description,
                    "display_order": display_order,
                    "color_code": color_code,
                    "is_active": True,
                },
            )

        for priority_name, description, weight, color_code in [
            ("high", "High priority", 3, "#e53935"),
            ("medium", "Medium priority", 2, "#f9a825"),
            ("low", "Low priority", 1, "#43a047"),
        ]:
            _get_or_create(
                db,
                CasePriority,
                priority_name=priority_name,
                defaults={
                    "description": description,
                    "weight": weight,
                    "color_code": color_code,
                },
            )

        for code, name in [("vi", "Vietnamese"), ("en", "English")]:
            _get_or_create(
                db,
                Language,
                language_code=code,
                defaults={"language_name": name, "is_active": True},
            )

        for status_name, description, display_order, color_code in [
            ("pending", "Audio file is pending processing", 1, "#757575"),
            ("uploaded", "Audio file has been uploaded", 2, "#1976d2"),
            ("processing", "Audio file is being processed", 3, "#f9a825"),
            ("transcribing", "Audio file is being transcribed", 4, "#f9a825"),
            ("transcribed", "Audio transcription is complete", 5, "#43a047"),
            ("summarizing", "Audio transcript is being summarized", 6, "#f9a825"),
            ("summarized", "Audio summary is complete", 7, "#43a047"),
            ("visualizing", "Visualization is being generated", 8, "#f9a825"),
            ("visualized", "Visualization is complete", 9, "#43a047"),
            ("completed", "Audio processing is complete", 10, "#43a047"),
            ("failed", "Audio processing failed", 11, "#e53935"),
            ("archived", "Audio file is archived", 12, "#607d8b"),
        ]:
            _get_or_create(
                db,
                AudioStatus,
                status_name=status_name,
                defaults={
                    "description": description,
                    "display_order": display_order,
                    "color_code": color_code,
                },
            )

        for sentiment_name, description, color_code in [
            ("positive", "Positive sentiment", "#43a047"),
            ("negative", "Negative sentiment", "#e53935"),
            ("neutral", "Neutral sentiment", "#757575"),
        ]:
            _get_or_create(
                db,
                Sentiment,
                sentiment_name=sentiment_name,
                defaults={"description": description, "color_code": color_code},
            )

        for type_name, description in [
            ("create", "Create action"),
            ("update", "Update action"),
            ("delete", "Delete action"),
            ("view", "View action"),
            ("upload", "Upload audio"),
            ("transcribe", "Transcribe audio"),
            ("summarize", "Summarize transcript"),
            ("visualize", "Generate visualization"),
            ("archive", "Archive resource"),
        ]:
            _get_or_create(
                db,
                ActivityType,
                type_name=type_name,
                defaults={"description": description, "is_system": True},
            )

        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin_password = os.getenv("INITIAL_ADMIN_PASSWORD")
            if not admin_password:
                raise RuntimeError(
                    "INITIAL_ADMIN_PASSWORD is required to seed the initial admin user"
                )
            admin = User(
                username="admin",
                email=os.getenv("INITIAL_ADMIN_EMAIL", "admin@example.com"),
                full_name=os.getenv("INITIAL_ADMIN_FULL_NAME", "Administrator"),
                is_active=True,
                role_id=admin_role.id,
            )
            admin.set_password(admin_password)
            db.add(admin)
            db.flush()
            logger.info("Created initial admin user")

        db.commit()
        logger.info("Database initialization completed successfully")
    except Exception:
        db.rollback()
        logger.exception("Database initialization failed")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
