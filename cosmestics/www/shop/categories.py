"""/shop/categories — the phones' category browser, as on PLM: departments
down a rail on the left, the chosen one's categories as tiles on the right."""

import frappe

from cosmestics import shop

no_cache = 1
sitemap = 0


def get_context(context):
	depts = shop.departments()
	active = next((d for d in depts if d["slug"] == frappe.form_dict.cat), depts[0] if depts else None)
	shop.base_context(
		context,
		title="Categories",
		description=f"Browse every product category at {shop.shop_settings().name}.",
		# ?cat= only changes which department is open; it is one page.
		canonical="/shop/categories",
	)
	context.departments = depts
	context.active = active
	context.tiles = [_tile(c) for c in active["categories"]] if active else []
	context.tab = "categories"
	return context


def _tile(c) -> dict:
	"""A category tile, pictured with its best seller's photo when it has one."""
	return {**c, "image": shop.category_image(c["key"])}
