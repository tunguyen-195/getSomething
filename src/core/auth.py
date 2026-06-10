import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Iterable

import bcrypt
import redis
from fastapi import Depends, HTTPException, Request, Response, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from src.core.config import settings
from src.database.config.database import SessionLocal, get_db
from src.database.models.models import (
    AudioFile,
    AuthSession,
    Case,
    CaseParticipant,
    SecurityAuditLog,
    Task,
    User,
)


PUBLIC_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/csrf",
    "/api/v1/auth/login",
}

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
DUMMY_BCRYPT_HASH = bcrypt.hashpw(b"invalid-password", bcrypt.gensalt()).decode()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_value(value: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def client_ip(request: Request) -> str:
    remote_addr = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and remote_addr in set(settings.TRUSTED_PROXY_IPS):
        return forwarded.split(",")[0].strip()[:45]
    return remote_addr


def user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:500]


def audit_security_event(
    db: Session,
    event_type: str,
    status_value: str,
    request: Request,
    user_id: int | None = None,
    attempted_identifier: str | None = None,
    detail: dict | None = None,
) -> None:
    safe_detail = detail or {}
    db.add(
        SecurityAuditLog(
            event_type=event_type,
            status=status_value,
            user_id=user_id,
            attempted_identifier_hash=hash_value(attempted_identifier.lower())
            if attempted_identifier
            else None,
            ip_address=client_ip(request),
            user_agent=user_agent(request),
            detail=safe_detail,
        )
    )


def _redis_client():
    password = settings.REDIS_PASSWORD or None
    return redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=password,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def check_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    try:
        r = _redis_client()
        count = r.incr(key)
        if count == 1:
            r.expire(key, window_seconds)
        if count > limit:
            raise HTTPException(status_code=429, detail="Too many requests")
    except HTTPException:
        raise
    except Exception as exc:
        production = settings.ENVIRONMENT.lower() in {"prod", "production"} or (
            settings.AUTH_ENABLED and not settings.DEBUG
        )
        if production:
            raise HTTPException(status_code=503, detail="Rate limiter unavailable") from exc


def issue_csrf_cookie(response: Response) -> str:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=settings.COOKIE_PATH,
    )
    return token


def _set_auth_cookie(response: Response, token: str, expires_at: datetime) -> None:
    max_age = max(0, int((expires_at - _utcnow()).total_seconds()))
    response.set_cookie(
        settings.AUTH_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=settings.COOKIE_PATH,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.AUTH_COOKIE_NAME, path=settings.COOKIE_PATH, domain=settings.COOKIE_DOMAIN)
    response.delete_cookie(settings.CSRF_COOKIE_NAME, path=settings.COOKIE_PATH, domain=settings.COOKIE_DOMAIN)


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.cookies.get(settings.AUTH_COOKIE_NAME)


def create_session(db: Session, user: User, request: Request, response: Response, csrf_token: str) -> str:
    expires_at = _utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    jti = secrets.token_urlsafe(32)
    token = jwt.encode(
        {"sub": str(user.id), "jti": jti, "exp": expires_at},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    db.add(
        AuthSession(
            user_id=user.id,
            jti=jti,
            csrf_token_hash=hash_value(csrf_token),
            expires_at=expires_at,
            ip_address=client_ip(request),
            user_agent=user_agent(request),
        )
    )
    user.last_login = _utcnow().replace(tzinfo=None)
    _set_auth_cookie(response, token, expires_at)
    return token


def authenticate_request(request: Request, db: Session) -> tuple[User, AuthSession]:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload["sub"])
        jti = payload["jti"]
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc

    session = db.query(AuthSession).filter(AuthSession.jti == jti).first()
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = session.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if session.revoked_at or not expires_at or expires_at < _utcnow():
        raise HTTPException(status_code=401, detail="Invalid session")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user, session


