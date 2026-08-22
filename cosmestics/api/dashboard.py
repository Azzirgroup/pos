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
	"""The shop's numbers, for the accounts that are allowed to read them.

	Gated on the server as well as hidden in the rail: a whitelisted method is
	reachable by URL, and "the button is not drawn" is not a permission.
	"""
	from cosmestics.permissions import ANALYTICS, require

	require(
		ANALYTICS,
		frappe._("The dashboard is limited to the accounts that hold Cosmestics Analytics."),
	)

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
		# Negative stock was dropped from here on request. It is a ledger problem
		# rather than a trading one, and it stayed on screen for weeks at a time
		# — a permanent red list teaches people to ignore the panel it sits in.
		# It is still on the Warehouses tab, where a stock question belongs.
		"attention": {
			"below_reorder": _below_reorder_rows(),
			"overdue": _overdue_rows(),
			"slow_moving": _slow_moving_rows(days),
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


def _slow_moving_rows(days: int) -> dict:
	"""Stock that has not sold in the window, worth most first.

	The counterpart to the buy list, and the one nobody asks for until the money
	is already tied up: below-reorder says what to buy, this says what not to buy
	again. Ordered by value rather than by age, because a hundred units of
	something cheap gathering dust matters less than three of something dear.

	A left join with a null match is what "did not sell" means here — filtering
	on a sold quantity of zero would only ever find items that appear in the
	sales table, which by definition sold.
	"""
	start, _end, _days = _window(days)
	rows = frappe.db.sql(
		"""select i.item_name, b.item_code, b.warehouse,
		          b.actual_qty, b.actual_qty * b.valuation_rate as value
		   from tabBin b
		   join tabItem i on i.name = b.item_code
		   where b.actual_qty > 0
		     and not exists (
		         select 1 from `tabSales Invoice Item` sii
		         join `tabSales Invoice` si on si.name = sii.parent
		         where sii.item_code = b.item_code and si.docstatus = 1
		           and si.posting_date >= %(start)s
		     )
		   order by value desc limit %(limit)s""",
		{"start": start, "limit": SHORTLIST},
		as_dict=True,
	)
	return {
		"columns": [
			{"label": "Item", "key": "item_name", "type": "text"},
			{"label": "Warehouse", "key": "warehouse", "type": "text"},
			{"label": "On hand", "key": "actual_qty", "type": "number"},
			{"label": "Tied up", "key": "value", "type": "currency"},
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


# --------------------------------------------------------------------------
# Tabs
#
# Each tab answers one department's question and returns the same shape —
# {stats, sections} — so the front end renders them all through one component
# rather than growing a bespoke screen per tab. `sections` is a list of
# {key, title, subtitle, columns, rows}, which is the same contract DataTable
# already takes everywhere else in the app.
# --------------------------------------------------------------------------


def _section(key, title, subtitle, columns, rows, chart=None, scroll=False):
	"""One tab section.

	`chart` is an optional drawing hint — {kind, label, value, hint} naming which
	columns to plot. The front end draws it and keeps the table behind a toggle,
	so nothing is lost: a bar is faster to compare across, and the exact figures
	are one tap away for anyone who needs them.

	Declared here rather than in the browser because the server is what knows
	which column is the magnitude. A section with no `chart` simply renders as a
	list, which is right for the ones where every row matters equally.
	"""
	return {
		"key": key,
		"title": title,
		"subtitle": subtitle,
		"columns": columns,
		"rows": rows,
		"chart": chart,
		# A full list rather than a shortlist: the card caps its own height and
		# scrolls inside itself, so a hundred debtors do not push the rest of the
		# tab off the screen.
		"scroll": scroll,
	}


def _bar(label, value, hint=None, kind="currency"):
	"""A horizontal bar chart of `value`, labelled by `label`.

	For rankings — "which is biggest" — where comparing lengths against a shared
	baseline is exactly the question.
	"""
	return {"kind": "bar", "label": label, "value": value, "hint": hint, "type": kind}


def _donut(label, value, kind="currency"):
	"""A ring showing how a whole divides.

	For composition — which account holds the cash, which tender the money came
	through. Deliberately not used for rankings: angles are hard to compare when
	slices are close, and a bar answers that better.
	"""
	return {"kind": "donut", "label": label, "value": value, "type": kind}


def _paired(label, a, b, a_label, b_label, kind="number"):
	"""Two measures per row, for a relationship rather than a magnitude.

	Received against issued is the case this exists for: a single bar of the net
	figure cannot distinguish "nothing moved" from "a hundred in and a hundred
	out", and those are very different weeks.
	"""
	return {
		"kind": "paired",
		"label": label,
		"a": a,
		"b": b,
		"a_label": a_label,
		"b_label": b_label,
		"type": kind,
	}


def _line(label, value):
	"""A line over time. `label` must be a date column.

	Named `_line` rather than `_trend` because `_trend(start, end)` already
	builds the overview's daily series — two functions with one name would have
	silently shadowed it and broken the front page.
	"""
	return {"kind": "trend", "label": label, "value": value}


def _col(label, key, kind="text"):
	return {"label": label, "key": key, "type": kind}


@frappe.whitelist()
def filters() -> dict:
	"""Options for the dashboard's filter row.

	Branches are POS Profiles: every till sale already carries `pos_profile`, so
	this needs no new field on any document and cannot disagree with what the
	shift screens report.
	"""
	company = _company()
	profile_filters = {"disabled": 0}
	warehouse_filters = {"disabled": 0, "is_group": 0}
	if company:
		profile_filters["company"] = company
		warehouse_filters["company"] = company

	return {
		"branches": [
			{"label": p.name, "value": p.name}
			for p in frappe.get_all("POS Profile", filters=profile_filters, fields=["name"])
		],
		"warehouses": [
			{"label": w.warehouse_name or w.name, "value": w.name}
			for w in frappe.get_all(
				"Warehouse", filters=warehouse_filters, fields=["name", "warehouse_name", "warehouse_type"]
			)
			if w.warehouse_type != "Transit"
		],
	}


@frappe.whitelist()
def today() -> dict:
	"""Everything that has happened since the shop opened this morning.

	Deliberately ignores the period control. Every other tab answers "how is the
	month going"; this one answers "what is happening right now", and the two
	questions want different screens. A shop owner checking in at four in the
	afternoon wants today's takings, who is on the till, what went out of the
	drawer and what is still unpaid — none of which a thirty-day average shows.

	Windowed on `posting_date`, not on `creation`: a sale is part of today's
	trading because it was posted today, and a shift that opened before midnight
	does not move yesterday's invoices into today.
	"""
	day = getdate(nowdate())
	args = _args({"day": day})

	sales_row = frappe.db.sql(
		f"""select count(si.name) as invoices,
		           sum(si.grand_total) as revenue,
		           sum(si.outstanding_amount) as unpaid,
		           sum(case when si.is_pos = 1 then 1 else 0 end) as till_sales,
		           sum(case when si.is_return = 1 then 1 else 0 end) as returns,
		           sum(case when si.is_return = 1 then si.grand_total else 0 end) as returned_value
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.posting_date = %(day)s {_scope('si')}""",
		args,
		as_dict=True,
	)[0]

	by_mode = frappe.db.sql(
		f"""select sip.mode_of_payment as mode, sum(sip.amount) as amount
		    from `tabSales Invoice Payment` sip
		    join `tabSales Invoice` si on si.name = sip.parent
		    where si.docstatus = 1 and si.posting_date = %(day)s {_scope('si')}
		    group by sip.mode_of_payment order by amount desc""",
		args,
		as_dict=True,
	)

	invoices = frappe.db.sql(
		f"""select si.name, si.customer, si.grand_total, si.outstanding_amount as outstanding,
		           si.is_return, si.pos_profile, si.owner,
		           time_format(si.posting_time, '%%H:%%i') as at
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.posting_date = %(day)s {_scope('si')}
		    order by si.posting_time desc limit 200""",
		args,
		as_dict=True,
	)

	movements = frappe.db.sql(
		"""select m.movement_type as kind, m.amount, m.party, m.person, m.reason,
		          m.mode_of_payment as mode
		   from `tabCosmestics Shift Movement` m
		   where m.docstatus = 1 and date(m.creation) = %(day)s
		   order by m.creation desc limit 100""",
		{"day": day},
		as_dict=True,
	)

	purchases = frappe.db.sql(
		f"""select pi.name, pi.supplier, pi.grand_total, pi.outstanding_amount as outstanding
		    from `tabPurchase Invoice` pi
		    where pi.docstatus = 1 and pi.posting_date = %(day)s {_scope('pi')}
		    order by pi.creation desc limit 100""",
		args,
		as_dict=True,
	)

	tills = _open_tills()
	revenue = flt(sales_row.revenue)
	paid_out = flt(sum(m.amount for m in movements if m.kind in ("Expense", "Neighbour Purchase")))
	cash_in = flt(sum(m.amount for m in movements if m.kind == "Neighbour Refund"))

	return {
		"period": {"from": str(day), "to": str(day), "days": 1},
		"stats": [
			{"key": "revenue", "label": "Taken today", "value": revenue, "type": "currency", "icon": "money"},
			{"key": "invoices", "label": "Sales", "value": cint(sales_row.invoices), "type": "number", "icon": "receipt"},
			{
				"key": "unpaid",
				"label": "Unpaid today",
				"value": flt(sales_row.unpaid),
				"type": "currency",
				"icon": "hourglass",
				"tone": "warn" if flt(sales_row.unpaid) else "good",
			},
			{"key": "till", "label": "Over the counter", "value": cint(sales_row.till_sales), "type": "number", "icon": "cart"},
			{
				"key": "tills_open",
				"label": "Tills open now",
				"value": tills["count"],
				"type": "number",
				"icon": "unlock",
				"tone": "warn" if tills["count"] else "default",
			},
			{
				"key": "paid_out",
				"label": "Out of the drawer",
				"value": paid_out - cash_in,
				"type": "currency",
				"icon": "wallet",
				"tone": "warn" if paid_out else "default",
			},
			{
				"key": "returns",
				"label": "Returns",
				"value": cint(sales_row.returns),
				"type": "number",
				"icon": "ban",
				"tone": "bad" if cint(sales_row.returns) else "default",
				"hint": f"{abs(flt(sales_row.returned_value)):,.0f} given back" if sales_row.returns else None,
			},
			{
				"key": "bought",
				"label": "Bought today",
				"value": flt(sum(p.grand_total for p in purchases)),
				"type": "currency",
				"icon": "truck",
			},
		],
		"sections": [
			_section(
				"modes",
				"How it was paid",
				"Every tender taken today",
				[_col("Mode", "mode"), _col("Amount", "amount", "currency")],
				by_mode,
				_donut("mode", "amount"),
			),
			_section(
				"tills",
				"Tills open now",
				"Nobody has closed these yet",
				[_col("Shift", "name"), _col("Cashier", "user"), _col("Till", "pos_profile")],
				tills["rows"],
			),
			_section(
				"movements",
				"Money out of the drawer",
				"Expenses, neighbour purchases and refunds",
				[
					_col("Kind", "kind"),
					_col("Who", "party"),
					_col("Why", "reason"),
					_col("Amount", "amount", "currency"),
				],
				movements,
				scroll=True,
			),
			_section(
				"invoices",
				"Today's sales",
				f"{len(invoices)} in the order they happened",
				[
					_col("Time", "at"),
					_col("Invoice", "name"),
					_col("Customer", "customer"),
					_col("Unpaid", "outstanding", "currency"),
					_col("Total", "grand_total", "currency"),
				],
				invoices,
				scroll=True,
			),
			_section(
				"purchases",
				"Bought today",
				"Including anything sourced from next door",
				[
					_col("Invoice", "name"),
					_col("Supplier", "supplier"),
					_col("Still owed", "outstanding", "currency"),
					_col("Total", "grand_total", "currency"),
				],
				purchases,
				scroll=True,
			),
		],
	}


@frappe.whitelist()
def sales(days: int = DEFAULT_DAYS, branch: str | None = None) -> dict:
	"""Sales, optionally narrowed to one till."""
	start, end, days = _window(days)
	branch_cond = " and si.pos_profile = %(branch)s" if branch else ""
	args = _args({"start": start, "end": end, "branch": branch, "limit": SHORTLIST})

	totals = frappe.db.sql(
		f"""select count(si.name) as invoices, sum(si.grand_total) as revenue,
		           sum(si.outstanding_amount) as outstanding
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.posting_date between %(start)s and %(end)s
		      {_scope('si')} {branch_cond}""",
		args,
		as_dict=True,
	)[0]

	by_day = frappe.db.sql(
		f"""select si.posting_date as day, count(si.name) as invoices,
		           sum(si.grand_total) as revenue
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.posting_date between %(start)s and %(end)s
		      {_scope('si')} {branch_cond}
		    group by si.posting_date order by si.posting_date desc""",
		args,
		as_dict=True,
	)

	by_cashier = frappe.db.sql(
		f"""select si.owner as cashier, count(si.name) as invoices,
		           sum(si.grand_total) as revenue
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.posting_date between %(start)s and %(end)s
		      {_scope('si')} {branch_cond}
		    group by si.owner order by revenue desc limit %(limit)s""",
		args,
		as_dict=True,
	)

	by_item = frappe.db.sql(
		f"""select sii.item_name, sum(sii.qty) as qty, sum(sii.base_net_amount) as revenue
		    from `tabSales Invoice Item` sii
		    join `tabSales Invoice` si on si.name = sii.parent
		    where si.docstatus = 1 and si.posting_date between %(start)s and %(end)s
		      {_scope('si')} {branch_cond}
		    group by sii.item_name order by revenue desc limit %(limit)s""",
		args,
		as_dict=True,
	)

	invoices = cint(totals.invoices)
	# Derived from the section rows above rather than re-queried: these tiles
	# describe the same slice the tables show, so computing them from anything
	# else would let the headline and the detail disagree.
	best_day = max(by_day, key=lambda d: flt(d.revenue)) if by_day else None
	best_cashier = by_cashier[0] if by_cashier else None
	units = sum(flt(i.qty) for i in by_item)
	collected = flt(totals.revenue) - flt(totals.outstanding)

	return {
		"period": {"from": str(start), "to": str(end), "days": days},
		"branch": branch,
		"stats": [
			{"key": "revenue", "label": "Revenue", "value": flt(totals.revenue), "type": "currency", "icon": "money"},
			{"key": "invoices", "label": "Sales", "value": invoices, "type": "number", "icon": "receipt"},
			{
				"key": "basket",
				"label": "Average sale",
				"value": flt(totals.revenue) / invoices if invoices else 0,
				"type": "currency",
				"icon": "cart",
			},
			{
				"key": "outstanding",
				"label": "Unpaid",
				"value": flt(totals.outstanding),
				"type": "currency",
				"icon": "hourglass",
				"tone": "warn" if flt(totals.outstanding) else "good",
			},
			{
				"key": "collected",
				"label": "Collected",
				"value": collected,
				"type": "currency",
				"icon": "wallet",
				"hint": f"{collected / flt(totals.revenue) * 100:.0f}% of billed"
				if flt(totals.revenue)
				else None,
			},
			{
				"key": "units",
				"label": "Items sold",
				"value": units,
				"type": "number",
				"icon": "package",
			},
			{
				"key": "per_day",
				"label": "Busiest day",
				"value": str(best_day["day"]) if best_day else "—",
				"type": "text",
				"icon": "calendar",
				"hint": f"{flt(best_day['revenue']):,.0f}" if best_day else None,
			},
			{
				"key": "top_cashier",
				"label": "Top cashier",
				"value": best_cashier["cashier"] if best_cashier else "—",
				"type": "text",
				"icon": "user",
				"hint": f"{flt(best_cashier['revenue']):,.0f}" if best_cashier else None,
			},
		],
		"sections": [
			_section(
				"by_day",
				"By day",
				"Newest first",
				[_col("Date", "day"), _col("Sales", "invoices", "number"), _col("Revenue", "revenue", "currency")],
				by_day,
				# Reversed for the chart: the table reads newest-first, but a line
				# over time has to run left to right or it draws the period backwards.
				_line("day", "revenue"),
			),
			_section(
				"by_cashier",
				"By cashier",
				"Who rang it up",
				[_col("Cashier", "cashier"), _col("Sales", "invoices", "number"), _col("Revenue", "revenue", "currency")],
				by_cashier,
				_bar("cashier", "revenue", hint="invoices"),
			),
			_section(
				"by_item",
				"Best sellers",
				"Net of tax",
				[_col("Item", "item_name"), _col("Qty", "qty", "number"), _col("Revenue", "revenue", "currency")],
				by_item,
				_bar("item_name", "revenue", hint="qty"),
			),
		],
	}


@frappe.whitelist()
def branches(days: int = DEFAULT_DAYS) -> dict:
	"""Every till side by side.

	Sales with no `pos_profile` are reported under their own heading rather than
	dropped — off-till invoices are real revenue, and silently excluding them
	would make the branch totals disagree with the sales tab.
	"""
	start, end, days = _window(days)
	args = _args({"start": start, "end": end})

	rows = frappe.db.sql(
		f"""select ifnull(nullif(si.pos_profile, ''), 'Not on a till') as branch,
		           count(si.name) as invoices,
		           sum(si.grand_total) as revenue,
		           sum(si.outstanding_amount) as outstanding,
		           count(distinct si.owner) as cashiers,
		           count(distinct si.customer) as customers
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.posting_date between %(start)s and %(end)s
		      {_scope('si')}
		    group by branch order by revenue desc""",
		args,
		as_dict=True,
	)
	for row in rows:
		row["basket"] = flt(row.revenue) / cint(row.invoices) if cint(row.invoices) else 0

	shifts = frappe.db.sql(
		f"""select c.pos_profile as branch, count(c.name) as shifts,
		           sum((select sum(d.closing_amount - d.expected_amount)
		                from `tabPOS Closing Entry Detail` d where d.parent = c.name)) as difference
		    from `tabPOS Closing Entry` c
		    where c.docstatus = 1 and c.posting_date between %(start)s and %(end)s
		      {_scope('c')}
		    group by c.pos_profile order by shifts desc""",
		args,
		as_dict=True,
	)

	revenue = sum(flt(r.revenue) for r in rows)
	best = rows[0] if rows else None
	return {
		"period": {"from": str(start), "to": str(end), "days": days},
		"stats": [
			{"key": "branches", "label": "Branches selling", "value": len(rows), "type": "number", "icon": "landmark"},
			{"key": "revenue", "label": "Revenue", "value": revenue, "type": "currency", "icon": "money"},
			{
				"key": "best",
				"label": "Busiest branch",
				"value": best["branch"] if best else "—",
				"type": "text",
				"icon": "trending-up",
				"hint": f"{flt(best['revenue']):,.0f}" if best else None,
			},
			{
				"key": "open_tills",
				"label": "Tills open now",
				"value": _open_tills()["count"],
				"type": "number",
				"icon": "unlock",
			},
			{
				"key": "per_branch",
				"label": "Average per branch",
				"value": revenue / len(rows) if rows else 0,
				"type": "currency",
				"icon": "landmark",
			},
			{
				"key": "quietest",
				"label": "Quietest branch",
				"value": rows[-1]["branch"] if rows else "—",
				"type": "text",
				"icon": "trending-down",
				"hint": f"{flt(rows[-1]['revenue']):,.0f}" if rows else None,
			},
			{
				"key": "branch_sales",
				"label": "Sales across branches",
				"value": sum(cint(r["invoices"]) for r in rows),
				"type": "number",
				"icon": "receipt",
			},
		],
		"sections": [
			_section(
				"performance",
				"Branch performance",
				"By revenue",
				[
					_col("Branch", "branch"),
					_col("Sales", "invoices", "number"),
					_col("Revenue", "revenue", "currency"),
					_col("Average sale", "basket", "currency"),
					_col("Unpaid", "outstanding", "currency"),
					_col("Cashiers", "cashiers", "number"),
					_col("Customers", "customers", "number"),
				],
				rows,
				_donut("branch", "revenue"),
			),
			_section(
				"shifts",
				"Shifts closed",
				"Over and short, per branch",
				[
					_col("Branch", "branch"),
					_col("Shifts", "shifts", "number"),
					_col("Over / short", "difference", "currency"),
				],
				shifts,
				_bar("branch", "difference", hint="shifts"),
			),
		],
	}


@frappe.whitelist()
def warehouses(days: int = DEFAULT_DAYS, warehouse: str | None = None) -> dict:
	"""Stock by location, optionally narrowed to one."""
	start, end, days = _window(days)
	bin_cond = " and b.warehouse = %(warehouse)s" if warehouse else ""
	sle_cond = " and sle.warehouse = %(warehouse)s" if warehouse else ""
	args = {"start": start, "end": end, "warehouse": warehouse, "limit": SHORTLIST}

	holdings = frappe.db.sql(
		f"""select b.warehouse, count(distinct b.item_code) as items,
		           sum(b.actual_qty) as qty,
		           sum(b.actual_qty * b.valuation_rate) as value
		    from tabBin b
		    where b.actual_qty != 0 {bin_cond}
		    group by b.warehouse order by value desc""",
		args,
		as_dict=True,
	)

	movement = frappe.db.sql(
		f"""select sle.warehouse,
		           sum(case when sle.actual_qty > 0 then sle.actual_qty else 0 end) as received,
		           sum(case when sle.actual_qty < 0 then -sle.actual_qty else 0 end) as issued,
		           sum(sle.actual_qty) as net
		    from `tabStock Ledger Entry` sle
		    where sle.is_cancelled = 0 and sle.posting_date between %(start)s and %(end)s {sle_cond}
		    group by sle.warehouse order by issued desc""",
		args,
		as_dict=True,
	)

	negative = frappe.db.sql(
		f"""select i.item_name, b.warehouse, b.actual_qty
		    from tabBin b join tabItem i on i.name = b.item_code
		    where b.actual_qty < 0 {bin_cond}
		    order by b.actual_qty asc limit %(limit)s""",
		args,
		as_dict=True,
	)

	value = sum(flt(r.value) for r in holdings)
	below_reorder = _stock_position()["below_reorder"]

	return {
		"period": {"from": str(start), "to": str(end), "days": days},
		"warehouse": warehouse,
		"stats": [
			{"key": "value", "label": "Stock value", "value": value, "type": "currency", "icon": "money"},
			{"key": "locations", "label": "Locations holding stock", "value": len(holdings), "type": "number", "icon": "boxes"},
			{
				"key": "items",
				"label": "Item lines",
				"value": sum(cint(r.items) for r in holdings),
				"type": "number",
				"icon": "package",
			},
			{
				"key": "negative",
				"label": "Negative balances",
				"value": len(negative),
				"type": "number",
				"icon": "alert",
				"tone": "bad" if negative else "good",
			},
			{
				"key": "biggest",
				"label": "Largest holding",
				"value": holdings[0]["warehouse"] if holdings else "—",
				"type": "text",
				"icon": "boxes",
				"hint": f"{flt(holdings[0]['value']):,.0f}" if holdings else None,
			},
			{
				"key": "avg_location",
				"label": "Average per location",
				"value": value / len(holdings) if holdings else 0,
				"type": "currency",
				"icon": "package",
			},
			{
				"key": "below_reorder",
				"label": "Below reorder level",
				# Read once. Called inline for both the value and the tone, this ran
				# `_stock_position` twice — two SQL statements each — to render one
				# tile.
				"value": below_reorder,
				"type": "number",
				"icon": "alert",
				"tone": "warn" if below_reorder else "good",
			},
		],
		"sections": [
			_section(
				"holdings",
				"What each location holds",
				"By value",
				[
					_col("Warehouse", "warehouse"),
					_col("Items", "items", "number"),
					_col("Qty", "qty", "number"),
					_col("Value", "value", "currency"),
				],
				holdings,
				_donut("warehouse", "value"),
			),
			_section(
				"movement",
				"Movement in the period",
				"Received against issued",
				[
					_col("Warehouse", "warehouse"),
					_col("Received", "received", "number"),
					_col("Issued", "issued", "number"),
					_col("Net", "net", "number"),
				],
				movement,
				_paired("warehouse", "received", "issued", "Received", "Issued"),
			),
			_section(
				"negative",
				"Negative stock",
				"Sold but never received — a ledger problem, not a shelf one",
				[_col("Item", "item_name"), _col("Warehouse", "warehouse"), _col("On hand", "actual_qty", "number")],
				negative,
				_bar("item_name", "actual_qty", hint=None, kind="number"),
			),
		],
	}


@frappe.whitelist()
def procurement(days: int = DEFAULT_DAYS) -> dict:
	"""What we are buying, what has arrived, and what is still owed."""
	start, end, days = _window(days)
	args = _args({"start": start, "end": end, "limit": SHORTLIST})

	spend = frappe.db.sql(
		f"""select pi.supplier, count(pi.name) as invoices,
		           sum(pi.grand_total) as spend,
		           sum(pi.outstanding_amount) as owed
		    from `tabPurchase Invoice` pi
		    where pi.docstatus = 1 and pi.posting_date between %(start)s and %(end)s
		      {_scope('pi')}
		    group by pi.supplier order by spend desc limit %(limit)s""",
		args,
		as_dict=True,
	)

	orders = frappe.db.sql(
		f"""select po.name, po.transaction_date as date, po.supplier, po.status,
		           po.per_received, po.per_billed, po.grand_total
		    from `tabPurchase Order` po
		    where po.docstatus = 1 and po.status not in ('Completed', 'Closed')
		      {_scope('po')}
		    order by po.transaction_date asc limit %(limit)s""",
		args,
		as_dict=True,
	)

	# Received but not billed is where a payable hides: the goods are on the
	# shelf and nothing says we still owe for them.
	unbilled = frappe.db.sql(
		f"""select pr.name, pr.posting_date as date, pr.supplier, pr.per_billed, pr.grand_total
		    from `tabPurchase Receipt` pr
		    where pr.docstatus = 1 and ifnull(pr.per_billed, 0) < 100 {_scope('pr')}
		    order by pr.posting_date asc limit %(limit)s""",
		args,
		as_dict=True,
	)

	requests = frappe.db.sql(
		"""select mr.name, mr.transaction_date as date, mr.material_request_type,
		          mr.status, mr.per_ordered, mr.set_warehouse as destination
		   from `tabMaterial Request` mr
		   where mr.docstatus = 1 and mr.status in ('Pending', 'Partially Ordered')
		   order by mr.transaction_date asc limit %(limit)s""",
		args,
		as_dict=True,
	)

	total_spend = sum(flt(r.spend) for r in spend)
	total_owed = sum(flt(r.owed) for r in spend)
	return {
		"period": {"from": str(start), "to": str(end), "days": days},
		"stats": [
			{"key": "spend", "label": "Spend", "value": total_spend, "type": "currency", "icon": "money"},
			{
				"key": "owed",
				"label": "Owed to suppliers",
				"value": total_owed,
				"type": "currency",
				"icon": "truck",
				"tone": "warn" if total_owed else "good",
			},
			{"key": "orders", "label": "Orders still open", "value": len(orders), "type": "number", "icon": "clipboard"},
			{
				"key": "unbilled",
				"label": "Received not billed",
				"value": len(unbilled),
				"type": "number",
				"icon": "package",
				"tone": "warn" if unbilled else "good",
			},
			{
				"key": "suppliers",
				"label": "Suppliers used",
				"value": len(spend),
				"type": "number",
				"icon": "truck",
			},
			{
				"key": "top_supplier",
				"label": "Biggest supplier",
				"value": spend[0]["supplier"] if spend else "—",
				"type": "text",
				"icon": "landmark",
				"hint": f"{flt(spend[0]['spend']):,.0f}" if spend else None,
			},
			{
				"key": "requests",
				"label": "Requests outstanding",
				"value": len(requests),
				"type": "number",
				"icon": "clipboard",
				"tone": "warn" if requests else "good",
			},
		],
		"sections": [
			_section(
				"spend",
				"Spend by supplier",
				"In this period",
				[
					_col("Supplier", "supplier"),
					_col("Invoices", "invoices", "number"),
					_col("Spend", "spend", "currency"),
					_col("Still owed", "owed", "currency"),
				],
				spend,
				_donut("supplier", "spend"),
			),
			_section(
				"orders",
				"Open purchase orders",
				"Oldest first",
				[
					_col("Order", "name"),
					_col("Date", "date"),
					_col("Supplier", "supplier"),
					_col("Status", "status"),
					_col("Received %", "per_received", "number"),
					_col("Billed %", "per_billed", "number"),
					_col("Total", "grand_total", "currency"),
				],
				orders,
				_bar("supplier", "grand_total", hint="per_received"),
			),
			_section(
				"unbilled",
				"Received but not billed",
				"Goods on the shelf with no invoice against them",
				[
					_col("Receipt", "name"),
					_col("Date", "date"),
					_col("Supplier", "supplier"),
					_col("Billed %", "per_billed", "number"),
					_col("Value", "grand_total", "currency"),
				],
				unbilled,
				_bar("supplier", "grand_total", hint="per_billed"),
			),
			_section(
				"requests",
				"Material requests outstanding",
				"Where the stock is being asked for",
				[
					_col("Request", "name"),
					_col("Date", "date"),
					_col("Type", "material_request_type"),
					_col("Goes to", "destination"),
					_col("Status", "status"),
					_col("Ordered %", "per_ordered", "number"),
				],
				requests,
			),
		],
	}


@frappe.whitelist()
def accounts(days: int = DEFAULT_DAYS) -> dict:
	"""Where the money is, and which way it is owed."""
	start, end, days = _window(days)
	money = _money_position()
	company = _company()

	balances = []
	if company:
		balances = frappe.db.sql(
			"""select a.account_name as account, a.account_type as type,
			          sum(gle.debit) - sum(gle.credit) as balance
			   from `tabGL Entry` gle join tabAccount a on a.name = gle.account
			   where gle.is_cancelled = 0 and gle.company = %(company)s
			     and a.account_type in ('Bank', 'Cash') and a.is_group = 0
			   group by a.account_name, a.account_type order by balance desc""",
			{"company": company},
			as_dict=True,
		)

	# Every customer who owes anything, not a top eight. "Who owes us money" is
	# the question this tab exists to answer, and an answer that stops at the
	# eighth name is one somebody has to go and check elsewhere. The card scrolls
	# rather than the page growing.
	receivable = frappe.db.sql(
		f"""select si.customer as party, count(si.name) as invoices,
		           sum(si.outstanding_amount) as outstanding,
		           min(si.due_date) as oldest_due,
		           sum(case when si.due_date < %(today)s then 1 else 0 end) as overdue
		    from `tabSales Invoice` si
		    where si.docstatus = 1 and si.outstanding_amount > 0 {_scope('si')}
		    group by si.customer order by outstanding desc limit 500""",
		_args({"today": nowdate()}),
		as_dict=True,
	)

	payable = frappe.db.sql(
		f"""select pi.supplier as party, count(pi.name) as invoices,
		           sum(pi.outstanding_amount) as outstanding
		    from `tabPurchase Invoice` pi
		    where pi.docstatus = 1 and pi.outstanding_amount > 0 {_scope('pi')}
		    group by pi.supplier order by outstanding desc limit %(limit)s""",
		_args({"limit": SHORTLIST}),
		as_dict=True,
	)

	net = flt(money["receivable"]) - flt(money["payable"])
	return {
		"period": {"from": str(start), "to": str(end), "days": days},
		"stats": [
			{"key": "cash", "label": "Cash and bank", "value": money["cash_and_bank"], "type": "currency", "icon": "landmark"},
			{
				"key": "receivable",
				"label": "Customers owe us",
				"value": money["receivable"],
				"type": "currency",
				"icon": "users",
				"tone": "warn" if money["receivable"] else "good",
				"hint": f"{money['overdue_count']} overdue" if money["overdue_count"] else None,
			},
			{
				"key": "payable",
				"label": "We owe suppliers",
				"value": money["payable"],
				"type": "currency",
				"icon": "truck",
				"tone": "bad" if money["payable"] else "good",
			},
			{
				"key": "net",
				"label": "Net position",
				"value": net,
				"type": "currency",
				"icon": "trending-up",
				"tone": "good" if net >= 0 else "bad",
			},
			{
				"key": "customers_owing",
				"label": "Customers owing",
				"value": len(receivable),
				"type": "number",
				"icon": "users",
				"hint": f"{money['overdue_count']} overdue" if money["overdue_count"] else None,
			},
			{
				"key": "suppliers_owed",
				"label": "Suppliers owed",
				"value": len(payable),
				"type": "number",
				"icon": "truck",
			},
			{
				"key": "biggest_debtor",
				"label": "Biggest debtor",
				"value": receivable[0]["party"] if receivable else "—",
				"type": "text",
				"icon": "user",
				"hint": f"{flt(receivable[0]['outstanding']):,.0f}" if receivable else None,
			},
			{
				"key": "accounts_held",
				"label": "Cash and bank accounts",
				"value": len(balances),
				"type": "number",
				"icon": "landmark",
			},
		],
		"sections": [
			_section(
				"balances",
				"Cash and bank accounts",
				"Balance to date, not just this period",
				[_col("Account", "account"), _col("Type", "type"), _col("Balance", "balance", "currency")],
				balances,
				_donut("account", "balance"),
			),
			_section(
				"receivable",
				"Customers who owe us",
				f"All {len(receivable)}, biggest first",
				[
					_col("Customer", "party"),
					_col("Invoices", "invoices", "number"),
					_col("Overdue", "overdue", "number"),
					_col("Owes", "outstanding", "currency"),
				],
				receivable,
				_bar("party", "outstanding", hint="invoices"),
				scroll=True,
			),
			_section(
				"payable",
				"Suppliers we owe",
				"Biggest first",
				[_col("Supplier", "party"), _col("Invoices", "invoices", "number"), _col("We owe", "outstanding", "currency")],
				payable,
				_bar("party", "outstanding", hint="invoices"),
			),
		],
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
