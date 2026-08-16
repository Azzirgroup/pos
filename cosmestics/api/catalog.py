"""The sellable catalog, served to the till in one call.

Deliberately one request, not one per item: the POS holds the whole catalog in
memory and searches it locally, because a keystroke-per-request search is the
single biggest cause of a sluggish till.

Everything is batched into four queries regardless of catalog size — items,
prices, stock, barcodes — rather than N+1 per item.
"""

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_catalog():
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	# The same warehouse the sale will draw from, so a stock figure on a card is
	# never a count of somewhere else's shelf.
	from cosmestics.api.pos import selling_warehouse

	warehouse = selling_warehouse()
	price_list = settings.selling_price_list or frappe.db.get_value(
		"Price List", {"selling": 1, "enabled": 1}, "name"
	)

	items = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1},
		fields=[
			"name as item_code",
			"item_name",
			"item_group",
			"brand",
			"stock_uom",
			"has_batch_no",
			"has_serial_no",
			"image",
		],
		limit_page_length=0,
		order_by="item_name asc",
	)
	if not items:
		return {"items": [], "categories": [], "warehouses": [], "neighbours": [], "empty": True}

	codes = [i.item_code for i in items]

	prices = _prices(codes, price_list)
	stock = _stock(codes, warehouse)
	barcodes = _barcodes(codes)
	stock_uoms = {i.item_code: i.stock_uom for i in items}
	uoms = _sellable_uoms(codes, stock_uoms, prices)

	rows = []
	for it in items:
		rows.append(
			{
				"item_code": it.item_code,
				"item_name": it.item_name,
				"brand": it.brand,
				"category": it.item_group,
				"price": flt(prices.get((it.item_code, it.stock_uom)) or prices.get((it.item_code, None))),
				"stock": flt(stock.get(it.item_code)),
				"barcodes": barcodes.get(it.item_code, []),
				# Passed through exactly as the Item carries it. See `_images`
				# below for why this is deliberately not filtered.
				"image": it.image,
				"uom": it.stock_uom,
				# Every unit this may be sold in. One entry — the stock unit — on
				# the vast majority of items, so the till only offers a choice
				# where the shop has actually configured one.
				"uoms": uoms.get(it.item_code) or [],
				"batched": bool(it.has_batch_no or it.has_serial_no),
			}
		)

	return {
		"items": rows,
		"categories": _categories(rows),
		"warehouses": _warehouses(warehouse),
		"neighbours": _neighbours(),
		"sourcing": _sourcing_status(),
		"price_list": price_list,
		"warehouse": warehouse,
		"empty": False,
	}


#: Where an uploaded file actually lives, as opposed to an `/assets/…` path
#: shipped with an app or an absolute URL to somewhere else.
_UPLOAD_PREFIXES = ("/files/", "/private/files/")


#
# Why item images are **not** filtered on the way out
# ---------------------------------------------------
#
# There was a version of this module that dropped any `Item.image` with no
# matching `File.file_url`, on the reasoning that a path to a file this site
# does not have is a doomed request worth not making. It was wrong, and it
# blanked every photo on a real shop.
#
# A `File` row and a file on disk are two different things. Items imported from
# another site, or given their `image` by a data import rather than an upload,
# have a perfectly good picture sitting in `public/files` and **no File row at
# all** — so "no File row" means "we cannot see a record of this upload", never
# "the picture is missing". Reading it as the latter turned a working grid into
# a grid of placeholders.
#
# The browser is the only thing that actually knows whether a URL resolves, and
# it already reports it: `ItemCell` swaps in the shop's mark on the image's own
# `error` event. That fallback costs one failed request per broken photo and is
# never wrong about which ones are broken, which is the trade to keep.
#
# `diagnose_images` below is for finding out *why* a shop's photos 404, which is
# a question to answer with facts rather than by guessing in the hot path.


