from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.auth import (
    audit_security_event,
    authenticate_request,
    check_rate_limit,
    clear_auth_cookies,
    client_ip,
    create_session,
    get_current_user,
    hash_value,
    issue_csrf_cookie,
    verify_password,
)
from src.database.config.database import get_db
from src.database.models.models import AuthSession, User

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


def _generic_login_error():
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/csrf")
def get_csrf(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(settings.CSRF_COOKIE_NAME) or issue_csrf_cookie(response)
    if settings.AUTH_ENABLED and request.cookies.get(settings.AUTH_COOKIE_NAME):
        try:
            _, session = authenticate_request(request, db)
            db_session = db.query(AuthSession).filter(AuthSession.id == session.id).first()
            if db_session:
                db_session.csrf_token_hash = hash_value(token)
                db.commit()
        except HTTPException:
            db.rollback()
    return {"csrf_token": token}


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    csrf_cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)
    csrf_header = request.headers.get("x-csrf-token")
    if settings.AUTH_ENABLED and (not csrf_cookie or not csrf_header or csrf_cookie != csrf_header):
        raise HTTPException(status_code=403, detail="CSRF validation failed")

    identifier = payload.username.strip().lower()
    identifier_hash = hash_value(identifier)
    ip = client_ip(request)
    check_rate_limit(
        f"rl:login:{ip}:{identifier_hash}",
        limit=settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )

    user = (
        db.query(User)
        .filter((User.username == payload.username) | (User.email == payload.username))
        .first()
    )
    password_ok = verify_password(user, payload.password)
    if not user or not password_ok or not user.is_active:
        audit_security_event(
            db,
            "login",
            "failure",
            request,
            user_id=user.id if user else None,
            attempted_identifier=identifier,
            detail={"reason": "invalid_credentials"},
        )
        db.commit()
        _generic_login_error()

    csrf_token = csrf_cookie or issue_csrf_cookie(response)
    create_session(db, user, request, response, csrf_token)
    audit_security_event(db, "login", "success", request, user_id=user.id)
    db.commit()
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.role_name if user.role else None,
        }
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = getattr(request.state, "auth_session", None)
    if session:
        db_session = db.query(AuthSession).filter(AuthSession.id == session.id).first()
        if db_session:
            db_session.revoked_at = datetime.now(timezone.utc)
    audit_security_event(db, "logout", "success", request, user_id=current_user.id)
    db.commit()
    clear_auth_cookies(response)
    return {"detail": "Logged out"}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role.role_name if current_user.role else None,
        "is_active": current_user.is_active,
    }
