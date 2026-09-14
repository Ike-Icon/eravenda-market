# EraVenda Design System Architecture

**Status:** Proposed architecture for the existing frontend
**Scope:** Marketplace, Handyman Hub, seller workspace, professional workspace, admin workspace, authentication, checkout, and public content pages
**Primary stack:** Jinja templates, Tailwind CSS CDN utilities, `frontend/static/css/custom.css`, legacy tokenized CSS, Lucide, Font Awesome

## 1. Purpose

The design system gives EraVenda one visual and interaction language across two connected businesses:

- **EraVenda Market:** product discovery, stores, cart, checkout, orders, and seller operations.
- **EraVenda Handyman Hub:** professional discovery, service requests, booking progress, payments, reviews, and professional operations.

The system should make these surfaces feel related without making them indistinguishable. Marketplace flows emphasize products, price, delivery, and inventory. Handyman flows emphasize trust, qualifications, job progress, payment protection, and reviews. Admin flows emphasize density, scanning, and decision-making.

## 2. Current Architecture

### Shared shell

`frontend/templates/base.html` is the composition root for public and authenticated pages. It provides:

- Document metadata and theme initialization.
- Tailwind CDN configuration.
- Brand and accent color scales.
- Font loading for Space Grotesk and Inter.
- Lucide and Font Awesome icon libraries.
- Shared header and footer includes.
- Shared frontend configuration and client logic.

### Shared components

- `frontend/templates/components/header.html`: logo, search, primary navigation, category navigation, account menu, cart and wishlist actions, mobile drawer.
- `frontend/templates/components/footer.html`: newsletter, support, selling, handyman, legal, and payment links.
- `frontend/templates/components/seller-nav.html`: seller workspace navigation.

### Styling layers

1. **Tailwind utility layer:** primary implementation style for newer templates.
2. **`frontend/static/css/custom.css`:** current shared overrides, navigation styles, dark-theme behavior, and reusable visual rules.
3. **`frontend/css/style.css`:** legacy tokenized CSS layer with reusable `.btn`, layout, header, footer, and section classes.
4. **Inline template classes:** page-specific composition and responsive layout.

### Runtime model

- Jinja renders page structure and server-provided data.
- Browser JavaScript loads authenticated data and handles interactive states.
- `apiFetch` is the frontend request boundary.
- Backend routers own business behavior; templates own presentation.

## 3. Design Principles

1. **Trust before decoration:** payment, identity, status, and next actions must be obvious.
2. **One action hierarchy:** each surface has one primary action, one secondary action, and quiet tertiary actions.
3. **Scan-friendly density:** admin and seller screens favor compact rows and tables; public pages have more breathing room.
4. **Progressive disclosure:** show the next required decision first, with details available in expandable or secondary regions.
5. **Consistent semantics:** the same status, amount, error, and success states use the same visual treatment everywhere.
6. **Responsive by default:** layouts must work at mobile width without relying on hover or horizontal overflow for essential actions.
7. **Accessible defaults:** visible focus, keyboard-operable controls, semantic landmarks, labels, meaningful alt text, and non-color-only status communication.
8. **No business logic in visual primitives:** pricing, authorization, payment, and status rules stay in backend services or page controllers.

## 4. Brand Foundations

### 4.1 Color roles

Use semantic roles instead of inventing page-specific colors.

| Role | Current value | Use |
| --- | --- | --- |
| Brand 50 | `#eaf5f0` | Soft selected and success backgrounds |
| Brand 100 | `#cfe9dc` | Selected borders and light emphasis |
| Brand 300 | `#5fa886` | Secondary brand accents |
| Brand 500 | `#1c6b4f` | Primary buttons, links, active states |
| Brand 600 | `#17573f` | Hover and pressed states |
| Brand 700 | `#12503a` | Strong text and navigation emphasis |
| Brand 900 | `#0b2d20` | Footer, deep brand surfaces, high contrast areas |
| Accent 400 | `#f4b85c` | Soft highlights and price emphasis |
| Accent 500 | `#f2a93b` | Primary commerce CTA and attention state |
| Accent 600 | `#c98a22` | Accent hover and dark text-safe accent |
| Ink | `#14201b` | Primary text |
| Ink soft | `#4b564f` | Body and supporting text |
| Surface | `#f5f6f2` | Quiet panels and page bands |
| Border | `#e3e1d8` | Dividers and control borders |
| Danger | `#c1443a` | Destructive actions and blocking errors |

Status colors should be semantic and consistent:

- `pending`: amber
- `approved`, `completed`, `paid`, `released`: brand green
- `in_progress`, `processing`, `assigned`: blue
- `rejected`, `failed`, `cancelled`, `held`: red
- `out_of_stock`: neutral slate