def diagnose_images(limit: int = 10) -> dict:
	"""Why the till is showing placeholders instead of product photos.

	Run it directly — there is nothing to click:

	    bench --site <site> execute cosmestics.api.catalog.diagnose_images

	Answers the three questions that separate the causes, because they need
	different fixes and look identical from behind the counter:

	* **Is `Item.image` even set?** If most items have no path, nothing is
	  broken — the shop simply has not uploaded photos, and the placeholder is
	  correct.
	* **Is the file on disk?** A path with no file behind it is an import that
	  brought the paths and not the images. The fix is to upload them; nothing
	  in the app can conjure the picture.
	* **Is it private?** A file under `private/files` is served from
	  `/private/files/…` and refused to anyone not signed in. If `image` says
	  `/files/…` and the file is private, the path is simply wrong, and that one
	  *is* repairable — the field needs the private path.

	Read-only. It looks at the filesystem and prints what it finds; it changes
	nothing, so it is safe on a live shop.
	"""
	import os

	rows = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1},
		fields=["name", "image"],
		limit_page_length=0,
	)

	report = {
		"items": len(rows),
		"with_image": 0,
		"uploads": 0,
		"found_public": 0,
		"found_private": 0,
		"missing": 0,
		"external": 0,
		"has_file_row": 0,
		"examples_missing": [],
		"examples_wrong_path": [],
	}

	public_dir = frappe.get_site_path("public", "files")
	private_dir = frappe.get_site_path("private", "files")

	for row in rows:
		path = (row.image or "").strip()
		if not path:
			continue
		report["with_image"] += 1

		if not path.startswith(_UPLOAD_PREFIXES):
			report["external"] += 1
			continue

		report["uploads"] += 1
		basename = os.path.basename(path.split("?")[0])
		in_public = os.path.exists(os.path.join(public_dir, basename))
		in_private = os.path.exists(os.path.join(private_dir, basename))

		if in_public:
			report["found_public"] += 1
		if in_private:
			report["found_private"] += 1

		if not in_public and not in_private:
			report["missing"] += 1
			if len(report["examples_missing"]) < limit:
				report["examples_missing"].append({"item": row.name, "image": path})
		elif in_private and not in_public and path.startswith("/files/"):
			# The repairable case: the file is here, the path says otherwise.
			if len(report["examples_wrong_path"]) < limit:
				report["examples_wrong_path"].append(
					{"item": row.name, "image": path, "should_be": f"/private/files/{basename}"}
				)

		if frappe.db.exists("File", {"file_url": path}):
			report["has_file_row"] += 1

	print(frappe.as_json(report, indent=2))
	return report


def _prices(codes, price_list) -> dict:
	if not price_list:
		return {}

	rows = frappe.get_all(
		"Item Price",
		filters={"price_list": price_list, "item_code": ("in", codes)},
		fields=["item_code", "price_list_rate", "valid_from", "uom"],
		limit_page_length=0,
		# Newest first, so the loop below keeps the most recent price per item.
		order_by="valid_from desc, modified desc",
	)

	# Keyed by (item, uom). A shop can price a dozen separately from twelve
	# singles — a carton is usually cheaper than its contents — and that price
	# has to win over the multiplication. A row with no UOM is the base price.
	out = {}
	for r in rows:
		out.setdefault((r.item_code, r.uom or None), r.price_list_rate)
	return out


def _sellable_uoms(codes, stock_uoms, prices) -> dict:
	"""The units each item may be sold in, with the price of one of each.

	A shop that sells shampoo by the piece and by the dozen has one item, one
	shelf and two ways to ring it up. ERPNext already models that as UOM
	Conversion Detail rows; nothing here invents units.

	The price of a larger unit is the base price times the conversion factor,
	*unless* the shop has priced that unit explicitly — which is the whole point
	of buying by the dozen, so an explicit price always wins.
	"""
	rows = frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": ("in", codes), "parenttype": "Item"},
		fields=["parent", "uom", "conversion_factor"],
		limit_page_length=0,
	)

	by_item = {}
	for code in codes:
		stock_uom = stock_uoms.get(code)
		base = flt(prices.get((code, stock_uom)) or prices.get((code, None)))
		# The stock unit is always sellable, at factor 1. Listed first because it
		# is what the till defaults to.
		by_item[code] = [{"uom": stock_uom, "factor": 1, "rate": base}]

	for r in rows:
		factor = flt(r.conversion_factor)
		stock_uom = stock_uoms.get(r.parent)
		if factor <= 0 or r.uom == stock_uom:
			continue
		explicit = prices.get((r.parent, r.uom))
		by_item.setdefault(r.parent, []).append(
			{
				"uom": r.uom,
				"factor": factor,
				"rate": flt(explicit) if explicit else flt(
					prices.get((r.parent, stock_uom)) or prices.get((r.parent, None))
				) * factor,
				"priced": bool(explicit),
			}
		)

	return by_item


