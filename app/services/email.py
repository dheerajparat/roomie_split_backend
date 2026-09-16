import smtplib
from email.message import EmailMessage

from app.core.config import settings


def is_smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    if not is_smtp_configured():
        return

    message = EmailMessage()
    message["Subject"] = "Reset your RoomieSplit password"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message.set_content(
        "We received a request to reset your RoomieSplit password.\n\n"
        f"Open this link to choose a new password:\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message)
