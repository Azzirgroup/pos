"""Bulk price maintenance.

Changing prices one item at a time in the desk is the single most tedious job in
a cosmetics shop — a supplier raises a whole brand by 8% and someone edits forty
Item Prices by hand. This does it as one reviewed operation.

Every change is written as a normal Item Price document so it stays visible to
ERPNext's own pricing, reporting and versioning.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate


@frappe.whitelist()
def get_price_list_options():
	rows = frappe.get_all(
		"Price List", filters={"enabled": 1, "selling": 1}, fields=["name", "currency"]
	)
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	return {
		"options": [{"label": r.name, "value": r.name} for r in rows],
		"default": settings.selling_price_list or (rows[0].name if rows else None),
	}


@frappe.whitelist()
def get_prices(
	price_list: str,
	search: str | None = None,
	item_group: str | None = None,
	brand: str | None = None,
	item_codes: list | str | None = None,
	limit: int = 300,
):
	"""Current selling price per item, including items that have none yet.

	`item_codes` fetches an explicit set regardless of the alphabetical window —
	needed by the preview, which must resolve exactly the rows the user ticked.
	"""
	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)

	filters = {"disabled": 0, "is_sales_item": 1}
	if item_codes:
		filters["name"] = ("in", item_codes)
	if item_group:
		filters["item_group"] = item_group
	if brand:
		filters["brand"] = brand
	if search:
		filters["item_name"] = ("like", f"%{search}%")

	items = frappe.get_all(
		"Item",
		filters=filters,
		fields=["name as item_code", "item_name", "item_group", "brand", "stock_uom"],
		order_by="item_name asc",
		limit_page_length=int(limit),
	)
	if not items:
		return {"rows": [], "currency": None}

	codes = [i.item_code for i in items]
	prices = {}
	for p in frappe.get_all(
		"Item Price",
		filters={"price_list": price_list, "item_code": ("in", codes)},
		fields=["name", "item_code", "price_list_rate", "valid_from"],
		order_by="valid_from desc, modified desc",
		limit_page_length=0,
	):
		prices.setdefault(p.item_code, p)

	# Last purchase cost, so a margin can be judged while editing.
	costs = {}
	for v in frappe.get_all(
		"Item",
		filters={"name": ("in", codes)},
		fields=["name", "last_purchase_rate", "valuation_rate"],
		limit_page_length=0,
	):
		costs[v.name] = flt(v.last_purchase_rate) or flt(v.valuation_rate)

	rows = []
	for it in items:
		p = prices.get(it.item_code)
		rate = flt(p.price_list_rate) if p else None
		cost = flt(costs.get(it.item_code))
		rows.append(
			{
				"item_code": it.item_code,
				"item_name": it.item_name,
				"item_group": it.item_group,
				"brand": it.brand,
				"uom": it.stock_uom,
				"price": rate,
				"cost": cost,
				"margin_pct": round((rate - cost) / rate * 100, 1) if rate and cost else None,
				"price_doc": p.name if p else None,
			}
		)

	currency = frappe.db.get_value("Price List", price_list, "currency")
	return {"rows": rows, "currency": currency}


@frappe.whitelist()
def get_filters():
	groups = frappe.get_all("Item Group", filters={"is_group": 0}, pluck="name", order_by="name")
	brands = (
		frappe.get_all("Brand", pluck="name", order_by="name")
		if frappe.db.exists("DocType", "Brand")
		else []
	)
	return {"item_groups": groups, "brands": brands}


@frappe.whitelist(methods=["POST"])
def preview_bulk_change(
	price_list: str,
	item_codes: list | str,
	mode: str = "percent",
	value: float = 0,
	rounding: str = "none",
):
	"""Show what a bulk change would do, before it does it.

	A price change is hard to unpick once it is live and a cashier has sold at
	the wrong rate, so this is deliberately a two-step operation.
	"""
	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)

	# Fetch by code, not by a limit: get_prices orders alphabetically, so a
	# limit of len(selection) returns the first N items in the catalog rather
	# than the N that were selected, and the preview silently comes back empty.
	current = get_prices(price_list=price_list, item_codes=item_codes, limit=0)
	by_code = {r["item_code"]: r for r in current["rows"]}

	out = []
	for code in item_codes:
		row = by_code.get(code)
		if not row:
			continue
		old = flt(row["price"])
		new = _apply(old, mode, flt(value))
		new = _round(new, rounding)
		out.append(
			{
				"item_code": code,
				"item_name": row["item_name"],
				"cost": row["cost"],
				"old_price": old,
				"new_price": new,
				"delta": new - old,
				# Selling under cost is the mistake this preview exists to catch.
				"below_cost": bool(row["cost"]) and new < flt(row["cost"]),
			}
		)

	return {
		"rows": out,
		"below_cost": sum(1 for r in out if r["below_cost"]),
		"count": len(out),
	}


def _apply(old, mode, value):
	if mode == "percent":
		return old * (1 + value / 100.0)
	if mode == "amount":
		return old + value
	if mode == "set":
		return value
	if mode == "margin":
		# Not used yet, but keeps the mode list honest if the UI grows one.
		return old
	frappe.throw(_("Unknown price change mode: {0}").format(mode))


def _round(value, rounding):
	if rounding == "whole":
		return float(round(value))
	if rounding == "ten":
		return float(round(value / 10.0) * 10)
	if rounding == "psych":
		# 1,250 -> 1,249. Common retail pricing, and cheap to offer.
		return float(max(0, round(value) - 1))
	return flt(value, 2)


@frappe.whitelist(methods=["POST"])
def apply_bulk_change(price_list: str, changes: list | str):
	"""Write the reviewed prices. `changes` is [{item_code, new_price}]."""
	if isinstance(changes, str):
		changes = frappe.parse_json(changes)

	if not changes:
		frappe.throw(_("Nothing to apply"))

	updated, created = 0, 0
	for c in changes:
		code = c["item_code"]
		rate = flt(c["new_price"])
		if rate < 0:
			frappe.throw(_("{0}: price cannot be negative").format(code))

		existing = frappe.db.get_value(
			"Item Price", {"item_code": code, "price_list": price_list}, "name"
		)
		if existing:
			doc = frappe.get_doc("Item Price", existing)
			if flt(doc.price_list_rate) == rate:
				continue
			doc.price_list_rate = rate
			doc.save(ignore_permissions=True)
			updated += 1
		else:
			doc = frappe.new_doc("Item Price")
			doc.item_code = code
			doc.price_list = price_list
			doc.price_list_rate = rate
			doc.valid_from = nowdate()
			doc.insert(ignore_permissions=True)
			created += 1

	frappe.db.commit()
	return {"updated": updated, "created": created}
