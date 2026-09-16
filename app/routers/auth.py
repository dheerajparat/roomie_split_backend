from datetime import datetime, timedelta, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    MessageResponse,
    ResetPasswordRequest,
    UserCreate,
    UserLogin,
    UserOut,
    Token,
)
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    get_password_hash,
    get_password_reset_token_hash,
    verify_password,
)
from app.routers.deps import get_current_user
from app.services.email import is_email_configured, send_password_reset_email

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_REQUEST_MESSAGE = "If this email exists, a password reset link has been sent."

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    # Check if user already exists
    existing = db.query(User).filter(
        or_(User.email == user_in.email, User.username == user_in.username)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email or username already exists.",
        )

    db_user = User(
        email=user_in.email,
        username=user_in.username,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    access_token = create_access_token(subject=db_user.id)
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserOut.model_validate(db_user),
    )

@router.post("/login", response_model=Token)
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        or_(
            User.email == login_data.username_or_email,
            User.username == login_data.username_or_email,
        )
    ).first()
    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password",
        )

    access_token = create_access_token(subject=user.id)
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )

@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(
    reset_request: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == reset_request.email).first()
    response = ForgotPasswordResponse(message=RESET_REQUEST_MESSAGE)

    if not user:
        return response

    token = create_password_reset_token()
    token_hash = get_password_reset_token_hash(token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    )
    reset_url = f"{settings.FRONTEND_RESET_PASSWORD_URL}?token={token}"

    user.reset_password_token_hash = token_hash
    user.reset_password_expires_at = expires_at
    db.add(user)
    db.commit()

    email_sent = send_password_reset_email(user.email, reset_url)

    if (
        (not is_email_configured() or not email_sent)
        and settings.ENVIRONMENT.lower() != "production"
    ):
        response.reset_token = token
        response.reset_url = reset_url

    return response

@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    reset_data: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    token_hash = get_password_reset_token_hash(reset_data.token)
    user = (
        db.query(User)
        .filter(User.reset_password_token_hash == token_hash)
        .first()
    )

    now = datetime.now(timezone.utc)
    if (
        not user
        or not user.reset_password_expires_at
        or user.reset_password_expires_at.replace(tzinfo=timezone.utc) < now
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    user.hashed_password = get_password_hash(reset_data.new_password)
    user.reset_password_token_hash = None
    user.reset_password_expires_at = None
    db.add(user)
    db.commit()

    return MessageResponse(message="Password reset successfully.")

@router.get("/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)

@router.get("/users/search", response_model=List[UserOut])
def search_users(
    q: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if len(q.strip()) < 2:
        return []
    query = f"%{q.strip().lower()}%"
    users = (
        db.query(User)
        .filter(
            User.id != current_user.id,
            or_(
                User.username.ilike(query),
                User.email.ilike(query),
                User.full_name.ilike(query),
            ),
        )
        .limit(10)
        .all()
    )
    return [UserOut.model_validate(u) for u in users]
