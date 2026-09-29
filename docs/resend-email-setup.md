# Email Setup (Resend)

The code is ready. Password reset, order confirmations, seller/handyman
welcome emails, and admin payment notifications all go through
`send_email()` in `backend/app/email_utils.py`, which now calls
[Resend](https://resend.com)'s HTTPS API instead of raw SMTP.

That switch wasn't optional: Render's free web-service plan blocks
outbound traffic on SMTP ports 25, 465, and 587, so Gmail SMTP could
never actually deliver from `eravenda-api` while it stays on that plan.
Resend sends over plain HTTPS, so the port block doesn't apply and this
keeps working without upgrading Render.

Until `RESEND_API_KEY` is set, `send_email()` just logs the email to the
console instead of sending it, so local dev and the rest of the app work
with zero setup.

## 1. Create a Resend account (free, takes about 5 minutes)

1. Go to [resend.com](https://resend.com) and sign up. The free tier
   covers 3,000 emails/month and 100/day, more than enough at this stage.
2. Go to **API Keys** in the dashboard, click **Create API Key**, give it
   a name like `eravenda-production`, and leave the permission as
   **Full access** (or **Sending access** if you want to be stricter).
3. Copy the key — it starts with `re_` and is only shown once.

## 2. Verify eravenda.com in Resend

You already own the domain, so do this now:

1. In the Resend dashboard, go to **Domains > Add Domain** and enter
   `eravenda.com`.
2. Resend gives you a handful of DNS records — usually one or two DKIM
   `TXT`/`CNAME` records, an `MX` + `TXT` pair for the `send` subdomain it
   uses for the technical return-path, and it may ask for an `SPF`
   `TXT` record on the root domain. Add each one in Cloudflare
   (**DNS > Records**), exactly as Resend shows them, with the proxy
   status set to **DNS only** (grey cloud) — these are mail records, not
   web traffic, so they must never be proxied.
3. Verification is usually done within a few minutes, sometimes up to a
   few hours. The Domains page shows **Verified** once it's picked up.

**Important — don't break support@eravenda.com's forwarding.** You
already have `support@eravenda.com` set up as a rerouting address, which
almost certainly means there's already an `MX` record (and possibly an
`SPF` `TXT` record) on `eravenda.com` for that forwarding to work. A
domain can only have **one** SPF record — if Resend's setup asks you to
add a new `SPF` `TXT` record and one already exists (it'll look like
`v=spf1 ...`), don't add a second one; instead edit the existing record
so it includes Resend's mechanism in the same line, e.g.
`v=spf1 include:_spf.resend.com include:<your-current-provider> ~all`.
Two separate SPF records is invalid and can cause your existing
`support@eravenda.com` forwarding to start failing spam checks. If
you're not sure what's already there, check Cloudflare's DNS records
for `eravenda.com` before adding anything, or paste what Resend gives
you here and I'll tell you exactly how to merge it.

Once verified, set `FROM_EMAIL` to `no-reply@eravenda.com` (or any
address on the domain) — you don't need a real inbox behind it, Resend
just needs to confirm you own the domain. `SUPPORT_EMAIL` and
`ADMIN_NOTIFICATION_EMAIL` are unaffected by any of this; those are just
destination addresses, only the `from` address needs a verified domain.
Until verification finishes, `FROM_EMAIL` can stay
`onboarding@resend.dev` (Resend's shared sandbox address) — that works
immediately but only delivers to the inbox you signed up to Resend with,
so it's fine for testing the flow but not for real buyers or sellers.

## 3. Put the values in place

Two places, same two variables:

- **Local `.env`** (`backend/.env`): set `RESEND_API_KEY` to the key from
  step 1, and `FROM_EMAIL` per step 2. `SUPPORT_EMAIL` and
  `ADMIN_NOTIFICATION_EMAIL` already default to `support@eravenda.com`.
- **Render dashboard**, your web service's **Environment** tab: same two
  keys, same values. `render.yaml` already declares both with
  `sync: false`, which means Render leaves them blank until you fill
  them in here — it won't pick up your local `.env` automatically.

`SUPPORT_EMAIL` and `ADMIN_NOTIFICATION_EMAIL` don't change — leave them
as whichever inbox should receive replies and payment notifications.

## 4. Testing after it's set

1. Restart the local server (or redeploy on Render) so the new env vars
   load.
2. Check the startup logs. If you still see `RESEND_API_KEY is not set`,
   the variable didn't take, double-check spelling and that you restarted
   the right service.
3. Go to `/forgot-password`, submit the email address you signed up to
   Resend with (if you're still on the `onboarding@resend.dev` sandbox
   address), and confirm the email actually arrives.
4. Check the Resend dashboard's **Logs** tab, every send attempt shows up
   there with its delivery status, useful if an email doesn't arrive but
   the app didn't log an error either.
5. Once a domain is verified, repeat the test with a real buyer's email
   address to confirm production sending works too.

## What happens on the backend

`send_email()` posts to `https://api.resend.com/emails` with your API key
as a bearer token, and raises if Resend responds with an error, the same
way a failed SMTP send used to. Every call site (`routers/auth.py`,
`routers/payments.py`, `routers/contact.py`, `routers/admin.py`,
`routers/delivery.py`, `routers/services.py`) already wraps its
`send_email()` call in its own `try/except` and just logs a failure
rather than breaking the request it's on, so nothing else needed to
change when the sending mechanism switched from SMTP to Resend.

## Who gets emailed, for what

| Event | Buyer / Client | Seller / Pro | Admin |
|---|---|---|---|
| Password reset requested | reset link | — | — |
| Contact form submitted | — | — | message, reply-to the sender |
| Seller applies for a store | welcome + status | — | — |
| Store approved / rejected | — | approval or reason | — |
| Product approved / rejected | — | approval or reason | — |
| Product order paid (online or COD) | order confirmation | "you've got a sale" | payment summary |
| Handyman applies | welcome + status | — | — |
| Handyman profile approved / rejected | — | approval or reason | — |
| Client requests a booking | — | new job request | request summary |
| Handyman booking paid | payment confirmation | — | payment summary |
| Delivery partner applies | welcome + status | — | — |
| Delivery application approved / rejected | — | approval or reason | — |
| Order marked delivered | delivery confirmation | delivery confirmation | delivery confirmation |

Cash-on-delivery payments (`record_cod_payment` in `routers/admin.py`)
send the same buyer/seller/admin emails as an online payment — both
paths call the shared `_notify_product_payment()` in
`routers/payments.py`, so there's one place that owns what that email
says.
