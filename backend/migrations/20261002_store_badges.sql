-- Lets admins apply publicity/trust badges to a seller's store, the same way
-- products and service professionals already get them (see BADGE_CATALOG in
-- routers/admin.py). A store's badges are shown on its store page and
-- propagate onto every one of its products, alongside that product's own
-- badges — see page_context() usage in main.py and the product card
-- templates for where they're merged in.
ALTER TABLE stores ADD COLUMN IF NOT EXISTS badge_keys JSON;
