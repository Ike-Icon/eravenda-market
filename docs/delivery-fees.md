# Delivery fees

Admins change delivery fees in **Admin dashboard > Delivery fees**. Changes
apply to every new checkout quote and order straight away. An order keeps the
fee it was charged when it was placed. Pickup is always free.

Each store in a cart gets its own fee: **distance fee + weight charge**, unless
the free-delivery rule below makes it free.

## Distance

There are no GPS coordinates, so distance is the relationship between the
buyer's address and the seller's store. Five bands, each with its own fee:

| Band | Standard fee (GHS) |
|---|---|
| Same neighbourhood in the base city | 8 |
| Base city, different neighbourhood | 10 |
| Same city (outside the base city) | 18 |
| Same region, different city | 30 |
| Different region | 45 |

The base city is Sunyani and can be changed. The standard fees match what was
hardcoded before, so nothing changed on the day this shipped.

## Free delivery

On by default at GHS 200. A delivery is free when the buyer and the store are
both in the base city (Sunyani) and that store's order subtotal is **above** the
amount. Exactly GHS 200 still pays. The subtotal counts discounted prices, is
worked out per store, and excludes the delivery fee. Free delivery replaces the
whole fee, including any weight charge. Orders to or from other cities are not
affected. The admin can switch it off or change the amount in the same tab.

## Weight

Off by default. When switched on, each store's order gets an extra charge from
its total weight (item weight x quantity, summed):

- Sellers enter an item's weight (kg) on the add and edit product forms.
- A product with no weight counts as the **default item weight** (1 kg to start).
- Up to 6 bands. A weight exactly on a band's limit falls in that band, so 5 kg
  is in "up to 5 kg". The last band is "over X kg" and has no limit.
- Pre-filled suggestion: up to 5 kg +0, up to 20 kg +5, up to 50 kg +15, over
  50 kg +30. Review these before switching weight on.

Limits: every fee or charge is GHS 0 to 1,000. Weight limits go up to 1,000 kg.

## Where it lives

- Rules: `delivery_fee_settings` table (one row), `backend/app/delivery_fees.py`
- Admin API: `GET` and `PUT /api/admin/delivery-fees`
- Quote and checkout: `backend/app/routers/orders.py`
- Product weight: `products.weight_kg`
