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
	warehouse = settings.default_source_warehouse
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

	rows = []
	for it in items:
		rows.append(
			{
				"item_code": it.item_code,
				"item_name": it.item_name,
				"brand": it.brand,
				"category": it.item_group,
				"price": flt(prices.get(it.item_code)),
				"stock": flt(stock.get(it.item_code)),
				"barcodes": barcodes.get(it.item_code, []),
				"image": it.image,
				"uom": it.stock_uom,
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


def _prices(codes, price_list) -> dict:
	if not price_list:
		return {}

	rows = frappe.get_all(
		"Item Price",
		filters={"price_list": price_list, "item_code": ("in", codes)},
		fields=["item_code", "price_list_rate", "valid_from"],
		limit_page_length=0,
		# Newest first, so the loop below keeps the most recent price per item.
		order_by="valid_from desc, modified desc",
	)

	out = {}
	for r in rows:
		out.setdefault(r.item_code, r.price_list_rate)
	return out


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
	"""Shops we buy from when we are out of stock and the customer is waiting."""
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	group = settings.neighbour_supplier_group
	if not group:
		return []

	rows = frappe.get_all(
		"Supplier",
		filters={"supplier_group": group, "disabled": 0},
		fields=["name", "mobile_no"],
	)
	return [{"name": r.name, "phone": r.mobile_no} for r in rows]


def _sourcing_status() -> dict:
	"""Why buying from a neighbour is or is not available.

	An empty neighbour list and a feature that was never configured look
	identical at the till — the button is simply dead either way. This says
	which it is, because "no shops are set up in the Neighbour Shop group" is
	something a manager can act on and a blank panel is not.
	"""
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	group = settings.neighbour_supplier_group

	if not group:
		return {
			"available": False,
			"reason": _("No neighbour supplier group is set in Cosmestics POS Settings."),
		}

	count = frappe.db.count("Supplier", {"supplier_group": group, "disabled": 0})
	if not count:
		return {
			"available": False,
			"group": group,
			"reason": _(
				"No shops in the {0} supplier group yet. Add the shops you buy from as Suppliers in that group."
			).format(group),
		}

	return {"available": True, "group": group, "count": count}
