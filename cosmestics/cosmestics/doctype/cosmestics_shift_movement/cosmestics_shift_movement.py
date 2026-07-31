"""Money that left the till without being a sale.

Three things happen at a counter that a Sales Invoice cannot describe: the
cashier pays a neighbouring shop in cash, buys something the shop needed out of
the drawer, or counts less than the till says should be there. All three change
what the drawer holds, and none of them appear in `get_invoices`.

Kept as one doctype rather than three because the closing screen has to add
them up in one place. `movement_type` is what differs; the arithmetic is the
same — an amount, against a mode of payment, inside a shift.

Expense and Neighbour Purchase take cash *out* and reduce what the drawer should
hold. A Short is the opposite direction of causation: it is discovered by
counting rather than recorded before it, so it never adjusts the expectation —
it records who the discrepancy is against, which is the part ERPNext's own
closing entry has nowhere to put.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

#: Types that take money out of the drawer. A Short is excluded deliberately —
#: see the module docstring.
PAID_OUT_TYPES = ("Expense", "Neighbour Purchase")


class CosmesticsShiftMovement(Document):
	def validate(self):
		if flt(self.amount) <= 0:
			frappe.throw(_("A movement needs an amount above zero"))

		if not self.shift:
			frappe.throw(_("A movement has to belong to a shift"))

		# Denormalised from the shift so the closing summary and the reports can
		# scope by till and company without joining every time.
		opening = frappe.db.get_value(
			"POS Opening Entry", self.shift, ["pos_profile", "company", "user"], as_dict=True
		)
		if not opening:
			frappe.throw(_("{0} is not a POS Opening Entry").format(self.shift))

		self.pos_profile = opening.pos_profile
		self.company = opening.company
		self.cashier = self.cashier or opening.user

		if self.movement_type == "Short" and not self.person:
			# The entire point of recording a short here rather than leaving it on
			# the closing entry is that it carries a name.
			frappe.throw(_("Say who the short is against"))

	def on_submit(self):
		"""Book the ledger side, where this movement has one.

		Only Expense posts its own entry. A Neighbour Purchase is already a
		Purchase Invoice written by `sourcing.receive_from_neighbours`, and
		posting a second document for the same money would double-count it — this
		record only tells the closing screen that the cash left. A Short is
		booked by ERPNext's POS Closing Entry as the reconciliation difference.
		"""
		if self.movement_type != "Expense" or self.reference_name:
			return

		entry = self._make_journal_entry()
		self.db_set("reference_doctype", "Journal Entry")
		self.db_set("reference_name", entry)

	def on_cancel(self):
		"""Cancel what we posted, and only what we posted.

		A Neighbour Purchase's invoice is cancelled from the purchase side — it
		receives stock, so reversing it from here would silently reverse a goods
		movement the cashier was not asking about.
		"""
		if self.reference_doctype == "Journal Entry" and self.reference_name:
			doc = frappe.get_doc("Journal Entry", self.reference_name)
			if doc.docstatus == 1:
				doc.cancel()

	def _make_journal_entry(self) -> str:
		"""Debit the expense, credit the drawer.

		Written as a Journal Entry rather than left as a note on the shift because
		the cash is genuinely gone: a drawer that reconciles against a till total
		which the general ledger does not know about is a difference somebody has
		to chase at month end.
		"""
		credit_to = _mode_account(self.mode_of_payment, self.company)
		debit_to = self.expense_account or _default_expense_account(self.company)
		if not debit_to:
			frappe.throw(
				_("Pick an expense account — there is no default expense account on {0}").format(
					self.company
				)
			)

		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Cash Entry"
		je.company = self.company
		je.posting_date = nowdate()
		je.user_remark = _("Till expense on shift {0}: {1}").format(
			self.shift, self.reason or self.movement_type
		)

		cost_center = frappe.db.get_value("Company", self.company, "cost_center")

		je.append(
			"accounts",
			{
				"account": debit_to,
				"debit_in_account_currency": flt(self.amount),
				"cost_center": cost_center,
			},
		)
		je.append(
			"accounts",
			{
				"account": credit_to,
				"credit_in_account_currency": flt(self.amount),
				"cost_center": cost_center,
			},
		)

		je.insert()
		je.submit()
		return je.name


def _mode_account(mode_of_payment: str, company: str) -> str:
	"""The account a mode of payment settles into.

	Falls back to the company's default cash account: a shop that has not mapped
	every mode should still be able to record that money left the drawer.
	"""
	account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mode_of_payment, "company": company},
		"default_account",
	)
	if not account:
		account = frappe.db.get_value("Company", company, "default_cash_account")
	if not account:
		frappe.throw(
			_("{0} has no account on {1}, and {1} has no default cash account").format(
				mode_of_payment, company
			)
		)
	return account


def _default_expense_account(company: str) -> str | None:
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	if settings.default_expense_account:
		return settings.default_expense_account
	return frappe.db.get_value("Company", company, "default_expense_account")
