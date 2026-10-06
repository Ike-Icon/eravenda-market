# Weekly Newsletter

The footer's "Get new-arrival alerts" form stores emails in the
`newsletter_subscribers` table. A GitHub Actions job calls the send endpoint
every Monday at 08:00 UTC (08:00 in Ghana). You can also send from the admin
dashboard: **Overview > Weekly newsletter**.

## What gets sent

- Approved products and stores created in the last 7 days. If there are none,
  nothing is sent and the response says `skipped_reason: no_new_content`.
- An HTML email with product thumbnails, prices, deals and new sellers, plus a
  plain-text version, a footer unsubscribe link and a one-click unsubscribe
  header.
- Anyone who already got a digest in the last 6 days is skipped. Re-running a
  failed job is safe, and people who were missed get picked up.
- Mail goes out 100 per Resend call. Rate limits (HTTP 429) are retried.

## One-time setup checklist

1. **Render service you keep** (Environment tab): set `RESEND_API_KEY`,
   `FROM_EMAIL` (an address on a domain you verified in Resend, for example
   `noreply@eravenda.com`), `SUPPORT_EMAIL` (`support@eravenda.com`, where
   replies go) and `SITE_URL`. Note the generated
   `NEWSLETTER_CRON_SECRET`.
   - `FROM_EMAIL=onboarding@resend.dev` only delivers to the email you
     registered with Resend. The dashboard warns you if you are on it.
2. **GitHub** (Settings > Secrets and variables > Actions):
   - Secret `NEWSLETTER_CRON_SECRET` = the value from that Render service.
   - Variable `NEWSLETTER_API_URL` = that service's URL, no trailing slash,
     for example `https://eravenda-api.onrender.com`. With two Render
     services, each has its own secret, so the pair must match.
3. Open the admin dashboard and press **Send test to me**. Check inbox and spam.
4. In GitHub, open **Actions > Weekly newsletter > Run workflow**. It should
   finish green.

## Reading the result

The workflow prints the HTTP status and the server's JSON, and fails (red) on
anything that is not a successful send:

| Status | Meaning | Fix |
|---|---|---|
| 200 | Sent, or nothing new this week | none |
| 401 | Secret in GitHub differs from Render | copy the secret again |
| 404 | Wrong `NEWSLETTER_API_URL` | fix the variable |
| 503 | `RESEND_API_KEY` missing on the server | add it, redeploy |
| 502 | Resend refused the key or sender domain, or every send failed | verify the domain, check `FROM_EMAIL` |

A successful response looks like:

```json
{ "sent": 42, "failed": 0, "subscriber_count": 42, "skipped_recently": 0, "test": false, "error": null }
```

The workflow retries up to 3 times, 60 seconds apart, because a free Render
instance can take a minute to wake up.

## Manual and API sends

Admin dashboard buttons call these (admin JWT required):

```
POST /api/newsletter/admin/send-test            one copy to your own address, nobody marked as sent
POST /api/newsletter/admin/send-weekly          send now, skipping people emailed in the last 6 days
POST /api/newsletter/admin/send-weekly?force=true   send to everyone, ignoring the 6-day rule
```

## Unsubscribing

The link in each email opens a confirmation page. The click on "Yes,
unsubscribe me" does the unsubscribing, so mail scanners that open links
cannot remove anyone by accident. Gmail and Apple Mail's built-in
Unsubscribe button works too.

## Render Cron Job instead of GitHub Actions

Create a Render Cron Job with schedule `0 8 * * 1` and this command, with
`NEWSLETTER_CRON_SECRET` set on the cron service:

```
curl -sS --fail-with-body -X POST "https://eravenda-api.onrender.com/api/newsletter/cron/send-weekly" -H "X-Newsletter-Secret: $NEWSLETTER_CRON_SECRET"
```
