"""/shop/p/<slug> — one product, or one shade / size of a product."""

import frappe
from frappe.utils import strip_html

from cosmestics import shop

no_cache = 1
sitemap = 0


def get_context(context):
	code, canonical = shop.resolve_slug(frappe.form_dict.slug or "")
	if not code:
		raise frappe.PageDoesNotExistError

	snap = shop.snapshot()
	p = snap["products"][code]
	url = shop.product_url(p)
	if not canonical:
		# An old or hashed link to an item that now has a cleaner one.
		frappe.flags.redirect_location = url
		raise frappe.Redirect(301)

	root = shop.products_family_root(p)
	is_family_page = p is root and bool(root.get("variants"))
	name = p["name"]
	image = p["image"] or root["image"]
	status = shop.stock_status(p["qty"])
	category = next((c for c in snap["categories"] if c["key"] == root.get("cat")), None)

	if is_family_page and root.get("price_max", 0) > root["price"]:
		price = f"{shop.money(root['price'])} - {shop.money(root['price_max'])}"
	else:
		price = shop.money(p["price"])

	desc_html = shop.description(p["code"]) or (shop.description(root["code"]) if root is not p else "")
	desc_text = strip_html(desc_html or "").strip()
	meta = (
		desc_text
		or f"Buy {name} at {shop.shop_settings().name} for {price}. {status['label']}."
	)

	shop.base_context(context, title=name, description=meta, canonical=url)
	context.p = p
	context.name = name
	context.image = image
	context.card = shop.card(p)
	context.price = price
	context.status = status
	context.category = category
	context.active_category = root.get("cat")
	context.choices = shop.choices(p)
	context.is_family_page = is_family_page
	context.description_html = desc_html
	context.whatsapp = "" if is_family_page else shop.whatsapp_link(p, shop.absolute(url))
	# What a customer can actually buy online right now (net of paid orders
	# and other shoppers' held carts). The shop app refreshes it live.
	from cosmestics.online_orders import available

	context.available = 0 if is_family_page else available([p["code"]]).get(p["code"], 0)
	context.related = [shop.card(x) for x in shop.related(p)]
	context.share = shop.share_links(shop.absolute(url), name)
	context.specs = _specs(p, category, status)
	context.tab = "shop"
	context.og_type = "product"
	context.og_image = shop.absolute(image) if image else ""
	context.json_ld = _json_ld(
		p, root, name, image, desc_text, category, snap["currency"], url, is_family_page
	)
	return context


def _specs(p, category, status) -> list:
	"""The Specifications table. Built from what ERPNext actually knows about
	the item — nothing here is invented to fill the table out."""
	rows = []
	if category:
		rows.append(("Category", category["label"]))
	rows += [(attr, value) for attr, value in p["attrs"]]
	rows.append(("Availability", status["label"]))
	rows.append(("Product code", p["code"]))
	return rows


def _json_ld(p, root, name, image, desc, category, currency, url, is_family_page) -> list:
	"""schema.org Product, which is what puts price and stock under the result
	in Google. A family page offers a price range; a single item its price."""
	products = shop.snapshot()["products"]
	availability = "https://schema.org/InStock" if p["qty"] > 0 else "https://schema.org/OutOfStock"
	if is_family_page:
		offers = {
			"@type": "AggregateOffer",
			"priceCurrency": currency,
			"lowPrice": root["price"],
			"highPrice": root.get("price_max") or root["price"],
			"offerCount": len(root["variants"]),
			"availability": availability,
		}
	else:
		offers = {
			"@type": "Offer",
			"priceCurrency": currency,
			"price": p["price"],
			"availability": availability,
			"url": shop.absolute(url),
			"itemCondition": "https://schema.org/NewCondition",
		}

	product = {
		"@context": "https://schema.org",
		"@type": "Product",
		"name": name,
		"sku": p["code"],
		"offers": offers,
	}
	if image:
		product["image"] = [shop.absolute(image)]
	if desc:
		product["description"] = desc[:5000]
	if category:
		product["category"] = category["label"]
	if root is not p:
		product["isVariantOf"] = {
			"@type": "ProductGroup",
			"name": root["name"],
			"productGroupID": root["code"],
		}

	crumbs = [{"@type": "ListItem", "position": 1, "name": "Shop", "item": shop.absolute("/shop")}]
	if category:
		crumbs.append(
			{
				"@type": "ListItem",
				"position": 2,
				"name": category["label"],
				"item": shop.absolute(shop.category_url(category)),
			}
		)
	crumbs.append(
		{"@type": "ListItem", "position": len(crumbs) + 1, "name": name, "item": shop.absolute(url)}
	)

	return [product, {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": crumbs}]
