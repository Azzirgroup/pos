"""Checks for the public shop at /shop.

    bench --site <site> execute cosmestics.setup.shop_check.run

Renders every kind of shop page through Frappe's own website router, and
builds a throwaway shade × size product family to prove the variant pickers —
this shop has no variants yet, so nothing else would exercise them. Everything
it creates is rolled back, and the cached snapshot is dropped either side so
the shop never serves a product that only existed during the check.
"""

import json
import re

import frappe
from frappe.utils import random_string

from cosmestics import shop
from cosmestics.setup.smoke import _Report


def run():
	r = _Report()
	try:
		shop.clear_snapshot()
		_names(r)
		_catalog(r)
		_pages(r)
		_variants(r)
	finally:
		frappe.db.rollback()
		shop.clear_snapshot()
		frappe.local.cosmestics_shop_snapshot = None
	return r.summary()


def _render(path) -> tuple[int, str, dict]:
	"""Render a shop URL the way a browser request would. The route rules
	(`/shop/p/<slug>`) are only evaluated against a live request, so one is
	built rather than calling the page modules directly."""
	from urllib.parse import parse_qsl

	from frappe.utils import set_request
	from frappe.website.serve import get_response

	path, _sep, qs = path.partition("?")
	set_request(method="GET", path=path, query_string=qs)
	frappe.local.form_dict = frappe._dict(parse_qsl(qs))
	frappe.flags.redirect_location = None
	resp = get_response(path.strip("/"))
	return resp.status_code, resp.get_data(as_text=True), dict(resp.headers)


def _names(r):
	cases = {
		"1L BODY SERUM": "1l Body Serum",
		"bio oil": "Bio Oil",
		"NIVEA COCOA BUTTER 400ML": "Nivea Cocoa Butter 400ml",
		"Peau Claire Body Cream 150 Ml": "Peau Claire Body Cream 150 Ml",
		# Cased by hand, however oddly — left alone.
		"shea butter AND honey": "shea butter AND honey",
		"ROSE AND HONEY SOAP": "Rose and Honey Soap",
	}
	for raw, want in cases.items():
		got = shop.display_name(raw)
		r.check(f"display name {raw!r}", got == want, got)
	r.check("slug", shop.slugify("Nice & Lovely body lotion 200ml") == "nice-and-lovely-body-lotion-200ml")


def _catalog(r):
	snap = shop.snapshot()
	products = snap["products"]
	listed = [products[c] for c in snap["listed"]]
	r.check("catalog lists something", listed, len(listed))
	r.check("no unpriced item listed", all(p["price"] > 0 for p in listed))
	r.check("no variant has its own card", not any(p["template"] for p in listed))
	r.check("every listed item has a photo on disk", all(shop._image_ok(p["image"]) for p in listed))
	r.check("a photo that is not on disk is refused", not shop._image_ok("/files/no-such-photo-anywhere.jpg"))
	r.check("a private photo is refused", not shop._image_ok("/private/files/x.jpg"))
	unlisted_groups = {c["key"] for c in snap["categories"]} - {p.get("cat") for p in listed}
	r.check("every category has a listed product", not unlisted_groups, unlisted_groups)

	slugs = [p["slug"] for p in products.values()]
	r.check("slugs are unique", len(slugs) == len(set(slugs)))

	# Same price the till would charge.
	from cosmestics.api.catalog import _prices

	p = listed[0]
	uom = frappe.db.get_value("Item", p["code"], "stock_uom")
	till = _prices([p["code"]], shop.shop_settings().price_list)
	r.check(
		"price matches the till's price list",
		p["price"] == (till.get((p["code"], uom)) or till.get((p["code"], None))),
		f"{p['code']}: {p['price']}",
	)

	keys = [c["key"] for c in snap["categories"]]
	r.check("merged categories are unique", len(keys) == len(set(keys)))


