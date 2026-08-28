"""Make the two single-cashier guards on POS Opening Entry roster-aware.

Both of ERPNext's checks here read the one `user` field, which is right until a
shift has more than one person on it:

* `check_user_already_assigned` stops a cashier being on two open shifts. With a
  roster it stops reading the truth — a cashier rostered on another till is
  assigned, and nothing noticed. Two open drawers that both expect the same
  person's takings cannot both reconcile.
* `check_poe_is_cancellable` refuses to cancel a shift that already has sales,
  looking them up with `get_invoices(..., self.user)`. Scoped to the opener, it
  cannot see a co-cashier's sales — so a shift with somebody else's money in it
  cancels without complaint, and those invoices are left pointing at a
  cancelled shift they can never be settled against.

`check_open_pos_exists` is deliberately untouched. One open entry per POS
Profile is exactly the constraint the roster is built on top of.
"""

import frappe
from frappe import _
from frappe.utils import get_link_to_form

from cosmestics.overrides.shift_roster import ROSTER_FIELD, open_shift_for, roster_users


class SharedShiftOpeningMixin:
	def before_validate(self):
		"""Make the Cashiers table the one place a shift's people are named.

		ERPNext's `user` field cannot be removed — it is `reqd`, and the closing
		entry, the cancellation guard and every standard POS report read it. Two
		controls asking the same question is worse than one, though: a form with
		both a Cashier field and a Cashiers table invites them to disagree, and
		nothing on screen says which one decides.

		So the table wins and the field follows it. `user` becomes the first row —
		the shift's owner, which is the single name ERPNext insists on — and the
		field itself is hidden on the form (see `setup.install`). Filling only the
		table is now the whole interaction; the field is a derived value that
		happens to live in ERPNext's schema.

		Runs in `before_validate` deliberately: mandatory fields are checked in
		`_validate`, which comes after, so a hidden `user` is populated in time.
		"""
		parent_hook = getattr(super(), "before_validate", None)
		if parent_hook:
			parent_hook()

		if not self.meta.has_field(ROSTER_FIELD):
			return

		current = [row.user for row in (self.get(ROSTER_FIELD) or []) if row.user]
		users = list(dict.fromkeys(current))

		# An empty table on a doc that already names somebody — the desk's default,
		# or a shift opened by an older client — means a one-cashier shift. Writing
		# them in makes the table the complete answer rather than a partial one.
		if not users and self.user:
			users = [self.user]

		if not users:
			return

		self.user = users[0]
		# Only rewritten when it actually changed, so an unedited save does not
		# replace every child row with a fresh one.
		if users != current:
			self.set(ROSTER_FIELD, [{"user": u} for u in users])

	def check_open_pos_exists(self):
		"""One shift per till — and, when the shop says so, one per till per day.

		ERPNext's own check is kept exactly as it is: a counter may not have two
		shifts open at once, which is the constraint the roster is built on.

		The day rule is this shop's, and it is about reconciliation rather than
		concurrency. Two shifts run back to back produce two closing entries for
		one drawer and one day's takings, and nothing downstream adds them up —
		so the day cannot be reconciled against a single count, and a shortfall
		in the morning is invisible beside a surplus in the afternoon.

		Deliberately a setting, defaulting on, because the cost of the rule is
		real: a shift closed by mistake at nine o'clock locks that counter until
		midnight. The message says how to lift it, and the setting sits next to
		the other till rules rather than being buried in code.
		"""
		parent_hook = getattr(super(), "check_open_pos_exists", None)
		if parent_hook:
			parent_hook()

		if self.docstatus == 2 or not self.pos_profile:
			return
		if not frappe.db.get_single_value("Cosmestics POS Settings", "one_shift_per_day"):
			return

		posting_date = self.posting_date or frappe.utils.nowdate()
		earlier = frappe.db.get_value(
			"POS Opening Entry",
			{
				"pos_profile": self.pos_profile,
				"posting_date": posting_date,
				"docstatus": 1,
				"name": ("!=", self.name or ""),
			},
			["name", "user", "status"],
			as_dict=True,
		)
		if not earlier:
			return

		frappe.throw(
			title=_("Already Opened Today"),
			msg=_(
				"{0} was already opened today by {1} ({2}). One shift per till per day keeps "
				"the whole day's takings on one closing entry. Add this cashier to that shift "
				"instead — or, if the counter really must reopen, turn off <b>One Shift Per "
				"Till Per Day</b> in the till settings."
			).format(
				frappe.bold(self.pos_profile),
				frappe.bold(earlier.user),
				get_link_to_form("POS Opening Entry", earlier.name),
			),
		)

	def check_user_already_assigned(self):
		"""Nobody on this shift may already be on another open one.

		Checks every name on the roster, not just the opener. The opener is in
		`roster_users` too, so the original behaviour is the single-name case of
		this one rather than a branch beside it.
		"""
		for user in sorted(roster_users(self)):
			other = open_shift_for(user)
			# `self.name` is set by the time validate runs on an existing doc;
			# on a new one it is a temporary hash that matches nothing, which is
			# the right answer either way.
			if other and other != self.name:
				frappe.throw(
					title=_("Cannot Assign Cashier"),
					msg=_("{0} is already on an open shift ({1}).").format(
						frappe.bold(user), get_link_to_form("POS Opening Entry", other)
					),
				)

	def check_poe_is_cancellable(self):
		"""Refuse to cancel a shift that anyone on it has already sold against.

		ERPNext asks its own `get_invoices` for the opener's sales. This asks the
		same question the closing entry does — every `is_pos` invoice tagged with
		this profile inside the window, whoever rang it up — because that is the
		set the shift is actually responsible for.
		"""
		from cosmestics.api.shift import _shift_invoices

		data = _shift_invoices(self.pos_profile, self.period_start_date, frappe.utils.get_datetime())
		if data.get("invoices"):
			frappe.throw(
				_("You cannot cancel this shift — {0} sales have already been rung up on it.").format(
					frappe.bold(len(data["invoices"]))
				)
			)
