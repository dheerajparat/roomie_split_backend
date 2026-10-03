from datetime import datetime, timedelta, timezone
from typing import List
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.core.config import settings
from html import escape
from urllib.parse import quote
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import (
    DirectResetPasswordRequest,
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
    req_email = str(reset_request.email).strip().lower()

    user = db.query(User).filter(
        User.email.ilike(req_email)
    ).first()

    # Don't reveal whether the email exists
    if not user:
        return ForgotPasswordResponse(
            message="If this email exists, a password reset link has been sent."
        )

    # Generate random reset token
    token = create_password_reset_token()

    # Store only the hash in database
    token_hash = get_password_reset_token_hash(token)

    # Token valid for 10 minutes
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    )

    # URL that will be sent through email
    reset_url = (
        f"{settings.PASSWORD_RESET_WEB_URL}"
        f"?token={quote(token, safe='')}"
    )

    # Save reset information
    user.reset_password_token_hash = token_hash
    user.reset_password_expires_at = expires_at

    db.add(user)
    db.commit()

    # Send email
    if not send_password_reset_email(user.email, reset_url):
        logger.error(
            "Failed to send password reset email to %s",
            user.email,
        )

    return ForgotPasswordResponse(
        message="If this email exists, a password reset link has been sent."
    )

@router.post("/direct-reset-password", response_model=MessageResponse)
def direct_reset_password(
    reset_data: DirectResetPasswordRequest,
    db: Session = Depends(get_db),
):
    if reset_data.master_password != settings.DIRECT_RESET_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid master password.",
        )
    identifier = reset_data.username_or_email.strip().lower()
    user = db.query(User).filter(
        or_(
            User.email.ilike(identifier),
            User.username.ilike(identifier),
        )
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found with this username or email.",
        )

    user.hashed_password = get_password_hash(reset_data.new_password)
    user.reset_password_token_hash = None
    user.reset_password_expires_at = None
    db.add(user)
    db.commit()

    print(f"\n🔑 [DIRECT RESET] Password updated for {user.username} ({user.email})\n", flush=True)

    return MessageResponse(
        message=f"Password for '{user.username}' reset successfully! You can now log in."
    )

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
@router.get("/forgetpassword", response_class=HTMLResponse)
def forget_password_page(token: str):
    safe_token = escape(token, quote=True)

    return HTMLResponse(
        content=f"""
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <title>Reset Password - RoomieSplit</title>

    <style>
        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;
            min-height: 100vh;

            display: flex;
            align-items: center;
            justify-content: center;

            font-family: Arial, sans-serif;

            background: #f5f7fb;
        }}

        .card {{
            width: min(420px, 92%);

            padding: 30px;

            background: white;

            border-radius: 16px;

            box-shadow:
                0 10px 35px rgba(0, 0, 0, 0.10);
        }}

        h2 {{
            margin-top: 0;
            margin-bottom: 8px;
        }}

        .subtitle {{
            color: #666;
            font-size: 14px;
            margin-bottom: 24px;
        }}

        label {{
            display: block;

            margin-top: 16px;
            margin-bottom: 7px;

            font-weight: 600;
        }}

        input {{
            width: 100%;

            padding: 13px;

            border: 1px solid #d1d5db;
            border-radius: 9px;

            font-size: 16px;

            outline: none;
        }}

        input:focus {{
            border-color: #2563eb;
        }}

        button {{
            width: 100%;

            margin-top: 22px;

            padding: 13px;

            border: none;
            border-radius: 9px;

            background: #2563eb;
            color: white;

            font-size: 16px;
            font-weight: 600;

            cursor: pointer;
        }}

        button:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
        }}

        #message {{
            margin-top: 16px;
            font-size: 14px;
        }}

        .success {{
            color: #15803d;
        }}

        .error {{
            color: #dc2626;
        }}
    </style>
</head>

<body>

<div class="card">

    <h2>Reset Password</h2>

    <div class="subtitle">
        Create a new password for your RoomieSplit account.
        This link is valid for 10 minutes.
    </div>

    <form id="resetForm">

        <label for="password">
            New Password
        </label>

        <input
            id="password"
            type="password"
            required
            autocomplete="new-password"
        >

        <label for="confirmPassword">
            Confirm Password
        </label>

        <input
            id="confirmPassword"
            type="password"
            required
            autocomplete="new-password"
        >

        <input
            type="hidden"
            id="token"
            value="{safe_token}"
        >

        <button
            id="submitButton"
            type="submit"
        >
            Reset Password
        </button>

    </form>

    <div id="message"></div>

</div>

<script>

const form = document.getElementById("resetForm");
const message = document.getElementById("message");
const button = document.getElementById("submitButton");

form.addEventListener("submit", async function(event) {{

    event.preventDefault();

    const password =
        document.getElementById("password").value;

    const confirmPassword =
        document.getElementById("confirmPassword").value;

    const token =
        document.getElementById("token").value;

    message.className = "";

    if (password !== confirmPassword) {{

        message.textContent =
            "Passwords do not match.";

        message.className = "error";

        return;
    }}

    button.disabled = true;
    button.textContent = "Resetting...";

    try {{

        const response = await fetch(
            "/api/auth/reset-password",
            {{
                method: "POST",

                headers: {{
                    "Content-Type": "application/json"
                }},

                body: JSON.stringify({{
                    token: token,
                    new_password: password
                }})
            }}
        );

        const data = await response.json();

        if (!response.ok) {{

            message.textContent =
                data.detail ||
                "Invalid or expired reset link.";

            message.className = "error";

            button.disabled = false;
            button.textContent = "Reset Password";

            return;
        }}

        message.textContent =
            data.message ||
            "Password reset successfully.";

        message.className = "success";

        form.reset();

        button.disabled = true;
        button.textContent = "Password Reset";

    }} catch (error) {{

        message.textContent =
            "Unable to connect to the server.";

        message.className = "error";

        button.disabled = false;
        button.textContent = "Reset Password";
    }}

}});

</script>

</body>

</html>
"""
    )
