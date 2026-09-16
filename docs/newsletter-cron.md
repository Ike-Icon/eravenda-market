# Weekly Newsletter Scheduling

The footer's "Get new-arrival alerts" signup stores emails in the
`newsletter_subscribers` table. Nothing sends automatically on a schedule,
someone or something has to call the send endpoint once a week. This
document covers the two ways to do that.

## What actually sends the email

Both options below call the same endpoint:

```
POST /api/newsletter/cron/send-weekly
Header: X-Newsletter-Secret: <value of NEWSLETTER_CRON_SECRET>
```

It checks the last 7 days for approved products and approved stores, skips
sending if nothing new happened, and emails every active subscriber. The
response tells you what happened:

```json
{ "sent": 42, "failed": 0, "subscriber_count": 42 }
```

or, if there was nothing new that week:

```json
{ "sent": 0, "failed": 0, "subscriber_count": 0, "skipped_reason": "no_new_content" }
```

`NEWSLETTER_CRON_SECRET` is set automatically in `render.yaml`
(`generateValue: true`). Find the actual value in the Render dashboard under
your web service's **Environment** tab after your first deploy, you'll need
to copy it into whichever option below you choose.

## Option 1: GitHub Actions (free)

This runs on GitHub's infrastructure, not Render's, so it costs nothing and
doesn't need any extra Render service.

1. In your GitHub repo, go to **Settings > Secrets and variables > Actions**
   and add a new repository secret named `NEWSLETTER_CRON_SECRET` with the
   same value Render generated.
2. Add this file to your repo at `.github/workflows/weekly-newsletter.yml`:

```yaml
name: Weekly newsletter

on:
  schedule:
    # 08:00 UTC every Monday. Adjust the cron expression for a different
    # day or time; GitHub's schedule runs in UTC, not your local time.
    - cron: "0 8 * * 1"
  workflow_dispatch: {}  # lets you trigger it manually from the Actions tab

jobs:
  send:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger weekly digest
        run: |
          curl -sf -X POST "https://eravenda-api.onrender.com/api/newsletter/cron/send-weekly" \
            -H "X-Newsletter-Secret: ${{ secrets.NEWSLETTER_CRON_SECRET }}"
```

3. Commit it. You can test it immediately from the repo's **Actions** tab
   using **Run workflow** (that's what `workflow_dispatch` enables), instead
   of waiting until next Monday.

One thing worth knowing: your Render web service is on the free plan, which
spins down after inactivity. If nobody has hit the site in a while, this
request might take 30 to 60 seconds to wake it up before it responds. That's
fine for a weekly cron job, curl will just wait, but don't be alarmed if the
Actions log shows a long request.

## Option 2: Render Cron Job (paid, small)

Render's own Cron Jobs are billed per minute, a weekly job that runs for a
few seconds costs a small fraction of a dollar a month, but it isn't free
like GitHub Actions.

1. In the Render dashboard, click **New > Cron Job**.
2. Point it at the same repo, set the schedule to `0 8 * * 1` (or your
   preferred time), and set the command to:

```
curl -sf -X POST "https://eravenda-api.onrender.com/api/newsletter/cron/send-weekly" -H "X-Newsletter-Secret: $NEWSLETTER_CRON_SECRET"
```

3. Add `NEWSLETTER_CRON_SECRET` as an environment variable on the Cron Job
   service itself (copy the same value from your web service).

## Testing without waiting for a schedule

As an admin, you can trigger the same send manually any time by logging in
and calling:

```
POST /api/newsletter/admin/send-weekly
Authorization: Bearer <your admin JWT>
```

Use this to confirm the email actually arrives and reads correctly before
trusting a schedule with it.
