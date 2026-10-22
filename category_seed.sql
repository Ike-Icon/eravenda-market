BEGIN;

-- 1. Main (parent) categories
INSERT INTO public.categories (id, name, slug, parent_id, icon_url, created_at) VALUES
  (gen_random_uuid(), 'Electronics & Gadgets', 'electronics-gadgets', NULL, 'laptop', NOW()),
  (gen_random_uuid(), 'Fashion & Apparel', 'fashion-apparel', NULL, 'shirt', NOW()),
  (gen_random_uuid(), 'Home, Kitchen & Living', 'home-kitchen-living', NULL, 'home', NOW()),
  (gen_random_uuid(), 'Health, Beauty & Personal Care', 'health-beauty-personal-care', NULL, 'sparkles', NOW()),
  (gen_random_uuid(), 'Groceries & Essentials', 'groceries-essentials', NULL, 'shopping-bag', NOW()),
  (gen_random_uuid(), 'Sports, Outdoor & Fitness', 'sports-outdoor-fitness', NULL, 'activity', NOW()),
  (gen_random_uuid(), 'Toys, Kids & Baby', 'toys-kids-baby', NULL, 'baby', NOW()),
  (gen_random_uuid(), 'Automotive & Tools', 'automotive-tools', NULL, 'wrench', NOW());

-- 2. Subcategories — each looks up its parent's id from the table directly,
--    now that step 1 has actually committed those rows within this transaction.
INSERT INTO public.categories (id, name, slug, parent_id, icon_url, created_at) VALUES
  -- Electronics & Gadgets
  (gen_random_uuid(), 'Mobile & Accessories', 'mobile-accessories', (SELECT id FROM categories WHERE slug = 'electronics-gadgets'), '/static/img/categories/mobile-accessories.svg', NOW()),
  (gen_random_uuid(), 'Computers & Office', 'computers-office', (SELECT id FROM categories WHERE slug = 'electronics-gadgets'), '/static/img/categories/computers-office.svg', NOW()),
  (gen_random_uuid(), 'Audio & Wearables', 'audio-wearables', (SELECT id FROM categories WHERE slug = 'electronics-gadgets'), '/static/img/categories/audio-wearables.svg', NOW()),
  (gen_random_uuid(), 'Home Entertainment', 'home-entertainment', (SELECT id FROM categories WHERE slug = 'electronics-gadgets'), '/static/img/categories/home-entertainment.svg', NOW()),

  -- Fashion & Apparel
  (gen_random_uuid(), 'Men''s Wear', 'mens-wear', (SELECT id FROM categories WHERE slug = 'fashion-apparel'), '/static/img/categories/mens-wear.svg', NOW()),
  (gen_random_uuid(), 'Women''s Wear', 'womens-wear', (SELECT id FROM categories WHERE slug = 'fashion-apparel'), '/static/img/categories/womens-wear.svg', NOW()),
  (gen_random_uuid(), 'Footwear', 'footwear', (SELECT id FROM categories WHERE slug = 'fashion-apparel'), '/static/img/categories/footwear.svg', NOW()),
  (gen_random_uuid(), 'Bags & Accessories', 'bags-accessories', (SELECT id FROM categories WHERE slug = 'fashion-apparel'), '/static/img/categories/bags-accessories.svg', NOW()),

  -- Home, Kitchen & Living
  (gen_random_uuid(), 'Furniture', 'furniture', (SELECT id FROM categories WHERE slug = 'home-kitchen-living'), '/static/img/categories/furniture.svg', NOW()),
  (gen_random_uuid(), 'Kitchen & Dining', 'kitchen-dining', (SELECT id FROM categories WHERE slug = 'home-kitchen-living'), '/static/img/categories/kitchen-dining.svg', NOW()),
  (gen_random_uuid(), 'Home Decor', 'home-decor', (SELECT id FROM categories WHERE slug = 'home-kitchen-living'), '/static/img/categories/home-decor.svg', NOW()),
  (gen_random_uuid(), 'Bedding & Bath', 'bedding-bath', (SELECT id FROM categories WHERE slug = 'home-kitchen-living'), '/static/img/categories/bedding-bath.svg', NOW()),
  (gen_random_uuid(), 'Cleaning Supplies', 'cleaning-supplies', (SELECT id FROM categories WHERE slug = 'home-kitchen-living'), '/static/img/categories/cleaning-supplies.svg', NOW()),

  -- Health, Beauty & Personal Care
  (gen_random_uuid(), 'Skincare', 'skincare', (SELECT id FROM categories WHERE slug = 'health-beauty-personal-care'), '/static/img/categories/skincare.svg', NOW()),
  (gen_random_uuid(), 'Haircare', 'haircare', (SELECT id FROM categories WHERE slug = 'health-beauty-personal-care'), '/static/img/categories/haircare.svg', NOW()),
  (gen_random_uuid(), 'Makeup & Cosmetics', 'makeup-cosmetics', (SELECT id FROM categories WHERE slug = 'health-beauty-personal-care'), '/static/img/categories/makeup-cosmetics.svg', NOW()),
  (gen_random_uuid(), 'Personal Care', 'personal-care', (SELECT id FROM categories WHERE slug = 'health-beauty-personal-care'), '/static/img/categories/personal-care.svg', NOW()),

  -- Groceries & Essentials
  (gen_random_uuid(), 'Packaged Foods', 'packaged-foods', (SELECT id FROM categories WHERE slug = 'groceries-essentials'), '/static/img/categories/packaged-foods.svg', NOW()),
  (gen_random_uuid(), 'Beverages', 'beverages', (SELECT id FROM categories WHERE slug = 'groceries-essentials'), '/static/img/categories/beverages.svg', NOW()),
  (gen_random_uuid(), 'Household Supplies', 'household-supplies', (SELECT id FROM categories WHERE slug = 'groceries-essentials'), '/static/img/categories/household-supplies.svg', NOW()),

  -- Sports, Outdoor & Fitness
  (gen_random_uuid(), 'Fitness & Exercise', 'fitness-exercise', (SELECT id FROM categories WHERE slug = 'sports-outdoor-fitness'), '/static/img/categories/fitness-exercise.svg', NOW()),
  (gen_random_uuid(), 'Outdoor Gear', 'outdoor-gear', (SELECT id FROM categories WHERE slug = 'sports-outdoor-fitness'), '/static/img/categories/outdoor-gear.svg', NOW()),
  (gen_random_uuid(), 'Sports Equipment', 'sports-equipment', (SELECT id FROM categories WHERE slug = 'sports-outdoor-fitness'), '/static/img/categories/sports-equipment.svg', NOW()),

  -- Toys, Kids & Baby
  (gen_random_uuid(), 'Baby Care', 'baby-care', (SELECT id FROM categories WHERE slug = 'toys-kids-baby'), '/static/img/categories/baby-care.svg', NOW()),
  (gen_random_uuid(), 'Toys & Games', 'toys-games', (SELECT id FROM categories WHERE slug = 'toys-kids-baby'), '/static/img/categories/toys-games.svg', NOW()),

  -- Automotive & Tools
  (gen_random_uuid(), 'Auto Accessories', 'auto-accessories', (SELECT id FROM categories WHERE slug = 'automotive-tools'), '/static/img/categories/auto-accessories.svg', NOW()),
  (gen_random_uuid(), 'Tools & Home Improvement', 'tools-home-improvement', (SELECT id FROM categories WHERE slug = 'automotive-tools'), '/static/img/categories/tools-home-improvement.svg', NOW());

COMMIT;
