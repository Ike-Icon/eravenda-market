# EraVenda Commission Rates

This document explains the commission policy for product sellers and handyman professionals, plus the two optional seller revenue features (subscription plan and promoted listings). Product commissions and handyman commissions are intentionally separate systems.

## Summary

| Area | Who pays | Current enforced rate | Basis |
|---|---|---:|---|
| Products | Seller | **Flat 7%** for every seller; **10% hard cap** | Product sale value |
| Products, subscribed seller | Seller | Plan rate (default 4%) while the plan is live | Product sale value |
| Handyman services | Professional | 4% | Completed job value |

The product rate was a flat 5% from launch and became a flat 7% on **4 October 2026**. It applies to every seller and every category. There is no launch discount and no category-specific rate at the moment.

Buyer-facing product prices do not include a separate EraVenda commission line. The commission is recorded on the order and deducted from the seller's product proceeds.

**Platform-wide rule: no product commission rate may ever exceed 10%.** This is enforced in code (`PRODUCT_COMMISSION_RATE_CAP` in `product_pricing.py`, clamped in `product_commission_rate()`) and by validation on the admin settings form.

## Where the numbers live

Every adjustable value is stored in one row of the `platform_settings` table and edited by an admin under **Admin dashboard > Monetization**. Changes apply to new activity immediately.

| Setting | Default | Allowed range |
|---|---:|---|
| Standard product commission | 7% | 0 to 10% |
| Subscription on/off | off | |
| Subscription monthly fee | GHS 150 | above 0, up to GHS 10,000 |
| Subscriber commission rate | 4% | 0 up to, but below, the standard rate |
| Promotions on/off | off | |
| Promotions open from | 14 Jan 2027 (Month 4 of a 14 Oct 2026 launch) | any date, or none |
| One-product pin price | GHS 20 / week | GHS 20 to GHS 50 (enforced in code) |
| Whole-store pin price | GHS 50 / week | GHS 20 to GHS 50 (enforced in code) |
| Max weeks per purchase | 4 | 1 to 12 |
| Pinned spots per category | 3 | 1 to 20 |

The subscription fee, subscriber rate and promotion prices above are starting values chosen so the plan breaks even at about GHS 5,000 in monthly sales (150 / (7% - 4%)). Adjust them from the admin dashboard once real sales data exists.

## Product calculation

For each order item:

```text
commission = item line total x applicable product rate / 100
```

The rate used is the standard rate, or the store's subscription rate while it has a live subscription, whichever is lower. The order stores `commission_amount`, and each order item stores `commission_rate` and `commission_amount`. **Orders already placed keep the rate they were placed at**, so changing a rate never rewrites history.

### Product payout example

For a product sold at GHS 100 under the standard 7% rate:

```text
Sale value                         GHS 100.00
EraVenda commission, 7%            -GHS   7.00
Estimated Paystack fee             -GHS   2.25
Approximate seller proceeds        GHS  90.75
```

The GHS 2.25 Paystack amount is an estimate based on approximately 1.95% plus GHS 0.30 for mobile money. Delivery fees or delivery-fee splits are separate.

## Seller subscription

- A seller pays the monthly fee through Paystack (reference prefix `ERVSUB-`) for 1 to 12 months. Each month is 30 days.
- While the plan is live the seller's commission is the subscriber rate. When the period ends the seller returns to the standard rate automatically; nothing needs to run on a schedule.
- Plans do not renew by themselves. Renewing early adds the new months to the days remaining.
- The fee and rate are snapshotted when the plan is bought or renewed, so later admin edits never change a plan a seller already paid for.
- An admin can grant a free plan or end one early from the Monetization tab. Turning the plan off stops new purchases but does not cut short plans already paid for.

## Promoted listings

