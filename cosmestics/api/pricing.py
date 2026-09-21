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


def _current_price_rows(price_list: str, codes: list) -> dict:
	"""The Item Price row this app treats as current, per item code.

	The single place that decides which row wins. An item can carry several Item
	Prices on one price list — a different UOM, or a future `valid_from` — and
	when the screen read one row while the write picked another, a bulk change
	appeared to do nothing: the price was updated, just not the one being shown.
	Read and write both come through here so they cannot disagree.
	"""
	if not codes:
		return {}

	out = {}
	for p in frappe.get_all(
		"Item Price",
		filters={"price_list": price_list, "item_code": ("in", codes)},
		fields=["name", "item_code", "price_list_rate", "valid_from", "uom"],
		# Newest first, then a stable tiebreak on name so two rows sharing a
		# date never swap places between two calls.
		order_by="valid_from desc, modified desc, name asc",
		limit_page_length=0,
	):
		out.setdefault(p.item_code, p)
	return out


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
	prices = _current_price_rows(price_list, codes)

	costs = _costs(codes)
	kept_costs = _kept_costs(codes)

	rows = []
	for it in items:
		p = prices.get(it.item_code)
		rate = flt(p.price_list_rate) if p else None
		cost = flt(costs.get(it.item_code))
		kept = it.item_code in kept_costs
		rows.append(
			{
				"item_code": it.item_code,
				"item_name": it.item_name,
				"item_group": it.item_group,
				"brand": it.brand,
				"uom": it.stock_uom,
				"price": rate,
				"cost": cost,
				# Whether that cost is the one the shop maintains, or merely the
				# last thing paid for it — the two behave differently and a
				# manager deciding a price needs to know which they are reading.
				"cost_kept": kept,
				"margin_pct": round((rate - cost) / rate * 100, 1) if rate and cost else None,
				"price_doc": p.name if p else None,
			}
		)

	currency = frappe.db.get_value("Price List", price_list, "currency")
	return {"rows": rows, "currency": currency}


#: Where a maintained cost price lives. ERPNext's own buying price list, so a
#: cost typed here is the cost every purchase form and report already reads.
COST_PRICE_LIST = "Standard Buying"


def _kept_costs(codes: list) -> dict:
	"""{item_code: cost} the shop maintains itself, from `COST_PRICE_LIST`."""
	if not codes:
		return {}
	rows = frappe.get_all(
		"Item Price",
		filters={"price_list": COST_PRICE_LIST, "item_code": ("in", codes), "selling": 0},
		fields=["item_code", "price_list_rate", "name"],
		order_by="valid_from desc, modified desc",
		limit_page_length=0,
	)
	out = {}
	for r in rows:
		out.setdefault(r.item_code, flt(r.price_list_rate))
	return out


def _costs(codes: list) -> dict:
	"""What each item costs, the maintained figure first.

	A neighbour shop's price is what one shop charged on one afternoon, and it
	lands on `last_purchase_rate` the moment the purchase posts. Reading that as
	*the* cost made every margin on this screen swing with whatever was paid
	next door last, which is the complaint this answers: a cost the shop has
	set itself wins, and the last price paid is only the fallback for items
	nobody has costed yet.
	"""
	kept = _kept_costs(codes)
	fallback = {
		v.name: flt(v.last_purchase_rate) or flt(v.valuation_rate)
		for v in frappe.get_all(
			"Item",
			filters={"name": ("in", codes)},
			fields=["name", "last_purchase_rate", "valuation_rate"],
			limit_page_length=0,
		)
	}
	return {code: kept.get(code) or fallback.get(code, 0) for code in codes}


@frappe.whitelist(methods=["POST"])
def set_costs(changes: list | str) -> dict:
	"""Set the cost price the shop maintains. `changes` is [{item_code, cost}].

	Written to the buying price list rather than onto the Item, so ERPNext's own
	purchase forms and reports read the same figure — and so a neighbour
	purchase, which only moves `last_purchase_rate`, can never overwrite it.
	"""
	if isinstance(changes, str):
		changes = frappe.parse_json(changes)
	changes = [c for c in (changes or []) if c.get("item_code")]
	if not changes:
		frappe.throw(_("Nothing to apply"))

	written, cleared = 0, 0
	for c in changes:
		code = c["item_code"]
		cost = flt(c.get("cost"))
		if cost < 0:
			frappe.throw(_("{0}: a cost cannot be negative").format(code))

		existing = frappe.db.get_value(
			"Item Price", {"price_list": COST_PRICE_LIST, "item_code": code, "selling": 0}, "name"
		)
		if not cost:
			# Cleared: back to whatever was last paid for it.
			if existing:
				frappe.delete_doc("Item Price", existing, ignore_permissions=True)
				cleared += 1
			continue
		if existing:
			_write_price(existing, cost)
		else:
			doc = frappe.new_doc("Item Price")
			doc.item_code = code
			doc.price_list = COST_PRICE_LIST
			doc.price_list_rate = cost
			doc.insert(ignore_permissions=True)
		written += 1

	return {
		"written": written,
		"cleared": cleared,
		"message": _("{0} cost price(s) set{1}").format(written, _(", {0} cleared").format(cleared) if cleared else ""),
	}


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


def _write_price(name: str, rate: float, _retry: bool = True):
	"""Save one Item Price, surviving a concurrent edit.

	`doc.save()` refuses when the row's `modified` has moved since it was read —
	which happens for real here, because another app's hook can touch an Item
	Price during the same bulk run, and because two managers can apply price
	changes at the same time. Left unhandled it fails the whole batch partway
	through, leaving some prices written and some not, with no way to tell which.

	`reload()` re-reads the row and the new rate is applied on top. That is safe
	precisely because this endpoint sets an absolute price rather than adjusting
	the existing one — the arithmetic was already done in the preview, so a
	fresher row cannot change the answer. One retry only: a second failure is a
	real conflict and should be reported, not looped over.
	"""
	doc = frappe.get_doc("Item Price", name)
	doc.price_list_rate = rate
	try:
		doc.save(ignore_permissions=True)
	except frappe.TimestampMismatchError:
		if not _retry:
			raise
		doc.reload()
		doc.price_list_rate = rate
		doc.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def apply_bulk_change(price_list: str, changes: list | str):
	"""Write the reviewed prices. `changes` is [{item_code, new_price}]."""
	if isinstance(changes, str):
		changes = frappe.parse_json(changes)

	if not changes:
		frappe.throw(_("Nothing to apply"))

	# Resolved through the same rule the screen read them with, so the row that
	# gets written is the row the user was looking at.
	current = _current_price_rows(price_list, [c["item_code"] for c in changes])

	updated, created, unchanged = 0, 0, 0
	for c in changes:
		code = c["item_code"]
		rate = flt(c["new_price"])
		if rate < 0:
			frappe.throw(_("{0}: price cannot be negative").format(code))

		existing = current.get(code)
		if existing:
			if flt(existing.price_list_rate) == rate:
				unchanged += 1
				continue
			_write_price(existing.name, rate)
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
	# `unchanged` is reported rather than swallowed: "0 updated" on its own reads
	# as a broken screen, when usually it means the prices were already right.
	return {"updated": updated, "created": created, "unchanged": unchanged}
