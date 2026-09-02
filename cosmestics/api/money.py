"""Moving money: paying suppliers, and shifting it between the shop's accounts.

Receiving money from customers already lives in `credit.py`. This is the other
two directions a shop needs and had nowhere to do from the app:

* **Paying a supplier**, against one purchase invoice or across everything a
  supplier is owed.
* **Transferring between accounts** — cash banked, float drawn, an M-Pesa
  balance swept into the bank.

Both go through ERPNext's own documents rather than writing GL entries here. A
supplier payment is a **Payment Entry** built by `get_payment_entry`, so the
party account, the outstanding allocation and the reference row are whatever
ERPNext would have produced from the desk. A transfer is a **Journal Entry**
with two lines — the destination debited, the source credited — which is what an
internal transfer is; a Payment Entry of type Internal Transfer would do the
same thing while also insisting on a party the movement does not have.

The accounts offered are the same cash and bank accounts the Accounts screen
shows, so money always lands somewhere the shop can see it.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def _company() -> str:
	return frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default(
		"company"
	)


def _balance_of(account: str) -> float:
	total = frappe.db.sql(
		"""select sum(debit) - sum(credit) from `tabGL Entry`
		   where account = %s and is_cancelled = 0""",
		account,
	)
	return flt(total[0][0] if total and total[0] else 0)


@frappe.whitelist()
def pay_accounts() -> list:
	"""Cash and bank accounts money can come out of or go into, with balances.

	The same set the Accounts screen lists, so a picker here can never offer a
	destination that screen does not show — a transfer into an account nobody
	can see is money the shop believes it has lost.
	"""
	company = _company()
	if not company:
		return []

	rows = frappe.get_all(
		"Account",
		filters={
			"company": company,
			"is_group": 0,
			"account_type": ("in", ["Bank", "Cash"]),
			"disabled": 0,
		},
		fields=["name", "account_name", "account_type"],
		order_by="account_type asc, account_name asc",
	)
	return [
		{
			"account": r.name,
			"label": r.account_name,
			"type": r.account_type,
			"balance": _balance_of(r.name),
		}
		for r in rows
	]


@frappe.whitelist(methods=["POST"])
def transfer_funds(
	from_account: str,
	to_account: str,
	amount: float,
	posting_date: str | None = None,
	reference: str | None = None,
) -> dict:
	"""Move money between two of the shop's own accounts.

	Three refusals, each for a mistake that is easy to make on a phone and
	expensive to unpick afterwards:

	* **The same account twice.** A transfer from an account to itself posts two
	  cancelling lines and looks, in every report, like nothing happened — while
	  the person who did it believes the money moved.
	* **More than is there.** Cash cannot go overdrawn in a drawer, and a
	  negative cash balance is the sort of thing nobody notices until a
	  reconciliation months later.
	* **Nothing, or a negative.** Both produce a document that means nothing.
	"""
	company = _company()
	if not company:
		frappe.throw(_("No company is set, so there is nothing to move money within"))

	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Enter an amount above zero"))
	if not from_account or not to_account:
		frappe.throw(_("Choose the account the money leaves and the one it lands in"))
	if from_account == to_account:
		frappe.throw(_("Choose two different accounts — money cannot be moved to itself"))

	allowed = {a["account"] for a in pay_accounts()}
	for account in (from_account, to_account):
		if account not in allowed:
			frappe.throw(_("{0} is not one of this shop's cash or bank accounts").format(account))

	available = _balance_of(from_account)
	if amount > available:
		frappe.throw(
			_("{0} only holds {1}. You cannot move {2} out of it.").format(
				frappe.db.get_value("Account", from_account, "account_name") or from_account,
				frappe.utils.fmt_money(available, currency=frappe.get_cached_value("Company", company, "default_currency")),
				frappe.utils.fmt_money(amount, currency=frappe.get_cached_value("Company", company, "default_currency")),
			)
		)

	je = frappe.new_doc("Journal Entry")
	# "Journal Entry", not "Bank Entry", and the difference is not cosmetic:
	# ERPNext refuses to submit a Bank Entry without a Reference No *and* a
	# Reference Date — so classifying it that way would make the reference field
	# mandatory, and moving cash from the drawer to the safe has no transaction
	# id to type. The GL effect is identical either way.
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = getdate(posting_date) if posting_date else nowdate()
	if reference:
		je.cheque_no = reference
		je.cheque_date = je.posting_date
	je.user_remark = _("Transfer between accounts")

	# Destination debited, source credited — that is the whole of an internal
	# transfer, and doing it in one document keeps both sides on one voucher so
	# the pair can never be half-cancelled.
	je.append("accounts", {"account": to_account, "debit_in_account_currency": amount})
	je.append("accounts", {"account": from_account, "credit_in_account_currency": amount})

	je.insert()
	je.submit()

	return {
		"name": je.name,
		"amount": amount,
		"from_balance": _balance_of(from_account),
		"to_balance": _balance_of(to_account),
		"message": _("Moved {0} to {1}").format(
			frappe.utils.fmt_money(amount, currency=frappe.get_cached_value("Company", company, "default_currency")),
			frappe.db.get_value("Account", to_account, "account_name") or to_account,
		),
	}


def _unpaid_invoices(supplier: str) -> list:
	"""What this supplier is owed, oldest first — the order a shop pays in."""
	return frappe.get_all(
		"Purchase Invoice",
		filters={
			"supplier": supplier,
			"docstatus": 1,
			"outstanding_amount": (">", 0),
			"company": _company(),
		},
		fields=["name", "posting_date", "grand_total", "outstanding_amount", "bill_no"],
		order_by="posting_date asc, name asc",
	)


@frappe.whitelist()
def supplier_owed(supplier: str) -> dict:
	"""What one supplier is owed, and on which invoices."""
	rows = _unpaid_invoices(supplier)
	return {
		"supplier": supplier,
		"supplier_name": frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier,
		"total": flt(sum(r.outstanding_amount for r in rows)),
		"invoices": [
			{
				"name": r.name,
				"date": str(r.posting_date),
				"bill_no": r.bill_no,
				"grand_total": flt(r.grand_total),
				"outstanding": flt(r.outstanding_amount),
			}
			for r in rows
		],
	}


@frappe.whitelist(methods=["POST"])
def pay_purchase_invoice(
	invoice: str,
	amount: float,
	paid_from: str,
	reference: str | None = None,
	posting_date: str | None = None,
) -> dict:
	"""Pay one supplier bill, in full or in part.

	`paid_from` is the account the money actually leaves, chosen on screen —
	cash, the bank, an M-Pesa float. Left to ERPNext it would default to
	whatever the company's default is, which is right about as often as the shop
	happens to pay from that one account.
	"""
	doc = frappe.get_doc("Purchase Invoice", invoice)
	if doc.docstatus != 1:
		frappe.throw(_("{0} is not submitted, so there is nothing to pay yet").format(invoice))

	outstanding = flt(doc.outstanding_amount)
	if outstanding <= 0:
		frappe.throw(_("{0} is already paid").format(invoice))

	amount = flt(amount) or outstanding
	if amount <= 0:
		frappe.throw(_("Enter an amount above zero"))
	if amount > outstanding:
		frappe.throw(
			_("{0} only has {1} outstanding — paying more would leave the supplier owing you.").format(
				invoice, frappe.utils.fmt_money(outstanding, currency=doc.currency)
			)
		)

	allowed = {a["account"] for a in pay_accounts()}
	if paid_from not in allowed:
		frappe.throw(_("Choose the account this is paid from"))

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	pe = get_payment_entry("Purchase Invoice", invoice, party_amount=amount)
	pe.paid_from = paid_from
	pe.posting_date = getdate(posting_date) if posting_date else nowdate()
	if reference:
		pe.reference_no = reference
		pe.reference_date = pe.posting_date
	pe.setup_party_account_field()
	pe.set_missing_values()
	pe.insert()
	pe.submit()

	left = flt(frappe.db.get_value("Purchase Invoice", invoice, "outstanding_amount"))
	return {
		"name": pe.name,
		"invoice": invoice,
		"paid": amount,
		"outstanding": left,
		"message": _("Paid {0} to {1}").format(
			frappe.utils.fmt_money(amount, currency=doc.currency), doc.supplier_name or doc.supplier
		)
		+ ("" if left <= 0 else _(" — {0} still owed").format(frappe.utils.fmt_money(left, currency=doc.currency))),
	}


@frappe.whitelist(methods=["POST"])
def pay_supplier(
	supplier: str,
	amount: float,
	paid_from: str,
	reference: str | None = None,
	posting_date: str | None = None,
) -> dict:
	"""Pay a supplier a lump sum, spread across what they are owed.

	Oldest invoice first, which is how a shop settles an account and how the
	supplier's own statement will read. A part payment therefore clears the
	oldest bills completely and leaves the newest one short, rather than
	shaving a little off every bill and leaving nothing closed.
	"""
	rows = _unpaid_invoices(supplier)
	if not rows:
		frappe.throw(_("{0} is not owed anything").format(supplier))

	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Enter an amount above zero"))

	owed = flt(sum(r.outstanding_amount for r in rows))
	if amount > owed:
		frappe.throw(
			_("{0} is only owed {1}").format(supplier, frappe.utils.fmt_money(owed))
		)

	allowed = {a["account"] for a in pay_accounts()}
	if paid_from not in allowed:
		frappe.throw(_("Choose the account this is paid from"))

	paid = []
	left = amount
	for row in rows:
		if left <= 0:
			break
		part = min(left, flt(row.outstanding_amount))
		res = pay_purchase_invoice(
			invoice=row.name,
			amount=part,
			paid_from=paid_from,
			reference=reference,
			posting_date=posting_date,
		)
		paid.append({"invoice": row.name, "amount": part, "entry": res["name"]})
		left -= part

	return {
		"supplier": supplier,
		"paid": amount - left,
		"entries": paid,
		"still_owed": _owed_now(supplier),
		"message": _("Paid {0} across {1} invoice(s)").format(
			frappe.utils.fmt_money(amount - left), len(paid)
		),
	}


def _owed_now(supplier: str) -> float:
	return flt(sum(r.outstanding_amount for r in _unpaid_invoices(supplier)))
