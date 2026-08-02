"""Sales the shop is still owed for, and taking the money when it arrives.

A credit sale leaves the counter with the goods gone and nothing in the drawer.
Until now the till could *create* one — the pay sheet has had an "on account"
route since the beginning — but nothing in the app could take the money
afterwards, so a customer coming back to settle had to be handled in the desk by
somebody who knew what a Payment Entry was.

## Why a Payment Entry, and why a till movement as well

The payment itself is an ordinary **Payment Entry** allocated against the
invoice, because that is what ERPNext's ageing, statements and reconciliation
all read. Nothing invented.

But a Payment Entry is invisible to the shift. `get_closing_summary` builds the
expected drawer from the payment rows of POS invoices plus the till's own
movements, and a settlement against last week's invoice is neither. Cash would
go into the drawer, the count would come up over, and the cashier would have no
way to explain it.

So a **Credit Payment** movement is recorded alongside it — the same mechanism a
neighbour refund uses, in the same direction: money in, expectation up by
exactly that much. The Payment Entry is the accounting; the movement is what the
drawer knows about it.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, nowdate

#: How far back the till offers to collect. Anything older is a debt-collection
#: matter rather than a customer at the counter, and the list stops being usable.
DEFAULT_DAYS = 90


@frappe.whitelist()
def list_credit_sales(days: int = DEFAULT_DAYS, this_shift: int = 0, limit: int = 200) -> dict:
	"""Sales still owed for, newest first.

	`this_shift` narrows to what this cashier put on account during the open
	shift — which is the question the closing screen asks. Without it, the till
	is answering "who owes us anything", which is the question a customer walking
	in to pay asks.
	"""
	filters = {
		"docstatus": 1,
		"is_return": 0,
		"outstanding_amount": (">", 0),
		"posting_date": (">=", add_days(nowdate(), -int(days or DEFAULT_DAYS))),
	}

	if int(this_shift or 0):
		from cosmestics.api.shift import get_open_shift

		shift = get_open_shift()
		if not shift:
			return _empty("No shift is open, so there is nothing from this one to show.")
		filters["owner"] = frappe.session.user
		filters["creation"] = ("between", [shift["period_start_date"], frappe.utils.now()])

	rows = frappe.get_all(
		"Sales Invoice",
		filters=filters,
		fields=[
			"name",
			"customer",
			"customer_name",
			"posting_date",
			"due_date",
			"grand_total",
			"outstanding_amount",
			"is_pos",
			"owner",
		],
		order_by="posting_date desc, creation desc",
		limit=min(int(limit or 200), 500),
	)

	today = frappe.utils.getdate(nowdate())
	out = []
	for r in rows:
		overdue = bool(r.due_date and frappe.utils.getdate(r.due_date) < today)
		out.append(
			{
				"name": r.name,
				"customer": r.customer,
				"customer_name": r.customer_name or r.customer,
				"date": str(r.posting_date),
				"due_date": str(r.due_date) if r.due_date else None,
				"grand_total": flt(r.grand_total),
				"outstanding": flt(r.outstanding_amount),
				# What has already come in, so a part payment is visible as one.
				"paid": flt(r.grand_total) - flt(r.outstanding_amount),
				"overdue": overdue,
				"sold_by": r.owner,
				"_tone": "bad" if overdue else None,
			}
		)

	return {
		"rows": out,
		"totals": {
			"count": len(out),
			"outstanding": flt(sum(r["outstanding"] for r in out)),
			"overdue": flt(sum(r["outstanding"] for r in out if r["overdue"])),
			"customers": len({r["customer"] for r in out}),
		},
		"reason": None,
	}


def _empty(reason):
	return {
		"rows": [],
		"totals": {"count": 0, "outstanding": 0, "overdue": 0, "customers": 0},
		"reason": reason,
	}


@frappe.whitelist(methods=["POST"])
def pay_credit_sale(
	invoice: str,
	amount: float | None = None,
	mode_of_payment: str | None = None,
	reference: str | None = None,
) -> dict:
	"""Take money against a credit sale.

	`amount` defaults to whatever is still outstanding, which is the common case
	— a customer settling in full. A smaller amount is a part payment and is
	allocated against the same invoice.
	"""
	doc = frappe.get_doc("Sales Invoice", invoice)
	if doc.docstatus != 1:
		frappe.throw(_("{0} is not a completed sale").format(invoice))

	owed = flt(doc.outstanding_amount)
	if owed <= 0:
		frappe.throw(_("{0} is already settled").format(invoice))

	amount = flt(amount) if amount not in (None, "") else owed
	if amount <= 0:
		frappe.throw(_("Enter how much is being paid"))
	if amount > owed + 0.005:
		frappe.throw(
			_("{0} is more than the {1} still owed on {2}").format(
				frappe.format_value(amount, {"fieldtype": "Currency"}),
				frappe.format_value(owed, {"fieldtype": "Currency"}),
				invoice,
			)
		)

	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	mode = mode_of_payment or settings.mode_cash or frappe.db.get_value(
		"Mode of Payment", {"type": "Cash", "enabled": 1}, "name"
	)
	if not mode:
		frappe.throw(_("No mode of payment to receive this through"))

	entry = _make_payment_entry(doc, amount, mode, reference)
	movement = _record_till_receipt(doc, amount, mode, entry)

	doc.reload()
	return {
		"payment_entry": entry,
		"invoice": doc.name,
		"paid": amount,
		"outstanding": flt(doc.outstanding_amount),
		"settled": flt(doc.outstanding_amount) <= 0,
		"mode_of_payment": mode,
		"movement": movement,
	}


def _make_payment_entry(invoice, amount, mode, reference):
	"""An ordinary Payment Entry, allocated against the invoice.

	Built through ERPNext's own `get_payment_entry` so the accounts, exchange
	rates and reference row are whatever ERPNext would have used from the desk.
	Hand-rolling one here would be a second implementation of party accounting
	that only this app knows about.
	"""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	pe = get_payment_entry("Sales Invoice", invoice.name, party_amount=amount)
	pe.mode_of_payment = mode
	pe.reference_no = reference or invoice.name
	pe.reference_date = nowdate()
	pe.posting_date = nowdate()

	account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mode, "company": invoice.company},
		"default_account",
	)
	if account:
		pe.paid_to = account

	pe.setup_party_account_field()
	pe.set_missing_values()
	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe.name


def _record_till_receipt(invoice, amount, mode, entry):
	"""Tell the open shift that money came in for an older sale.

	Silent when no shift is open — settling a debt has to work at a counter
	nobody opened a shift on, and the payment is already posted by this point.
	"""
	from cosmestics.api.shift import get_open_shift, post_movement

	if not get_open_shift():
		return None

	try:
		return post_movement(
			movement_type="Credit Payment",
			amount=amount,
			mode_of_payment=mode,
			party=None,
			person=invoice.customer_name or invoice.customer,
			reason=_("{0} paid {1} against {2}").format(
				invoice.customer_name or invoice.customer,
				frappe.format_value(amount, {"fieldtype": "Currency"}),
				invoice.name,
			),
			reference_doctype="Payment Entry",
			reference_name=entry,
		)
	except Exception:
		frappe.log_error(
			f"Could not record the till receipt for {entry}", "Cosmetics POS"
		)
		return None
