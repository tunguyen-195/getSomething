from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, JSON, Text, DateTime, func, Index, UniqueConstraint, CheckConstraint, Float
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declared_attr
from .base import BaseModel
import bcrypt
import os
from pathlib import Path
from sqlalchemy.dialects.postgresql import JSONB
import datetime

# Constants for file storage
AUDIO_STORAGE_ROOT = os.getenv('AUDIO_STORAGE_ROOT', 'storage/audio')
AUDIO_STORAGE_ROOT = Path(AUDIO_STORAGE_ROOT)

class User(BaseModel):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    full_name = Column(String)
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    role_id = Column(Integer, ForeignKey("user_roles.id"))
    role = relationship("UserRole", back_populates="users")

    # Relationships
    cases = relationship("Case", back_populates="created_by_user")
    audio_files = relationship("AudioFile", back_populates="uploaded_by_user")
    activities = relationship("ActivityLog", back_populates="user")

    # Indexes
    __table_args__ = (
        Index('idx_user_username_email', 'username', 'email'),
        Index('idx_user_role', 'role_id'),
        Index('idx_user_status', 'is_active'),
    )

    def set_password(self, password: str):
        """Hash and set password"""
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode(), salt).decode()

    def check_password(self, password: str) -> bool:
        """Check password against hash"""
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())

class UserRole(BaseModel):
    __tablename__ = 'user_roles'

    id = Column(Integer, primary_key=True, index=True)
    role_name = Column(String, unique=True, index=True)
    description = Column(String)
    permissions = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    users = relationship("User", back_populates="role")

    # Constraints
    __table_args__ = (
        CheckConstraint("role_name ~ '^[a-z_]+$'", name="check_role_name_format"),
    )

class Case(BaseModel):
    __tablename__ = 'cases'

    id = Column(Integer, primary_key=True, index=True)
    case_code = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    status_id = Column(Integer, ForeignKey('casestatuses.id'), nullable=False)
    priority_id = Column(Integer, ForeignKey('casepriorities.id'), nullable=False)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    closed_at = Column(DateTime(timezone=True))
    is_archived = Column(Boolean, default=False)
    archive_reason = Column(Text)
    case_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    status = relationship("CaseStatus", back_populates="cases")
    priority = relationship("CasePriority", back_populates="cases")
    created_by_user = relationship("User", back_populates="cases")
    participants = relationship("CaseParticipant", back_populates="case")
    audio_files = relationship("AudioFile", back_populates="case")
    notes = relationship("CaseNote", back_populates="case")
    activities = relationship("ActivityLog", back_populates="case")
    summaries = relationship("Summary", back_populates="case", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index('idx_case_code', 'case_code'),
        Index('idx_case_status', 'status_id'),
        Index('idx_case_priority', 'priority_id'),
        Index('idx_case_created_by', 'created_by'),
        Index('idx_case_archived', 'is_archived'),
    )

