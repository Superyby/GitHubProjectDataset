import hashlib
import hmac
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import AuthToken, EmailVerificationCode, User


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_secret(secret: str, salt: str | None = None) -> str:
    current_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), current_salt.encode(), 120_000)
    return f"{current_salt}${digest.hex()}"


def verify_secret(secret: str, stored_hash: str) -> bool:
    try:
        salt, expected = stored_hash.split("$", 1)
    except ValueError:
        return False
    candidate = hash_secret(secret, salt).split("$", 1)[1]
    return hmac.compare_digest(candidate, expected)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_email_code(self, db: Session, email: str, purpose: str = "login") -> None:
        normalized_email = email.strip().lower()
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = _now() + timedelta(minutes=self.settings.email_code_expire_minutes)
        db.add(
            EmailVerificationCode(
                email=normalized_email,
                code_hash=hash_secret(code),
                purpose=purpose,
                expires_at=expires_at,
            )
        )
        db.commit()
        self._send_code_email(normalized_email, code)

    def register_user(self, db: Session, username: str, email: str, password: str) -> User:
        normalized_username = username.strip()
        normalized_email = email.strip().lower()
        existing = db.scalar(
            select(User).where(
                or_(User.username == normalized_username, User.email == normalized_email)
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="Username or email already exists")
        user = User(
            username=normalized_username,
            email=normalized_email,
            password_hash=hash_secret(password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def login_with_password(self, db: Session, account: str, password: str) -> tuple[User, str]:
        normalized_account = account.strip().lower()
        user = db.scalar(
            select(User).where(
                or_(User.username == account.strip(), User.email == normalized_account),
                User.is_active.is_(True),
            )
        )
        if user is None or not verify_secret(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username/email or password")
        return user, self.create_token(db, user)

    def login_with_email_code(self, db: Session, email: str, code: str) -> tuple[User, str]:
        normalized_email = email.strip().lower()
        verification = db.scalar(
            select(EmailVerificationCode)
            .where(
                EmailVerificationCode.email == normalized_email,
                EmailVerificationCode.purpose == "login",
                EmailVerificationCode.consumed_at.is_(None),
                EmailVerificationCode.expires_at > _now(),
            )
            .order_by(EmailVerificationCode.created_time.desc())
        )
        if verification is None or not verify_secret(code.strip(), verification.code_hash):
            raise HTTPException(status_code=401, detail="Invalid or expired email code")
        user = db.scalar(select(User).where(User.email == normalized_email, User.is_active.is_(True)))
        if user is None:
            username = normalized_email.split("@", 1)[0]
            suffix = secrets.token_hex(3)
            user = self.register_user(db, f"{username}_{suffix}", normalized_email, secrets.token_urlsafe(24))
        verification.consumed_at = _now()
        db.commit()
        return user, self.create_token(db, user)

    def create_token(self, db: Session, user: User) -> str:
        token = secrets.token_urlsafe(32)
        db.add(
            AuthToken(
                user_id=user.id,
                token_hash=token_digest(token),
                expires_at=_now() + timedelta(hours=self.settings.auth_token_expire_hours),
            )
        )
        db.commit()
        return token

    def revoke_token(self, db: Session, token: str) -> None:
        auth_token = self._find_token(db, token)
        if auth_token is not None:
            auth_token.revoked_at = _now()
            db.commit()

    def authenticate_token(self, db: Session, token: str) -> User:
        auth_token = self._find_token(db, token)
        if (
            auth_token is None
            or auth_token.revoked_at is not None
            or auth_token.expires_at <= _now()
            or not auth_token.user.is_active
        ):
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return auth_token.user

    def _find_token(self, db: Session, token: str) -> AuthToken | None:
        return db.scalar(
            select(AuthToken).where(
                AuthToken.token_hash == token_digest(token),
                AuthToken.expires_at > _now(),
                AuthToken.revoked_at.is_(None),
            )
        )

    def _send_code_email(self, email: str, code: str) -> None:
        if not self.settings.smtp_host or not self.settings.smtp_from:
            raise HTTPException(status_code=500, detail="SMTP is not configured")

        message = EmailMessage()
        message["Subject"] = "Your GitHub Radar login code"
        message["From"] = self.settings.smtp_from
        message["To"] = email
        message.set_content(
            f"Your login code is {code}. It expires in "
            f"{self.settings.email_code_expire_minutes} minutes."
        )

        smtp_class = smtplib.SMTP_SSL if self.settings.smtp_use_ssl else smtplib.SMTP
        with smtp_class(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as smtp:
            if self.settings.smtp_use_tls and not self.settings.smtp_use_ssl:
                smtp.starttls()
            if self.settings.smtp_username and self.settings.smtp_password:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    token = authorization.split(" ", 1)[1].strip()
    return AuthService(settings).authenticate_token(db, token)
