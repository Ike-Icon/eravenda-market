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

**One SPF record only.** A domain can only have **one** SPF `TXT` record
(it starts with `v=spf1`). Resend normally puts its own on the `send`
subdomain, so there is nothing to merge. If Resend does ask for an SPF
record on the root domain and one already exists (Google Workspace needs one,
see section 7), don't add a second; edit the existing one so every sender is in
the same line. Two SPF records is invalid and makes mail fail spam checks.

Once verified, set `FROM_EMAIL` to `noreply@eravenda.com` (or any address on
the domain). The address doesn't need a real inbox behind it for sending, as
Resend only needs to confirm you own the domain. Until verification finishes,
`FROM_EMAIL` can stay `onboarding@resend.dev` (Resend's shared sandbox
address). That works immediately but only delivers to the inbox you signed up
to Resend with, so it's fine for testing the flow but not for real buyers or
sellers.

Your Google Workspace mailboxes (`support@` and `noreply@`) and how they fit
with Resend are explained in section 7.

## 3. Put the values in place

Two places, same variables:

- **Local `.env`** (`backend/.env`)
- **Render dashboard**, your web service's **Environment** tab. `render.yaml`
  declares these keys with `sync: false`, which means Render leaves them blank
  until you fill them in here. It won't pick up your local `.env`.

| Variable | Value | What it does |
|---|---|---|
| `RESEND_API_KEY` | the key from step 1 | Lets the app send. Without it nothing is delivered. |
| `FROM_EMAIL` | `EraVenda Market <noreply@eravenda.com>` | The "From" on every email the app sends. |
| `SUPPORT_EMAIL` | `support@eravenda.com` | Where replies go, where contact-form messages arrive, and the address shown in email footers. |
| `ADMIN_NOTIFICATION_EMAIL` | `support@eravenda.com` | Where admin alerts (payments, applications) arrive. |

Set `SUPPORT_EMAIL` explicitly. If you leave it blank it falls back to
`FROM_EMAIL`, and the footers would tell people to write to the no-reply
address. In `.env`, put quotes around a value that contains a name and angle
brackets: `FROM_EMAIL="EraVenda Market <noreply@eravenda.com>"`.

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

## 5. Sender name in your emails

To show "EraVenda Market" in the inbox instead of
`noreply@eravenda.com`, set `FROM_EMAIL` to the name plus the address:

