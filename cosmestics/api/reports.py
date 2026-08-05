"""Reports a shop actually runs.

Each returns {columns, rows, totals} in one shape, so the front end renders them
all through a single table rather than a bespoke component per report.

Aggregation is done in SQL: these span whole periods, and pulling every invoice
line into Python to sum it would not survive a busy month.
"""

import frappe
from frappe.utils import add_days, flt, nowdate

#: `hint` says what question the report answers, in the words somebody would ask
#: it. The picker is a set of cards rather than a list of labels, and a label
#: alone ("Dead stock", "Audit trail") does not tell a shop manager whether it is
#: the one they want — which is how a report nobody opens ends up unused.
REPORTS = [
	{
		"key": "sales_summary",
		"label": "Sales summary",
		"group": "Sales",
		"hint": "Revenue and invoice count, day by day",
	},
	{
		"key": "top_items",
		"label": "Best sellers",
		"group": "Sales",
		"hint": "What actually moves, by quantity and revenue",
	},
	{
		"key": "payment_modes",
		"label": "Payment modes",
		"group": "Sales",
		"hint": "How customers paid — cash against each M-Pesa channel",
	},
	{
		"key": "profit_margin",
		"label": "Profit margin",
		"group": "Sales",
		"hint": "What each item earns after what it cost",
	},
	{
		"key": "cashier_sales",
		"label": "Sales by cashier",
		"group": "Sales",
		"hint": "Who sold what, over the period",
	},
	{
		"key": "stock_balance",
		"label": "Stock balance",
		"group": "Inventory",
		"hint": "What is on hand and what it is worth",
	},
	{
		"key": "below_reorder",
		"label": "Below reorder level",
		"group": "Inventory",
		"hint": "The buy list — what has fallen under its level",
	},
	{
		"key": "dead_stock",
		"label": "Dead stock",
		"group": "Inventory",
		"hint": "Money sitting on the shelf that has not sold",
	},
	{
		"key": "stock_movement",
		"label": "Stock movement",
		"group": "Inventory",
		"hint": "What came in and what went out, and on which document",
	},
	{
		"key": "receivables",
		"label": "Customer balances",
		"group": "Accounts",
		"hint": "Who owes you, oldest first",
	},
	{
		"key": "payables",
		"label": "Supplier balances",
		"group": "Accounts",
		"hint": "Who you owe, and how much",
	},
	{
		"key": "tax_collected",
		"label": "Tax collected",
		"group": "Accounts",
		"hint": "VAT charged over the period",
	},
	{
		"key": "shift_history",
		"label": "Shift history",
		"group": "Audit",
		"hint": "Every till close, and whether it balanced",
	},
	{
		"key": "audit_trail",
		"label": "User audit trail",
		"group": "Audit",
		"hint": "Who created what, and when",
	},
	{
		"key": "price_changes",
		"label": "Price changes",
		"group": "Audit",
		"hint": "What was repriced, and by whom",
	},
	{
		"key": "sales_returns",
		"label": "Sales returns",
		"group": "Sales",
		"hint": "What customers brought back, and what it cost you",
	},
	{
		"key": "neighbour_returns",
		"label": "Returns to neighbours",
		"group": "Purchasing",
		"hint": "Stock sent back to the shop next door",
	},
	{
		"key": "cancelled_docs",
		"label": "Cancelled & amended",
		"group": "Audit",
		"hint": "Documents that were undone after submitting",
	},
]


@frappe.whitelist()
def list_reports():
	return REPORTS


def _window(days):
	days = int(days or 30)
	return add_days(nowdate(), -days), nowdate()


@frappe.whitelist()
def run(report: str, days: int = 30, warehouse: str | None = None):
	fn = {
		"sales_summary": _sales_summary,
		"top_items": _top_items,
		"payment_modes": _payment_modes,
		"profit_margin": _profit_margin,
		"cashier_sales": _cashier_sales,
		"stock_balance": _stock_balance,
		"below_reorder": _below_reorder,
		"dead_stock": _dead_stock,
		"receivables": _receivables,
		"payables": _payables,
		"tax_collected": _tax_collected,
		"shift_history": _shift_history,
		"audit_trail": _audit_trail,
		"price_changes": _price_changes,
		"sales_returns": _sales_returns,
		"neighbour_returns": _neighbour_returns,
		"cancelled_docs": _cancelled_docs,
		"stock_movement": _stock_movement,
	}.get(report)

	if not fn:
		frappe.throw(frappe._("Unknown report: {0}").format(report))

	return fn(days, warehouse)


