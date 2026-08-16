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


@frappe.whitelist()
def list_credit_customers(days: int = DEFAULT_DAYS, limit: int = 200) -> dict:
	"""Who owes the shop money, and how much.

	The other half of `list_credit_sales`. That one answers "which sales are
	unpaid", which is the right shape for chasing a document; this answers "who
	owes us", which is the shape of the question actually asked at a counter —
	a customer walks in to pay and nobody knows which of their four invoices
	they mean. They do not know either, which is why the payment reconciles
	itself (see `pay_customer`).

	Built from the same invoices rather than from a balance query, so the total
	on this list and the total on that one cannot disagree.
	"""
	sales = list_credit_sales(days=days, this_shift=0, limit=limit)

	customers = {}
	for row in sales["rows"]:
		entry = customers.setdefault(
			row["customer"],
			{
				"customer": row["customer"],
				"customer_name": row["customer_name"],
				"outstanding": 0.0,
				"overdue": 0.0,
				"invoices": 0,
				# The oldest unpaid one — the invoice a payment lands on first,
				# so the list can say so before anybody presses anything.
				"oldest_date": row["date"],
				"oldest_invoice": row["name"],
				"phone": None,
			},
		)
		entry["outstanding"] += row["outstanding"]
		if row["overdue"]:
			entry["overdue"] += row["outstanding"]
		entry["invoices"] += 1
		if row["date"] < entry["oldest_date"]:
			entry["oldest_date"] = row["date"]
			entry["oldest_invoice"] = row["name"]

	rows = sorted(customers.values(), key=lambda r: r["outstanding"], reverse=True)

	# One lookup for the page rather than one per row: this list is refreshed on
	# every filter change and every payment.
	if rows:
		meta = frappe.get_meta("Customer")
		field = next((f for f in ("mobile_no", "phone") if meta.has_field(f)), None)
		if field:
			phones = dict(
				frappe.get_all(
					"Customer",
					filters={"name": ("in", [r["customer"] for r in rows])},
					fields=["name", field],
					as_list=True,
				)
			)
			for r in rows:
				r["phone"] = phones.get(r["customer"])

	return {
		"rows": rows,
		"totals": {
			"customers": len(rows),
			"outstanding": flt(sum(r["outstanding"] for r in rows)),
			"overdue": flt(sum(r["overdue"] for r in rows)),
			"invoices": sum(r["invoices"] for r in rows),
		},
		"reason": None if rows else _("Nobody owes anything in this window."),
	}


@frappe.whitelist()
def customer_credit(customer: str, days: int = DEFAULT_DAYS) -> dict:
	"""One customer's unpaid sales, oldest first.

	Oldest first rather than newest, deliberately: this is the order a payment
	is going to be applied in, and a list that shows the opposite invites a
	cashier to expect the opposite. See `pay_customer`.
	"""
	sales = list_credit_sales(days=days, this_shift=0, limit=500)
	rows = [r for r in sales["rows"] if r["customer"] == customer]
	rows.sort(key=lambda r: (r["date"], r["name"]))

	return {
		"customer": customer,
		"customer_name": rows[0]["customer_name"] if rows else customer,
		"rows": rows,
		"totals": {
			"count": len(rows),
			"outstanding": flt(sum(r["outstanding"] for r in rows)),
			"overdue": flt(sum(r["outstanding"] for r in rows if r["overdue"])),
		},
	}