def validate_csrf(request: Request, session: AuthSession) -> None:
    if request.method.upper() not in UNSAFE_METHODS:
        return
    header_token = request.headers.get("x-csrf-token")
    cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
    if not header_token or not cookie_token or header_token != cookie_token:
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    if not hmac.compare_digest(hash_value(header_token), session.csrf_token_hash):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def verify_password(user: User | None, password: str) -> bool:
    if not user or not user.password_hash:
        bcrypt.checkpw(password.encode(), DUMMY_BCRYPT_HASH.encode())
        return False
    return user.check_password(password)


async def auth_middleware(request: Request, call_next):
    if not settings.AUTH_ENABLED:
        return await call_next(request)
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    db = SessionLocal()
    try:
        user, session = authenticate_request(request, db)
        validate_csrf(request, session)
        request.state.user = user
        request.state.auth_session = session
        return await call_next(request)
    except HTTPException as exc:
        return Response(
            content=f'{{"detail":"{exc.detail}"}}',
            status_code=exc.status_code,
            media_type="application/json",
        )
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    if not settings.AUTH_ENABLED:
        user = db.query(User).filter(User.username == "admin").first() or db.query(User).first()
        if not user:
            raise HTTPException(status_code=500, detail="No development user available")
        return user
    if getattr(request.state, "user", None):
        user_id = request.state.user.id
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid session")
        return user
    user, session = authenticate_request(request, db)
    validate_csrf(request, session)
    return user


def is_admin(user: User) -> bool:
    return bool(user.role and user.role.role_name == "admin")


def has_role_permission(user: User, permission: str) -> bool:
    permissions = user.role.permissions if user.role and isinstance(user.role.permissions, dict) else {}
    return bool(permissions.get("all") or permissions.get(permission))


def case_permission(db: Session, user: User, case_id: int) -> str | None:
    if is_admin(user):
        return "admin"
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return None
    if case.created_by == user.id:
        return "owner"
    participant = (
        db.query(CaseParticipant)
        .filter(
            CaseParticipant.case_id == case_id,
            CaseParticipant.user_id == user.id,
            CaseParticipant.is_active.is_(True),
        )
        .first()
    )
    return participant.role.role_name if participant and participant.role else None


def assert_case_access(db: Session, user: User, case_id: int, action: str) -> None:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.is_archived and action != "read":
        raise HTTPException(status_code=403, detail="Archived case is read-only")

    role = case_permission(db, user, case_id)
    allowed = {
        "admin": {"read", "write", "process", "delete", "archive"},
        "owner": {"read", "write", "process", "delete", "archive"},
        "member": {"read", "write", "process"},
        "viewer": {"read"},
    }
    if action not in allowed.get(role or "", set()):
        raise HTTPException(status_code=403, detail="Forbidden")


def accessible_case_ids(db: Session, user: User) -> Iterable[int] | None:
    if is_admin(user):
        return None
    participant_case_ids = [
        row.case_id
        for row in db.query(CaseParticipant.case_id)
        .filter(CaseParticipant.user_id == user.id, CaseParticipant.is_active.is_(True))
        .all()
    ]
    owned_case_ids = [row.id for row in db.query(Case.id).filter(Case.created_by == user.id).all()]
    return set(participant_case_ids + owned_case_ids)


def assert_audio_access(db: Session, user: User, audio_id: int, action: str) -> AudioFile:
    audio = db.query(AudioFile).filter(AudioFile.id == audio_id).first()
    if not audio:
        raise HTTPException(status_code=404, detail="Audio file not found")
    assert_case_access(db, user, audio.case_id, action)
    return audio


def assert_task_access(db: Session, user: User, task_id: str, action: str) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    linked_audio = db.query(AudioFile).filter(AudioFile.task_id == task_id).first()
    if task.case_id is None:
        if linked_audio:
            assert_case_access(db, user, linked_audio.case_id, action)
            return task
        if not is_admin(user) and task.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        return task
    try:
        assert_case_access(db, user, task.case_id, action)
    except HTTPException as exc:
        if exc.status_code != 403 or not linked_audio:
            raise
        assert_case_access(db, user, linked_audio.case_id, action)
    return task
