# Admin Email center

Admin dashboard > **Email center**. Write one message and send it to one group
at a time. Groups are never mixed in a single send.

| Group | Who is in it |
| --- | --- |
| Users | Active buyer accounts. Anyone who owns a store or is a professional is in their own group instead, so nobody gets the same message twice. |
| Sellers | Owners of approved stores. A checkbox also adds sellers whose store is still pending. |
| Professionals | Approved handyman / service professionals. A checkbox also adds pending ones. |
| Newsletter subscribers | People who signed up in the site footer. Every email carries an unsubscribe link. |

## Writing

* Plain text. A blank line starts a new paragraph.
* `**bold**` and `[link text](https://example.com)` are supported (the B and Link buttons insert them).
* Per-person placeholders: `{{first_name}}`, `{{full_name}}`, `{{store_name}}` (sellers), `{{job_title}}` (professionals). A placeholder that doesn't fit the group is rejected before sending.
* Optional call-to-action button (text and https link, both or neither).
* The preview is rendered by the server with the same code that sends the email.
* **Templates:** start from a starter, or save your own and update or delete it later. **Reuse** in Recent sends loads an earlier message back into the editor.

## Sending

1. **Send test to me** emails only your admin address (subject starts with `[TEST]`).
2. **Send** asks for confirmation, then delivers in the background (100 per batch). A progress bar shows how far it is, and the result is kept in **Recent sends**.
3. Only one send runs at a time. The same message to the same group within 10 minutes is refused, which protects against double clicks.
4. If Resend refuses the API key or sender domain the send stops at once and the reason is shown. Set `RESEND_API_KEY` and a `FROM_EMAIL` on a verified domain (see `resend-email-setup.md`).

A single send is limited to 5,000 recipients.

## Data

`migrations/20261007_admin_broadcasts.sql` (applied automatically on deploy) adds
`email_templates` and `email_campaigns`.

## Not included

Accounts (users, sellers, professionals) have no email opt-out setting yet, so
these emails are meant for platform announcements. Newsletter subscribers can
unsubscribe from every email.
