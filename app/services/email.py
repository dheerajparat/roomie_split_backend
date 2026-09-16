import smtplib
from email.message import EmailMessage
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    if not is_smtp_configured():
        return False

    message = EmailMessage()
    message["Subject"] = "Reset your RoomieSplit password"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message.set_content(
        "We received a request to reset your RoomieSplit password.\n\n"
        f"Open this link to choose a new password:\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )

    try:
        with smtplib.SMTP(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        ) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                password = settings.SMTP_PASSWORD
                if settings.SMTP_HOST == "smtp.gmail.com":
                    password = password.replace(" ", "")
                server.login(settings.SMTP_USERNAME, password)
            server.send_message(message)
        return True
    except Exception:
        logger.exception("Failed to send password reset email")
        return False
