import smtplib
import socket
import logging
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
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
    return bool(settings.RESEND_API_KEY) or bool(
        settings.SMTP_HOST and settings.SMTP_FROM_EMAIL
    )


# Keep the old name for backwards-compat with auth.py
def is_smtp_configured() -> bool:
    return is_email_configured()


# ---------------------------------------------------------------------------
# Resend (HTTPS – works on any cloud host)
# ---------------------------------------------------------------------------

def _send_via_resend(to_email: str, reset_url: str) -> bool:
    """Send using the official Resend SDK (HTTPS, port 443 – never blocked)."""
    try:
        import resend  # installed via requirements.txt
    except ImportError:
        logger.error(
            "resend package not installed. Run: pip install resend"
        )
        return False

    resend.api_key = settings.RESEND_API_KEY

    # Free email providers (gmail, yahoo, etc.) cannot be used as Resend senders.
    # Only verified custom domains or Resend's own sandbox address are allowed.
    _FREE_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com"}
    configured_from = settings.RESEND_FROM_EMAIL or ""
    # Extract domain from "Name <email@domain.com>" or "email@domain.com"
    _addr = configured_from.split("<")[-1].rstrip(">").strip()
    _domain = _addr.split("@")[-1].lower() if "@" in _addr else ""
    if not configured_from or _domain in _FREE_DOMAINS:
        if configured_from:
            logger.warning(
                "RESEND_FROM_EMAIL uses a free email domain (%s) which Resend does not allow. "
                "Falling back to sandbox sender. To send to any user, verify your own domain at "
                "https://resend.com/domains and set RESEND_FROM_EMAIL to noreply@yourdomain.com",
                _domain,
            )
        from_addr = "RoomieSplit <onboarding@resend.dev>"
    else:
        from_addr = configured_from

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
# SMTP fallback
# ---------------------------------------------------------------------------

def _send_via_smtp(to_email: str, reset_url: str) -> bool:
    """Send via SMTP (requires port 587/465 to be open on the host)."""
    message = EmailMessage()
    message["Subject"] = "Reset your RoomieSplit password"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message.set_content(_build_reset_email_text(reset_url))
    message.add_alternative(_build_reset_email_html(reset_url), subtype="html")

    # Force IPv4 to avoid Python 3.12+ Happy-Eyeballs masking real errors with
    # IPv6 "Network is unreachable" when IPv4 is being silently firewall-dropped.
    orig_getaddrinfo = socket.getaddrinfo
    def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return [r for r in orig_getaddrinfo(host, port, family, type, proto, flags)
                if r[0] == socket.AF_INET]
    socket.getaddrinfo = _getaddrinfo_ipv4

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
# Public interface
# ---------------------------------------------------------------------------

def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """
    Send a password-reset email.
    Uses Resend (HTTPS) if RESEND_API_KEY is set, otherwise falls back to SMTP.
    """
    if settings.RESEND_API_KEY:
        return _send_via_resend(to_email, reset_url)

    if settings.SMTP_HOST and settings.SMTP_FROM_EMAIL:
        return _send_via_smtp(to_email, reset_url)

    logger.warning(
        "No email provider configured. "
        "Set RESEND_API_KEY (recommended) or SMTP_* variables."
    )
    return False