```
FROM_EMAIL=EraVenda Market <noreply@eravenda.com>
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
   passes. Resend and Google Workspace both will once their DKIM records are in
   (section 7). Anything else you use to send "from" an eravenda.com
   address (for example Gmail's "send mail as" for the support address) must
   also pass SPF or DKIM, or it will start failing once you enforce.
2. **Enforce.** Change the record to
   `v=DMARC1; p=quarantine; rua=mailto:support@eravenda.com; pct=100`.
   Keep `pct=100`, since a partial rollout does not qualify for BIMI in Gmail.
   `p=reject` also qualifies, if you want the strictest setting later.
3. Mail people send *to* `support@eravenda.com` is unaffected: DMARC only
   judges mail that claims to be *from* your domain.

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

### Without a certificate: the Gmail profile photo

You can get your logo beside the sender name **in Gmail only** without BIMI or
any certificate. Gmail looks up the From address (`noreply@eravenda.com`) and,
when it belongs to a Google Workspace user or alias, shows that account's
profile photo. It works even though the email is sent by Resend, because Gmail
matches on the address.

1. Use a square PNG or JPG (a static image, not an animated GIF). A ready
   512 x 512 version of the logo is `eravenda-profile-picture.png`. Google
   crops photos to a circle, and this one keeps the mark well inside it.
2. Sign in to Google as `noreply@eravenda.com` (a private/incognito window
   avoids mixing it up with your own account; if you don't know its password,
   reset it in the Admin console under **Directory > Users**).
3. Open `myaccount.google.com`, then **Personal info**, click the profile
   picture, upload the logo and save it.
4. When asked who can see the picture, choose **Anyone**. A photo uploaded by
   an admin on the user's behalf is visible only inside your organisation and
   to people the account has contacted, so set it from the account itself.
   If the camera icon is locked ("managed by your organization"), allow
   profile photo editing in the Admin console under
   **Directory > Directory settings > Profile editing**.
5. Wait. Gmail caches sender photos, and it can take 24 to 72 hours to appear.
   Test with an email sent to a Gmail address.

Limits: this shows only for Gmail recipients. Outlook, Apple Mail and Yahoo
ignore it, which is where BIMI above helps. If `noreply@` is an alias of
another user instead of its own user, the photo shown is the photo of that
user.

## 7. Your Google Workspace mailboxes (support@ and noreply@)

**Resend sends, Google Workspace receives.** The app does not send through
Gmail or Google Workspace. It sends through Resend's API, and your Workspace
mailboxes are where people write back to.

| Address | Role | Set in |
|---|---|---|
| `noreply@eravenda.com` | The "From" of every email the app sends: system emails, the weekly newsletter and everything from the admin Email center. | `FROM_EMAIL` |
| `support@eravenda.com` | The inbox you read. Replies to app emails land here, as do contact-form messages and admin alerts. | `SUPPORT_EMAIL`, `ADMIN_NOTIFICATION_EMAIL` |

Every app email carries a Reply-To of `SUPPORT_EMAIL`, so when someone taps
Reply on a newsletter or an order email, the reply goes to `support@` and not
to the no-reply address. (Emails where the app sets a specific reply address,
such as the contact form and service bookings, keep it.)

### Why not send through Google Workspace?

- **Render blocks it.** On Render's free web service plan, outbound SMTP
  (ports 25, 465, 587) is blocked, so Gmail SMTP can't deliver from the app.
  That is why the app uses Resend's HTTPS API.
- **It isn't built for bulk mail.** Workspace has daily sending limits and is
  meant for person-to-person mail. A newsletter sent from it risks being
  throttled or flagged. Use Resend for the newsletter and Email center.

### DNS: Resend and Google Workspace side by side

They don't conflict, as long as the root domain is set up like this. Check
Cloudflare (**DNS > Records**; set every mail record to **DNS only**, grey cloud):

| Record | What it should be |
|---|---|
| `MX` on `eravenda.com` | Only Google's: priority `1`, `smtp.google.com`. Delete any other MX records on the root, including leftover `*.mx.cloudflare.net` ones from Cloudflare Email Routing. Mixed MX records make incoming mail land in the wrong place. |
| `TXT` (SPF) on `eravenda.com` | One record only: `v=spf1 include:_spf.google.com ~all`. Remove `include:_spf.mx.cloudflare.net` if it's still there. Resend's own SPF lives on the `send` subdomain, so nothing to merge unless Resend asked for a root record. |
| Resend DKIM (`resend._domainkey`) and the `send` MX/TXT | Leave exactly as Resend gave them (section 2). |
| Google DKIM (`google._domainkey`) | Add it. In the Google Admin console go to **Apps > Google Workspace > Gmail > Authenticate email**, pick `eravenda.com`, generate the record, add the `TXT` record in Cloudflare, then click **Start authentication**. |
| `_dmarc` | One record (section 6.2). Now that `support@` is a real mailbox, its `rua` reports will arrive. |

Google's free MX checker (search for "Google Admin Toolbox CheckMX") flags a
wrong or stray MX record. DNS changes can take a few hours to be picked up.

### The noreply@ user (optional saving)

Because Resend sends the email, `noreply@eravenda.com` doesn't need to be a
mailbox. If it was created as its own Workspace user, that user uses up a paid
seat. To avoid paying for it, add `noreply@eravenda.com` as an alternate email
address (an alias) on the support user, or on a group, and delete the separate
user. Nothing in the app changes, since sending doesn't depend on it. One
trade-off: an alias shows its user's profile photo, so if you want the logo
as the sender picture (see the Gmail profile photo steps in section 6), put
the logo on that user's photo.

### Sending limits (Resend)

As of 2026 Resend's free plan allows 3,000 emails a month and 100 a day. An
Email center send or newsletter to more than 100 people in a day won't
complete on the free plan. The Pro plan (about $20 a month for 50,000 emails)
has no daily limit. Check resend.com/pricing before a large send.

### Test the whole setup

1. **Sending:** in the admin **Email center**, write a short message and
   choose **Send test to me**. It arrives from `EraVenda Market`. In Gmail,
   open the three-dot menu > **Show original** and check SPF, DKIM and DMARC
   all say **PASS**.
2. **Replying:** tap Reply on that test. The "To" should be
   `support@eravenda.com`.
3. **Receiving:** from a personal email address, write to
   `support@eravenda.com`. It should arrive in the Workspace inbox within a
   minute. If it doesn't, the MX records are the first thing to check.
4. **Contact form:** submit the site's contact form. The message arrives at
   `support@eravenda.com`, and replying goes to the visitor.

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
