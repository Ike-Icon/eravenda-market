# EraVenda Commission Rates

This document explains the commission policy for product sellers and handyman professionals. Product commissions and handyman commissions are intentionally separate systems.

## Summary

| Area | Who pays the commission | Current enforced rate | Basis |
|---|---|---:|---|
| Products | Seller | Category-based; 8% default | Product sale value |
| Handyman services | Professional | 10% | Completed job value |

Buyer-facing product prices do not include a separate EraVenda product commission line. The product commission is recorded on the order and deducted from the seller's product proceeds.

## Product Commission Policy

### Standard category rates

The current product pricing module uses these rates:

| Product category | Rate |
|---|---:|
| Groceries and perishables | 4.5% |
| Electronics and phones | 6.5% |
| Home, kitchen, household goods and furniture | 9.5% |
| Fashion, beauty, clothing, shoes and accessories | 13% |
| Other or unclassified products | 8% |

The 8% rate is the recommended launch rate and the fallback rate for products that do not match a recognized category.

Category detection checks the product category and its parent categories. It uses category names containing terms such as:

- Groceries: `grocery`, `food`, `beverage`, `perishable`
- Electronics: `electronic`, `phone`, `computer`, `mobile`, `gadget`
- Fashion: `fashion`, `beauty`, `clothing`, `shoe`, `accessory`
- Home: `home`, `kitchen`, `household`, `furniture`

A category that does not match one of those groups receives the 8% default rate.

### Launch discount

Eligible early vendors receive half of their applicable standard category rate:

- Start date: **14 September 2026**
- Duration: **90 days**
- End date: **13 December 2026**
- Vendor cap: **first 20 vendors**
- The discount ends when the date window expires or the vendor cap is reached, whichever comes first.

Examples during the launch offer:

| Category | Standard rate | Launch rate |
|---|---:|---:|
| Groceries | 4.5% | 2.25% |
| Electronics | 6.5% | 3.25% |
| Home goods | 9.5% | 4.75% |
| Fashion and beauty | 13% | 6.5% |
| Other categories | 8% | 4% |

The vendor rank is based on store creation order. The first 20 registered stores are the launch cohort. The rate is evaluated at checkout and stored on each order item.

### Product calculation

For each order item:

```text
commission = item line total × applicable product rate ÷ 100
```

For an order containing several products:

```text
order commission = sum of each order item's commission
```

The order stores:

- `commission_amount`: total product commission for the order
- Each order item stores `commission_rate`
- Each order item stores `commission_amount`

This preserves the historical rate even if the policy changes later.

### Product payout example

For a product sold at GHS 100 under the standard 8% rate:

```text
Sale value                         GHS 100.00
EraVenda commission, 8%            -GHS   8.00
Estimated Paystack fee             -GHS   2.25
Approximate seller proceeds        GHS  89.75
```

The GHS 2.25 Paystack amount is an estimate based on approximately 1.95% plus GHS 0.30 for mobile money. Actual payment fees may vary by payment method and provider rules. Delivery fees or delivery-fee splits are separate and can change the final settlement amount.

Seller screens describe the amount after EraVenda commission as an estimated payout before Paystack and delivery-fee deductions.

## Handyman Commission Policy

Handyman pricing does not use product category rates or product price tiers.

### Current rate

- Rate: **10% of the completed job value**
- Payer: handyman/professional
- Buyer/seeker pays: agreed job amount plus the service commission
- Professional receives: agreed job amount after payment and verification

The rate is configured with:

```env
SERVICE_COMMISSION_RATE=0.10
```

The code stores the rate as a decimal fraction. Therefore:

```text
0.10 = 10%
```

The supported strategic range is 10%–15%; the current implementation uses the conservative 10% starting rate.

### Handyman calculation

For a job amount of GHS 100:

```text
Agreed professional job amount       GHS 100.00
EraVenda service commission, 10%     GHS  10.00
Seeker payment total                 GHS 110.00
Professional payout                  GHS 100.00
```

The backend functions are:

- `service_commission_for(base_amount)`: calculates the commission
- `service_charge_for(base_amount)`: calculates job amount plus commission

Handyman commission is stored on `service_bookings.commission_amount`. The professional payout is stored separately in `service_bookings.payout_amount`.

### Handyman payment flow

1. The professional accepts or prices the job.
2. The backend calculates the 10% commission and total escrow charge.
3. The professional requests completion sign-off.
4. The seeker reviews the completed work and pays through Paystack.
5. EraVenda holds the payment while completion is verified.
6. An admin can release or hold the professional payout.
7. The professional receives the agreed job amount, while the service commission remains EraVenda's charge.

Off-platform payment for EraVenda-booked jobs is prohibited by the professional terms.

## Product Versus Handyman Rules

| Rule | Products | Handyman services |
|---|---|---|
| Pricing basis | Product line total | Completed job value |
| Rate selection | Category and launch cohort | Service commission setting |
| Who is charged | Seller proceeds | Professional job settlement |
| Buyer sees commission | Not as a separate checkout line | Yes, as part of service total |
| Historical snapshot | Order and order-item commission fields | Booking commission and payout fields |
| Rate source | `product_pricing.py` | `service_pricing.py` |

Do not apply product category rates to handyman bookings, and do not include handyman commission in product order commission totals.

## API and Configuration

### Read product policy

```http
GET /api/products/commission-policy
```

This returns the standard rate, category rates, launch dates, vendor cap and discount description.

### Environment settings

```env
COMMISSION_LAUNCH_START_DATE=2026-09-14
COMMISSION_LAUNCH_DURATION_DAYS=90
COMMISSION_LAUNCH_VENDOR_CAP=20
SERVICE_COMMISSION_RATE=0.10
```

The product launch settings are also defined in `render.yaml` for deployment.

## Implementation File Map

- Product rules: [product_pricing.py](../backend/app/product_pricing.py)
- Product checkout calculation: [orders.py](../backend/app/routers/orders.py)
- Product commission response: [products.py](../backend/app/routers/products.py)
- Order and order-item commission fields: [models.py](../backend/app/models.py)
- Handyman rules: [service_pricing.py](../backend/app/service_pricing.py)
- Handyman booking and payout flow: [services.py](../backend/app/routers/services.py)
- Handyman payment flow: [payments.py](../backend/app/routers/payments.py)
- Seller onboarding and payout explanation: [dashboard.html](../frontend/templates/seller/dashboard.html)
- Public seller FAQ: [faq.html](../frontend/templates/faq.html)
- Public platform terms: [terms.html](../frontend/templates/terms.html)

## Policy Change Checklist

Before changing a commission rate:

1. Update the backend pricing module.
2. Update the Render environment configuration if the setting is environment-controlled.
3. Update seller onboarding terms and payout examples.
4. Update the FAQ and public terms.
5. Keep existing order and booking snapshots unchanged.
6. Test a new checkout and a new handyman booking.
7. Verify the admin payment and seller payout displays.
8. Announce rate changes with the notice period promised in the applicable terms.
