# Security guide

What protects the site, what you have to switch on, and how to check it.

## What is in place

| Area | What the code does |
|---|---|
| Login | bcrypt password hashes (cost 12). Login token is an HttpOnly cookie that scripts cannot read. |
| Sessions | Changing or resetting a password ends all older sessions. A reset link works once. Reset and verification links cannot be used as logins. |
| Cross-site requests | Cookie requests that change data must come from our own pages (Origin, Referer, Sec-Fetch-Site check) on top of SameSite=Lax. |
| Email | New accounts get a confirmation link. Google and Apple sign-in need a verified email at the provider. |
| Rate limits | Login, register, password reset, contact, newsletter, checkout, payments, store creation, plus 600 requests a minute per visitor on the API. In memory, per server instance. |
| CORS | Only your own site by default. `*` is ignored. |
| Production | `/docs`, `/redoc` and `/openapi.json` are off. HSTS is on. Admin pages need an admin session. |
| Input | Length limits, price above zero, https-only image links, hex-only colors, descriptions cleaned of scripts (on save, on import and on display). |
| Uploads | Resumes are checked by content, not only by extension. Excel import: 5 MB, 500 rows, zip-bomb check. |
| Logs | Tokens in URLs and anything shaped like a JWT are masked in production. Email bodies are not logged in production. |
| Database | Row level security is on for every table with no policies, so any role other than the app's own sees nothing. |
| Webhooks | Paystack signature (HMAC-SHA512) and amount are checked before an order is marked paid. |

## Settings you control on Render

| Variable | Default | When to change |
|---|---|---|
| `REQUIRE_VERIFIED_EMAIL` | `false` | Set `true` after a test sign-up receives the confirmation email. |
| `CSP_MODE` | `report-only` | Browse every page with the browser console open. If it shows no "Content Security Policy" messages, set `enforce`. |
| `ALLOWED_ORIGINS` | empty | Only if another website must call the API. |
| `CLIENT_IP_HEADER` | unset | Only if rate limits look wrong. |
| `SECRET_KEY` | generated | Use 32+ random characters. Changing it signs everyone out. |

## Things code cannot fix. Do these yourself

1. **Cloudinary upload preset.** The preset name is public, so anyone can upload to your Cloudinary. In the Cloudinary dashboard, limit the preset to images, a maximum size (for example 5 MB), and one folder.
2. **Render database access.** In the Render dashboard open the database and make sure external access is limited to the addresses you need (or off). The app reaches it over Render's internal network.
3. **GitHub.** Add the repository secret `CLAUDE_API_KEY` for the security-review workflow, turn on "Require approval for all external contributors", and keep Dependabot alerts on.
4. **Paystack.** Keep the live secret key only in Render's environment, never in the repository or the browser.
5. **Backups.** Check that your Render database plan keeps daily backups and test one restore.

## Checking it yourself

```
cd backend
pip install -r requirements.txt pip-audit
pip-audit -r requirements.txt          # known vulnerabilities: should say none
RATE_LIMIT_DISABLED=1 python -m pytest tests -q
```

`tests/test_security.py` holds one test per attack that used to work.

## Known limits

- Rate limit counters live in one server's memory. With more than one instance, move them to Redis.
- The Content-Security-Policy allows inline scripts because the pages use them. Moving every inline script to a file would let you drop that allowance.
- Tailwind is loaded from its CDN script, which cannot carry an integrity hash. Building the CSS into a file removes that dependency.
- Registration still answers "an account with this email already exists", which reveals which emails are registered. That is a usability trade-off; the login and reset forms do not reveal it.
