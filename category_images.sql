BEGIN;

-- Sets an illustrated image for each of the 27 sub-categories (matched by slug, safe to re-run).
UPDATE public.categories SET icon_url = '/static/img/categories/audio-wearables.png' WHERE slug = 'audio-wearables';
UPDATE public.categories SET icon_url = '/static/img/categories/auto-accessories.png' WHERE slug = 'auto-accessories';
UPDATE public.categories SET icon_url = '/static/img/categories/baby-care.png' WHERE slug = 'baby-care';
UPDATE public.categories SET icon_url = '/static/img/categories/bags-accessories.png' WHERE slug = 'bags-accessories';
UPDATE public.categories SET icon_url = '/static/img/categories/bedding-bath.png' WHERE slug = 'bedding-bath';
UPDATE public.categories SET icon_url = '/static/img/categories/beverages.png' WHERE slug = 'beverages';
UPDATE public.categories SET icon_url = '/static/img/categories/cleaning-supplies.png' WHERE slug = 'cleaning-supplies';
UPDATE public.categories SET icon_url = '/static/img/categories/computers-office.png' WHERE slug = 'computers-office';
UPDATE public.categories SET icon_url = '/static/img/categories/fitness-exercise.png' WHERE slug = 'fitness-exercise';
UPDATE public.categories SET icon_url = '/static/img/categories/footwear.png' WHERE slug = 'footwear';
UPDATE public.categories SET icon_url = '/static/img/categories/furniture.png' WHERE slug = 'furniture';
UPDATE public.categories SET icon_url = '/static/img/categories/haircare.png' WHERE slug = 'haircare';
UPDATE public.categories SET icon_url = '/static/img/categories/home-decor.png' WHERE slug = 'home-decor';
UPDATE public.categories SET icon_url = '/static/img/categories/home-entertainment.png' WHERE slug = 'home-entertainment';
UPDATE public.categories SET icon_url = '/static/img/categories/household-supplies.png' WHERE slug = 'household-supplies';
UPDATE public.categories SET icon_url = '/static/img/categories/kitchen-dining.png' WHERE slug = 'kitchen-dining';
UPDATE public.categories SET icon_url = '/static/img/categories/makeup-cosmetics.png' WHERE slug = 'makeup-cosmetics';
UPDATE public.categories SET icon_url = '/static/img/categories/mens-wear.png' WHERE slug = 'mens-wear';
UPDATE public.categories SET icon_url = '/static/img/categories/mobile-accessories.png' WHERE slug = 'mobile-accessories';
UPDATE public.categories SET icon_url = '/static/img/categories/outdoor-gear.png' WHERE slug = 'outdoor-gear';
UPDATE public.categories SET icon_url = '/static/img/categories/packaged-foods.png' WHERE slug = 'packaged-foods';
UPDATE public.categories SET icon_url = '/static/img/categories/personal-care.png' WHERE slug = 'personal-care';
UPDATE public.categories SET icon_url = '/static/img/categories/skincare.png' WHERE slug = 'skincare';
UPDATE public.categories SET icon_url = '/static/img/categories/sports-equipment.png' WHERE slug = 'sports-equipment';
UPDATE public.categories SET icon_url = '/static/img/categories/tools-home-improvement.png' WHERE slug = 'tools-home-improvement';
UPDATE public.categories SET icon_url = '/static/img/categories/toys-games.png' WHERE slug = 'toys-games';
UPDATE public.categories SET icon_url = '/static/img/categories/womens-wear.png' WHERE slug = 'womens-wear';

COMMIT;
