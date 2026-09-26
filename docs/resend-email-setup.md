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

## 2. Decide what you can send FROM, right now

Resend needs to know you actually control the domain in your `from`
address, so there are two options:

**Testing (no domain needed):** use `onboarding@resend.dev` as
`FROM_EMAIL`. This works immediately, but Resend will only deliver to the
email address you signed up to Resend with — fine for confirming the
whole flow works end to end, not for real buyers or sellers. This is
already the default in `backend/.env`.

**Production (needs a domain you own):** once you buy a domain for
Eravenda, go to **Domains > Add Domain** in the Resend dashboard, enter
it, and add the DKIM/SPF (and optionally DMARC) records it gives you at
your domain registrar's DNS settings. Verification usually takes a few
minutes to a few hours depending on the registrar. Once it shows
**Verified**, set `FROM_EMAIL` to any address on that domain, e.g.
`no-reply@eravenda.com` — you don't need a real inbox behind it, Resend
just needs to confirm you own the domain.

Gmail addresses (`@gmail.com`) can never be used as `FROM_EMAIL` here —
you don't control that domain's DNS, so Resend won't let you send as it.
`SUPPORT_EMAIL` and `ADMIN_NOTIFICATION_EMAIL` are unaffected by any of
this; those are just destination addresses (they can stay Gmail), only
the `from` address is restricted.

## 3. Put the values in place

Two places, same two variables:

- **Local `.env`** (`backend/.env`): set `RESEND_API_KEY` to the key from
  step 1, and `FROM_EMAIL` per step 2.
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
