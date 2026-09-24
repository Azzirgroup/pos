"""/shop/c/<slug> — one category, on the catalog layout."""

import frappe

from cosmestics import shop

no_cache = 1
sitemap = 0


def get_context(context):
	c = shop.category_by_slug(frappe.form_dict.slug or "")
	if not c:
		raise frappe.PageDoesNotExistError

	path = shop.category_url(c)
	shop.base_context(
		context,
		title=c["label"],
		description=f"Shop {c['count']} {c['label'].lower()} products at {shop.shop_settings().name}. "
		"Genuine products, live prices and stock, order on WhatsApp.",
	)
	page = shop.listing_context(
		context, codes=shop.in_category(c["key"]), path=path, title=c["label"], category=c
	)
	if page.page > 1:
		context.page_title = f"{c['label']} - page {page.page} · {context.shop.name}"
	# One canonical per page of the default view, so Google indexes each
	# category once rather than once per sort order or filter.
	context.canonical = shop.absolute(shop.listing_url(path, page=page.page))
	listing = context.listing
	context.noindex = bool(listing.stock or listing.min or listing.max or listing.sort != "popular" or listing.view == "list")
	context.category = c
	context.active_category = c["key"]
	context.tab = "shop"
	context.json_ld = [
		{
			"@context": "https://schema.org",
			"@type": "BreadcrumbList",
			"itemListElement": [
				{"@type": "ListItem", "position": 1, "name": "Shop", "item": shop.absolute("/shop")},
				{"@type": "ListItem", "position": 2, "name": c["label"], "item": shop.absolute(path)},
			],
		}
	]
	return context
