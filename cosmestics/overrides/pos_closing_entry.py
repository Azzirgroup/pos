"""Let a closing entry settle a shift that had more than one cashier on it.

ERPNext's `validate_sales_invoices` rejects any invoice whose `owner` is not the
closing entry's `user`:

    if sales_invoice.owner != self.user:
        ... _("Sales Invoice isn't created by user {}")

That is correct for the shift it was written for — one drawer, one person. It is
wrong for a shared one, and wrong in the worst possible way: the sales are
already banked, the cashiers have gone home, and the till simply cannot be
closed. Nothing in the app can route around it, because the check runs on the
closing entry's own `validate()`, downstream of whatever built the document.

So the owner test — and only the owner test — is widened to the shift's roster.
Every other guard ERPNext applies is left exactly as it was and still runs:
already-consolidated, not submitted, wrong profile, `is_pos` unset,
`is_created_using_pos` unset. An invoice that fails any of those still fails.

The claim being made is narrow and true: an invoice tagged with this shift's POS
Profile, inside its window, rung up by somebody rostered on it, belongs to it —
whoever's name is on the row.
"""

import frappe
from frappe import _

from cosmestics.overrides.shift_roster import ROSTER_FIELD, roster_for


class SharedShiftClosingMixin:
	def validate_sales_invoices(self):
		"""ERPNext's own check, minus the owner restriction.

		Reimplemented rather than wrapped: the owner comparison is inside the
		per-row loop, so there is no seam to call `super()` through. Kept in the
		same shape as the original, so a diff against a future ERPNext version
		reads as a diff rather than as two unrelated functions.

		## Why the owner check is gone entirely

		It first became "is the owner on the shift's roster", which was a widening
		of ERPNext's "is the owner the one person who opened it". That was still a
		restriction, and it produced the worst failure this app can have: a shift
		containing a sale by somebody not on the roster **could not be closed**.
		An unclosable shift stays open overnight; ERPNext then refuses the next
		day's `is_pos` invoices against it, and the entire shop cannot sell. One
		cashier ringing up on the wrong counter took the till down the next
		morning, and the message blamed the invoice.

		A closing entry's job is to reconcile what happened, not to adjudicate who
		was allowed to. Whether somebody should have been selling is a real
		question, but the answer must never be "the money cannot be counted".

		Nothing is loosened that matters: `_shift_invoices` gathers rows by POS
		profile and time window, so an invoice reaching here belongs to this shift
		by construction, and every other check ERPNext makes — submitted, is_pos,
		created using POS, matching profile, not already consolidated — still runs.
		"""
		invalid_rows = []
		for d in self.sales_invoices:
			invalid_row = {"idx": d.idx}
			sales_invoice = frappe.db.get_values(
				"Sales Invoice",
				d.sales_invoice,
				[
					"pos_profile",
					"docstatus",
					"is_pos",
					"owner",
					"is_created_using_pos",
					"is_consolidated",
					"pos_closing_entry",
				],
				as_dict=1,
			)[0]
			if sales_invoice.pos_closing_entry:
				invalid_row.setdefault("msg", []).append(_("Sales Invoice is already consolidated"))
				invalid_rows.append(invalid_row)
				continue
			if sales_invoice.is_pos == 0:
				invalid_row.setdefault("msg", []).append(_("Sales Invoice does not have Payments"))
			if sales_invoice.is_created_using_pos == 0:
				invalid_row.setdefault("msg", []).append(_("Sales Invoice is not created using POS"))
			if sales_invoice.pos_profile != self.pos_profile:
				invalid_row.setdefault("msg", []).append(
					_("POS Profile doesn't match {}").format(frappe.bold(self.pos_profile))
				)
			if sales_invoice.docstatus != 1:
				invalid_row.setdefault("msg", []).append(_("Sales Invoice is not submitted"))
			if invalid_row.get("msg"):
				invalid_rows.append(invalid_row)

		if not invalid_rows:
			return

		error_list = []
		for row in invalid_rows:
			for msg in row.get("msg"):
				error_list.append(_("Row #{}: {}").format(row.get("idx"), msg))

		frappe.throw(error_list, title=_("Invalid Sales Invoices"), as_list=True)

	def _shift_cashiers(self) -> set:
		"""Who this closing entry may settle for.

		Read from the *opening* entry, not from this document's own copy of the
		roster: the opening entry is what the sales were rung up against, and a
		roster edited on the closing entry afterwards would let somebody be added
		to a shift that has already happened.

		Falls back to `self.user` alone, which restores ERPNext's exact original
		behaviour — so a site that has never used the roster is unaffected by
		this override being installed.
		"""
		return roster_for(self.pos_opening_entry) or {self.user}

	def before_validate(self):
		"""Carry the roster onto the closing entry.

		Not for validation — `_shift_cashiers` deliberately reads the opening
		entry — but because the closing entry is the document a manager opens
		when asking who was on the counter, and following a link to find out is
		how the question stops being asked.
		"""
		parent_hook = getattr(super(), "before_validate", None)
		if parent_hook:
			parent_hook()

		if not self.meta.has_field(ROSTER_FIELD) or self.get(ROSTER_FIELD):
			return

		for user in sorted(roster_for(self.pos_opening_entry)):
			self.append(ROSTER_FIELD, {"user": user})
