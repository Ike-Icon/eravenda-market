"""
Minimal email sending.

No third-party email service is wired in — that's a deliberate choice,
since which provider you want (SendGrid, Postmark, AWS SES, etc.) is a
business decision, not something to bake in silently.

Instead: if SMTP_HOST is set in .env, this sends real mail over SMTP
(works with Gmail, Mailtrap, SendGrid's SMTP relay, or your own mail
server). If it's not set, it just logs the email to the console, so
password reset and the contact form both work end-to-end in local dev
without any setup, and you never lose a reset link during testing.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText

logger = logging.getLogger("eravenda.email")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL", "no-reply@eravenda.com")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", FROM_EMAIL)


def send_email(to: str, subject: str, body: str, reply_to: str | None = None) -> None:
    if not SMTP_HOST:
        logger.info("=== EMAIL (console fallback, SMTP_HOST not set) ===")
        logger.info("To: %s", to)
        logger.info("Subject: %s", subject)
        logger.info("Body:\n%s", body)
        logger.info("=== END EMAIL ===")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(FROM_EMAIL, [to], msg.as_string())
