# Performance guide

What was slow, what was changed, how to check it, and what to do as you grow.
Numbers come from a test database with 8,000 products, 22,000 reviews and 12,000
orders, measured before and after.

## Results

| Page or call | Before | After |
|---|---|---|
| `/products` page: time, database queries, bytes sent | 1,070 ms, 650, 1,097 KB | 136 ms, 7, 80 KB |
| Home page | 460 ms, 218, 654 KB | 75 ms to 150 ms, 37, 58 KB |
| Seller orders list | 784 ms, 620 queries | 53 ms, 14 |
| Buyer orders list | 129 ms, 111 queries | 24 ms, 13 |
| Admin accounts table | 447 ms, 964 KB | about 10 ms, 1 KB per page |
| Category pictures (27 files) | 7.5 MB | 0.96 MB |
| Social preview image | 1.4 MB | 129 KB |

"Bytes sent" is the compressed size that crosses the network.

## What changed

| Item | What was done |
|---|---|
| N+1 queries | Images, stores, categories, order items and addresses now load in batches (`lazy="selectin"` in `models.py`). The cause of most of the slowness. |
| Index the database | All 31 foreign keys plus the order, product and review list queries now have indexes (`migrations/20261026_performance_indexes.sql`). Product-name search has a trigram index when the database allows it. |
| Cache expensive queries | The category menu is kept for 60 seconds. The home page product pool is kept for 60 seconds and reshuffled on every visit. Both clear or re-check themselves when data changes. |
| Server-side caching | `app/cache.py`, in memory, per server. |
| Cache API responses | Anonymous reads of `/api/categories` (60 s) and `/api/products` (30 s) are cacheable. A request with a login is never cached. |
| Compress API payloads | gzip on HTML, JSON, CSS and JS. Images and PDFs are skipped. |
| Compress images | Category pictures 320 px, 256 colours, same file names. The social preview is 1200 by 630. |
| Cloudinary photos | Product photos are requested resized (`f_auto,q_auto,w_N`). Cloudinary picks WebP or AVIF and never serves more pixels than shown. If Cloudinary ever refuses a resized link, the page falls back to the original photo. |
| Minify JS and CSS | `tools/build-assets.sh` writes minified copies to `frontend/static/dist/`. The server uses a copy only while its source file is unchanged, so a forgotten rebuild cannot ship stale code. |
| Tailwind | Built into one 60 KB file (10 KB compressed) instead of a compiler that ran in every visitor's browser. |
| Browser caching | Scripts and CSS carry a content hash in the address and are kept for a year. Images for a week. |
| Lazy loading | Images below the fold load as the page scrolls. |
| Defer non-critical scripts | The 450 KB icon library now downloads early but runs at the end of the page, so it no longer holds up the first paint. Preconnect hints open the third-party connections sooner. |
| Loading skeletons | Cart, orders, checkout, order tracking and the seller lists show grey placeholders while loading. |
| Debounce input handlers | The services and admin search boxes wait 200 ms after the last keystroke. |
| Paginate large lists | The admin accounts table fetches 20 rows at a time, with search and role filter done in the database. The public product API already paged. |
| Connection pooling | Already in place (5 connections plus 10 spare per server, with health checks). See "Growing" below. |
| Unused dependencies | `cloudinary`, `websockets`, `watchfiles` and `PyYAML` are gone. Every other listed package is used. |
| Missing files | `favicon.png` did not exist (404 on every page view) and product and store pages pointed at a missing `og-default.jpg`. Both fixed. |

## When you change the site

* **Added or changed a Tailwind class, `custom.css` or a script?** Run
  `tools/build-assets.sh` (needs Node.js), then commit the changed files in
  `frontend/static/css/`, `frontend/static/dist/` and `tools/tailwind/`.
  If you forget, the tests fail and name what is out of date. Visitors never get stale code
  (the server falls back to the unminified source), but they get a slower page.
* **Page looks unstyled after a deploy?** Set `TAILWIND_MODE=cdn` on Render to go back to
  the browser-compiled version, then rebuild and switch back.
* **Need unminified scripts to debug?** Set `MINIFIED_ASSETS=false`.
* **Added a model with a ForeignKey?** Add an index for it in a new file in
  `backend/migrations/`. `test_every_foreign_key_column_is_indexed` fails until you do.

## Growing

**More than one server.** Render balances traffic across instances for you
(Scaling page in the dashboard). Before you turn it on:

1. Resumes are saved to the server's own disk (`backend/uploads`). A second server would
   not have them. Move them to Cloudinary or another file store first. Do not attach a
   persistent disk instead: Render does not allow multiple instances with one.
2. The category menu, product pool and rate limits live in each server's memory. Each
   copy refreshes within 60 seconds, and rate limits are counted per server. Use Redis for
   rate limits when you reach this point.
3. Every server opens up to 15 database connections (`DB_POOL_SIZE` 5 plus `DB_MAX_OVERFLOW`
   10). Three servers use 45. Check your Render Postgres plan's connection limit and lower
   the two settings if you are near it.

**A CDN.** Cloudinary already serves your product photos from a CDN. For scripts, styles and
pictures that come from your own server, the cache headers added here are what a CDN needs.
The simplest way to add one is Cloudflare's free plan in front of your domain: it caches
`/static/*` and the public product and category calls and leaves everything with a login
alone. The rate limiter already reads Cloudflare's `CF-Connecting-IP` header.

**Bigger catalogue.** `/products` still sends up to 500 products at once and pages them in the
browser, so the category filters work across all of them (80 KB compressed). When you pass
a few thousand products, switch it to server-side paging like the accounts table.

## Checking it yourself

    cd backend
    RATE_LIMIT_DISABLED=1 python -m pytest tests/test_performance.py -q

The tests count database queries per page, so a new N+1 problem fails them.
