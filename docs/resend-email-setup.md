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

## 5. Logo and sender name in your emails

Every email EraVenda sends (system emails, the weekly newsletter and
messages from the admin Email center) now starts with a small header: your
logo mark and "EraVenda Market", above the banner image.

- The logo is `frontend/static/img/email-logo.png`, served from
  `SITE_URL/static/img/email-logo.png`. It is a PNG on purpose: Gmail and most
  other email apps do not show SVG images.
- To use a different logo, upload a square PNG (at least 128 x 128, transparent
  or solid background) somewhere public over https and set `EMAIL_LOGO_URL`
  to its address. Set `EMAIL_LOGO_URL=none` to remove the header entirely.
- The header is built in one place, `email_logo_header_html()` in
  `backend/app/email_utils.py`, and used by all three layouts.
- When an email app blocks images (many do until the reader taps "show
  images"), the words "EraVenda Market" still show and the logo area stays
  quietly empty.

**Sender name.** To show "EraVenda Market" in the inbox instead of
`no-reply@eravenda.com`, set `FROM_EMAIL` to the name plus the address:

```
FROM_EMAIL=EraVenda Market <no-reply@eravenda.com>
```

Also set `SUPPORT_EMAIL` to a plain address (for example
`support@eravenda.com`). In the code `SUPPORT_EMAIL` defaults to `FROM_EMAIL`,
so without it the reply-to and the "write to us" lines in emails would show the
name and angle brackets too.

## 6. Logo next to the sender in the inbox (BIMI)

The round picture beside the sender in the inbox list is chosen by the
receiving app, not by the email. For a custom domain the standard way to get
your logo there is **BIMI**. It shows your logo only when your domain proves it
sent the email and the logo is certified, so it takes four things: DMARC,
a BIMI-format SVG, a certificate (for Gmail and Apple Mail), and one DNS record.

| App | What shows |
|---|---|
| Gmail (web, Android, iOS) | Logo with a VMC or a CMC certificate. The blue verified checkmark needs a VMC. |
| Apple Mail / iCloud | Logo with a VMC. A CMC is not accepted yet. |
| Yahoo, AOL, Fastmail | Logo; some accept only the SVG plus DMARC enforcement. |
| Outlook | Not supported. |

(Based on BIMI Group and provider documentation as of mid-2026. Gmail's own
BIMI help page is the final word if anything here has changed.)

### 6.1 Make sure sending is authenticated

In Resend, **Domains** must show `eravenda.com` as **Verified** (step 2). That
sets up the SPF and DKIM records that DMARC relies on.

### 6.2 Add a DMARC record, then tighten it slowly

BIMI needs DMARC at `p=quarantine` or `p=reject`, applied to 100% of mail.
`p=none` is not enough, and Gmail will not show the logo until DMARC is
enforced. Do it in stages, because enforcing too early can push
legitimate mail to spam.

In Cloudflare (**DNS > Records**) add a `TXT` record:

| Field | Value |
|---|---|
| Name | `_dmarc` |
| Content | `v=DMARC1; p=none; rua=mailto:support@eravenda.com; pct=100` |

1. **Watch (2 to 4 weeks).** `p=none` changes nothing for delivery; it only
   makes mailbox providers send you daily summary reports (XML attachments) to
   the `rua` address. A free DMARC report reader makes them easy to read.
   Look for every service that sends mail as `@eravenda.com` and check each one
   passes. Resend will. Anything else you use to send "from" an eravenda.com
   address (for example Gmail's "send mail as" for the support address) must
   also pass SPF or DKIM, or it will start failing once you enforce.
2. **Enforce.** Change the record to
   `v=DMARC1; p=quarantine; rua=mailto:support@eravenda.com; pct=100`.
   Keep `pct=100`, since a partial rollout does not qualify for BIMI in Gmail.
   `p=reject` also qualifies, if you want the strictest setting later.
3. Replies and forwarding to `support@eravenda.com` are unaffected: DMARC only
   judges mail that claims to be from your domain.

### 6.3 The SVG logo

BIMI does not accept a normal logo file. It needs SVG Tiny Portable/Secure.
A ready one is included: `frontend/static/img/bimi-logo.svg`, served at
`https://eravenda.com/static/img/bimi-logo.svg`.

It follows the rules: version 1.2 with `baseProfile="tiny-ps"`, a title, a
square shape, a solid background filling the whole square (Gmail crops it to a
circle, so rounded corners would leave white corners), no scripts, gradients,
raster images, animation or external links, and a tiny file size.

If you change it, keep those rules, keep the mark near the centre, and check
the file with a BIMI validator (the BIMI Group has a free inspector) before
you pay for a certificate. The validator also checks your DMARC and DNS record
once they are in place.

### 6.4 The certificate (Gmail and Apple Mail need one)

Gmail requires a VMC or a CMC. Without one the logo will not show in Gmail.

| | VMC | CMC |
|---|---|---|
| Needs | Your logo registered as a trademark at an office the issuer accepts | Proof you have used the logo for about 12 months |
| Gmail | Logo and blue checkmark | Logo, no checkmark |
| Apple Mail | Yes | Not yet |

Both are paid, issued by approved authorities (DigiCert and Entrust for VMC;
SSL.com and others for CMC), and last about a year, so put the renewal date in
your calendar. Ask the issuer whether your trademark registry is accepted
before buying a VMC; a CMC is the realistic route if it is not or if you have
no trademark. You will receive a `.pem` file.

### 6.5 Publish the BIMI DNS record

Save the certificate file where it can be fetched over https, for example
`frontend/static/bimi/eravenda.pem` (served at
`https://eravenda.com/static/bimi/eravenda.pem`), then add a `TXT` record in
Cloudflare:

| Field | Value |
|---|---|
| Name | `default._bimi` |
| Content | `v=BIMI1; l=https://eravenda.com/static/img/bimi-logo.svg; a=https://eravenda.com/static/bimi/eravenda.pem;` |

Before you have a certificate you can publish the same record without the
`a=` part. Providers that do not require a certificate may show the logo,
but Gmail and Apple Mail will not.

### 6.6 Check it worked

1. Run your domain through a BIMI inspector. It should report valid DMARC, a
   valid SVG and a valid certificate.
2. Send a real email to a Gmail address (for example the weekly newsletter test
   from the admin Email center). The logo shows beside the sender name in the
   inbox list.
3. Gmail caches BIMI results, so allow time after any change. If you change the
   logo later, publish it at a new file name and get a new certificate for it.

If no logo appears, work through this list: DMARC is still `p=none` or below
100%; the SVG failed validation; no certificate (Gmail and Apple Mail); the
certificate is expired or was issued for a different logo; the `From` address is
not on `eravenda.com`; the DNS record name or the `a=`/`l=` links are wrong.

### Without BIMI

You can create a Google account that uses `no-reply@eravenda.com` as its email
address and give it your logo as the profile photo. Some Gmail users will then
see it. This is unofficial and inconsistent, so treat it as a stopgap, not a
replacement for BIMI.

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
