"""/shop/sitemap.xml — every shop page a search engine should know about.

Frappe's own /sitemap.xml only lists static pages and web-view doctypes, so it
can never see a product: they live behind a route rule. Submit this one to
Google Search Console, and name it in robots.txt (Website Settings).
"""

from frappe.utils import nowdate

from cosmestics import shop

no_cache = 1
sitemap = 0
base_template_path = "www/shop/sitemap.xml"


def get_context(context):
	snap = shop.snapshot()
	today = nowdate()
	links = [
		{"loc": shop.absolute(path), "lastmod": today}
		for path in ("/shop", "/shop/catalog", "/shop/categories")
	]
	links += [{"loc": shop.absolute(shop.category_url(c)), "lastmod": today} for c in snap["categories"]]

	listed = set(snap["listed"])
	for code, p in snap["products"].items():
		# Listed products and their variants; each variant is its own page.
		if code in listed or p.get("template") in listed:
			links.append({"loc": shop.absolute(shop.product_url(p)), "lastmod": today})

	context.links = links
	return context