def _money(label, key):
	return {"label": label, "key": key, "type": "currency"}


def _num(label, key):
	return {"label": label, "key": key, "type": "number"}


def _text(label, key):
	return {"label": label, "key": key, "type": "text"}


# ---------------- Sales ----------------


def _sales_summary(days, _wh):
	start, end = _window(days)
	rows = frappe.db.sql(
		"""select posting_date as day, count(name) as invoices,
		          sum(grand_total) as revenue, sum(net_total) as net,
		          sum(total_taxes_and_charges) as tax
		   from `tabSales Invoice`
		   where docstatus = 1 and posting_date between %s and %s
		   group by posting_date order by posting_date desc""",
		(start, end),
		as_dict=True,
	)
	return {
		"columns": [
			_text("Date", "day"),
			_num("Invoices", "invoices"),
			_money("Net", "net"),
			_money("Tax", "tax"),
			_money("Revenue", "revenue"),
		],
		"rows": rows,
		"totals": {
			"invoices": sum(flt(r.invoices) for r in rows),
			"revenue": sum(flt(r.revenue) for r in rows),
		},
	}


def _top_items(days, _wh):
	start, end = _window(days)
	rows = frappe.db.sql(
		"""select sii.item_code, sii.item_name,
		          sum(sii.qty) as qty, sum(sii.base_net_amount) as revenue
		   from `tabSales Invoice Item` sii
		   join `tabSales Invoice` si on si.name = sii.parent
		   where si.docstatus = 1 and si.posting_date between %s and %s
		   group by sii.item_code, sii.item_name
		   order by revenue desc limit 50""",
		(start, end),
		as_dict=True,
	)
	return {
		"columns": [
			_text("Item", "item_name"),
			_text("Code", "item_code"),
			_num("Qty sold", "qty"),
			_money("Revenue", "revenue"),
		],
		"rows": rows,
		"totals": {"revenue": sum(flt(r.revenue) for r in rows)},
	}


def _payment_modes(days, _wh):
	start, end = _window(days)
	rows = frappe.db.sql(
		"""select sip.mode_of_payment, count(distinct sip.parent) as invoices,
		          sum(sip.amount) as amount
		   from `tabSales Invoice Payment` sip
		   join `tabSales Invoice` si on si.name = sip.parent
		   where si.docstatus = 1 and si.posting_date between %s and %s
		   group by sip.mode_of_payment order by amount desc""",
		(start, end),
		as_dict=True,
	)
	return {
		"columns": [
			_text("Mode", "mode_of_payment"),
			_num("Invoices", "invoices"),
			_money("Collected", "amount"),
		],
		"rows": rows,
		"totals": {"amount": sum(flt(r.amount) for r in rows)},
	}


def _profit_margin(days, _wh):
	"""Revenue against cost of goods actually delivered.

	COGS comes from the stock ledger's valuation, not a price list, so the
	margin reflects what the stock really cost.
	"""
	start, end = _window(days)
	rows = frappe.db.sql(
		"""select sii.item_code, sii.item_name,
		          sum(sii.qty) as qty,
		          sum(sii.base_net_amount) as revenue,
		          sum(ifnull(sii.incoming_rate, 0) * sii.qty) as cost
		   from `tabSales Invoice Item` sii
		   join `tabSales Invoice` si on si.name = sii.parent
		   where si.docstatus = 1 and si.posting_date between %s and %s
		   group by sii.item_code, sii.item_name
		   order by revenue desc limit 100""",
		(start, end),
		as_dict=True,
	)
	for r in rows:
		r["margin"] = flt(r.revenue) - flt(r.cost)
		r["margin_pct"] = round(r["margin"] / flt(r.revenue) * 100, 1) if flt(r.revenue) else 0

	return {
		"columns": [
			_text("Item", "item_name"),
			_num("Qty", "qty"),
			_money("Revenue", "revenue"),
			_money("Cost", "cost"),
			_money("Margin", "margin"),
			_num("Margin %", "margin_pct"),
		],
		"rows": rows,
		"totals": {
			"revenue": sum(flt(r["revenue"]) for r in rows),
			"margin": sum(flt(r["margin"]) for r in rows),
		},
	}