def _pages(r):
	snap = shop.snapshot()
	p = snap["products"][snap["listed"][0]]
	c = snap["categories"][0]

	pages = (
		"/shop",
		"/shop/catalog",
		"/shop/catalog?view=list&sort=price_asc&min=100&max=500&stock=1&page=2",
		"/shop/categories",
		f"/shop/c/{c['slug']}",
		f"/shop/p/{p['slug']}",
		"/shop/search?q=cream",
	)
	for path in pages:
		status, html, _h = _render(path)
		r.check(f"{path} renders", status == 200, status)
		has_canonical = 'rel="canonical"' in html or "search" in path
		r.check(f"{path} has a title and canonical", "<title>" in html and has_canonical)

	status, html, _h = _render(f"/shop/p/{p['slug']}")
	ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
	blocks = [json.loads(b) for b in ld]
	product = next((b for b in blocks if b.get("@type") == "Product"), None)
	r.check("product page carries schema.org Product", product and product["offers"]["price"] == p["price"])

	for path in ("/shop/p/no-such-thing", "/shop/c/no-such-thing"):
		status, _html, _h = _render(path)
		r.check(f"{path} is a 404", status == 404, status)

	status, html, _h = _render('/shop/search?q="><script>alert(1)</script>')
	r.check("search query is escaped", "<script>alert(1)" not in html and "&lt;script&gt;" in html)
	status, html, _h = _render("/shop/search?q=cream")
	r.check("search results are noindex", 'content="noindex' in html)

	status, html, _h = _render("/shop/catalog?sort=price_asc")
	r.check("a sorted catalog is noindex", 'content="noindex' in html)
	status, html, _h = _render("/shop/catalog")
	r.check("the plain catalog is indexable", 'content="noindex' not in html)

	status, html, _h = _render(f"/shop/c/{c['slug']}?min=100&max=500&stock=1")
	r.check("filtered category renders", status == 200, status)
	r.check("active filters show as removable chips", html.count('class="chip-x"') == 3, html.count('class="chip-x"'))
	r.check("category links keep the price filter", "min=100&amp;max=500" in html.split('class="cat-list"')[1][:4000])
	status, html, _h = _render("/shop/catalog?min=900&max=100")
	r.check("a reversed price range is read the right way round", status == 200 and "chip-x" in html)

	hits = shop.suggest("cream")
	r.check("header suggestions answer", 0 < len(hits) <= 6 and all(h["url"].startswith("/shop/p/") for h in hits))
	r.check("suggestions for nonsense are empty", shop.suggest("zzqqxxnothing") == [])

	depts = shop.departments()
	placed = sum(len(d["categories"]) for d in depts)
	r.check("every category sits in exactly one department", placed == len(shop.categories()), placed)

	status, xml, headers = _render("/shop/sitemap.xml")
	kind = headers.get("Content-Type", "")
	r.check("sitemap is XML", status == 200 and "xml" in kind, kind)
	r.check("sitemap lists the product", f"/shop/p/{p['slug']}</loc>" in xml)

	# A hashed slug for an item with a clean one redirects to the clean one.
	if p["slug"] != p["hslug"]:
		status, _html, headers = _render(f"/shop/p/{p['hslug']}")
		to = headers.get("Location", "")
		r.check("hashed slug redirects to the clean one", status == 301 and to.endswith(p["slug"]), to)


def _variants(r):
	tag = random_string(5).lower()
	shade, size = f"Shade {tag}", f"Size {tag}"
	for attr, values in ((shade, ["Nude", "Cocoa"]), (size, ["30ml", "50ml"])):
		frappe.get_doc(
			{
				"doctype": "Item Attribute",
				"attribute_name": attr,
				"item_attribute_values": [{"attribute_value": v, "abbr": v[:3].upper()} for v in values],
			}
		).insert(ignore_permissions=True)

	group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	template = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": f"Shop Check Foundation {tag}",
			"item_name": f"Shop Check Foundation {tag}",
			"item_group": group,
			"stock_uom": "Nos" if frappe.db.exists("UOM", "Nos") else frappe.db.get_value("UOM", {}, "name"),
			"is_stock_item": 1,
			"has_variants": 1,
			"attributes": [{"attribute": shade}, {"attribute": size}],
		}
	).insert(ignore_permissions=True)

	from erpnext.controllers.item_variant import create_variant

	price_list = shop.shop_settings().price_list
	# The shop only lists items whose photo exists, so the family borrows one.
	photo = shop.snapshot()["products"][shop.snapshot()["listed"][0]]["image"]
	combos = {("Nude", "30ml"): 900, ("Nude", "50ml"): 1400, ("Cocoa", "30ml"): 950}
	codes = {}
	for (s, z), rate in combos.items():
		v = create_variant(template.name, {shade: s, size: z})
		v.item_code = f"{template.name}-{s}-{z}"
		v.image = photo
		v.insert(ignore_permissions=True)
		codes[(s, z)] = v.name
		frappe.get_doc(
			{"doctype": "Item Price", "item_code": v.name, "price_list": price_list, "price_list_rate": rate}
		).insert(ignore_permissions=True)

	shop.clear_snapshot()
	frappe.local.cosmestics_shop_snapshot = None
	snap = shop.snapshot()
	products = snap["products"]
	t = products.get(template.name)

	r.check("template is listed once", template.name in snap["listed"])
	r.check("variants are not listed", not any(c in snap["listed"] for c in codes.values()))
	r.check(
		"template shows the price range",
		t and t["price"] == 900 and t.get("price_max") == 1400,
		t and (t["price"], t.get("price_max")),
	)

	nude30 = products[codes[("Nude", "30ml")]]
	picks = {c["attribute"]: c["options"] for c in shop.choices(nude30)}
	sizes = {o["value"]: o for o in picks[size]}
	shades = {o["value"]: o for o in picks[shade]}
	r.check("current choice is selected", sizes["30ml"]["selected"] and shades["Nude"]["selected"])
	r.check(
		"picking a size keeps the shade",
		sizes["50ml"]["url"] == shop.product_url(products[codes[("Nude", "50ml")]]),
	)
	r.check(
		"a combination that does not exist falls back to one that does",
		shop.product_url(products[codes[("Cocoa", "30ml")]]) == shades["Cocoa"]["url"],
	)

	status, html, _h = _render(shop.product_url(t))
	r.check("family page renders its pickers", status == 200 and "Nude" in html and "50ml" in html)
	r.check("family page asks for a choice before ordering", "Choose" in html)
	status, html, _h = _render(shop.product_url(nude30))
	r.check("variant page renders with its own price", status == 200 and "KES 900" in html)
