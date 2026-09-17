import smtplib
import socket
import urllib.request
import urllib.error
import json
import logging
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Email body builders
# ---------------------------------------------------------------------------

def _build_reset_email_html(reset_url: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto">
      <h2 style="color:#333">Reset your RoomieSplit password</h2>
      <p>We received a request to reset your password. Click the button below
         to choose a new one. The link expires in
         {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes.</p>
      <a href="{reset_url}"
         style="display:inline-block;padding:12px 24px;background:#4F46E5;
                color:#fff;text-decoration:none;border-radius:6px;font-weight:bold">
        Reset Password
      </a>
      <p style="margin-top:24px;color:#888;font-size:13px">
        If you didn't request this, you can safely ignore this email.
      </p>
    </div>
    """


def _build_reset_email_text(reset_url: str) -> str:
    return (
        "We received a request to reset your RoomieSplit password.\n\n"
        f"Open this link to choose a new password:\n{reset_url}\n\n"
        f"The link expires in {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes.\n\n"
        "If you did not request this, you can ignore this email."
    )


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def is_email_configured() -> bool:
    """Return True if at least one email provider is configured."""
    return (
        bool(settings.BREVO_API_KEY)
        or bool(settings.RESEND_API_KEY)
        or bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)
    )


# Keep old name as alias (used in auth.py)
def is_smtp_configured() -> bool:
    return is_email_configured()


# ---------------------------------------------------------------------------
# Brevo / Sendinblue  (RECOMMENDED – free 300/day, no domain needed)
# HTTPS API → port 443, never blocked by cloud firewalls.
# Just verify your sender email at https://app.brevo.com/senders
# ---------------------------------------------------------------------------

def _send_via_brevo(to_email: str, reset_url: str) -> bool:
    payload = json.dumps({
        "sender": {
            "name": "RoomieSplit",
            "email": settings.BREVO_FROM_EMAIL or settings.BREVO_SENDER_EMAIL,
        },
        "to": [{"email": to_email}],
        "subject": "Reset your RoomieSplit password",
        "htmlContent": _build_reset_email_html(reset_url),
        "textContent": _build_reset_email_text(reset_url),
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "api-key": settings.BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            logger.info("Brevo email sent: messageId=%s", body.get("messageId"))
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error("Brevo API error %s: %s", e.code, body)
        return False
    except Exception:
        logger.exception("Brevo send failed")
        return False


# ---------------------------------------------------------------------------
# Resend  (requires verified custom domain for non-sandbox recipients)
# ---------------------------------------------------------------------------

def _send_via_resend(to_email: str, reset_url: str) -> bool:
    try:
        import resend
    except ImportError:
        logger.error("resend package not installed. Run: pip install resend")
        return False

    resend.api_key = settings.RESEND_API_KEY

    # Resend does not allow free email domains (gmail, yahoo…) as sender.
    _FREE = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com"}
    raw = settings.RESEND_FROM_EMAIL or ""
    _addr = raw.split("<")[-1].rstrip(">").strip()
    _domain = _addr.split("@")[-1].lower() if "@" in _addr else ""
    if not raw or _domain in _FREE:
        if raw:
            logger.warning(
                "RESEND_FROM_EMAIL uses %s which Resend does not allow. "
                "Verify a custom domain at https://resend.com/domains",
                _domain,
            )
        from_addr = "RoomieSplit <onboarding@resend.dev>"
    else:
        from_addr = raw

    try:
        params: resend.Emails.SendParams = {
            "from": from_addr,
            "to": [to_email],
            "subject": "Reset your RoomieSplit password",
            "html": _build_reset_email_html(reset_url),
            "text": _build_reset_email_text(reset_url),
        }
        response = resend.Emails.send(params)
        logger.info("Resend email sent: id=%s", response.get("id"))
        return True
    except Exception:
        logger.exception("Resend SDK send failed")
        return False


# ---------------------------------------------------------------------------
# SMTP fallback  (usually blocked on cloud hosts — use Brevo instead)
# ---------------------------------------------------------------------------

def _send_via_smtp(to_email: str, reset_url: str) -> bool:
    message = EmailMessage()
    message["Subject"] = "Reset your RoomieSplit password"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message.set_content(_build_reset_email_text(reset_url))
    message.add_alternative(_build_reset_email_html(reset_url), subtype="html")

    # Force IPv4 — Python 3.12+ Happy-Eyeballs can hide firewall timeouts
    # behind an instant IPv6 "Network is unreachable" error.
    orig_getaddrinfo = socket.getaddrinfo
    def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        return [r for r in orig_getaddrinfo(host, port, family, type, proto, flags)
                if r[0] == socket.AF_INET]
    socket.getaddrinfo = _ipv4_only

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
        logger.exception("SMTP send failed")
        return False
    finally:
        socket.getaddrinfo = orig_getaddrinfo


# ---------------------------------------------------------------------------
# Public interface — priority: Brevo → Resend → SMTP
# ---------------------------------------------------------------------------

def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """
    Send a password-reset email using the first configured provider:
      1. Brevo  (BREVO_API_KEY)  — recommended, free 300/day, no domain needed
      2. Resend (RESEND_API_KEY) — needs verified custom domain for real users
      3. SMTP   (SMTP_HOST)      — usually blocked by cloud host firewalls
    """
    if settings.BREVO_API_KEY:
        return _send_via_brevo(to_email, reset_url)

    if settings.RESEND_API_KEY:
        return _send_via_resend(to_email, reset_url)

    if settings.SMTP_HOST and settings.SMTP_FROM_EMAIL:
        return _send_via_smtp(to_email, reset_url)

    logger.warning(
        "No email provider configured. "
        "Set BREVO_API_KEY (recommended) in your .env to enable password reset emails."
    )
    return False
