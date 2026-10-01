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
ADMIN_NOTIFICATION_EMAIL = os.getenv("ADMIN_NOTIFICATION_EMAIL", "support@eravenda.com")
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
SITE_URL = os.getenv("SITE_URL", "https://eravenda.com").rstrip("/")


def _item_thumbnail_html(item: dict) -> str:
    """One row: a 48x48 product thumbnail plus name (and quantity/price when
    given). Falls back to a blank placeholder square rather than skipping the
    row when a product has no photo, so the list still lines up."""
    image_url = item.get("image_url")
    thumb = (
        f'<img src="{escape(image_url)}" alt="" width="48" height="48" '
        'style="display:block;width:48px;height:48px;object-fit:cover;'
        'border-radius:6px;border:1px solid #d8e5de;">'
        if image_url
        else '<div style="width:48px;height:48px;border-radius:6px;background:#eef3f0;'
        'border:1px solid #d8e5de;"></div>'
    )
    detail_bits = []
    if item.get("quantity") is not None:
        detail_bits.append(f"Qty {item['quantity']}")
    if item.get("line_total") is not None:
        detail_bits.append(f"GHS {float(item['line_total']):.2f}")
    detail = f'<div style="color:#5b6b63;font-size:13px;margin-top:2px;">{escape(" · ".join(detail_bits))}</div>' if detail_bits else ""
    return f"""<tr>
        <td style="padding:8px 0;width:56px;vertical-align:top;">{thumb}</td>
        <td style="padding:8px 0 8px 12px;vertical-align:top;font-size:14px;">
            <div style="font-weight:600;">{escape(item.get("name") or "")}</div>
            {detail}
        </td>
    </tr>"""


def _html_email(body: str, items: list[dict] | None = None) -> str:
        paragraphs = "<br>".join(escape(body).splitlines())
        banner = f'<img src="{escape(EMAIL_FLYER_URL)}" alt="EraVenda Market" style="display:block;width:100%;max-width:600px;height:auto;margin:0 auto 24px;border:0;">'
        items_html = ""
        if items:
            rows = "".join(_item_thumbnail_html(item) for item in items)
            items_html = f'<table role="presentation" style="width:100%;border-collapse:collapse;margin:16px 0;">{rows}</table>'
        return f"""<!doctype html>
<html lang="en">
    <body style="margin:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:#24352e;">
        <div style="padding:20px 12px;">
            <div style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #d8e5de;border-radius:10px;overflow:hidden;">
                <div style="padding:20px;line-height:1.6;font-size:15px;text-align:center;">
                    {banner}
                    <div style="text-align:left;">{paragraphs}{items_html}</div>
                </div>
            </div>
        </div>
    </body>
</html>"""


def send_email(
    to: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
    items: list[dict] | None = None,
) -> None:
    """items, when given, renders as a thumbnail + name (+ qty/price if present)
    block in the HTML version only — the plain-text `body` already has its own
    text-only item list (e.g. "- Widget x2 — GHS 40.00") built by the caller,
    since a plain-text email can't show an image anyway. Each dict: {"name",
    "image_url" (optional), "quantity" (optional), "line_total" (optional)}."""
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
        "html": _html_email(body, items),
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
