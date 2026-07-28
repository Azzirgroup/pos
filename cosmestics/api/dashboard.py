"""The one screen a shop owner opens first.

Everything here answers a question someone actually asks at the start of a day:
what did we take, what is it costing us, who owes us, and what is about to run
out. Nothing is here because it was easy to compute.

Two rules shape the module:

* **Every headline carries its comparison.** A revenue figure on its own is not
  information — the same window immediately before it is what makes it one. So
  the period totals are computed twice, once for now and once for the preceding
  window of equal length.
* **The trend is a complete day series.** Days with no sales are returned as
  zero rather than omitted, because a chart that silently closes a gap draws a
  quiet day as if it never happened.

Aggregation is in SQL for the same reason as `reports.py`: these span whole
periods, and pulling every invoice line into Python would not survive a busy
month.
"""

import frappe
from frappe.utils import add_days, cint, flt, getdate, nowdate

DEFAULT_DAYS = 30
# Enough to see the shape of a list without turning the dashboard into a report.
SHORTLIST = 8


def _company():
	return frappe.defaults.get_global_default("company")


def _window(days: int):
	days = cint(days) or DEFAULT_DAYS
	end = getdate(nowdate())
	start = add_days(end, -(days - 1))
	return getdate(start), end, days


def _scope(alias: str) -> str:
	"""Company clause for a table aliased `alias`, or nothing on a single-company
	site. Every figure a shop owner reads as "ours" has to mean one company."""
	return f" and {alias}.company = %(company)s" if _company() else ""


def _args(extra: dict | None = None) -> dict:
	args = {"company": _company()}
	args.update(extra or {})
	return args


def _delta(current, previous):
	"""Percentage change, or None when there is nothing to compare against.

	None rather than 0 or 100: "no sales at all last week" and "the same as last
	week" are different facts, and a tile that shows +100% for the first is
	worse than one that shows nothing.
	"""
	previous = flt(previous)
	if not previous:
		return None
	return round((flt(current) - previous) / abs(previous) * 100, 1)


# --------------------------------------------------------------------------


@frappe.whitelist()
def overview(days: int = DEFAULT_DAYS) -> dict:
	start, end, days = _window(days)
	prev_end = add_days(start, -1)
	prev_start = add_days(prev_end, -(days - 1))

	now = _sales_totals(start, end)
	before = _sales_totals(prev_start, prev_end)
	money = _money_position()
	stock = _stock_position()

	basket = flt(now["revenue"]) / now["invoices"] if now["invoices"] else 0
	prev_basket = flt(before["revenue"]) / before["invoices"] if before["invoices"] else 0

	stats = [
		{
			"key": "revenue",
			"label": "Revenue",
			"value": now["revenue"],
			"type": "currency",
			"icon": "money",
			"delta": _delta(now["revenue"], before["revenue"]),
			"delta_good": "up",
		},
		{
			"key": "invoices",
			"label": "Sales",
			"value": now["invoices"],
			"type": "number",
			"icon": "receipt",
			"delta": _delta(now["invoices"], before["invoices"]),
			"delta_good": "up",
		},
		{
			"key": "basket",
			"label": "Average sale",
			"value": basket,
			"type": "currency",
			"icon": "cart",
			"delta": _delta(basket, prev_basket),
			"delta_good": "up",
		},
		{
			"key": "margin",
			"label": "Gross margin",
			"value": now["margin"],
			"type": "currency",
			"icon": "trending-up",
			"tone": "bad" if flt(now["margin"]) < 0 else "good",
			"hint": f"{now['margin_pct']}% of revenue",
			"delta": _delta(now["margin"], before["margin"]),
			"delta_good": "up",
		},
		{
			"key": "cash",
			"label": "Cash and bank",
			"value": money["cash_and_bank"],
			"type": "currency",
			"icon": "landmark",
		},
		{
			"key": "receivable",
			"label": "Customers owe us",
			"value": money["receivable"],
			"type": "currency",
			"icon": "users",
			"tone": "warn" if flt(money["receivable"]) else "good",
			"hint": f"{money['overdue_count']} overdue" if money["overdue_count"] else None,
		},
		{
			"key": "stock_value",
			"label": "Stock value",
			"value": stock["value"],
			"type": "currency",
			"icon": "boxes",
		},
		{
			"key": "below_reorder",
			"label": "Below reorder level",
			"value": stock["below_reorder"],
			"type": "number",
			"icon": "alert",
			"tone": "bad" if stock["below_reorder"] else "good",
		},
	]

	return {
		"period": {"from": str(start), "to": str(end), "days": days},
		"previous": {"from": str(prev_start), "to": str(prev_end)},
		"stats": stats,
		"trend": _trend(start, end),
		"payment_mix": _payment_mix(start, end),
		"top_items": _top_items(start, end),
		"attention": {
			"below_reorder": _below_reorder_rows(),
			"overdue": _overdue_rows(),
			"negative_stock": _negative_stock_rows(),
		},
		"tills": _open_tills(),
	}


