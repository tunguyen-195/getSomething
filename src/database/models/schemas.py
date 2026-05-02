from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, EmailStr

# User schemas
class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Task schemas
class Task(BaseModel):
    id: str
    filename: Optional[str] = None
    status: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    case_id: Optional[int] = None
    user_id: Optional[int] = None

    class Config:
        from_attributes = True

# Result schemas
class ResultBase(BaseModel):
    transcript: str
    summary: str
    metadata: Dict[str, Any]

class ResultCreate(ResultBase):
    task_id: int

class Result(ResultBase):
    id: int
    task_id: int
    created_at: datetime

    class Config:
        from_attributes = True

# Response schemas
class TaskResponse(BaseModel):
    task: Task
    result: Optional[Result] = None

class BatchTaskResponse(BaseModel):
    tasks: List[TaskResponse]

# WebSocket schemas
class TaskStatus(BaseModel):
    task_id: int
    status: str
    progress: Optional[float] = None
    message: Optional[str] = None

# Summary schemas
class SummaryBase(BaseModel):
    type: str
    created_at: datetime
    case_id: Optional[int] = None
    files: Optional[List[dict]] = None  # List of file info dicts
    content: str

class SummaryCreate(SummaryBase):
    pass

class SummaryOut(SummaryBase):
    id: int

    class Config:
        from_attributes = True

# Chuẩn hóa schema cho result của Task
class TaskResult(BaseModel):
    transcription: str = ""  # Transcript text (required but can be empty initially)
    summary: str = ""  # Summary (optional, filled later)
    context_analysis: dict = {}  # Context analysis (optional)
    confidence: float = 1.0  # Confidence score
    duration: float = 0.0  # Audio duration in seconds
    language: str = "vi"  # Detected language
    processing_time: float = 0.0  # Processing time in seconds
    # Optional fields for transcription
    filename: Optional[str] = None
    has_diarization: Optional[bool] = False
    num_speakers: Optional[int] = 1
    segments: Optional[list] = []
    formatted_transcript: Optional[str] = None
    transcript_file: Optional[str] = None
    speed_factor: Optional[float] = 0.0
    diarization_method: Optional[str] = "none"
    transcription_time: Optional[float] = 0.0
    diarization_time: Optional[float] = 0.0
    fast_mode: Optional[bool] = True
    audio_url: Optional[str] = None
    caption: Optional[str] = None
    # Có thể mở rộng thêm các trường khác nếu cần

    class Config:
        extra = "allow"  # Cho phép các trường mở rộng nếu có
