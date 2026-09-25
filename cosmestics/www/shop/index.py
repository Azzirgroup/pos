"""/shop — the front page: a hero with a collage of best sellers, the
promise strip, round category pictures, then product sliders — best
sellers, new arrivals and the busiest categories — around a contact banner."""

from cosmestics import shop

no_cache = 1
sitemap = 0  # Listed by /shop/sitemap.xml with everything else in the shop.

#: Category rows under Best Sellers and New Arrivals, busiest first.
HOME_ROWS = 6
#: A category needs this many products to earn a row of its own.
MIN_ROW = 4

TRUST = (
	("shield", "Genuine Products", "Original & trusted"),
	("headset", "Expert Support", "Professional help"),
	("truck", "Fast Delivery", "Quick & secure"),
	("percent", "Best Value", "Competitive prices"),
)


def get_context(context):
	snap = shop.snapshot()
	settings = shop.shop_settings()
	total = len(snap["listed"])

	shop.base_context(
		context,
		title=settings.name,
		description=settings.tagline
		or f"Shop {total:,} genuine beauty and personal care products from {settings.name} in Kenya. "
		"Live prices and stock, order on WhatsApp.",
		canonical="/shop",
	)
	context.tab = "home"
	context.total = total
	context.headline = settings.tagline or "Beauty & Personal Care, Delivered"
	context.subtitle = settings.subtitle or (
		"Genuine skin, body and hair care, fragrance and wellness - "
		"at the same prices as our shop counter."
	)
	context.trust = TRUST
	context.hero_products = [shop.card(p) for p in shop.hero_products()]
	context.in_stock = sum(1 for c in snap["listed"] if snap["products"][c]["qty"] > 0)
	context.circles = [
		{**c, "image": shop.category_image(c["key"])} for c in snap["categories"]
	]
	rows = []
	best = shop.best_sellers()
	if best:
		rows.append({"title": "Best Sellers", "url": "/shop/catalog",
			"cards": [shop.card(p) for p in best], "eager": True})
	rows.append({"title": "New Arrivals", "url": "/shop/catalog?sort=new",
		"cards": [shop.card(p) for p in shop.new_arrivals()], "eager": not best})
	for c in snap["categories"]:
		if len(rows) >= HOME_ROWS + 2:
			break
		if c["count"] < MIN_ROW:
			continue
		rows.append({"title": c["label"], "url": shop.category_url(c),
			"cards": [shop.card(p) for p in shop.sort_products(shop.in_category(c["key"]))[:12]]})
	# The first rows sit above the banner, the rest below it.
	context.rows_top, context.rows_bottom = rows[:3], rows[3:]
	context.json_ld = [
		{
			"@context": "https://schema.org",
			"@type": "WebSite",
			"name": settings.name,
			"url": shop.absolute("/shop"),
			"potentialAction": {
				"@type": "SearchAction",
				"target": shop.absolute("/shop/search") + "?q={search_term_string}",
				"query-input": "required name=search_term_string",
			},
		},
		_organization(settings),
	]
	return context


def _organization(settings) -> dict:
	org = {"@context": "https://schema.org", "@type": "Store", "name": settings.name, "url": shop.absolute("/shop")}
	if settings.phone:
		org["telephone"] = settings.phone
	if settings.email:
		org["email"] = settings.email
	same = [u for u in (settings.facebook, settings.instagram) if u]
	if same:
		org["sameAs"] = same
	return org
