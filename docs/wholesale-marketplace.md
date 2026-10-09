# Wholesale / Retail marketplace

Products are either **retail** (default, unchanged behaviour) or **wholesale**.

## Rules
- Seller picks Sales Type per product. Wholesale needs a Minimum Wholesale Quantity (whole number, 2 to 100,000). Each product has its own minimum.
- The product's normal `price` is the per-unit wholesale price (no duplicate price column).
- The minimum is counted per product across colour/size/option lines.
- The cart can hold a below-minimum quantity (the cart page flags it). Checkout is blocked on the server (400) and on the page.
- Checkout reads sales type, price, minimum and stock from the database. Nothing from the request body is trusted.
- Checkout creates one order per seller **and** sales type, so every order is wholly retail or wholly wholesale.
- Each order line stores a snapshot of the minimum that applied (`order_items.wholesale_min_quantity`).

## Database (migration `20261008_wholesale_marketplace.sql`, idempotent)
- `products.sales_type` (default `retail`), `products.wholesale_min_quantity`
- `orders.order_type` (default `retail`), `order_items.wholesale_min_quantity`

## API
- `GET /api/products?sales_type=retail|wholesale` (new optional filter)
- `POST/PUT /api/products`, `PUT /api/admin/products/{id}`: accept `sales_type`, `wholesale_min_quantity`
- `GET /api/cart`: new `wholesale_issues`
- `POST /api/orders/checkout`: wholesale validation, split by type
- Orders now return `order_type`, `total_quantity`, item `wholesale_min_quantity`
- Admin (admin only): `GET /api/admin/wholesale/summary|orders|products`

## Tests
Needs a throwaway PostgreSQL:

    DATABASE_URL=postgresql://localhost:5432/eravenda_test SECRET_KEY=test \
      python -m pytest backend/tests/test_wholesale.py -q

## Dashboard auto-refresh
`startAutoRefresh()` in `frontend/static/js/main.js` polls every 30 seconds so new orders appear without a manual reload.
- Seller orders: redraws only when the list changed, shows a "New order received" toast.
- Seller dashboard: rebuilds only when the order list changed.
- Admin dashboard: sidebar badges and attention cards refresh on every tab; the Wholesale tab also refreshes its stats and orders table (same page, filters kept).
- Pauses on hidden tabs and offline, catches up when the tab returns, never overlaps, backs off after errors, and skips a round while the user has unsaved input (so a half-written customer update is never wiped).

## Email center: One user
New audience "One user" (admin only). The admin searches by name or email (min 2 letters, active accounts, any role, max 10 results), picks one account, and the normal preview / test / send flow applies to just that person.
- `GET /api/admin/broadcasts/users?q=` finds accounts. `POST .../preview|send-test|send` accept `audience: "user"` plus `user_id`.
- Placeholders: `{{first_name}}`, `{{full_name}}`.
- The send is recorded in Recent sends as "One user: <email>" (new column `email_campaigns.target_email`, migration `20261009_email_campaign_single_user.sql`).
- The 10-minute duplicate guard is per person, so the same text can go to two different people but not twice to one.
- Deactivated or unknown accounts are refused with a clear message; nothing is sent.