### 4.2 Typography

- **Display and headings:** Space Grotesk, weight 500-700.
- **Body and controls:** Inter, weight 400-700.
- Avoid introducing another font family at page level.
- Use sentence case for labels and actions.
- Reserve large display sizes for public hero content; dashboards and panels use compact heading scales.

Suggested type scale:

| Token | Size | Use |
| --- | --- | --- |
| `display` | 3.75rem | Public hero only |
| `h1` | 2.25rem | Page title |
| `h2` | 1.5rem | Major section |
| `h3` | 1.125rem | Card or panel title |
| `body-lg` | 1.125rem | Introductory copy |
| `body` | 0.9375rem | Default body |
| `small` | 0.8125rem | Supporting metadata |
| `micro` | 0.6875rem | Compact status and table labels |

### 4.3 Shape, elevation, and motion

- Default control radius: 6px.
- Small cards and compact surfaces: 6-8px.
- Feature panels and grouped workflows: 10px.
- Avoid deeply nested cards; use page bands and one framed surface for a repeated tool.
- Use borders first, shadows second. Shadows should communicate elevation, not decoration.
- Motion should be short and purposeful: 150-300ms for controls, up to 700ms for image or hero transitions.
- Respect `prefers-reduced-motion` for transitions, carousels, and animated feedback.

## 5. Layout System

### Breakpoints

Use the existing breakpoint intent:

- `xs`: 480px
- `sm`: 640px
- `md`: 768px
- `lg`: 1024px

### Containers

- Public content: `max-w-7xl` with `px-4`.
- Reading content and terms: `max-w-3xl` or `max-w-4xl`.
- Admin and seller workspaces: `max-w-6xl` to `max-w-7xl`.
- Full-width bands may contain a constrained inner container but should not become floating decorative cards.

### Grid guidance

- Product browsing: 2 columns on small screens, 3-5 columns as space allows.
- Professional discovery: 1 column mobile, 2 columns tablet, 3 columns desktop.
- Admin KPI cards: 2 columns small screens, 4+ columns desktop.
- Operational lists: use stacked rows on mobile and tables only when the data remains readable.

## 6. Component Taxonomy

### Tier 1: Foundations

Owned by `base.html`, `custom.css`, and the future token layer:

- Color tokens
- Typography
- Spacing
- Breakpoints
- Radius and elevation
- Focus ring
- Icon sizing
- Motion and reduced-motion behavior

### Tier 2: Shared primitives

These should be reusable across all product areas:

- `Button`: primary, accent, outline, danger, ghost, disabled, loading.
- `IconButton`: icon-only action with `aria-label` and tooltip/title.
- `TextInput`, `Select`, `Textarea`, `SearchInput`.
- `Field`: label, control, hint, error.
- `Badge`: status, count, trust badge, category label.
- `Alert`: info, success, warning, error.
- `Card`: only for repeated items or framed tools.
- `Modal` and `Drawer`.
- `Tabs` and `SegmentedControl`.
- `Pagination` and `EmptyState`.
- `Money`: currency, amount, discount, fee, and total formatting.
- `StatusPill`: shared state vocabulary and colors.
- `DataTable`: responsive overflow, row actions, empty and loading states.
- `Skeleton`: loading placeholders for cards, rows, and detail views.

### Tier 3: Domain components

**Market**

- ProductCard
- ProductGallery
- PriceBlock
- CategoryStrip
- CartLineItem
- CheckoutSummary
- DeliveryQuote
- OrderStatusTimeline
- StoreSummary

**Handyman Hub**

- ProfessionalCard
- ProfessionalProfileSummary
- BookingRequestForm
- BookingStepper
- BookingPaymentSummary
- JobPhotoGrid
- ReviewComposer
- PayoutLedger

**Operations**

- KpiCard
- MonthlyKpiTable
- ApprovalQueue
- PaymentTrackingRow
- PayoutActionBar
- AdminSidebar
- SellerSidebar

### Tier 4: Page compositions

Pages should compose domain components and own only page-specific arrangement:

- Home
- Product listing and detail
- Cart and checkout
- Orders and payment callback
- Handyman directory, profile, request, bookings, tracker
- Seller overview, products, orders
- Professional overview and jobs
- Admin overview, approvals, requests, payments, reviews, users
- Authentication and legal pages

## 7. Navigation Architecture

### Primary navigation

The shared header owns global navigation. Its stable destinations are:

- Products
- Handyman Hub
- Search and categories
- Cart and wishlist where relevant
- Authenticated account menu

Do not duplicate global navigation inside individual pages. Add local navigation only for a workspace, such as seller or admin sections.

### Mobile navigation

