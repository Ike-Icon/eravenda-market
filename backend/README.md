# Eravenda API

FastAPI backend for Eravenda. Handles buyers, sellers, stores, products,
carts, orders, and admin approvals.

## Setup

1. Install PostgreSQL and create a database:

```bash
createdb eravenda
```

2. Create a virtual environment and install dependencies:

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Copy the environment file and fill in your values:

```bash
cp .env.example .env
```

Set `DATABASE_URL` to your PostgreSQL connection string and `SECRET_KEY` to a
long random string (run `python -c "import secrets; print(secrets.token_hex(32))"`
to generate one).

4. Run the server:

```bash
uvicorn app.main:app --reload --port 8000
```

Tables are created automatically on startup for local development. The Render
start command also runs the checked-in idempotent SQL migrations before Uvicorn
starts, so an existing production database receives newly added columns.

5. Open the interactive API docs at `http://localhost:8000/docs`.

## Creating your first admin account

There's no public endpoint for creating admins, on purpose. Register a normal
account, then run this in `psql` to promote it:

```sql
UPDATE users SET role = 'admin' WHERE email = 'you@example.com';
```

## Key endpoints

| Method | Path                           | Purpose                                            |
| ------ | ------------------------------ | -------------------------------------------------- |
| POST   | `/auth/register`             | Create a buyer or seller account                   |
| POST   | `/auth/login`                | Get a JWT (form fields:`username`, `password`) |
| GET    | `/products`                  | Browse/search/filter approved products             |
| POST   | `/stores`                    | Register a store (requires login)                  |
| POST   | `/products`                  | Add a product (requires an approved store)         |
| POST   | `/cart/items`                | Add an item to the cart                            |
| POST   | `/orders/checkout`           | Turn the cart into one order per store             |
| GET    | `/orders/store/mine`         | Seller's incoming orders                           |
| PUT    | `/admin/stores/{id}/approve` | Approve a pending store                            |

Full request/response shapes are in the auto-generated docs at `/docs`.

## Commission policy

EraVenda charges sellers a product commission on each completed sale, deducted from
the seller's proceeds before payout. The rate depends on the product's category, and
**no category rate may ever exceed 10%** — this is enforced in code by
`standard_product_rate()` in `app/product_pricing.py`, not just documented here.

| Category | Standard rate |
| -------- | -------------:|
| Groceries and perishables | 4.5% |
| Electronics and phones | 6.5% |
| Home, kitchen and household goods | 9.5% |
| Fashion, beauty, clothing and accessories | 10% |
| Other / unclassified | 8% (default) |

Handyman/professional bookings use a separate flat **4%** service commission
(`app/service_pricing.py`), well inside the 10% product-category ceiling above.

**Launch discount:** early vendors pay half the standard category rate for the first
90 days starting **14 October 2026** (ending 12 January 2027), or for the first 20
vendors, whichever comes first. Configured via `COMMISSION_LAUNCH_START_DATE`,
`COMMISSION_LAUNCH_DURATION_DAYS`, and `COMMISSION_LAUNCH_VENDOR_CAP` in `.env` /
`render.yaml`.

See [`docs/commission-rates.md`](../docs/commission-rates.md) for the full policy,
calculation examples, and the checklist to follow before changing any rate.

## Image uploads

Products store image URLs, not files. The frontend uploads directly to
Cloudinary using an unsigned upload preset, then sends the resulting URL to
`POST /products/{id}/images`. Set your Cloudinary cloud name and preset in
`frontend/js/config.js`.
