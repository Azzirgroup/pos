"""Who is on a shift.

ERPNext models a till shift as belonging to one person: `POS Opening Entry` has
a single `user` field, and everything downstream — the closing entry's invoice
validation, the cancellation guard — reads that one name. A counter with two
cashiers on it does not fit, and the mismatch is not cosmetic: the shift cannot
be closed at all (see `cosmestics.overrides.pos_closing_entry`).

The roster is a Table custom field, `cosmestics_cashiers`, added to POS Opening
Entry and copied onto POS Closing Entry. The core `user` field stays exactly as
it was — it is `reqd`, ERPNext depends on it, and it still answers a real
question: who opened the drawer. The roster answers the different one: who is
allowed to sell against it.

This module is the single place that reads the roster, because three different
overrides need the same answer and a second implementation is a second answer.
"""

import frappe

#: The Table custom field carrying the roster, on both POS entries.
ROSTER_FIELD = "cosmestics_cashiers"


def roster_users(doc) -> set:
	"""Every user who may transact against this shift.

	Always includes the entry's own `user`. Somebody has to have opened the
	drawer, and a roster that could exclude the opener would let a shift exist
	that its own owner cannot sell on — which is the bug this exists to fix,
	pointed the other way.

	Takes a document rather than a name so a validating document, whose roster
	rows are not in the database yet, gets the same answer as a saved one.
	"""
	users = {row.user for row in (doc.get(ROSTER_FIELD) or []) if row.user}
	if doc.get("user"):
		users.add(doc.user)
	return users


def roster_for(opening_entry: str) -> set:
	"""The same answer, for a shift known only by name."""
	if not opening_entry:
		return set()
	return roster_users(frappe.get_doc("POS Opening Entry", opening_entry))


def open_shift_for(user: str) -> str | None:
	"""The open shift this user is on — their own, or one they are rostered on.

	Used by the assignment guard so a cashier cannot be put on two open tills at
	once, which would make both drawers unreconcilable against them.
	"""
	own = frappe.db.get_value("POS Opening Entry", {"user": user, "status": "Open"}, "name")
	if own:
		return own

	# `parenttype` matters: the same child doctype is reused on POS Closing
	# Entry, and a closed shift's roster must not read as an open assignment.
	parents = frappe.get_all(
		"Cosmestics Shift Cashier",
		filters={"user": user, "parenttype": "POS Opening Entry", "parentfield": ROSTER_FIELD},
		pluck="parent",
	)
	if not parents:
		return None

	return frappe.db.get_value(
		"POS Opening Entry", {"name": ("in", parents), "status": "Open"}, "name"
	)