The mobile drawer must expose the same primary destinations as desktop, including Products and Handyman Hub. Essential paths must not depend on hover dropdowns.

### Workspace navigation

- Seller navigation: Overview, Products, Orders.
- Professional navigation: profile and job management.
- Admin navigation: Overview, Stores, Products, Badges, Categories, Professionals, Service requests, Reviews, Payments, Accounts.

## 8. Interaction and State Contracts

Every async or stateful component should define these states:

1. Initial/loading
2. Ready
3. Empty
4. Validation error
5. Request error
6. Success confirmation
7. Disabled or unauthorized
8. Destructive confirmation where applicable

### Payments and money

Money values must be shown with:

- Currency code or symbol.
- Two decimal places.
- A line-item breakdown before confirmation.
- Separate base amount, platform commission, delivery fee, discount, and total where applicable.

For handyman bookings, the UI must distinguish:

- Agreed job amount.
- EraVenda service commission.
- Total seeker charge.
- Professional payout.

### Status

Status labels should come from a shared mapping rather than ad hoc text. Status must be communicated by label and color/icon, never color alone.

### Errors

- Inline validation belongs next to the invalid field.
- Network or server errors belong in an alert region near the affected workflow.
- Preserve entered form data where possible.
- Never expose raw stack traces or provider responses to customers.

## 9. Accessibility Contract

- Every form control has a visible label or an accessible name.
- Every icon-only button has `aria-label` and a tooltip/title where useful.
- `:focus-visible` remains visible with at least a 2px high-contrast outline.
- Modal and drawer focus is trapped and Escape closes it.
- Status badges include readable text.
- Tables have headings and remain usable on narrow screens.
- Images have meaningful alt text; decorative icons use `aria-hidden="true"`.
- Live payment, upload, and form messages use `aria-live` where appropriate.
- Do not use emoji as the only representation of a product or state.

## 10. File Ownership Rules

| Concern | Owner |
| --- | --- |
| Global shell | `frontend/templates/base.html` |
| Global navigation | `frontend/templates/components/header.html` |
| Global footer | `frontend/templates/components/footer.html` |
| Seller local navigation | `frontend/templates/components/seller-nav.html` |
| Shared CSS tokens and legacy primitives | `frontend/css/style.css` |
| Current Tailwind-era overrides | `frontend/static/css/custom.css` |
| API and auth client behavior | `frontend/static/js/main.js`, `frontend/static/js/config.js`, `frontend/js/api.js` |
| Page layout | Page template under `frontend/templates/` |
| Business rules | `backend/app/routers/`, service modules, and models |
| API contracts | `backend/app/schemas.py` |

Do not put business calculations in templates. Do not put page-specific styles into global CSS unless the rule is demonstrably reusable.

## 11. Recommended Implementation Direction

The project currently has no frontend build step, so the design system should evolve without requiring an immediate React or bundler migration.

### Phase 1: Establish canonical tokens

- Keep the values already defined in `base.html` and `style.css`.
- Move repeated values into one documented token source in `frontend/static/css/custom.css`.
- Keep Tailwind config values synchronized until the legacy layer is retired.
- Add semantic status tokens and focus/motion tokens.

### Phase 2: Normalize primitives

- Standardize button classes and control focus states.
- Standardize status pills, alerts, cards, inputs, and money blocks.
- Replace repeated inline variants in the most-used templates first: checkout, booking tracker, admin dashboard, seller dashboard.

### Phase 3: Extract domain components

- Extract repeated product cards and status/price blocks.
- Extract booking payment summary, ledger, stepper, and photo grid.
- Extract admin KPI cards and responsive tables.
- Keep Jinja includes or macros as the first extraction mechanism; do not introduce a new frontend framework solely for component reuse.

### Phase 4: Accessibility and visual regression

- Add keyboard checks for header, mobile drawer, tabs, forms, payment actions, and admin tables.
- Add screenshot checks at mobile and desktop widths for the public header, product listing, booking tracker, professional dashboard, and admin dashboard.
- Test dark theme separately if it remains a supported product mode.

### Phase 5: Governance

- Require new components to document purpose, states, variants, and owner.
- Prefer existing tokens and primitives over new one-off classes.
- Review changes to brand colors, typography, payment presentation, and status semantics as design-system changes.

## 12. Definition of Done for New UI

A new page or component is ready when:

- It uses the canonical fonts, colors, spacing, and radius values.
- It has loading, empty, error, success, and disabled states where relevant.
- It works at mobile and desktop widths.
- It is keyboard accessible and has visible focus.
- It uses semantic labels and readable status text.
- It does not duplicate global navigation or business logic.
- It has a clear owner and a reusable component boundary where repetition exists.
- Its money and payment information is explicit and auditable.
