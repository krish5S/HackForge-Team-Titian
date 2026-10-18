import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME, COOKIE_SECURE, SESSION_SECONDS, current_user, normalize_email,
    password_hasher, public_user, token_hash, validate_origin, verify_password,
)
from app.db.database import get_db
from app.db.models import AuthSession, AuthUser

router = APIRouter(prefix='/auth', tags=['Authentication'])


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class UserOutput(BaseModel):
    id: str
    email: str
    display_name: str
    role: Literal['EMPLOYEE', 'REVIEWER']
    employee_id: str | None


@router.post('/login', response_model=UserOutput, dependencies=[Depends(validate_origin)])
def login(body: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        email = normalize_email(body.email)
    except ValueError:
        email = ''
    user = db.scalar(select(AuthUser).where(AuthUser.email == email))
    if not verify_password(user, body.password):
        raise HTTPException(401, 'Invalid email or password.')
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(body.password)
    previous = request.cookies.get(COOKIE_NAME)
    if previous:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(previous)))
    now = int(time.time())
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, expires_at=now + SESSION_SECONDS))
    db.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=COOKIE_SECURE, samesite='lax', path='/')
    response.headers['Cache-Control'] = 'no-store'
    return public_user(user)


@router.get('/me', response_model=UserOutput)
def me(response: Response, user: AuthUser = Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return public_user(user)


@router.post('/logout', status_code=204, dependencies=[Depends(validate_origin)])
def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        db.commit()
    response = Response(status_code=204, headers={'Cache-Control': 'no-store'})
    response.delete_cookie(COOKIE_NAME, httponly=True, secure=COOKIE_SECURE, samesite='lax', path='/')
    return response
