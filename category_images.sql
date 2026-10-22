BEGIN;

-- Sets an illustrated image for each of the 27 sub-categories (matched by slug, safe to re-run).
UPDATE public.categories SET icon_url = '/static/img/categories/audio-wearables.svg' WHERE slug = 'audio-wearables';
UPDATE public.categories SET icon_url = '/static/img/categories/auto-accessories.svg' WHERE slug = 'auto-accessories';
UPDATE public.categories SET icon_url = '/static/img/categories/baby-care.svg' WHERE slug = 'baby-care';
UPDATE public.categories SET icon_url = '/static/img/categories/bags-accessories.svg' WHERE slug = 'bags-accessories';
UPDATE public.categories SET icon_url = '/static/img/categories/bedding-bath.svg' WHERE slug = 'bedding-bath';
UPDATE public.categories SET icon_url = '/static/img/categories/beverages.svg' WHERE slug = 'beverages';
UPDATE public.categories SET icon_url = '/static/img/categories/cleaning-supplies.svg' WHERE slug = 'cleaning-supplies';
UPDATE public.categories SET icon_url = '/static/img/categories/computers-office.svg' WHERE slug = 'computers-office';
UPDATE public.categories SET icon_url = '/static/img/categories/fitness-exercise.svg' WHERE slug = 'fitness-exercise';
UPDATE public.categories SET icon_url = '/static/img/categories/footwear.svg' WHERE slug = 'footwear';
UPDATE public.categories SET icon_url = '/static/img/categories/furniture.svg' WHERE slug = 'furniture';
UPDATE public.categories SET icon_url = '/static/img/categories/haircare.svg' WHERE slug = 'haircare';
UPDATE public.categories SET icon_url = '/static/img/categories/home-decor.svg' WHERE slug = 'home-decor';
UPDATE public.categories SET icon_url = '/static/img/categories/home-entertainment.svg' WHERE slug = 'home-entertainment';
UPDATE public.categories SET icon_url = '/static/img/categories/household-supplies.svg' WHERE slug = 'household-supplies';
UPDATE public.categories SET icon_url = '/static/img/categories/kitchen-dining.svg' WHERE slug = 'kitchen-dining';
UPDATE public.categories SET icon_url = '/static/img/categories/makeup-cosmetics.svg' WHERE slug = 'makeup-cosmetics';
UPDATE public.categories SET icon_url = '/static/img/categories/mens-wear.svg' WHERE slug = 'mens-wear';
UPDATE public.categories SET icon_url = '/static/img/categories/mobile-accessories.svg' WHERE slug = 'mobile-accessories';
UPDATE public.categories SET icon_url = '/static/img/categories/outdoor-gear.svg' WHERE slug = 'outdoor-gear';
UPDATE public.categories SET icon_url = '/static/img/categories/packaged-foods.svg' WHERE slug = 'packaged-foods';
UPDATE public.categories SET icon_url = '/static/img/categories/personal-care.svg' WHERE slug = 'personal-care';
UPDATE public.categories SET icon_url = '/static/img/categories/skincare.svg' WHERE slug = 'skincare';
UPDATE public.categories SET icon_url = '/static/img/categories/sports-equipment.svg' WHERE slug = 'sports-equipment';
UPDATE public.categories SET icon_url = '/static/img/categories/tools-home-improvement.svg' WHERE slug = 'tools-home-improvement';
UPDATE public.categories SET icon_url = '/static/img/categories/toys-games.svg' WHERE slug = 'toys-games';
UPDATE public.categories SET icon_url = '/static/img/categories/womens-wear.svg' WHERE slug = 'womens-wear';

COMMIT;
