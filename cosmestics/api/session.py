"""Who is using the till, and where they are selling from."""

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


@frappe.whitelist()
def context():
	"""Where this sale is going: which till, which shop, which warehouse.

	A cashier covering someone else's counter has no way of knowing which
	warehouse the app draws stock from, and getting that wrong is not visible
	until a stock report is wrong a week later. So it is stated on screen rather
	than left implicit in a settings page they cannot open.

	The warehouse resolution order matches what `pos.submit_sale` actually uses,
	so the header cannot claim one warehouse while the sale draws from another.
	"""
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default(
		"company"
	)

	shift = frappe.db.get_value(
		"POS Opening Entry",
		{"user": frappe.session.user, "docstatus": 1, "status": "Open"},
		["name", "pos_profile", "period_start_date"],
		as_dict=True,
	)

	profile = shift.pos_profile if shift else None
	# Outside a shift the till still sells; it just reconciles nowhere. Naming the
	# profile it *would* use keeps the header honest either way — but only when
	# there is no ambiguity about which one that is.
	if not profile:
		candidates = frappe.get_all(
			"POS Profile",
			filters={"disabled": 0, **({"company": company} if company else {})},
			pluck="name",
			limit_page_length=2,
		)
		profile = candidates[0] if len(candidates) == 1 else None

	# One resolver, shared with the sale — this header must never claim a
	# warehouse the invoice does not use.
	from cosmestics.api.pos import selling_warehouse

	warehouse = selling_warehouse()

	return {
		"company": company,
		"branch": profile,
		"warehouse": warehouse,
		"warehouse_label": frappe.db.get_value("Warehouse", warehouse, "warehouse_name")
		if warehouse
		else None,
		"shift": {"name": shift.name, "since": str(shift.period_start_date)} if shift else None,
		"price_list": settings.selling_price_list,
		# So the till can say "open a shift first" up front rather than letting a
		# cashier build a cart and be refused at checkout. The rule itself is
		# enforced in `pos.submit_sale`; this is only what the screen reads.
		"requires_shift": bool(settings.get("require_shift_to_sell")),
	}
