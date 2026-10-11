"""Credentials and revocable, HTTP-only local sessions."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AuthSession, User

COOKIE_NAME = "projecta_session"
SESSION_DAYS = 7

class SignUp(BaseModel):
    organization_name: str = Field(min_length=2, max_length=160)
    display_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)

class SignIn(BaseModel):
    email: str
    password: str

def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise HTTPException(422, "กรุณาระบุอีเมลที่ถูกต้อง")
    return value

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt, expected = encoded.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def set_session(response: Response, user: User, db: Session) -> None:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(user_id=user.id, token_hash=token_hash(token), expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=SESSION_DAYS)))
    db.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_DAYS * 86400, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")

def current_user(session_token: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)) -> User:
    if not session_token:
        raise HTTPException(401, "กรุณาเข้าสู่ระบบ")
    session = db.query(AuthSession).filter_by(token_hash=token_hash(session_token)).first()
    if not session or session.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(401, "Session หมดอายุ กรุณาเข้าสู่ระบบใหม่")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "ไม่พบบัญชีผู้ใช้")
    return user

def writable_user(user: User = Depends(current_user)) -> User:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(403, "บัญชีนี้ไม่มีสิทธิ์แก้ไขข้อมูล")
    return user

def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origins.split(","):
        raise HTTPException(403, "ไม่อนุญาตคำขอจากเว็บไซต์นี้")
