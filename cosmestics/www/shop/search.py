"""/shop/search?q= — search results on the catalog layout.

With no query it is the phones' Search tab: a search box and the busiest
categories. Never indexed: every query is a different page, and letting
Google crawl them would fill the index with thin copies of the categories.
"""

import frappe

from cosmestics import shop

no_cache = 1
sitemap = 0


def get_context(context):
	q = (frappe.form_dict.q or "").strip()[:100]
	shop.base_context(context, title=f"“{q}”" if q else "Search", noindex=True)
	context.query = q
	context.tab = "search"
	if q:
		shop.listing_context(
			context, codes=shop.search(q), path="/shop/search", title="Search results", q=q, relevance=True
		)
	context.suggestions = [{**c, "image": shop.category_image(c["key"])} for c in shop.categories()[:12]]
	return context