def _cashier_sales(days, _wh):
	start, end = _window(days)
	rows = frappe.db.sql(
		"""select owner as cashier, count(name) as invoices,
		          sum(grand_total) as revenue
		   from `tabSales Invoice`
		   where docstatus = 1 and posting_date between %s and %s
		   group by owner order by revenue desc""",
		(start, end),
		as_dict=True,
	)
	return {
		"columns": [
			_text("Cashier", "cashier"),
			_num("Invoices", "invoices"),
			_money("Revenue", "revenue"),
		],
		"rows": rows,
		"totals": {"revenue": sum(flt(r.revenue) for r in rows)},
	}


# ---------------- Inventory ----------------


def _stock_balance(_days, warehouse):
	cond = "and b.warehouse = %(wh)s" if warehouse else ""
	rows = frappe.db.sql(
		f"""select b.item_code, i.item_name, b.warehouse,
		           b.actual_qty, b.valuation_rate,
		           b.actual_qty * b.valuation_rate as value
		    from tabBin b join tabItem i on i.name = b.item_code
		    where b.actual_qty != 0 {cond}
		    order by value desc limit 500""",
		{"wh": warehouse},
		as_dict=True,
	)
	return {
		"columns": [
			_text("Item", "item_name"),
			_text("Warehouse", "warehouse"),
			_num("Qty", "actual_qty"),
			_money("Rate", "valuation_rate"),
			_money("Value", "value"),
		],
		"rows": rows,
		"totals": {"value": sum(flt(r.value) for r in rows)},
	}


def _below_reorder(_days, warehouse):
	"""Items at or under their configured reorder level — the buy list."""
	cond = "and ir.warehouse = %(wh)s" if warehouse else ""
	rows = frappe.db.sql(
		f"""select ir.parent as item_code, i.item_name, ir.warehouse,
		           ifnull(b.actual_qty, 0) as actual_qty,
		           ir.warehouse_reorder_level as reorder_level,
		           ir.warehouse_reorder_qty as reorder_qty,
		           ir.warehouse_reorder_level - ifnull(b.actual_qty, 0) as shortfall
		    from `tabItem Reorder` ir
		    join tabItem i on i.name = ir.parent
		    left join tabBin b on b.item_code = ir.parent and b.warehouse = ir.warehouse
		    where ifnull(b.actual_qty, 0) <= ir.warehouse_reorder_level {cond}
		    order by shortfall desc limit 500""",
		{"wh": warehouse},
		as_dict=True,
	)
	return {
		"columns": [
			_text("Item", "item_name"),
			_text("Warehouse", "warehouse"),
			_num("On hand", "actual_qty"),
			_num("Reorder at", "reorder_level"),
			_num("Short by", "shortfall"),
			_num("Order qty", "reorder_qty"),
		],
		"rows": rows,
		"totals": {"lines": len(rows)},
	}


def _dead_stock(days, warehouse):
	"""Stock on hand with no outward movement in the window — cash on a shelf."""
	start, _ = _window(days)
	cond = "and b.warehouse = %(wh)s" if warehouse else ""
	rows = frappe.db.sql(
		f"""select b.item_code, i.item_name, b.warehouse, b.actual_qty,
		           b.actual_qty * b.valuation_rate as value
		    from tabBin b join tabItem i on i.name = b.item_code
		    where b.actual_qty > 0 {cond}
		      and not exists (
		        select 1 from `tabStock Ledger Entry` sle
		        where sle.item_code = b.item_code and sle.warehouse = b.warehouse
		          and sle.actual_qty < 0 and sle.is_cancelled = 0
		          and sle.posting_date >= %(start)s)
		    order by value desc limit 500""",
		{"wh": warehouse, "start": start},
		as_dict=True,
	)
	return {
		"columns": [
			_text("Item", "item_name"),
			_text("Warehouse", "warehouse"),
			_num("Qty", "actual_qty"),
			_money("Tied-up value", "value"),
		],
		"rows": rows,
		"totals": {"value": sum(flt(r.value) for r in rows)},
	}


# ---------------- Accounts ----------------


def _receivables(_days, _wh):
	rows = frappe.db.sql(
		"""select customer, count(name) as invoices,
		          sum(outstanding_amount) as outstanding
		   from `tabSales Invoice`
		   where docstatus = 1 and outstanding_amount > 0
		   group by customer order by outstanding desc limit 200""",
		as_dict=True,
	)
	return {
		"columns": [
			_text("Customer", "customer"),
			_num("Invoices", "invoices"),
			_money("Owes", "outstanding"),
		],
		"rows": rows,
		"totals": {"outstanding": sum(flt(r.outstanding) for r in rows)},
	}