# --------------------------------------------------------------------------
# Sales
# --------------------------------------------------------------------------


def _sales_totals(start, end) -> dict:
	"""Revenue, count and margin for one window.

	Cost comes from `incoming_rate` — the stock ledger's own valuation at the
	moment the line was delivered — so the margin is against what the goods
	really cost, not against a price list someone last edited in March.
	"""
	row = frappe.db.sql(
		f"""select count(distinct si.name) as invoices,
		           sum(si.grand_total) as revenue
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.posting_date between %(start)s and %(end)s
		      {_scope('si')}""",
		_args({"start": start, "end": end}),
		as_dict=True,
	)[0]

	line = frappe.db.sql(
		f"""select sum(sii.base_net_amount) as net,
		           sum(ifnull(sii.incoming_rate, 0) * sii.qty) as cost
		    from `tabSales Invoice Item` sii
		    join `tabSales Invoice` si on si.name = sii.parent
		    where si.docstatus = 1 and si.posting_date between %(start)s and %(end)s
		      {_scope('si')}""",
		_args({"start": start, "end": end}),
		as_dict=True,
	)[0]

	net = flt(line.net)
	margin = net - flt(line.cost)
	return {
		"invoices": cint(row.invoices),
		"revenue": flt(row.revenue),
		"net": net,
		"margin": margin,
		"margin_pct": round(margin / net * 100, 1) if net else 0,
	}


def _trend(start, end) -> list:
	"""Daily revenue across the window, with quiet days present and zero."""
	rows = frappe.db.sql(
		f"""select si.posting_date as day, count(si.name) as invoices,
		           sum(si.grand_total) as revenue
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.posting_date between %(start)s and %(end)s
		      {_scope('si')}
		    group by si.posting_date""",
		_args({"start": start, "end": end}),
		as_dict=True,
	)
	by_day = {str(getdate(r.day)): r for r in rows}

	series = []
	day = getdate(start)
	while day <= getdate(end):
		hit = by_day.get(str(day))
		series.append(
			{
				"day": str(day),
				"revenue": flt(hit.revenue) if hit else 0,
				"invoices": cint(hit.invoices) if hit else 0,
			}
		)
		day = add_days(day, 1)
	return series


def _payment_mix(start, end) -> list:
	"""What was actually collected, by tender.

	Only real payment rows, so this does not silently include credit sales —
	money owed is not money in the drawer, and a chart that blurs the two is
	the one a shop most needs to trust.
	"""
	rows = frappe.db.sql(
		f"""select sip.mode_of_payment as mode, sum(sip.amount) as amount
		    from `tabSales Invoice Payment` sip
		    join `tabSales Invoice` si on si.name = sip.parent
		    where si.docstatus = 1 and si.posting_date between %(start)s and %(end)s
		      {_scope('si')}
		    group by sip.mode_of_payment
		    having amount != 0
		    order by amount desc""",
		_args({"start": start, "end": end}),
		as_dict=True,
	)
	total = sum(flt(r.amount) for r in rows)
	return [
		{
			"mode": r.mode,
			"amount": flt(r.amount),
			"share": round(flt(r.amount) / total * 100, 1) if total else 0,
		}
		for r in rows
	]


def _top_items(start, end) -> list:
	rows = frappe.db.sql(
		f"""select sii.item_code, sii.item_name,
		           sum(sii.qty) as qty, sum(sii.base_net_amount) as revenue
		    from `tabSales Invoice Item` sii
		    join `tabSales Invoice` si on si.name = sii.parent
		    where si.docstatus = 1 and si.posting_date between %(start)s and %(end)s
		      {_scope('si')}
		    group by sii.item_code, sii.item_name
		    having revenue > 0
		    order by revenue desc limit %(limit)s""",
		_args({"start": start, "end": end, "limit": SHORTLIST}),
		as_dict=True,
	)
	return [
		{"item_code": r.item_code, "item_name": r.item_name, "qty": flt(r.qty), "revenue": flt(r.revenue)}
		for r in rows
	]


# --------------------------------------------------------------------------
# Money and stock position
# --------------------------------------------------------------------------


