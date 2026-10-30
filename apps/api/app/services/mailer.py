"""Transactional email. Uses SMTP when configured; in development/test, messages go to an
in-memory outbox (exposed only via a development-only endpoint) and are never logged."""

from __future__ import annotations

from collections import deque
from email.message import EmailMessage
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("mailer")

DEV_OUTBOX: deque[dict[str, Any]] = deque(maxlen=50)


class MailNotConfigured(RuntimeError):
    pass


async def send_email(to: str, subject: str, text: str) -> None:
    settings = get_settings()
    if not settings.smtp_configured:
        if settings.is_production:
            raise MailNotConfigured("SMTP is not configured")
        DEV_OUTBOX.append({"to": to, "subject": subject, "text": text})
        log.info("email_captured_in_dev_outbox", subject=subject)
        return
    import aiosmtplib

    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME or None,
        password=settings.SMTP_PASSWORD or None,
        start_tls=settings.SMTP_STARTTLS if settings.SMTP_PORT != 465 else False,
        use_tls=settings.SMTP_PORT == 465,
        timeout=20,
    )
    log.info("email_sent", subject=subject)


def verification_email(name: str, link: str, app_name: str) -> tuple[str, str]:
    return (
        f"Verify your email for {app_name}",
        f"Hi {name or 'there'},\n\nConfirm your email address to start researching:\n\n{link}\n\n"
        "This link expires in 24 hours and can be used once. If you did not create an account, ignore this email.\n",
    )


def reset_email(name: str, link: str, app_name: str) -> tuple[str, str]:
    return (
        f"Reset your {app_name} password",
        f"Hi {name or 'there'},\n\nUse this link to choose a new password:\n\n{link}\n\n"
        "The link expires in 30 minutes and can be used once. If you did not request a reset, you can ignore this email; "
        "your password has not changed.\n",
    )


def existing_account_email(link: str, app_name: str) -> tuple[str, str]:
    return (
        f"Someone tried to register with your email on {app_name}",
        "Someone (hopefully you) tried to create a new account with this email address, but an account already exists.\n\n"
        f"If it was you, sign in or reset your password here:\n\n{link}\n\nIf it was not you, no action is needed.\n",
    )
