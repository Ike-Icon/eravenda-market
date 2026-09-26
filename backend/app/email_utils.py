"""
Minimal email sending, over Resend's HTTPS API.

Switched from raw SMTP because Render's free web-service plan blocks
outbound traffic on SMTP ports 25/465/587 (a deliberate anti-spam
restriction), so Gmail SMTP could never actually deliver mail from this
app while it stays on that plan. Resend sends over plain HTTPS instead,
so the port block doesn't apply and this keeps working on the free plan.

If RESEND_API_KEY isn't set, this just logs the email to the console, so
password reset and the contact form both work end-to-end in local dev
without any setup, and you never lose a reset link during testing.
"""

import os
import logging
from html import escape

import httpx  # type: ignore[reportMissingImports]

logger = logging.getLogger("eravenda.email")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_API_URL = "https://api.resend.com/emails"

# Must be an address "you@yourdomain.com" on a domain verified in the Resend
# dashboard (Domains -> Add Domain -> add the DKIM/SPF records at your DNS
# provider). Until a domain is verified, Resend only accepts FROM_EMAIL as
# onboarding@resend.dev, and even then it will only deliver TO the email
# address you signed up to Resend with — fine for testing, not for real
# customers. See docs/resend-email-setup.md for the full walkthrough.
FROM_EMAIL = os.getenv("FROM_EMAIL", "no-reply@eravenda.com")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", FROM_EMAIL)
ADMIN_NOTIFICATION_EMAIL = os.getenv("ADMIN_NOTIFICATION_EMAIL", "asieduisaac5775@gmail.com")
DEFAULT_EMAIL_FLYER_URL = "https://res.cloudinary.com/ni2pcrua/image/upload/v1789391753/EraVenda_Banner.jpg"
EMAIL_FLYER_URL = os.getenv("EMAIL_FLYER_URL", DEFAULT_EMAIL_FLYER_URL).strip() or DEFAULT_EMAIL_FLYER_URL

# Single source of truth for the site's public URL, used to build links in
# every outgoing email (password reset, welcome emails, Paystack callbacks,
# the sitemap). Previously each file that needed this declared its own
# `os.getenv("SITE_URL", ...)` with a different, mostly-wrong fallback
# (some pointed at "https://www.eravenda.com", a domain that was never
# actually live; others fell back to "http://localhost:8000"), so a missing
# SITE_URL env var could silently send buyers a password-reset link that
# only worked on someone's laptop. Now deployed on Render, so the one
# correct fallback is the live API URL.
SITE_URL = os.getenv("SITE_URL", "https://eravenda-api.onrender.com").rstrip("/")


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
    if not RESEND_API_KEY:
        logger.info("=== EMAIL (console fallback, RESEND_API_KEY not set) ===")
        logger.info("To: %s", to)
        logger.info("Subject: %s", subject)
        logger.info("Body:\n%s", body)
        logger.info("=== END EMAIL ===")
        return

    payload = {
        "from": FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "text": body,
        "html": _html_email(body),
    }
    if reply_to:
        payload["reply_to"] = reply_to

    # Same 10s ceiling the old SMTP path used: fail fast on a network hiccup
    # rather than hanging the request (and whatever button triggered it).
    with httpx.Client(timeout=10) as client:
        res = client.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json=payload,
        )
    if res.status_code >= 400:
        # Surfaced to the caller's try/except, same as an smtplib exception
        # used to be — every send_email() call site already logs and swallows
        # this rather than letting a failed email break the request it's on.
        raise RuntimeError(f"Resend API error {res.status_code}: {res.text[:300]}")


def send_role_welcome_email(to: str, full_name: str, role_label: str, next_steps: list[str], dashboard_path: str) -> None:
    """Common 'thanks for signing up as X' email for the three role
    applications (seller, delivery partner, handyman). Errors are caught by
    the caller — a failed welcome email should never block the signup
    itself, it should just get logged."""
    first_name = (full_name or "").strip().split(" ")[0] or "there"
    steps = "\n".join(f"{i}. {step}" for i, step in enumerate(next_steps, start=1))
    body = (
        f"Hi {first_name},\n\n"
        f"Thanks for signing up to become a {role_label} on EraVenda Market!\n\n"
        f"What happens next:\n{steps}\n\n"
        f"You can check your application status any time here:\n{SITE_URL}{dashboard_path}\n\n"
        f"Questions? Just reply to this email or reach us at {SUPPORT_EMAIL}.\n\n"
        "— The EraVenda Market team"
    )
    send_email(to, f"Welcome to EraVenda Market — your {role_label} application", body)