def _money_position() -> dict:
	company = _company()
	cash_and_bank = 0
	if company:
		row = frappe.db.sql(
			"""select sum(gle.debit) - sum(gle.credit) as balance
			   from `tabGL Entry` gle
			   join tabAccount a on a.name = gle.account
			   where gle.is_cancelled = 0 and gle.company = %(company)s
			     and a.account_type in ('Bank', 'Cash') and a.is_group = 0""",
			{"company": company},
			as_dict=True,
		)[0]
		cash_and_bank = flt(row.balance)

	receivable = frappe.db.sql(
		f"""select sum(si.outstanding_amount) as total,
		           sum(case when si.due_date < %(today)s then 1 else 0 end) as overdue_count,
		           sum(case when si.due_date < %(today)s then si.outstanding_amount else 0 end) as overdue
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.outstanding_amount > 0 {_scope('si')}""",
		_args({"today": nowdate()}),
		as_dict=True,
	)[0]

	payable = frappe.db.sql(
		f"""select sum(pi.outstanding_amount) as total from `tabPurchase Invoice` pi
		    where pi.docstatus = 1 and pi.outstanding_amount > 0 {_scope('pi')}""",
		_args(),
	)

	return {
		"cash_and_bank": cash_and_bank,
		"receivable": flt(receivable.total),
		"overdue": flt(receivable.overdue),
		"overdue_count": cint(receivable.overdue_count),
		"payable": flt(payable[0][0] if payable and payable[0] else 0),
	}


def _stock_position() -> dict:
	value = frappe.db.sql(
		"""select sum(actual_qty * valuation_rate) from tabBin where actual_qty != 0"""
	)
	below = frappe.db.sql(
		"""select count(*) from `tabItem Reorder` ir
		   left join tabBin b on b.item_code = ir.parent and b.warehouse = ir.warehouse
		   where ifnull(b.actual_qty, 0) <= ir.warehouse_reorder_level"""
	)
	return {
		"value": flt(value[0][0] if value and value[0] else 0),
		"below_reorder": cint(below[0][0] if below and below[0] else 0),
	}


# --------------------------------------------------------------------------
# Needs attention
# --------------------------------------------------------------------------


def _below_reorder_rows() -> dict:
	"""The buy list, shortened. `shortfall` is what the reorder screen calls it,
	so the same number keeps the same name and the same colour."""
	rows = frappe.db.sql(
		"""select i.item_name, ir.warehouse,
		          ifnull(b.actual_qty, 0) as actual_qty,
		          ir.warehouse_reorder_level as reorder_level,
		          ir.warehouse_reorder_level - ifnull(b.actual_qty, 0) as shortfall
		   from `tabItem Reorder` ir
		   join tabItem i on i.name = ir.parent
		   left join tabBin b on b.item_code = ir.parent and b.warehouse = ir.warehouse
		   where ifnull(b.actual_qty, 0) <= ir.warehouse_reorder_level
		   order by shortfall desc limit %(limit)s""",
		{"limit": SHORTLIST},
		as_dict=True,
	)
	return {
		"columns": [
			{"label": "Item", "key": "item_name", "type": "text"},
			{"label": "Warehouse", "key": "warehouse", "type": "text"},
			{"label": "On hand", "key": "actual_qty", "type": "number"},
			{"label": "Reorder at", "key": "reorder_level", "type": "number"},
			{"label": "Short by", "key": "shortfall", "type": "number"},
		],
		"rows": rows,
	}


def _overdue_rows() -> dict:
	rows = frappe.db.sql(
		f"""select si.name, si.customer, si.due_date,
		           datediff(%(today)s, si.due_date) as days_overdue,
		           si.outstanding_amount as outstanding
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.outstanding_amount > 0 and si.due_date < %(today)s
		      {_scope('si')}
		    order by si.due_date asc limit %(limit)s""",
		_args({"today": nowdate(), "limit": SHORTLIST}),
		as_dict=True,
	)
	return {
		"columns": [
			{"label": "Invoice", "key": "name", "type": "text"},
			{"label": "Customer", "key": "customer", "type": "text"},
			{"label": "Due", "key": "due_date", "type": "text"},
			{"label": "Days late", "key": "days_overdue", "type": "number"},
			{"label": "Outstanding", "key": "outstanding", "type": "currency"},
		],
		"rows": rows,
	}


def _negative_stock_rows() -> dict:
	"""Negative balances are always a data problem, never a stock problem —
	something was sold that the ledger never received."""
	rows = frappe.db.sql(
		"""select i.item_name, b.warehouse, b.actual_qty
		   from tabBin b join tabItem i on i.name = b.item_code
		   where b.actual_qty < 0
		   order by b.actual_qty asc limit %(limit)s""",
		{"limit": SHORTLIST},
		as_dict=True,
	)
	return {
		"columns": [
			{"label": "Item", "key": "item_name", "type": "text"},
			{"label": "Warehouse", "key": "warehouse", "type": "text"},
			{"label": "On hand", "key": "actual_qty", "type": "number"},
		],
		"rows": rows,
	}


def _open_tills() -> dict:
	rows = frappe.db.sql(
		f"""select o.name, o.user, o.pos_profile, o.period_start_date
		    from `tabPOS Opening Entry` o
		    where o.docstatus = 1 and o.status = 'Open' {_scope('o')}
		    order by o.period_start_date desc limit %(limit)s""",
		_args({"limit": SHORTLIST}),
		as_dict=True,
	)
	return {"count": len(rows), "rows": rows}