class CaseStatus(BaseModel):
    __tablename__ = 'casestatuses'

    status_name = Column(String(50), unique=True, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    display_order = Column(Integer, default=0)
    color_code = Column(String(7))  # Hex color code

    # Relationships
    cases = relationship("Case", back_populates="status")

    # Constraints
    __table_args__ = (
        CheckConstraint("status_name ~ '^[a-z_]+$'", name="check_status_name_format"),
        CheckConstraint("color_code ~ '^#[0-9a-fA-F]{6}$'", name="check_color_code_format"),
    )

class CasePriority(BaseModel):
    __tablename__ = 'casepriorities'

    priority_name = Column(String(50), unique=True, nullable=False)
    description = Column(Text)
    weight = Column(Integer, nullable=False)
    color_code = Column(String(7))  # Hex color code

    # Relationships
    cases = relationship("Case", back_populates="priority")

    # Constraints
    __table_args__ = (
        CheckConstraint("priority_name ~ '^[a-z_]+$'", name="check_priority_name_format"),
        CheckConstraint("color_code ~ '^#[0-9a-fA-F]{6}$'", name="check_color_code_format"),
        CheckConstraint("weight > 0", name="check_positive_weight"),
    )

class CaseParticipant(BaseModel):
    __tablename__ = 'caseparticipants'

    case_id = Column(Integer, ForeignKey('cases.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    role_id = Column(Integer, ForeignKey('participantroles.id'), nullable=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    left_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)

    # Relationships
    case = relationship("Case", back_populates="participants")
    user = relationship("User")
    role = relationship("ParticipantRole")

    # Indexes and constraints
    __table_args__ = (
        UniqueConstraint('case_id', 'user_id', name='uq_case_user'),
        Index('idx_participant_case', 'case_id'),
        Index('idx_participant_user', 'user_id'),
        Index('idx_participant_role', 'role_id'),
        Index('idx_participant_active', 'is_active'),
    )

class ParticipantRole(BaseModel):
    __tablename__ = 'participantroles'

    role_name = Column(String(50), unique=True, nullable=False)
    description = Column(Text)
    permissions = Column(JSON, nullable=False, default=dict)
    is_system = Column(Boolean, default=False)

    # Constraints
    __table_args__ = (
        CheckConstraint("role_name ~ '^[a-z_]+$'", name="check_role_name_format"),
    )

class AudioFile(BaseModel):
    __tablename__ = 'audio_files'

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    file_path = Column(String)
    file_size = Column(Integer)
    duration = Column(Float)
    status = Column(String)
    audio_status_id = Column(Integer, ForeignKey('audiostatuses.id'))
    audio_status = relationship("AudioStatus")
    processed_at = Column(DateTime)
    error_message = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    task_id = Column(String, ForeignKey("tasks.id"))
    task = relationship("Task")

    case_id = Column(Integer, ForeignKey('cases.id'), nullable=False)
    language_id = Column(Integer, ForeignKey('languages.id'), nullable=False)
    uploaded_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    is_archived = Column(Boolean, default=False)
    archive_reason = Column(Text)
    storage_type = Column(String(50), default='local')  # local, s3, etc.
    storage_config = Column(JSON, default=dict)  # Storage-specific configuration
    extra_metadata = Column(JSON, default=dict)

    # Relationships
    case = relationship("Case", back_populates="audio_files")
    language = relationship("Language")
    uploaded_by_user = relationship("User", back_populates="audio_files")
    activities = relationship("ActivityLog", back_populates="audio_file")

    # Indexes
    __table_args__ = (
        Index('idx_audio_case', 'case_id'),
        Index('idx_audio_status', 'status'),
        Index('idx_audio_language', 'language_id'),
        Index('idx_audio_uploaded_by', 'uploaded_by'),
        Index('idx_audio_archived', 'is_archived'),
        Index('idx_audio_storage', 'storage_type'),
    )

    @property
    def absolute_path(self) -> Path:
        """Get absolute path to audio file"""
        path = Path(self.file_path or "")
        if path.is_absolute():
            return path
        if len(path.parts) >= 2 and path.parts[0] == "storage" and path.parts[1] == "audio":
            return path
        return AUDIO_STORAGE_ROOT / path

    @property
    def exists(self) -> bool:
        """Check if audio file exists"""
        return self.absolute_path.exists()

    def get_storage_path(self) -> str:
        """Get storage path based on storage type"""
        if self.storage_type == 'local':
            return str(self.absolute_path)
        elif self.storage_type == 's3':
            return self.storage_config.get('s3_path', '')
        return ''

    def archive(self, reason: str = None):
        """Archive audio file"""
        if self.is_archived:
            return

        # Move file to archive directory
        archive_dir = AUDIO_STORAGE_ROOT / 'archive' / str(self.id)
        archive_dir.mkdir(parents=True, exist_ok=True)

        if self.exists:
            new_path = archive_dir / self.filename
            self.absolute_path.rename(new_path)
            self.file_path = str(new_path.relative_to(AUDIO_STORAGE_ROOT))

        self.is_archived = True
        self.archive_reason = reason

    def restore(self):
        """Restore archived audio file"""
        if not self.is_archived:
            return

        # Move file back to original location
        if self.exists:
            original_dir = AUDIO_STORAGE_ROOT / 'cases' / str(self.case_id)
            original_dir.mkdir(parents=True, exist_ok=True)

            new_path = original_dir / self.filename
            self.absolute_path.rename(new_path)
            self.file_path = str(new_path.relative_to(AUDIO_STORAGE_ROOT))

        self.is_archived = False
        self.archive_reason = None

    def delete_file(self):
        """Delete audio file from storage"""
        if self.exists:
            self.absolute_path.unlink()

    @classmethod
    def create_storage_path(cls, case_id: int, file_name: str) -> str:
        """Create storage path for new audio file"""
        storage_dir = AUDIO_STORAGE_ROOT / 'cases' / str(case_id)
        storage_dir.mkdir(parents=True, exist_ok=True)
        return str(storage_dir / file_name)

    @classmethod
    def get_storage_info(cls, file_path: str) -> dict:
        """Get file storage information"""
        path = AUDIO_STORAGE_ROOT / file_path
        if not path.exists():
            return {}

        return {
            'size': path.stat().st_size,
            'created_at': datetime.fromtimestamp(path.stat().st_ctime),
            'modified_at': datetime.fromtimestamp(path.stat().st_mtime)
        }

class Language(BaseModel):
    __tablename__ = 'languages'

    language_code = Column(String(10), unique=True, nullable=False)
    language_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)

    # Constraints
    __table_args__ = (
        CheckConstraint("language_code ~ '^[a-z]{2}(-[A-Z]{2})?$'", name="check_language_code_format"),
    )

class AudioStatus(BaseModel):
    __tablename__ = 'audiostatuses'

    status_name = Column(String(50), unique=True, nullable=False)
    description = Column(Text)
    display_order = Column(Integer, default=0)
    color_code = Column(String(7))  # Hex color code

    # Constraints
    __table_args__ = (
        CheckConstraint("status_name ~ '^[a-z_]+$'", name="check_status_name_format"),
        CheckConstraint("color_code ~ '^#[0-9a-fA-F]{6}$'", name="check_color_code_format"),
    )

# REMOVED: Transcription, AnalysisResult, AnalysisDetail classes
# These tables are not used - all data is stored in Task.result (JSONB)

class Sentiment(BaseModel):
    __tablename__ = 'sentiments'

    sentiment_name = Column(String(50), unique=True, nullable=False)
    description = Column(Text)
    color_code = Column(String(7))  # Hex color code

    # Constraints
    __table_args__ = (
        CheckConstraint("sentiment_name ~ '^[a-z_]+$'", name="check_sentiment_name_format"),
        CheckConstraint("color_code ~ '^#[0-9a-fA-F]{6}$'", name="check_color_code_format"),
    )

class CaseNote(BaseModel):
    __tablename__ = 'casenotes'

    case_id = Column(Integer, ForeignKey('cases.id'), nullable=False)
    audio_id = Column(Integer, ForeignKey('audio_files.id'))
    version = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    is_private = Column(Boolean, default=False)
    extra_metadata = Column(JSON, default=dict)

    # Relationships
    case = relationship("Case", back_populates="notes")
    audio_file = relationship("AudioFile")
    created_by_user = relationship("User")

    # Indexes
    __table_args__ = (
        Index('idx_note_case', 'case_id'),
        Index('idx_note_audio', 'audio_id'),
        Index('idx_note_created_by', 'created_by'),
        Index('idx_note_private', 'is_private'),
    )

class ActivityLog(BaseModel):
    __tablename__ = 'activitylogs'

    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    case_id = Column(Integer, ForeignKey('cases.id'))
    audio_id = Column(Integer, ForeignKey('audio_files.id'))
    activity_type_id = Column(Integer, ForeignKey('activitytypes.id'), nullable=False)
    task_id = Column(String, ForeignKey('tasks.id'))
    action_detail = Column(JSON)
    ip_address = Column(String(45))
    user_agent = Column(String(500))

    # Relationships
    user = relationship("User", back_populates="activities")
    case = relationship("Case", back_populates="activities")
    audio_file = relationship("AudioFile", back_populates="activities")
    activity_type = relationship("ActivityType")
    task = relationship("Task", back_populates="activities")

    # Indexes
    __table_args__ = (
        Index('idx_activity_user', 'user_id'),
        Index('idx_activity_case', 'case_id'),
        Index('idx_activity_audio', 'audio_id'),
        Index('idx_activity_type', 'activity_type_id'),
        Index('idx_activity_created', 'created_at'),
        Index('idx_activity_task', 'task_id'),
    )

class ActivityType(BaseModel):
    __tablename__ = 'activitytypes'

    id = Column(Integer, primary_key=True, index=True)
    type_name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, default=False)
    updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Constraints
    __table_args__ = (
        CheckConstraint("type_name ~ '^[a-z_]+$'", name="check_type_name_format"),
    )

class AuthSession(BaseModel):
    __tablename__ = 'auth_sessions'

    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    jti = Column(String(128), unique=True, nullable=False, index=True)
    csrf_token_hash = Column(String(128), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    ip_address = Column(String(45))
    user_agent = Column(String(500))

    user = relationship("User")

    __table_args__ = (
        Index('idx_auth_session_user', 'user_id'),
        Index('idx_auth_session_expires', 'expires_at'),
        Index('idx_auth_session_revoked', 'revoked_at'),
    )

class SecurityAuditLog(BaseModel):
    __tablename__ = 'security_audit_logs'

    event_type = Column(String(80), nullable=False)
    status = Column(String(30), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    attempted_identifier_hash = Column(String(128))
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    detail = Column(JSON, default=dict)

    user = relationship("User")

    __table_args__ = (
        Index('idx_security_audit_event', 'event_type'),
        Index('idx_security_audit_user', 'user_id'),
        Index('idx_security_audit_created', 'created_at'),
        Index('idx_security_audit_identifier', 'attempted_identifier_hash'),
    )

class Task(BaseModel):
    __tablename__ = 'tasks'

    id = Column(String, primary_key=True, index=True)
    filename = Column(String)
    status = Column(String)
    result = Column(JSON)
    error = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    case_id = Column(Integer, ForeignKey('cases.id'), nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User")

    audio_files = relationship("AudioFile", back_populates="task")
    activities = relationship("ActivityLog", back_populates="task")

    # Indexes
    __table_args__ = (
        Index('idx_task_id', 'id'),
        Index('idx_task_status', 'status'),
        Index('idx_task_user', 'user_id'),
        Index('idx_task_created_at', 'created_at'),
        Index('idx_task_updated_at', 'updated_at'),
    )

class Summary(BaseModel):
    __tablename__ = 'summaries'
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)  # 'multi' hoặc 'case'
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    case_id = Column(Integer, ForeignKey('cases.id'), nullable=True)
    files = Column(JSONB, nullable=True)  # Danh sách file liên quan (id, filename)
    content = Column(Text, nullable=False)

    case = relationship('Case', back_populates='summaries')

    # Indexes
    __table_args__ = (
        Index('idx_summary_case', 'case_id'),
    )
