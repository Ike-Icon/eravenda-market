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
from html import escape
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("eravenda.email")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL", "no-reply@eravenda.com")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", FROM_EMAIL)
ADMIN_NOTIFICATION_EMAIL = os.getenv("ADMIN_NOTIFICATION_EMAIL", "asieduisaac5775@gmail.com")
DEFAULT_EMAIL_FLYER_URL = "https://res.cloudinary.com/ni2pcrua/image/upload/v1789391753/EraVenda_Banner.jpg"
EMAIL_FLYER_URL = os.getenv("EMAIL_FLYER_URL", DEFAULT_EMAIL_FLYER_URL).strip() or DEFAULT_EMAIL_FLYER_URL


def _html_email(body: str) -> str:
        paragraphs = "<br>".join(escape(body).splitlines())
        banner = f'<img src="{escape(EMAIL_FLYER_URL)}" alt="EraVenda Market" style="display:block;width:100%;max-width:600px;height:auto;margin:0 auto 24px;border:0;">'
        return f"""<!doctype html>
<html lang="en">
    <body style="margin:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:#24352e;">
        <div style="padding:20px 12px;">
            <div style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #d8e5de;border-radius:10px;overflow:hidden;">
                <div style="padding:20px;line-height:1.6;font-size:15px;text-align:center;">
                    {banner}
                    <div style="text-align:left;">{paragraphs}</div>
                </div>
            </div>
        </div>
    </body>
</html>"""


def send_email(to: str, subject: str, body: str, reply_to: str | None = None) -> None:
    if not SMTP_HOST:
        logger.info("=== EMAIL (console fallback, SMTP_HOST not set) ===")
        logger.info("To: %s", to)
        logger.info("Subject: %s", subject)
        logger.info("Body:\n%s", body)
        logger.info("=== END EMAIL ===")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(_html_email(body), "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(FROM_EMAIL, [to], msg.as_string())
