# Payment receipts

Every paid order has a PDF receipt (`RCP-<order number>`), e.g. `RCP-ORD-20261010-K7Q2ZX`.

| Who | How |
|---|---|
| Buyer, automatically | The payment-confirmation email carries the receipt as a PDF attachment (online payments, and cash-on-delivery once an admin records the cash). |
| Buyer, any time | **Download receipt** and **Email receipt** buttons on *Your orders*, on the order tracking page, and on the payment-success page. |
| Admin | **Download receipt** and **Email to buyer** on each successful payment in *Admin > Payments > Payment tracking*. |

A receipt exists only once a payment is confirmed. Orders still awaiting payment, and cash-on-delivery orders whose cash
hasn't been recorded yet, have none. A refunded payment still has a receipt, stamped **REFUNDED**.

## API
| Endpoint | Who |
|---|---|
| `GET /api/orders/{id}/receipt` | the order's own buyer (anyone else gets 404) |
| `POST /api/orders/{id}/receipt/email` | the order's own buyer; sends to their account email |
| `GET /api/admin/orders/{id}/receipt` | admin |
| `POST /api/admin/orders/{id}/receipt/email` | admin; always sends to the *buyer's* email, never an address supplied by the caller |

`OrderOut` gained `receipt_available` and `receipt_number`. Emailing is limited to once per order per minute.

## How it works
- Rendered on demand from the order and payment rows, so there is nothing stored and **no database migration**.
- `app/receipt_pdf.py` draws the PDF (reportlab, no web framework needed); `app/receipts.py` handles lookup, the download
  response and email.
- Fonts: `app/assets/fonts/` bundles DejaVu Sans so Ghanaian letters (ɛ, ɔ) draw correctly. Keep this folder in the repo.
- Amounts are shown in GHS. The seller commission and payout split are internal and never appear on a customer's receipt.

## Tests
- `cd backend && python -m unittest tests.test_receipt_pdf -v` (no database needed)
- `DATABASE_URL=... python -m pytest tests/test_receipts.py -q` (end to end; needs the PostgreSQL test database)