@frappe.whitelist(methods=["POST"])
def pay_customer(
	customer: str,
	amount: float,
	mode_of_payment: str | None = None,
	reference: str | None = None,
	days: int = DEFAULT_DAYS,
) -> dict:
	"""Take money from a customer and settle it against their oldest sales first.

	## Why oldest first, and why one payment rather than several

	The shop asked for exactly this, and it is also the only rule that works at
	a counter. A customer paying 20,000 against a 50,000 invoice and a later
	30,000 one is not choosing between them — they are paying down what they
	owe. Asking the cashier which invoice to apply it to makes them guess, and
	the guesses drift: the same customer's payments end up scattered across
	invoices in no order, and the ageing report becomes fiction.

	Oldest first is what ERPNext's own ageing assumes, so a shop that follows it
	gets a receivables report that means something.

	The money moves as **one** Payment Entry with several reference rows, not
	one entry per invoice. Two reasons. A customer handed over one amount, and
	a ledger that shows three payments for one handover is a ledger somebody has
	to reconcile by hand. And a part-allocated entry is ERPNext's ordinary shape
	— `get_payment_entry` builds exactly this — so nothing here is invented.

	Anything left over after every invoice is settled stays on the entry as an
	unallocated advance against the customer, which is what it is. It is
	reported back rather than refused: a customer overpaying by 200 shillings is
	an ordinary thing, and bouncing the whole payment over it is not.
	"""
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Enter how much is being paid"))

	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("{0} is not a customer").format(customer))

	owed = customer_credit(customer, days=days)
	if not owed["rows"]:
		frappe.throw(_("{0} does not owe anything").format(customer))

	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	mode = mode_of_payment or settings.mode_cash or frappe.db.get_value(
		"Mode of Payment", {"type": "Cash", "enabled": 1}, "name"
	)
	if not mode:
		frappe.throw(_("No mode of payment to receive this through"))

	# The allocation, worked out before anything is written, so the split can be
	# reported exactly as it was applied.
	remaining = amount
	allocation = []
	for row in owed["rows"]:
		if remaining <= 0.005:
			break
		applied = min(remaining, row["outstanding"])
		if applied <= 0:
			continue
		allocation.append(
			{
				"invoice": row["name"],
				"date": row["date"],
				"was_owed": row["outstanding"],
				"applied": flt(applied, 2),
				"now_owed": flt(row["outstanding"] - applied, 2),
			}
		)
		remaining -= applied

	entry = _make_customer_payment_entry(customer, amount, allocation, mode, reference)
	movement = _record_customer_receipt(customer, owed["customer_name"], amount, mode, entry)

	settled = [a["invoice"] for a in allocation if a["now_owed"] <= 0.005]

	return {
		"payment_entry": entry,
		"customer": customer,
		"customer_name": owed["customer_name"],
		"paid": flt(amount, 2),
		"allocated": allocation,
		"settled": settled,
		# What could not be put against an invoice — an overpayment, sitting as
		# an advance on the customer's account.
		"unallocated": flt(max(remaining, 0), 2),
		"outstanding": flt(max(owed["totals"]["outstanding"] - amount, 0), 2),
		"mode_of_payment": mode,
		"movement": movement,
	}


def _make_customer_payment_entry(customer, amount, allocation, mode, reference):
	"""One Payment Entry, allocated across the invoices in `allocation`.

	Built from ERPNext's own `get_payment_entry` against the oldest invoice so
	the accounts, party fields and exchange rates are whatever ERPNext would
	have used — then the reference table is replaced with the full allocation.
	Hand-rolling the whole entry would be a second implementation of party
	accounting that only this app knows about; hand-rolling only the reference
	rows is the part ERPNext has no single-call API for.
	"""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	first = allocation[0]["invoice"]
	pe = get_payment_entry("Sales Invoice", first, party_amount=amount)
	pe.mode_of_payment = mode
	pe.reference_no = reference or f"{customer} payment"
	pe.reference_date = nowdate()
	pe.posting_date = nowdate()
	pe.paid_amount = amount
	pe.received_amount = amount

	account = frappe.db.get_value(
		"Mode of Payment Account", {"parent": mode, "company": pe.company}, "default_account"
	)
	if account:
		pe.paid_to = account

	pe.set("references", [])
	for row in allocation:
		invoice = frappe.db.get_value(
			"Sales Invoice", row["invoice"], ["grand_total", "outstanding_amount", "due_date"], as_dict=True
		)
		pe.append(
			"references",
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": row["invoice"],
				"due_date": invoice.due_date,
				"total_amount": flt(invoice.grand_total),
				"outstanding_amount": flt(invoice.outstanding_amount),
				"allocated_amount": row["applied"],
			},
		)

	pe.setup_party_account_field()
	pe.set_missing_values()
	# After `set_missing_values`, which can recompute the pair from the
	# references it now sees — and the shop handed over one amount, not the sum
	# of what happened to fit.
	pe.paid_amount = amount
	pe.received_amount = amount
	pe.set_amounts()
	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe.name


def _record_customer_receipt(customer, customer_name, amount, mode, entry):
	"""Tell the open shift that money came in — see `_record_till_receipt`.

	The same reasoning, for a payment that spans several invoices: without this
	the cash is in the drawer and the shift's expected total does not know about
	it, so the count comes up over with nothing on screen explaining why.
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
			person=customer_name or customer,
			reason=_("{0} paid {1} against their account").format(
				customer_name or customer,
				frappe.format_value(amount, {"fieldtype": "Currency"}),
			),
			reference_doctype="Payment Entry",
			reference_name=entry,
		)
	except Exception:
		frappe.log_error(f"Could not record the till receipt for {entry}", "Cosmetics POS")
		return None


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
