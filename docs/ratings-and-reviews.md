# EraVenda Ratings and Reviews

This document describes the rating and review systems currently implemented for products and handyman professionals.

## At A Glance

| Area | Who can rate | When rating becomes available | Scale | Where the average is stored |
|---|---|---|---|---|
| Products | The buyer who purchased the item | After the order status is `delivered` | 1 to 5 stars | `products.average_rating` |
| Handyman services | The seeker who requested the booking | After the handyman requests completion sign-off | 1 to 5 stars | `handyman_profiles.average_rating` |

Both systems allow the reviewer to update an existing review instead of creating a duplicate.

## Product Ratings

### Eligibility

A buyer can rate a product only when all of these conditions are true:

- The buyer is signed in.
- The submitted `order_item_id` belongs to the submitted `product_id`.
- The order item belongs to an order owned by the signed-in buyer.
- The order status is `delivered`.
- The buyer has not already reviewed that specific order item, unless updating the existing review.

The review is attached to the order item, not just the product. This means a buyer can review separate purchases of the same product independently.

### Buyer experience

The review page is available from delivered orders:

- Page: `/orders/review?order_id=<order-id>&item_id=<order-item-id>`
- Template: [order-review.html](../frontend/templates/order-review.html)
- The buyer selects 1–5 stars.
- A written comment is optional.
- The buyer submits one review per delivered order item.
- A successful submission changes the button to `Rating saved`.

The order history and tracking interfaces expose the review action only after delivery.

### API

#### Submit or update a product review

```http
POST /api/reviews
Authorization: Bearer <buyer-token>
Content-Type: application/json
```

```json
{
  "product_id": "product-id",
  "order_item_id": "order-item-id",
  "rating": 5,
  "comment": "Exactly as described and delivered quickly."
}
```

`rating` must be an integer from 1 through 5. The API returns `403` if the buyer is not eligible.

#### Check whether a buyer can review a product

```http
GET /api/reviews/product/{product_id}/eligibility
Authorization: Bearer <buyer-token>
```

Response:

```json
{
  "eligible": true,
  "order_item_id": "order-item-id"
}
```

#### Read public product statistics

```http
GET /api/reviews/product/{product_id}/stats
```

Response:

```json
{
  "total": 12,
  "comments": 9,
  "distribution": {
    "1": 0,
    "2": 1,
    "3": 2,
    "4": 4,
    "5": 5
  },
  "average": 4.08
}
```

The product page uses the product's stored `average_rating` and `review_count` for its summary display. The stats endpoint calculates the distribution and average from the review rows when requested.

### Database record

Product reviews are stored in `reviews`:

- `product_id`: reviewed product
- `buyer_id`: reviewer
- `order_item_id`: qualifying purchase
- `rating`: integer from 1 to 5
- `comment`: optional text
- `created_at`: submission time

The database constraint `uq_buyer_orderitem_review` prevents duplicate reviews for the same buyer and order item.

When a review is created or updated, the API recalculates:

- `products.review_count`
- `products.average_rating`

The average is the arithmetic mean of all product review ratings and is rounded by the database value returned through the API.

## Handyman Ratings

### Eligibility

A seeker can rate a handyman when:

- The seeker is signed in.
- The booking belongs to the signed-in seeker.
- The booking status is one of:
  - `completion_requested`
  - `completed`
  - `released`
- The booking does not already have a review, unless the seeker is updating it.

The review can be submitted before the payment is released, because the seeker is expected to review the work after completion sign-off and before or around payment confirmation.

### Buyer/seeker experience

The rating form lives in the booking tracker:

- Page: `/services/bookings/{booking-id}`
- Template: [booking-tracker.html](../frontend/templates/booking-tracker.html)
- The seeker selects 1–5 stars.
- A written comment is optional.
- Work photos and payment information are shown alongside the review flow.
- After submission, the review is displayed in the tracker.

The public professional profile also displays:

- Average rating
- Review count
- Public review comments and star values

Template: [services-professional.html](../frontend/templates/services-professional.html)

### API

#### Submit or update a handyman review

