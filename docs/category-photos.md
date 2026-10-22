# Real photos for the 27 category tiles

Each tile is a circle, so pick photos where the subject sits in the middle and has space around it.
Name each file by its slug, put them all in one folder, then run:

    python tools/prepare_category_photos.py ~/Downloads/category-photos

The script crops to a square, resizes to 480x480 and overwrites the matching PNG in
`frontend/static/img/categories/`. No database change is needed, because the paths stay the same.
Any category without a photo keeps its current image.

## Where to download
Pexels (pexels.com), Unsplash (unsplash.com) and Burst (burst.shopify.com). All three allow free commercial use.
Avoid Alamy, Adobe Stock, Envato and Google Images results. Those are paid or restricted.
Before you download, check the licence line on each photo page.

## Photo brief
Real photography, one clear subject, natural light, plain or lightly blurred background.
Landscape photos are fine because the script crops the centre. No logos, no visible faces, no text overlays.

| File name (slug) | Search for |
|---|---|
| mobile-accessories | phone with charger cable and earbuds on table |
| computers-office | laptop on desk with notebook |
| audio-wearables | headphones and smartwatch |
| home-entertainment | television in living room |
| mens-wear | folded men's shirts |
| womens-wear | women's dresses on rail |
| footwear | sneakers on neutral background |
| bags-accessories | leather handbag |
| furniture | sofa in living room |
| kitchen-dining | cookware pots and pans kitchen |
| home-decor | vase with plant shelf decor |
| bedding-bath | made bed white linen |
| cleaning-supplies | cleaning spray bottles and sponge |
| skincare | skincare bottles and cream jar |
| haircare | shampoo bottles hair products |
| makeup-cosmetics | lipstick and makeup brushes |
| personal-care | toothbrush soap towel bathroom |
| packaged-foods | packaged food pantry shelf |
| beverages | bottled drinks juice water |
| household-supplies | laundry detergent and toilet paper |
| fitness-exercise | dumbbells and yoga mat |
| outdoor-gear | tent camping outdoors |
| sports-equipment | soccer ball on grass |
| baby-care | baby bottle and baby clothes |
| toys-games | wooden toys building blocks |
| auto-accessories | car interior steering wheel |
| tools-home-improvement | hand tools hammer drill on workbench |
