"""Undoing and correcting a sale after it has been rung up.

Two corrections a counter needs, and neither is a return.

**Void** — the sale should never have happened: rung up twice, the customer
walked out before paying, the wrong basket. A return is the wrong tool for it.
It books a *refund*, which takes money out of the shift the drawer never
received, and leaves a sale and a credit note in every report for something
that did not occur. Voiding cancels the invoice itself, and ERPNext's own cancel
reverses everything the submit posted — the stock comes back, the ledger
entries are reversed, and the shift stops counting it.

**Change payment** — the sale happened, but was booked to the wrong tender:
M-Pesa tapped for cash, or a split recorded as one method. A submitted
invoice's payment rows cannot be edited, so it is cancelled and **amended**,
which is ERPNext's own correction path: the original stays on record as
cancelled, the replacement carries `amended_from`, and both show in the audit
trail. The amendment keeps the original posting date and time, so the sale
stays in the day and the shift it belongs to.

## What cannot be undone here

Anything already reconciled or built upon. A sale inside a **closed shift** is
part of a submitted closing entry that ERPNext will not let go of, a sale with a
**return** against it has a credit note depending on it, and a credit sale that
has been **paid** has a payment entry allocated to it. Each is refused before
anything is touched, in words that say what to do instead, rather than halfway
through a cancel with a message naming a document.

## Who may do it

Whoever may cancel a Sales Invoice under the site's own permissions. A void is
the classic till fraud — take the cash, void the sale — so it is not opened up
to everyone who can sell; the shop grants it the same way it grants any other
cancel right in ERPNext.
"""

import frappe
from frappe import _
from frappe.utils import flt


def _can_cancel(doc=None) -> bool:
	return bool(frappe.has_permission("Sales Invoice", "cancel", doc=doc))


def _refusal(doc) -> str | None:
	"""Why this sale cannot be voided or re-booked, or None if it can."""
	if doc.docstatus == 2:
		return _("{0} has already been voided").format(doc.name)
	if doc.docstatus != 1:
		return _("{0} is not a completed sale").format(doc.name)
	if doc.get("is_return"):
		return _("{0} is a return, not a sale").format(doc.name)

	if doc.get("pos_closing_entry") and frappe.db.get_value(
		"POS Closing Entry", doc.pos_closing_entry, "docstatus"
	) == 1:
		return _(
			"This sale is in a shift that has already been closed ({0}). "
			"Use Return goods instead."
		).format(doc.pos_closing_entry)

	returns = frappe.get_all(
		"Sales Invoice",
		filters={"return_against": doc.name, "docstatus": 1},
		pluck="name",
	)
	if returns:
		return _("Goods have already been returned against this sale ({0}).").format(
			", ".join(returns)
		)

	payments = frappe.get_all(
		"Payment Entry Reference",
		filters={"reference_doctype": "Sales Invoice", "reference_name": doc.name, "docstatus": 1},
		pluck="parent",
	)
	if payments:
		return _("A payment has already been received against this sale ({0}).").format(
			", ".join(dict.fromkeys(payments))
		)

	return None


def _permission_refusal(doc) -> str | None:
	if _can_cancel(doc):
		return None
	return _("Only someone allowed to cancel sales invoices can do this. Ask a manager.")


