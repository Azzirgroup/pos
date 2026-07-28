"""Who is using the till."""

import frappe


@frappe.whitelist()
def me():
	"""Current user, with initials for the avatar.

	Read from the session rather than trusted from the client — the name in the
	corner is what a cashier checks before starting a shift, so it has to be the
	account the sale will actually be recorded against.
	"""
	user = frappe.session.user
	full_name = frappe.utils.get_fullname(user) or user

	parts = [p for p in full_name.replace(".", " ").split() if p]
	initials = "".join(p[0] for p in parts[:2]).upper() or user[:2].upper()

	return {
		"user": user,
		"full_name": full_name,
		"initials": initials,
		"roles": frappe.get_roles(user),
	}