```http
POST /api/services/bookings/{booking_id}/rating
Authorization: Bearer <seeker-token>
Content-Type: application/json
```

```json
{
  "rating": 5,
  "comment": "Arrived on time and completed the repair carefully."
}
```

`rating` must be an integer from 1 through 5. The API returns `403` when the booking is not owned by the seeker or is not ready for rating.

#### Read public handyman reviews

```http
GET /api/services/workers/{handyman_id}/ratings
```

The endpoint returns the professional's reviews in newest-first order.

#### Check review eligibility

```http
GET /api/services/workers/{handyman_id}/review-eligibility
Authorization: Bearer <seeker-token>
```

Response:

```json
{
  "eligible": true,
  "booking_id": "booking-id"
}
```

### Database record

Handyman reviews are stored in `service_reviews`:

- `booking_id`: one review per booking
- `handyman_id`: reviewed professional
- `client_id`: seeker who submitted the review
- `rating`: integer from 1 to 5
- `comment`: optional text
- `created_at`: submission time

The database constraint `uq_service_review_booking` prevents multiple review rows for one booking.

When a review is created or updated, the API recalculates:

- `handyman_profiles.review_count`
- `handyman_profiles.average_rating`

The public professional profile reads those stored summary fields.

## Safety Rating Versus Customer Rating

A handyman's `safety_rating` is separate from customer reviews:

- Customer reviews measure the seeker's experience with completed work.
- Safety rating is an admin-managed trust signal.
- Admins can update safety rating and professional badges from the admin dashboard.
- Safety rating is displayed separately as `Safety x/5`.

Do not combine `safety_rating` with `average_rating` when calculating the public customer review average.

## Admin Visibility and Moderation

### Handyman reviews

Admins can view handyman reviews from the admin dashboard's Reviews section. The admin view includes:

- Professional name
- Client name
- Rating
- Comment
- Date

### Product reviews

Product review statistics and comments are publicly available through the product review endpoints, but there is currently no dedicated product-review moderation panel in the admin dashboard.

If product-review moderation becomes necessary, add an admin-only review list and moderation status rather than deleting review rows directly. Preserve the original review for auditability.

## Rating Rules and Trust Model

- Ratings are always integers from 1 to 5.
- A rating is tied to a real transaction or service booking.
- A buyer cannot rate an undelivered product.
- A seeker cannot rate a handyman before completion sign-off.
- A reviewer can edit their own review by submitting the same qualifying order item or booking again.
- Other users cannot edit or submit a review on someone else's transaction.
- Public review endpoints do not expose buyer email addresses or phone numbers.

## Operational Notes

### Product review average

The product average is recalculated synchronously after every product review change. This is simple and accurate for the current scale. For a much larger review volume, move aggregation to a background job or maintain a transactional summary table with carefully tested increments/decrements.

### Handyman review average

The handyman average follows the same synchronous recalculation pattern. Updating a review recalculates the professional's count and average from all reviews for that professional.

### Comments

Product review comments currently have no explicit backend maximum length in `ReviewCreate`; the frontend textarea limits comments to 1,000 characters. Handyman comments are limited to 1,000 characters by the backend schema. If product comments are exposed to other clients, add the same backend limit for consistent protection.

### Deletion and account lifecycle

Product reviews use a buyer foreign key with no explicit `ON DELETE CASCADE` in the model. Handyman reviews use cascading foreign keys for the booking, handyman, and client relationships. Account deletion behavior should be tested before allowing permanent user deletion for accounts with review history.

## File Map

- Product review API: [reviews.py](../backend/app/routers/reviews.py)
- Handyman review API: [services.py](../backend/app/routers/services.py)
- Rating schemas: [schemas.py](../backend/app/schemas.py)
- Review models: [models.py](../backend/app/models.py)
- Product review UI: [order-review.html](../frontend/templates/order-review.html)
- Handyman review UI: [booking-tracker.html](../frontend/templates/booking-tracker.html)
- Public handyman reviews: [services-professional.html](../frontend/templates/services-professional.html)