@frappe.whitelist()
def sale_actions(invoice: str) -> dict:
	"""What can be done to this sale, asked before the sheet is drawn.

	So the till can say *why* an option is unavailable instead of offering a
	button that then refuses.
	"""
	doc = frappe.get_doc("Sales Invoice", invoice)
	doc.check_permission("read")

	blocked = _refusal(doc) or _permission_refusal(doc)

	from cosmestics.api.returns import returnable_sale

	can_return = False
	return_reason = None
	try:
		can_return = not returnable_sale(invoice)["fully_returned"]
		if not can_return:
			return_reason = _("Everything on this sale has already come back.")
	except Exception as e:
		return_reason = str(e)

	payments = _net_payments(doc)
	change_reason = blocked
	if not change_reason and not doc.get("is_pos"):
		change_reason = _("This was a credit sale — nothing was paid at the till to re-book.")
	if not change_reason and not payments:
		change_reason = _("No payment was recorded on this sale.")

	return {
		"invoice": doc.name,
		"customer": doc.customer_name or doc.customer,
		"grand_total": flt(doc.rounded_total or doc.grand_total),
		"outstanding": flt(doc.outstanding_amount),
		"paid": sum(p["amount"] for p in payments),
		"payments": payments,
		"can_return": can_return,
		"return_reason": return_reason,
		"can_void": not blocked,
		"void_reason": blocked,
		"can_change_payment": not change_reason,
		"change_reason": change_reason,
	}


def _net_payments(doc) -> list:
	"""The payment rows as money actually kept, not money handed over.

	A cash row carries what was *tendered*; the change went back across the
	counter. Re-booking 1,000 tendered for a 790 sale must move 790, so the
	change is taken off the cash row here.
	"""
	change = flt(doc.get("change_amount"))
	rows = []
	for p in doc.get("payments") or []:
		amount = flt(p.amount)
		if change > 0 and _is_cash(p.mode_of_payment):
			taken = min(change, amount)
			amount -= taken
			change -= taken
		if amount <= 0:
			continue
		rows.append({"mode_of_payment": p.mode_of_payment, "amount": amount, "reference": p.reference_no})
	return rows


def _is_cash(mode) -> bool:
	return frappe.get_cached_value("Mode of Payment", mode, "type") == "Cash"


def _require(doc):
	reason = _refusal(doc) or _permission_refusal(doc)
	if reason:
		frappe.throw(reason, title=_("Cannot change this sale"))


def _silent(method):
	"""Stands in for `Document.run_notifications` on a re-booked sale."""
	return None


def _comment(doc, text):
	try:
		doc.add_comment("Comment", text)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Cosmetics POS")


@frappe.whitelist(methods=["POST"])
def void_sale(invoice: str, reason: str | None = None) -> dict:
	"""Cancel a sale outright — stock, ledger and shift all reversed."""
	doc = frappe.get_doc("Sales Invoice", invoice)
	_require(doc)

	doc.cancel()

	_comment(
		doc,
		_("Voided at the till by {0}{1}").format(
			frappe.utils.get_fullname(frappe.session.user),
			f": {reason.strip()}" if (reason or "").strip() else "",
		),
	)

	return {
		"invoice": doc.name,
		"customer": doc.customer_name or doc.customer,
		"grand_total": flt(doc.rounded_total or doc.grand_total),
		"message": _("{0} voided — stock and accounts reversed").format(doc.name),
	}