- A seller pins **one product** (the product's own category) or **their store in a category** (up to 4 of the store's newest approved products there) for 1 to 12 weeks, paid through Paystack (prefix `ERVPRO-`). The promotion starts when payment is confirmed.
- Pins show first when buyers browse a category (the `/products?category_id=...` page), including its parent categories, oldest live promotion first, with a "Sponsored" tag. They do not appear on the unfiltered all-products page, and search text and other filters still apply to pinned items.
- Each category has a limited number of pinned spots. An unpaid purchase holds its spot for 30 minutes.
- A promotion ends when its time runs out; nothing runs on a schedule. An admin can grant a free promotion or stop one early.

## Revenue reporting

`GET /api/admin/stats` includes `subscription_revenue` and `promotion_revenue` under `overall` and adds both to `platform_revenue`. `GET /api/admin/monetization/revenue` gives totals, this month's figures, active subscribers and live promotions.

## Handyman Commission Policy

Handyman pricing does not use product rates. It is unchanged by the product commission, subscription and promotion features.

- Rate: **4% of the completed job value**, configured with `SERVICE_COMMISSION_RATE=0.04` (a decimal fraction; supported range 0% to 10%)
- Buyer/seeker pays the agreed job amount plus the service commission; the professional receives the agreed job amount after payment and verification

```text
Agreed professional job amount       GHS 100.00
EraVenda service commission, 4%      GHS   4.00
Seeker payment total                 GHS 104.00
Professional payout                  GHS 100.00
```

Backend functions: `service_commission_for(base_amount)` and `service_charge_for(base_amount)` in `service_pricing.py`. Commission is stored on `service_bookings.commission_amount`, payout on `service_bookings.payout_amount`.

Do not apply product rates to handyman bookings, and do not include handyman commission in product order commission totals.

## API

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/api/products/commission-policy` | public | Standard rate, plan and promotion prices |
| GET | `/api/monetization/overview` | seller | Rate, plan, break-even, promotions, product list |
| POST | `/api/monetization/subscription/initialize` | seller | Start a plan payment |
| POST | `/api/monetization/promotions/initialize` | seller | Start a promotion payment |
| GET | `/api/monetization/verify/{reference}` | seller/admin | Confirm a payment after Paystack redirect |
| GET/PUT | `/api/admin/monetization/settings` | admin | Read and change every setting above |
| GET/POST/PUT | `/api/admin/monetization/subscriptions...` | admin | List, grant, end |
| GET/POST/PUT | `/api/admin/monetization/promotions...` | admin | List, grant, cancel |
| GET | `/api/admin/monetization/revenue` | admin | Revenue totals |

The Paystack webhook (`/api/payments/webhook`) also confirms `ERVSUB-` and `ERVPRO-` payments, so a plan or promotion activates even if the seller never returns to the site.

## Implementation file map

- Rate rules: `backend/app/product_pricing.py`
- Settings, subscription lookup, promotion ordering: `backend/app/platform_settings.py`
- Activation of paid/granted plans and promotions: `backend/app/store_billing.py`
- Seller and admin endpoints: `backend/app/routers/monetization.py`
- Tables: `PlatformSettings`, `SellerSubscription`, `PromotedListing`, `StoreCharge` in `backend/app/models.py` (created automatically at startup)
- Checkout calculation: `backend/app/routers/orders.py`
- Seller page: `frontend/templates/seller/growth.html`; admin tab: `frontend/templates/admin/dashboard.html`
- Public copy: `faq.html`, `terms.html`, `seller/dashboard.html` (seller terms), `components/vendor-promo-popup.html`

## Policy change checklist

Before changing a commission rate:

1. Change it in Admin > Monetization (or `PRODUCT_DEFAULT_RATE` for a fresh database). Keep it at or under the 10% cap.
2. Update the FAQ, public terms and seller terms text if the number appears there.
3. Keep existing order and booking snapshots unchanged.
4. Test a new checkout and a new handyman booking.
5. Verify the admin payment and seller payout displays.
6. Announce rate changes with the notice period promised in the terms (currently 30 days).
