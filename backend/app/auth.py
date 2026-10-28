"""Password hashing, opaque revocable sessions and one-use email tokens.

No JWTs in localStorage, no plaintext passwords, no reset tokens in API responses.
Email flows are explicitly unavailable without configured SMTP.
"""
import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from .db import Session, User, AuthSession, AuthToken, Resume, Analysis, ConversionJob, DocumentRecord, get_db, now
from .config import settings

router = APIRouter(prefix='/api/auth', tags=['Authentication'])
COOKIE = 'formiqo_auth'
_password_slots = asyncio.Semaphore(2)


async def password_task(function,*args):
    async with _password_slots:
        return await asyncio.to_thread(function,*args)


def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def aware(value): return value.replace(tzinfo=now().tzinfo)

def user_owner(user): return 'u_' + user.id

def retention_expiry(owner_id):
    return now() + (timedelta(days=settings.account_retention_days) if owner_id.startswith('u_') else timedelta(hours=settings.retention_hours))


def hash_password(password):
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=65536, r=8, p=1, dklen=32, maxmem=128*1024*1024)
    return 'scrypt$65536$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(key).decode()


def verify_password(password, stored):
    try:
        algorithm, cost, salt, key = stored.split('$')
        if algorithm != 'scrypt' or cost not in ('16384','65536'): return False
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(cost), r=8, p=1, dklen=32, maxmem=128*1024*1024)
        return hmac.compare_digest(actual, base64.b64decode(key))
    except (ValueError, TypeError): return False


DUMMY_HASH = hash_password('not-a-real-user-password')


def current_user(request: Request, db=None):
    token = request.cookies.get(COOKIE, '')
    if len(token) != 64 or not settings.accounts_enabled: return None
    if db is None:
        with Session() as session: return current_user(request, session)
    record = db.get(AuthSession, digest(token))
    if not record or aware(record.expires_at) <= now(): return None
    return db.get(User, record.user_id)


def require_user(request: Request, db: DBSession = Depends(get_db)):
    user = current_user(request, db)
    if not user: raise HTTPException(401, 'Sign in to manage your account.')
    return user


def public_user(user):
    return {'id': user.id, 'name': user.name, 'email': user.email, 'verified': user.verified, 'created_at': user.created_at.isoformat()}


def start_session(db, user, response):
    token = secrets.token_hex(32)
    db.add(AuthSession(token_hash=digest(token), user_id=user.id, expires_at=now()+timedelta(days=settings.session_days)))
    response.set_cookie(COOKIE, token, max_age=settings.session_days*86400, secure=settings.secure_cookie, httponly=True, samesite='strict', path='/')


def claim_guest(db, request, user):
    token = request.cookies.get('resumeai_session', '')
    if not re.fullmatch(r'[0-9a-f]{64}', token): return
    old, new = digest(token), user_owner(user)
    expiry = retention_expiry(new)
    db.execute(update(Resume).where(Resume.owner == old, Resume.expires_at > now()).values(owner=new, expires_at=expiry))
    db.execute(update(Analysis).where(Analysis.owner == old).values(owner=new))
    db.execute(update(ConversionJob).where(ConversionJob.owner == old, ConversionJob.expires_at > now()).values(owner=new, expires_at=expiry))
    db.execute(update(DocumentRecord).where(DocumentRecord.owner == old).values(owner=new))


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    claim_guest: bool = False

    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value): raise ValueError('Enter a valid email address')
        return value


class Register(Credentials):
    name: str = Field(min_length=1, max_length=120)

    @field_validator('name')
    @classmethod
    def name_valid(cls, value):
        if not value.strip() or any(ord(c)<32 for c in value): raise ValueError('Enter your name')
        return value.strip()


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class TokenRequest(BaseModel):
    token: str = Field(pattern=r'^[a-f0-9]{64}$')


class ResetRequest(TokenRequest):
    password: str = Field(min_length=12, max_length=128)


class PasswordRequest(BaseModel):
    password: str = Field(min_length=12, max_length=128)


def send_mail(address, purpose, token):
    message = EmailMessage()
    message['From'], message['To'] = settings.smtp_from, address
    message['Subject'] = 'Reset your Formiqo password' if purpose == 'reset' else 'Verify your Formiqo email'
    # Fragment tokens are not sent in HTTP request URLs or proxy access logs.
    link = settings.public_url.rstrip('/') + '/app/settings#' + purpose + '=' + token
    message.set_content(f'Use this one-time link within one hour:\n{link}\n\nIf you did not request this, ignore this email.')
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_starttls: client.starttls()
        if settings.smtp_user: client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)


async def deliver_token(db, user, purpose):
    token = secrets.token_hex(32)
    try: await asyncio.to_thread(send_mail, user.email, purpose, token)
    except (OSError, smtplib.SMTPException): raise HTTPException(503, 'Email delivery is unavailable. Please retry later; no reset or verification success is claimed.')
    db.execute(delete(AuthToken).where(AuthToken.user_id == user.id, AuthToken.purpose == purpose))
    db.add(AuthToken(token_hash=digest(token), user_id=user.id, purpose=purpose, expires_at=now()+timedelta(hours=1)))
    db.commit()


def enabled():
    if not settings.accounts_enabled: raise HTTPException(503, 'Accounts are disabled by this deployment.')


@router.get('/me')
def me(request: Request, db: DBSession = Depends(get_db)):
    user = current_user(request, db)
    return {'user': public_user(user) if user else None, 'accounts_enabled': settings.accounts_enabled, 'email_available': bool(settings.smtp_host), 'verification_required': settings.require_email_verification}