@frappe.whitelist(methods=["POST"])
def change_payment(invoice: str, payments: list | str) -> dict:
	"""Re-book a sale to the tenders it was really paid with.

	`payments` — [{mode_of_payment, amount, reference}]. Must add up to what was
	originally paid: this corrects *how* the sale was paid, never *how much*, so
	the customer's balance and the invoice total are exactly as they were.
	"""
	if isinstance(payments, str):
		payments = frappe.parse_json(payments)

	original = frappe.get_doc("Sales Invoice", invoice)
	_require(original)
	if not original.get("is_pos"):
		frappe.throw(_("This was a credit sale — nothing was paid at the till to re-book."))

	before = _net_payments(original)
	paid = round(sum(p["amount"] for p in before), 2)

	rows = []
	allowed = _allowed_modes(original)
	for p in payments or []:
		mode = (p.get("mode_of_payment") or "").strip()
		amount = flt(p.get("amount"), 2)
		if not mode or amount <= 0:
			continue
		if mode not in allowed:
			frappe.throw(_("{0} is not a payment method this till accepts").format(mode))
		rows.append({"mode_of_payment": mode, "amount": amount, "reference": (p.get("reference") or "").strip() or None})

	if not rows:
		frappe.throw(_("Choose at least one payment method"))

	total = round(sum(r["amount"] for r in rows), 2)
	if abs(total - paid) > 0.005:
		frappe.throw(
			_("The payments add up to {0}, but {1} was paid on this sale.").format(
				frappe.format_value(total, {"fieldtype": "Currency"}),
				frappe.format_value(paid, {"fieldtype": "Currency"}),
			)
		)

	if _summary(before) == _summary(rows):
		frappe.throw(_("That is how the sale is already booked — nothing to change."))

	quotations = frappe.get_all(
		"Quotation", filters={"cosmestics_converted_invoice": original.name}, pluck="name"
	) if frappe.get_meta("Quotation").has_field("cosmestics_converted_invoice") else []

	# The shop's own "New Sale" alerts would announce the cancel and then the
	# replacement as a second sale. One accurate notice is sent instead. Silenced
	# on these two instances only: Frappe resets `flags.notifications_executed`
	# at the start of every save, so the flag cannot be pre-seeded.
	original.run_notifications = _silent
	original.cancel()

	amended = frappe.copy_doc(original)
	amended.amended_from = original.name
	amended.owner = original.owner
	# Same moment as the sale it replaces, so it stays in that day and shift.
	amended.set_posting_time = 1
	amended.posting_date = original.posting_date
	amended.posting_time = original.posting_time
	amended.set("payments", [])
	amended.change_amount = 0
	amended.base_change_amount = 0
	amended.account_for_change_amount = None
	for r in rows:
		amended.append(
			"payments",
			{
				"mode_of_payment": r["mode_of_payment"],
				"amount": r["amount"],
				"account": _payment_account(r["mode_of_payment"], amended.company),
				"reference_no": r["reference"],
			},
		)
	amended.run_notifications = _silent
	amended.insert()
	amended.submit()
	# `insert` stamps the session user; the sale is still the cashier's.
	if amended.owner != original.owner:
		amended.db_set("owner", original.owner, update_modified=False)

	for name in quotations:
		try:
			from cosmestics.api.quotations import mark_converted

			mark_converted(name, amended.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Cosmetics POS")

	changed_by = frappe.utils.get_fullname(frappe.session.user)
	_comment(
		amended,
		_("Payment changed by {0}: {1} → {2}").format(changed_by, _summary(before), _summary(rows)),
	)

	from cosmestics.api.notifications import queue_payment_change_notice

	queue_payment_change_notice(original.name, amended.name, _summary(before), _summary(rows), changed_by)

	return {
		"invoice": amended.name,
		"replaces": original.name,
		"was": _summary(before),
		"now": _summary(rows),
		"message": _("{0} re-booked as {1} · {2}").format(original.name, amended.name, _summary(rows)),
	}


def _summary(rows) -> str:
	merged = {}
	for r in rows:
		merged[r["mode_of_payment"]] = round(merged.get(r["mode_of_payment"], 0) + flt(r["amount"]), 2)
	if len(merged) == 1:
		return next(iter(merged))
	return " + ".join(f"{mode} {frappe.utils.fmt_money(amount, precision=2)}" for mode, amount in merged.items())


def _allowed_modes(doc) -> set:
	from cosmestics.api.pos import get_payment_methods

	modes = {m["mode_of_payment"] for m in get_payment_methods()["methods"] if m.get("mode_of_payment")}
	if doc.get("pos_profile"):
		modes.update(
			frappe.get_all("POS Payment Method", filters={"parent": doc.pos_profile}, pluck="mode_of_payment")
		)
	# Whatever the sale was already booked to stays valid, even if the till has
	# since stopped offering it.
	modes.update(p.mode_of_payment for p in doc.get("payments") or [])
	return modes


def _payment_account(mode, company):
	from cosmestics.api.pos import _payment_account as account

	return account(mode, company)
