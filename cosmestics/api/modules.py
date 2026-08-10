"""Back-office data for the inventory, purchasing, sales and accounts screens.

Read-only summaries built from ERPNext's own documents. Nothing here duplicates
ERPNext state — the desk remains the place to edit; these screens exist so a
shop manager can answer the day's questions without learning the desk.
"""

import frappe
from frappe.utils import add_days, flt, nowdate

from cosmestics.api.search import rank

# A shop manager thinks in weeks, not accounting periods.
DEFAULT_DAYS = 30


def _company():
	return frappe.defaults.get_global_default("company")


def _window(days):
	days = int(days or DEFAULT_DAYS)
	return add_days(nowdate(), -days), nowdate()


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------


@frappe.whitelist()
def inventory(warehouse: str | None = None, search: str | None = None, limit: int = 200):
	"""Stock on hand with value, newest movement first."""
	filters = {"actual_qty": ("!=", 0)}
	if warehouse:
		filters["warehouse"] = warehouse

	bins = frappe.get_all(
		"Bin",
		filters=filters,
		fields=[
			"item_code",
			"warehouse",
			"actual_qty",
			"reserved_qty",
			"projected_qty",
			"valuation_rate",
			"stock_uom",
		],
		limit_page_length=int(limit),
		order_by="modified desc",
	)
	if not bins:
		return {"rows": [], "totals": {"value": 0, "lines": 0}}

	names = {b.item_code for b in bins}
	titles = dict(
		frappe.get_all(
			"Item",
			filters={"name": ("in", list(names))},
			fields=["name", "item_name"],
			as_list=True,
			limit_page_length=0,
		)
	)

	rows = []
	for b in bins:
		title = titles.get(b.item_code, b.item_code)
		value = flt(b.actual_qty) * flt(b.valuation_rate)
		rows.append(
			{
				"item_code": b.item_code,
				"item_name": title,
				"warehouse": b.warehouse,
				"actual_qty": flt(b.actual_qty),
				"reserved_qty": flt(b.reserved_qty),
				"projected_qty": flt(b.projected_qty),
				"valuation_rate": flt(b.valuation_rate),
				"value": value,
				"uom": b.stock_uom,
			}
		)

	# Filtered after the rows are built, not while building them, so the match
	# runs against the same item name the screen shows. Tolerant of word order
	# and a missing letter, like every other list — see `api/search`.
	rows = rank(rows, search, ["item_code", "item_name"])

	return {
		"rows": rows,
		"totals": {"value": sum(r["value"] for r in rows), "lines": len(rows)},
	}


@frappe.whitelist()
def warehouses():
	filters = {"disabled": 0, "is_group": 0}
	company = _company()
	if company:
		filters["company"] = company
	rows = frappe.get_all(
		"Warehouse", filters=filters, fields=["name", "warehouse_name", "warehouse_type"]
	)
	return [
		{"name": r.name, "label": r.warehouse_name}
		for r in rows
		if r.warehouse_type != "Transit"
	]


# --------------------------------------------------------------------------
# Sales
# --------------------------------------------------------------------------


@frappe.whitelist()
def sales(days: int = DEFAULT_DAYS, limit: int = 100):
	start, end = _window(days)
	filters = {"docstatus": 1, "posting_date": ("between", [start, end])}
	company = _company()
	if company:
		filters["company"] = company

	rows = frappe.get_all(
		"Sales Invoice",
		filters=filters,
		fields=[
			"name",
			"posting_date",
			"customer",
			"grand_total",
			"outstanding_amount",
			"is_pos",
			"status",
		],
		order_by="posting_date desc, creation desc",
		limit_page_length=int(limit),
	)

	return {
		"rows": rows,
		"totals": {
			"count": len(rows),
			"revenue": sum(flt(r.grand_total) for r in rows),
			"outstanding": sum(flt(r.outstanding_amount) for r in rows),
			"pos": sum(1 for r in rows if r.is_pos),
		},
		"period": {"from": start, "to": end},
	}


# --------------------------------------------------------------------------
# Purchasing
# --------------------------------------------------------------------------


@frappe.whitelist()
def purchasing(days: int = DEFAULT_DAYS, limit: int = 100):
	start, end = _window(days)
	company = _company()

	def _fetch(doctype, extra_fields):
		filters = {"docstatus": ("<", 2), "transaction_date": ("between", [start, end])}
		if doctype == "Purchase Invoice":
			filters = {"docstatus": ("<", 2), "posting_date": ("between", [start, end])}
		if company:
			filters["company"] = company
		return frappe.get_all(
			doctype,
			filters=filters,
			fields=extra_fields,
			order_by="modified desc",
			limit_page_length=int(limit),
		)

	invoices = _fetch(
		"Purchase Invoice",
		["name", "posting_date as date", "supplier", "grand_total", "outstanding_amount", "status"],
	)
	orders = _fetch(
		"Purchase Order",
		["name", "transaction_date as date", "supplier", "grand_total", "status", "per_received"],
	)
	requests = frappe.get_all(
		"Material Request",
		filters={"docstatus": ("<", 2), "transaction_date": ("between", [start, end])},
		fields=["name", "transaction_date as date", "material_request_type", "status", "per_ordered"],
		order_by="modified desc",
		limit_page_length=int(limit),
	)

	return {
		"invoices": invoices,
		"orders": orders,
		"requests": requests,
		"totals": {
			"spend": sum(flt(r.grand_total) for r in invoices),
			"owed": sum(flt(r.outstanding_amount) for r in invoices),
			"open_orders": sum(1 for r in orders if r.status not in ("Completed", "Closed", "Cancelled")),
			"open_requests": sum(1 for r in requests if r.status in ("Pending", "Partially Ordered")),
		},
		"period": {"from": start, "to": end},
	}


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------


@frappe.whitelist()
def accounts(days: int = DEFAULT_DAYS):
	"""Cash and bank balances, plus what is owed in each direction."""
	company = _company()
	start, end = _window(days)

	balances = []
	if company:
		rows = frappe.get_all(
			"Account",
			filters={
				"company": company,
				"is_group": 0,
				"account_type": ("in", ["Bank", "Cash"]),
				"disabled": 0,
			},
			fields=["name", "account_name", "account_type"],
		)
		for a in rows:
			bal = frappe.db.sql(
				"""select sum(debit) - sum(credit) from `tabGL Entry`
				   where account = %s and is_cancelled = 0""",
				a.name,
			)
			balances.append(
				{
					"account": a.name,
					"label": a.account_name,
					"type": a.account_type,
					"balance": flt(bal[0][0] if bal and bal[0] else 0),
				}
			)

	receivable = frappe.db.sql(
		"""select sum(outstanding_amount) from `tabSales Invoice`
		   where docstatus = 1 and outstanding_amount > 0"""
	)
	payable = frappe.db.sql(
		"""select sum(outstanding_amount) from `tabPurchase Invoice`
		   where docstatus = 1 and outstanding_amount > 0"""
	)

	return {
		"balances": balances,
		"receivable": flt(receivable[0][0] if receivable and receivable[0] else 0),
		"payable": flt(payable[0][0] if payable and payable[0] else 0),
		"cash_total": sum(b["balance"] for b in balances if b["type"] == "Cash"),
		"bank_total": sum(b["balance"] for b in balances if b["type"] == "Bank"),
		"period": {"from": start, "to": end},
	}
