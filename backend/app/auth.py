"""Cookie session authentication and reusable authorization dependencies."""
import hashlib
import os
import re
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AuthSession, AuthUser

ALLOWED_ORIGINS = tuple(origin.strip().rstrip('/') for origin in os.getenv(
    'AUTH_ALLOWED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173'
).split(',') if origin.strip())
COOKIE_NAME = 'receipt_session'
COOKIE_SECURE = os.getenv('AUTH_COOKIE_SECURE', 'false').lower() == 'true'
SESSION_SECONDS = int(os.getenv('AUTH_SESSION_SECONDS', '28800'))
if SESSION_SECONDS <= 0:
    raise ValueError('AUTH_SESSION_SECONDS must be positive')
password_hasher = PasswordHasher()
# A missing account still performs password verification to avoid a fast lookup path.
_dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if len(normalized) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', normalized):
        raise ValueError('Provide a valid email address.')
    return normalized


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_password(user: AuthUser | None, password: str) -> bool:
    try:
        password_hasher.verify(user.password_hash if user else _dummy_hash, password)
        return user is not None
    except (VerificationError, InvalidHashError):
        return False


def validate_origin(request: Request):
    # Require an explicit trusted Origin, including for login (login CSRF).
    if request.headers.get('origin') not in ALLOWED_ORIGINS:
        raise HTTPException(403, 'Request origin is not allowed.')


def current_user(request: Request, db: Session = Depends(get_db)) -> AuthUser:
    token = request.cookies.get(COOKIE_NAME)
    session = db.get(AuthSession, token_hash(token)) if token and len(token) <= 256 else None
    if session is None or session.expires_at <= int(time.time()):
        raise HTTPException(401, 'Sign in to continue.')
    user = db.get(AuthUser, session.user_id)
    if user is None:
        raise HTTPException(401, 'Sign in to continue.')
    return user


def require_reviewer(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role != 'REVIEWER':
        raise HTTPException(403, 'Reviewer access is required.')
    return user


def public_user(user: AuthUser) -> dict:
    return {key: getattr(user, key) for key in (
        'id', 'email', 'display_name', 'role', 'employee_id'
    )}


def require_employee(user: AuthUser = Depends(current_user), db: Session = Depends(get_db)) -> AuthUser:
    from app.db.models import Employee
    if user.role != 'EMPLOYEE' or not user.employee_id or not db.get(Employee, user.employee_id):
        raise HTTPException(403, 'A linked employee account is required.')
    return user