def _payables(_days, _wh):
	rows = frappe.db.sql(
		"""select supplier, count(name) as invoices,
		          sum(outstanding_amount) as outstanding
		   from `tabPurchase Invoice`
		   where docstatus = 1 and outstanding_amount > 0
		   group by supplier order by outstanding desc limit 200""",
		as_dict=True,
	)
	return {
		"columns": [
			_text("Supplier", "supplier"),
			_num("Invoices", "invoices"),
			_money("We owe", "outstanding"),
		],
		"rows": rows,
		"totals": {"outstanding": sum(flt(r.outstanding) for r in rows)},
	}


# ---------------- Audit ----------------


def _tax_collected(days, _wh):
	start, end = _window(days)
	rows = frappe.db.sql(
		"""select t.account_head, t.description,
		          sum(t.base_tax_amount) as tax, count(distinct t.parent) as invoices
		   from `tabSales Taxes and Charges` t
		   join `tabSales Invoice` si on si.name = t.parent
		   where si.docstatus = 1 and si.posting_date between %s and %s
		   group by t.account_head, t.description order by tax desc""",
		(start, end),
		as_dict=True,
	)
	return {
		"columns": [
			_text("Account", "account_head"),
			_text("Description", "description"),
			_num("Invoices", "invoices"),
			_money("Tax", "tax"),
		],
		"rows": rows,
		"totals": {"tax": sum(flt(r.tax) for r in rows)},
	}


def _shift_history(days, _wh):
	"""Closed tills with their over/short, which is the number that matters."""
	start, end = _window(days)
	rows = frappe.db.sql(
		"""select c.name, c.posting_date as day, c.user as cashier, c.pos_profile,
		          c.grand_total, c.total_quantity,
		          (select sum(d.closing_amount - d.expected_amount)
		             from `tabPOS Closing Entry Detail` d where d.parent = c.name) as difference
		   from `tabPOS Closing Entry` c
		   where c.docstatus = 1 and c.posting_date between %s and %s
		   order by c.posting_date desc""",
		(start, end),
		as_dict=True,
	)
	return {
		"columns": [
			_text("Closing", "name"),
			_text("Date", "day"),
			_text("Cashier", "cashier"),
			_text("Till", "pos_profile"),
			_money("Sales", "grand_total"),
			_money("Over / short", "difference"),
		],
		"rows": rows,
		"totals": {
			"grand_total": sum(flt(r.grand_total) for r in rows),
			"difference": sum(flt(r.difference) for r in rows),
		},
	}


def _audit_trail(days, _wh):
	"""Who submitted or cancelled what.

	Read from Version, Frappe's own change log, rather than a table this app
	maintains — anything written through the desk is captured too.
	"""
	start, _ = _window(days)
	rows = frappe.db.sql(
		"""select v.ref_doctype as doctype, v.docname, v.owner as user,
		          v.creation as changed_at
		   from tabVersion v
		   where v.creation >= %s
		     and v.ref_doctype in (
		       'Sales Invoice','Purchase Invoice','Item','Item Price',
		       'POS Opening Entry','POS Closing Entry','Stock Entry','Customer')
		   order by v.creation desc limit 500""",
		start,
		as_dict=True,
	)
	return {
		"columns": [
			_text("When", "changed_at"),
			_text("User", "user"),
			_text("Type", "doctype"),
			_text("Document", "docname"),
		],
		"rows": rows,
		"totals": {"changes": len(rows)},
	}


def _price_changes(days, _wh):
	"""Price edits are the change most worth being able to trace back."""
	start, _ = _window(days)
	rows = frappe.db.sql(
		"""select ip.item_code, ip.price_list, ip.price_list_rate as price,
		          ip.modified_by as changed_by, ip.modified as changed_at
		   from `tabItem Price` ip
		   where ip.modified >= %s
		   order by ip.modified desc limit 500""",
		start,
		as_dict=True,
	)
	return {
		"columns": [
			_text("When", "changed_at"),
			_text("By", "changed_by"),
			_text("Item", "item_code"),
			_text("Price list", "price_list"),
			_money("Price", "price"),
		],
		"rows": rows,
		"totals": {"changes": len(rows)},
	}


