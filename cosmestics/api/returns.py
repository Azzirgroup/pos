"""Taking goods back at the till.

A customer returning something is a sale running backwards: the stock comes
back on the shelf and the money goes back across the counter. ERPNext models
that as a Sales Invoice with `is_return=1` and negative quantities — a credit
note — so that is what this creates rather than anything invented.

## The one real decision: where the money goes

Two refund routes, and they book differently on purpose.

**Cash** creates the credit note as a *POS* invoice inside the current shift,
with a negative payment row. That matters more than it looks: the shift's
closing summary is built from `get_invoices`, which sums the payment rows of
every POS invoice in the window. A negative row therefore reduces what the
drawer is expected to hold, automatically and by exactly the refund. No separate
movement is recorded — one would double-count the same cash.

**Credit** creates it as an ordinary credit note. Nothing leaves the drawer; the
customer's account carries the balance until they spend it or it is paid out.
That needs a named customer, for the same reason a credit sale does — a walk-in
has no account to hold it.

## Partial returns

What has already come back is tracked per line, so two returns of the same item
cannot exceed what was sold. Without that a determined customer could be
refunded twice for one purchase, and nothing in ERPNext would object.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate, nowtime

#: Refund routes. Anything else is refused rather than guessed at — a refund
#: booked the wrong way is money that reconciles nowhere.
REFUND_METHODS = ("cash", "credit")


@frappe.whitelist()
def returnable_sale(invoice: str) -> dict:
	"""A sale's lines, with how much of each can still come back.

	Fetched before the form is drawn so the cashier is choosing from what is
	actually returnable, rather than typing a quantity and being refused.
	"""
	doc = frappe.get_doc("Sales Invoice", invoice)
	if doc.docstatus != 1:
		frappe.throw(_("{0} is not a completed sale").format(invoice))
	if doc.get("is_return"):
		frappe.throw(_("{0} is already a return").format(invoice))

	returned = _already_returned(invoice)

	items = []
	for row in doc.items:
		available = flt(row.qty) - returned.get(row.item_code, 0)
		items.append(
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"sold_qty": flt(row.qty),
				"returned_qty": returned.get(row.item_code, 0),
				"qty": max(available, 0),
				"rate": flt(row.rate),
				"value": flt(row.rate) * max(available, 0),
				"uom": row.uom,
			}
		)

	return {
		"invoice": doc.name,
		"customer": doc.customer,
		"customer_name": doc.customer_name or doc.customer,
		"posting_date": str(doc.posting_date),
		"grand_total": flt(doc.grand_total),
		"outstanding": flt(doc.outstanding_amount),
		"is_pos": bool(doc.is_pos),
		"items": items,
		# Nothing left to give back — said here so the till can grey the action
		# out rather than opening a form with no rows in it.
		"fully_returned": not any(i["qty"] > 0 for i in items),
	}


def _already_returned(invoice: str) -> dict:
	"""Per item, how much of this sale has come back already."""
	rows = frappe.db.sql(
		"""select sii.item_code, sum(abs(sii.qty)) as qty
		   from `tabSales Invoice Item` sii
		   join `tabSales Invoice` si on si.name = sii.parent
		   where si.docstatus = 1 and si.is_return = 1 and si.return_against = %s
		   group by sii.item_code""",
		(invoice,),
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}


@frappe.whitelist(methods=["POST"])
def create_sales_return(
	invoice: str,
	lines: list | str | None = None,
	refund_method: str = "cash",
	reason: str | None = None,
) -> dict:
	"""Take goods back and refund them.

	`lines` is [{item_code, qty}] for a partial return; omit it to take back
	everything still returnable.
	"""
	if isinstance(lines, str):
		lines = frappe.parse_json(lines)

	if refund_method not in REFUND_METHODS:
		frappe.throw(_("{0} is not a way to refund").format(refund_method))

	from cosmestics.api.pos import _active_pos_profile, _payment_account

	original = frappe.get_doc("Sales Invoice", invoice)
	if original.docstatus != 1:
		frappe.throw(_("{0} is not a completed sale").format(invoice))
	if original.get("is_return"):
		frappe.throw(_("{0} is already a return").format(invoice))

	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	returned = _already_returned(invoice)
	wanted = {r["item_code"]: flt(r.get("qty")) for r in (lines or [])}

	doc = frappe.new_doc("Sales Invoice")
	doc.customer = original.customer
	doc.company = original.company
	doc.posting_date = nowdate()
	doc.posting_time = nowtime()
	doc.set_posting_time = 1
	doc.is_return = 1
	doc.return_against = original.name
	# The original moved stock on submit, so the return has to move it back or
	# the shelf never regains what the customer just handed over.
	doc.update_stock = original.update_stock
	if original.set_warehouse:
		doc.set_warehouse = original.set_warehouse
	if settings.selling_price_list:
		doc.selling_price_list = settings.selling_price_list

	for row in original.items:
		available = flt(row.qty) - returned.get(row.item_code, 0)
		qty = wanted.get(row.item_code, available) if lines else available
		if qty <= 0:
			continue
		if qty > available:
			frappe.throw(
				_("Only {0} of {1} can still be returned on {2}").format(
					available, row.item_code, invoice
				)
			)
		doc.append(
			"items",
			{
				"item_code": row.item_code,
				# Negative quantity is what makes this a return to ERPNext.
				"qty": -abs(qty),
				"rate": flt(row.rate),
				"warehouse": row.warehouse or original.set_warehouse,
				"sales_invoice_item": row.name,
			},
		)

	if not doc.items:
		frappe.throw(_("Nothing left to return on {0}").format(invoice))

	doc.remarks = reason or _("Returned against {0}").format(original.name)

	doc.set_missing_values()
	doc.calculate_taxes_and_totals()
	total = flt(doc.rounded_total or doc.grand_total)

	if refund_method == "cash":
		_refund_in_cash(doc, original, total, settings, _active_pos_profile, _payment_account)
	else:
		_refund_as_credit(doc, original)

	doc.insert()
	doc.submit()

	return {
		"name": doc.name,
		"against": original.name,
		"customer": doc.customer,
		# Positive: the cashier is being told how much to hand back, not signing
		# a ledger. The document itself is correctly negative.
		"refunded": abs(total),
		"method": refund_method,
		"items": len(doc.items),
		"outstanding": flt(doc.outstanding_amount),
	}


def _refund_in_cash(doc, original, total, settings, active_profile, payment_account):
	"""Hand the money back across the counter, inside the shift.

	Made a POS invoice with a negative payment row so the shift's own arithmetic
	picks it up: `get_closing_summary` sums the payment rows of every POS invoice
	in the window, so a negative row reduces the expected drawer by exactly the
	refund. Recording a separate till movement as well would subtract it twice.

	Falls back to a credit note when no shift is open — ERPNext refuses a POS
	invoice with no matching opening entry, and a shop must never be unable to
	take goods back just because nobody opened a shift.
	"""
	profile = active_profile()
	mode = settings.mode_cash or frappe.db.get_value(
		"Mode of Payment", {"type": "Cash", "enabled": 1}, "name"
	)

	if not profile or not mode:
		_refund_as_credit(doc, original)
		return

	doc.is_pos = 1
	doc.pos_profile = profile
	doc.is_created_using_pos = 1
	doc.append(
		"payments",
		{
			"mode_of_payment": mode,
			# Negative: money leaving the drawer, which is what a refund is.
			"amount": -abs(total),
			"account": payment_account(mode, doc.company),
		},
	)


def _refund_as_credit(doc, original):
	"""Leave the money on the customer's account.

	Needs somebody to hold it, for the same reason a credit sale does. A walk-in
	has no account, so the refund would sit against the shared walk-in customer
	where nobody could ever claim it — better to refuse and let the cashier
	either name the customer or hand back cash.
	"""
	from cosmestics.api.pos import WALK_IN_CUSTOMER

	if not doc.customer or doc.customer == WALK_IN_CUSTOMER:
		frappe.throw(
			_(
				"A credit refund needs a named customer — otherwise nobody can claim it. "
				"Refund in cash, or put the sale against a customer first."
			)
		)
	doc.is_pos = 0


@frappe.whitelist()
def list_returns(days: int = 30, limit: int = 50) -> dict:
	"""Recent returns, newest first — for the till's own history."""
	from frappe.utils import add_days

	rows = frappe.get_all(
		"Sales Invoice",
		filters={
			"docstatus": 1,
			"is_return": 1,
			"posting_date": (">=", add_days(nowdate(), -int(days or 30))),
		},
		fields=[
			"name",
			"customer",
			"return_against",
			"posting_date",
			"grand_total",
			"is_pos",
			"owner",
		],
		order_by="creation desc",
		limit=min(int(limit or 50), 200),
	)

	return {
		"rows": [
			{
				"name": r.name,
				"customer": r.customer,
				"against": r.return_against,
				"date": str(r.posting_date),
				# Reported as a magnitude; the sign is on the document.
				"value": abs(flt(r.grand_total)),
				"refund": "Cash" if r.is_pos else "Credit",
				"by": r.owner,
			}
			for r in rows
		],
		"total": flt(sum(abs(flt(r.grand_total)) for r in rows)),
		"count": len(rows),
	}
