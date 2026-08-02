"""Money that left the till without being a sale.

Three things happen at a counter that a Sales Invoice cannot describe: the
cashier pays a neighbouring shop in cash, buys something the shop needed out of
the drawer, or counts less than the till says should be there. All three change
what the drawer holds, and none of them appear in `get_invoices`.

Kept as one doctype rather than three because the closing screen has to add
them up in one place. `movement_type` is what differs; the arithmetic is the
same — an amount, against a mode of payment, inside a shift.

Expense and Neighbour Purchase take cash *out* and reduce what the drawer should
hold. A Neighbour Refund is the same trade running backwards — goods went back
next door and the shop handed the money over the counter — so it puts cash *in*.
A Short is the opposite direction of causation: it is discovered by counting
rather than recorded before it, so it never adjusts the expectation — it records
who the discrepancy is against, which is the part ERPNext's own closing entry has
nowhere to put.

**And the part it has nowhere to post.** A POS Closing Entry writes no GL entries
at all: `difference` is a reconciliation note on the document and nothing more.
Checked, not assumed — closing a shift 500 short produced zero GL entries against
the closing entry. So money that physically left the drawer was missing from the
till and present in the ledger, for ever. A Short now posts its own Journal
Entry, which is safe precisely because nothing else posts one.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

#: Types that take money out of the drawer. A Short is excluded deliberately —
#: see the module docstring.
PAID_OUT_TYPES = ("Expense", "Neighbour Purchase")

#: Types that put money back in. Amounts stay positive on the record — the
#: direction is the type's job, not the sign's, so a movement always reads as
#: "this much moved" and validation can keep refusing zero and below.
#:
#: A Credit Payment is a customer settling an older sale at the counter. Its
#: Payment Entry is invisible to `get_closing_summary`, which reads POS payment
#: rows and these movements and nothing else — so without this the cash would
#: land in the drawer and the count would come up over with nothing to explain
#: it.
CASH_IN_TYPES = ("Neighbour Refund", "Credit Payment")


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

		if self.movement_type == "Short" and not self.person and not self.unattributed:
			# The point of recording a short here rather than leaving it on the
			# closing entry is that it carries a name. A short with no name is
			# allowed only when it says so out loud — `unattributed` is set by
			# `_record_shorts` for the part of a difference nobody was named for,
			# and it books to a different account precisely because of that.
			frappe.throw(_("Say who the short is against, or record it as unattributed"))

	def on_submit(self):
		"""Book the ledger side, where this movement has one.

		Only Expense posts its own entry. Every other type already has a document
		behind it — a Neighbour Purchase has its Purchase Invoice, a Neighbour
		Refund the return that reverses it, a Credit Payment its Payment Entry —
		and posting a second one for the same money would double-count it, so
		those records only tell the closing screen which way the cash went. A
		Short posts one too, and has to: ERPNext's POS Closing Entry records the
		difference on the document without ever touching the ledger, so the cash
		was gone from the drawer and still on the books.
		"""
		if self.movement_type == "Short":
			entry = self._make_short_entry()
			# Overwrites the closing entry reference deliberately: the JE is what
			# this record *posted*, and the closing entry it came from is on the
			# movement's reason. Only one of the two can be the reference, and the
			# posting is the one anybody chasing this figure needs.
			self.db_set("reference_doctype", "Journal Entry")
			self.db_set("reference_name", entry)
			return

		if self.movement_type != "Expense" or self.reference_name:
			return

		entry = self._make_journal_entry()
		self.db_set("reference_doctype", "Journal Entry")
		self.db_set("reference_name", entry)

	def on_cancel(self):
		"""Cancel what we posted, and only what we posted.

		A Neighbour Purchase's or Refund's invoice is cancelled from the purchase
		side — both move stock, so reversing one from here would silently reverse
		a goods movement the cashier was not asking about.
		"""
		if self.reference_doctype == "Journal Entry" and self.reference_name:
			doc = frappe.get_doc("Journal Entry", self.reference_name)
			if doc.docstatus == 1:
				doc.cancel()

	def _make_short_entry(self) -> str:
		"""Charge a counted shortfall to whoever carries it.

		Credit the drawer, because the cash is genuinely not there. Debit either
		the till's own short account — a receivable from the person named, which
		is what a shop means by "it is on them" — or, when nobody is named, the
		company's unattributed account, which is a write-off.

		The two are separate accounts on purpose. "Owed by staff" and "lost" are
		different facts with different consequences, and a single account holding
		both cannot answer either question at month end.
		"""
		credit_to = _mode_account(self.mode_of_payment, self.company)

		if self.expense_account:
			# Tagged at closing: this person has their own account. Checked here
			# too rather than trusted from the form — the same party-account rule
			# applies however the account arrived.
			debit_to, kind = _assert_postable(self.expense_account), "tagged"
		else:
			debit_to, kind = _short_account(self.pos_profile, self.company, bool(self.person))

		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Cash Entry"
		je.company = self.company
		je.posting_date = nowdate()
		je.user_remark = (
			_("Till short on shift {0}, against {1}").format(self.shift, self.person)
			if self.person
			else _("Till short on shift {0}, nobody named").format(self.shift)
		)

		cost_center = frappe.db.get_value("Company", self.company, "cost_center")

		je.append(
			"accounts",
			{
				"account": debit_to,
				"debit_in_account_currency": flt(self.amount),
				"cost_center": cost_center,
				# Carried on the line as well as the remark: a receivable account
				# read on its own shows a column of identical amounts otherwise.
				"user_remark": self.person or _("Unattributed"),
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
		frappe.logger().info(f"Short {self.name}: {flt(self.amount)} to {debit_to} ({kind})")
		return je.name

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


def _assert_postable(account: str) -> str:
	"""An account a Journal Entry can actually post to without a party.

	A Receivable or Payable account demands one, and this app has no Employee to
	hand — the name on a short is text a cashier typed. Refused with the reason
	rather than failing inside ERPNext's validation, which would report it as a
	missing party on an entry the shop never made.
	"""
	account_type = frappe.db.get_value("Account", account, "account_type")
	if account_type in ("Receivable", "Payable"):
		frappe.throw(
			_(
				"{0} is a {1} account, which needs a party on every entry. Use a plain "
				"asset or expense account for till shortfalls."
			).format(account, account_type)
		)
	return account


def _short_account(pos_profile: str, company: str, named: bool) -> tuple[str, str]:
	"""Where a shortfall is charged, and which of the two answers it is.

	A named short goes to the till's own account, because which till it was is
	what decides whether staff carry the loss — two branches of one shop can
	answer that differently, which is why it lives on the POS Profile rather
	than in one company-wide setting.

	Both fall back to each other rather than to a guess. Booking a shortfall to
	whatever account happened to be lying around is worse than refusing: it is a
	number in the wrong place that nobody will ever question, and the refusal
	names the setting to fill in.
	"""
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	company_account = settings.company_short_account
	profile_account = (
		frappe.db.get_value("POS Profile", pos_profile, "cosmestics_short_account")
		if pos_profile
		else None
	)

	if named:
		account = profile_account or company_account
		kind = "profile" if profile_account else "company fallback"
	else:
		account = company_account or profile_account
		kind = "company" if company_account else "profile fallback"

	if not account:
		frappe.throw(
			_(
				"No account to charge this shortfall to. Set a Till Short Account on "
				"the POS Profile {0}, or an Unattributed Short Account in Cosmetics "
				"POS Settings."
			).format(pos_profile or "")
		)

	return _assert_postable(account), kind


def _default_expense_account(company: str) -> str | None:
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	if settings.default_expense_account:
		return settings.default_expense_account
	return frappe.db.get_value("Company", company, "default_expense_account")