@router.post('/register', status_code=201)
async def register(data: Register, request: Request, response: Response, db: DBSession = Depends(get_db)):
    from .storage import rate_limit
    enabled(); rate_limit(request, 'auth-register', limit=10)
    if settings.require_email_verification and not settings.smtp_host: raise HTTPException(503, 'SMTP must be configured before verified accounts can be enabled.')
    user = User(name=data.name, email=data.email, password_hash=await password_task(hash_password, data.password))
    db.add(user)
    try: db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, 'Registration could not be completed. Use sign in or password reset if you already have an account.')
    if data.claim_guest and not settings.require_email_verification: claim_guest(db, request, user)
    if not settings.require_email_verification: start_session(db, user, response)
    db.commit()
    if settings.require_email_verification:
        await deliver_token(db, user, 'verify')
        return {'user': None, 'notice': 'Check your email to verify the account, then sign in.'}
    return {'user': public_user(user), 'notice': 'Account created. Your server-side session is active.'}


@router.post('/login')
async def login(data: Credentials, request: Request, response: Response, db: DBSession = Depends(get_db)):
    from .storage import rate_limit
    enabled(); rate_limit(request, 'auth-login', limit=15)
    user = db.scalar(select(User).where(User.email == data.email))
    valid = await password_task(verify_password, data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid: raise HTTPException(401, 'Email or password is incorrect.')
    if settings.require_email_verification and not user.verified: raise HTTPException(403, 'Verify your email before signing in. Use Resend verification if needed.')
    old = request.cookies.get(COOKIE, '')
    if old: db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(old)))
    if data.claim_guest: claim_guest(db, request, user)
    start_session(db, user, response); db.commit()
    return {'user': public_user(user)}


@router.post('/logout', status_code=204)
def logout(request: Request, response: Response, db: DBSession = Depends(get_db)):
    db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(request.cookies.get(COOKIE, '')))); db.commit()
    response.delete_cookie(COOKIE, path='/'); response.status_code=204
    return response


@router.post('/refresh')
def refresh(request: Request, response: Response, user=Depends(require_user), db: DBSession = Depends(get_db)):
    db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(request.cookies.get(COOKIE, ''))))
    start_session(db, user, response); db.commit()
    return {'user': public_user(user)}


@router.get('/sessions')
def sessions(request: Request, user=Depends(require_user), db: DBSession = Depends(get_db)):
    current = digest(request.cookies.get(COOKIE, ''))
    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at > now()).order_by(AuthSession.created_at.desc())).all()
    return {'items': [{'created_at': r.created_at.isoformat(), 'expires_at': r.expires_at.isoformat(), 'current': r.token_hash == current} for r in rows]}


@router.post('/revoke-other-sessions', status_code=204)
def revoke_others(request: Request, user=Depends(require_user), db: DBSession = Depends(get_db)):
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != digest(request.cookies.get(COOKIE, '')))); db.commit()
    return Response(status_code=204)


@router.post('/forgot-password')
async def forgot(data: EmailRequest, request: Request, db: DBSession = Depends(get_db)):
    from .storage import rate_limit
    enabled(); rate_limit(request, 'auth-email', limit=10)
    if not settings.smtp_host: raise HTTPException(503, 'Password reset requires configured SMTP. Contact the deployment administrator; no email was sent.')
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if user: await deliver_token(db, user, 'reset')
    return {'notice': 'If this address belongs to an account, a one-time reset link has been sent.'}


@router.post('/resend-verification')
async def resend(data: EmailRequest, request: Request, db: DBSession = Depends(get_db)):
    from .storage import rate_limit
    enabled(); rate_limit(request, 'auth-email', limit=10)
    if not settings.smtp_host: raise HTTPException(503, 'Email verification requires configured SMTP; no email was sent.')
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if user and not user.verified: await deliver_token(db, user, 'verify')
    return {'notice': 'If verification is needed for this account, a one-time verification link has been sent.'}


def consume_token(db, token, purpose):
    # A conditional DELETE makes consumption atomic even across concurrent requests.
    result = db.execute(delete(AuthToken).where(AuthToken.token_hash == digest(token), AuthToken.purpose == purpose, AuthToken.expires_at > now()).returning(AuthToken.user_id)).scalar_one_or_none()
    if not result: raise HTTPException(400, 'The one-time link is invalid, expired or already used.')
    return db.get(User, result)


@router.post('/reset-password')
async def reset(data: ResetRequest, db: DBSession = Depends(get_db)):
    enabled(); user = consume_token(db, data.token, 'reset')
    user.password_hash = await password_task(hash_password, data.password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id)); db.commit()
    return {'notice': 'Password changed. All sessions were revoked. Sign in with the new password.'}


@router.post('/verify-email')
def verify(data: TokenRequest, db: DBSession = Depends(get_db)):
    enabled(); user = consume_token(db, data.token, 'verify'); user.verified=True; db.commit()
    return {'notice': 'Email verified. You can now sign in.'}


@router.delete('/account', status_code=204)
async def delete_account(data: PasswordRequest, request: Request, response: Response, user=Depends(require_user), db: DBSession = Depends(get_db)):
    if not await password_task(verify_password, data.password, user.password_hash): raise HTTPException(401, 'Password is incorrect.')
    from .library import delete_owned_data
    delete_owned_data(db, user_owner(user))
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id)); db.execute(delete(AuthToken).where(AuthToken.user_id == user.id))
    db.delete(user); db.commit(); response.delete_cookie(COOKIE, path='/'); response.status_code=204
    return response