def _stock(codes, warehouse) -> dict:
	if not warehouse:
		return {}

	rows = frappe.get_all(
		"Bin",
		filters={"warehouse": warehouse, "item_code": ("in", codes)},
		fields=["item_code", "actual_qty"],
		limit_page_length=0,
	)
	return {r.item_code: r.actual_qty for r in rows}


def _barcodes(codes) -> dict:
	rows = frappe.get_all(
		"Item Barcode",
		filters={"parent": ("in", codes)},
		fields=["parent", "barcode"],
		limit_page_length=0,
	)

	out = {}
	for r in rows:
		out.setdefault(r.parent, []).append(r.barcode)
	return out


def _categories(rows) -> list:
	"""Only groups that actually have sellable stock behind them — an empty
	category button wastes a tap at the counter."""
	seen = {}
	for r in rows:
		if r["category"]:
			seen[r["category"]] = seen.get(r["category"], 0) + 1
	return [{"name": name, "count": count} for name, count in sorted(seen.items())]


def _warehouses(exclude) -> list:
	"""Other branches we can request a transfer from.

	Only warehouses that actually hold stock. Every non-group warehouse used to
	qualify, which on a real site meant offering the cashier a per-customer van
	warehouse and "Work In Progress" as places to source goods from — neither is
	a branch, both are nonsense to pick, and the real branches were buried among
	them. A location with nothing in it cannot supply anything, so holding stock
	is the honest test of whether it is worth offering.
	"""
	company = frappe.defaults.get_global_default("company")
	filters = {"is_group": 0, "disabled": 0}
	if company:
		filters["company"] = company

	rows = frappe.get_all(
		"Warehouse", filters=filters, fields=["name", "warehouse_name", "warehouse_type"]
	)
	candidates = [w for w in rows if w.name != exclude and w.warehouse_type != "Transit"]
	if not candidates:
		return []

	stocked = set(
		frappe.get_all(
			"Bin",
			filters={"warehouse": ("in", [w.name for w in candidates]), "actual_qty": (">", 0)},
			pluck="warehouse",
			limit_page_length=0,
		)
	)

	return [{"name": w.name, "label": w.warehouse_name} for w in candidates if w.name in stocked]


def _neighbours() -> list:
	"""Shops we buy from when we are out of stock and the customer is waiting.

	Flagged on the Supplier itself (`cosmestics_is_neighbour_shop`), not by
	Supplier Group — a neighbour keeps whatever group actually classifies it;
	being a source for mid-sale purchases is a separate fact about it.
	"""
	rows = frappe.get_all(
		"Supplier",
		filters={"cosmestics_is_neighbour_shop": 1, "disabled": 0},
		fields=["name", "mobile_no"],
	)
	return [{"name": r.name, "phone": r.mobile_no} for r in rows]


def _sourcing_status() -> dict:
	"""Why buying from a neighbour is or is not available.

	An empty neighbour list and a feature that was never configured look
	identical at the till — the button is simply dead either way. This says
	which it is, because "no shop is checked as a neighbour yet" is something
	a manager can act on and a blank panel is not.
	"""
	count = frappe.db.count("Supplier", {"cosmestics_is_neighbour_shop": 1, "disabled": 0})
	if not count:
		return {
			"available": False,
			"reason": _(
				"No Supplier is checked as a Neighbour Shop yet. Open a Supplier and "
				"check Neighbour Shop on the ones you buy from mid-sale."
			),
		}

	return {"available": True, "count": count}