def _sales_returns(days, _wh):
	"""Goods customers brought back.

	A return in ERPNext is a Sales Invoice with `is_return=1` and negative
	quantities, so the figures come back negative. They are left that way rather
	than flipped: a return *is* a reduction, and a screen full of positive
	numbers under a heading called "returns" is the kind of thing that gets added
	to revenue by mistake.

	`return_against` names the original sale, which is the column anybody
	investigating a return actually needs.
	"""
	start, end = _window(days)
	rows = frappe.db.sql(
		"""select si.posting_date as day, si.name, si.customer,
		          si.return_against, si.grand_total, si.total_qty as qty,
		          si.owner as user
		   from `tabSales Invoice` si
		   where si.docstatus = 1 and si.is_return = 1
		     and si.posting_date between %s and %s
		   order by si.posting_date desc, si.creation desc limit 300""",
		(start, end),
		as_dict=True,
	)
	return {
		"columns": [
			_text("Date", "day"),
			_text("Credit note", "name"),
			_text("Customer", "customer"),
			_text("Against", "return_against"),
			_text("Taken by", "user"),
			_num("Units", "qty"),
			_money("Value", "grand_total"),
		],
		"rows": rows,
		"totals": {
			"returns": len(rows),
			"value": flt(sum(flt(r.grand_total) for r in rows)),
			"units": flt(sum(flt(r.qty) for r in rows)),
		},
	}


def _neighbour_returns(days, _wh):
	"""Stock sent back to the shop it was bought from.

	Scoped to suppliers flagged as neighbour shops, because a return to a
	wholesaler is ordinary purchasing and a return to the shop next door is
	the till undoing something it did mid-sale — different people chase them.
	"""
	start, end = _window(days)

	rows = frappe.db.sql(
		"""select pi.posting_date as day, pi.name, pi.supplier,
		          pi.return_against, pi.grand_total, pi.total_qty as qty,
		          pi.owner as user
		   from `tabPurchase Invoice` pi
		   join tabSupplier s on s.name = pi.supplier
		   where pi.docstatus = 1 and pi.is_return = 1
		     and s.cosmestics_is_neighbour_shop = 1
		     and pi.posting_date between %s and %s
		   order by pi.posting_date desc, pi.creation desc limit 300""",
		(start, end),
		as_dict=True,
	)
	return {
		"columns": [
			_text("Date", "day"),
			_text("Debit note", "name"),
			_text("Shop", "supplier"),
			_text("Against", "return_against"),
			_text("Sent by", "user"),
			_num("Units", "qty"),
			_money("Value", "grand_total"),
		],
		"rows": rows,
		"totals": {
			"returns": len(rows),
			"value": flt(sum(flt(r.grand_total) for r in rows)),
		},
	}


def _cancelled_docs(days, _wh):
	"""Cancellations and amendments — where losses and mistakes hide."""
	start, end = _window(days)
	rows = frappe.db.sql(
		"""select 'Sales Invoice' as doctype, name, posting_date as day,
		          owner as user, grand_total, amended_from
		   from `tabSales Invoice`
		   where docstatus = 2 and posting_date between %s and %s
		   union all
		   select 'Purchase Invoice', name, posting_date, owner, grand_total, amended_from
		   from `tabPurchase Invoice`
		   where docstatus = 2 and posting_date between %s and %s
		   order by day desc limit 300""",
		(start, end, start, end),
		as_dict=True,
	)
	return {
		"columns": [
			_text("Date", "day"),
			_text("Type", "doctype"),
			_text("Document", "name"),
			_text("User", "user"),
			_money("Value", "grand_total"),
			_text("Amended from", "amended_from"),
		],
		"rows": rows,
		"totals": {"cancelled": len(rows)},
	}


def _stock_movement(days, warehouse):
	start, end = _window(days)
	cond = "and sle.warehouse = %(wh)s" if warehouse else ""
	rows = frappe.db.sql(
		f"""select sle.item_code, i.item_name, sle.warehouse,
		           sum(case when sle.actual_qty > 0 then sle.actual_qty else 0 end) as received,
		           sum(case when sle.actual_qty < 0 then -sle.actual_qty else 0 end) as issued,
		           sum(sle.actual_qty) as net
		    from `tabStock Ledger Entry` sle
		    join tabItem i on i.name = sle.item_code
		    where sle.is_cancelled = 0 and sle.posting_date between %(start)s and %(end)s {cond}
		    group by sle.item_code, i.item_name, sle.warehouse
		    order by issued desc limit 500""",
		{"wh": warehouse, "start": start, "end": end},
		as_dict=True,
	)
	return {
		"columns": [
			_text("Item", "item_name"),
			_text("Warehouse", "warehouse"),
			_num("Received", "received"),
			_num("Issued", "issued"),
			_num("Net", "net"),
		],
		"rows": rows,
		"totals": {"issued": sum(flt(r.issued) for r in rows)},
	}
