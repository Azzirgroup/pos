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

	from cosmestics.permissions import abilities

	return {
		"user": user,
		"full_name": full_name,
		"initials": initials,
		"roles": frappe.get_roles(user),
		# What this session may do, resolved on the server. The frontend gates
		# screens on this rather than matching role names itself — see
		# `permissions.abilities`.
		"can": abilities(user),
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

	from cosmestics.api.shift import get_open_shift

	shift = get_open_shift()

	profile = shift["pos_profile"] if shift else None
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

	# Read from the profile actually in use, not trusted from the client — a
	# cashier should not be able to turn on rate editing by editing the page.
	profile_flags = (
		frappe.db.get_value(
			"POS Profile", profile, ["allow_rate_change", "allow_discount_change"], as_dict=True
		)
		if profile
		else None
	)

	return {
		"company": company,
		"branch": profile,
		"warehouse": warehouse,
		"warehouse_label": frappe.db.get_value("Warehouse", warehouse, "warehouse_name")
		if warehouse
		else None,
		"shift": {
			"name": shift["name"],
			"since": shift["period_start_date"],
			"user": shift["user"],
			"shared": shift["shared"],
		}
		if shift
		else None,
		"price_list": settings.selling_price_list,
		# So the till can say "open a shift first" up front rather than letting a
		# cashier build a cart and be refused at checkout. The rule itself is
		# enforced in `pos.submit_sale`; this is only what the screen reads.
		"requires_shift": bool(settings.get("require_shift_to_sell")),
		# Whether the grid draws product photos. Read here rather than fetched
		# separately so the first paint already knows — a grid that starts without
		# pictures and grows them a moment later reflows every cell under the
		# cashier's finger.
		"show_item_images": bool(settings.get("show_item_images")),
		# Gate the checkout cart's rate/discount editing controls. `pos.submit_sale`
		# does not enforce these — see the note there — so keeping the sale itself
		# safe from a client that ignores this flag is out of scope here.
		"allow_rate_change": bool(profile_flags and profile_flags.allow_rate_change),
		"allow_discount_change": bool(profile_flags and profile_flags.allow_discount_change),
	}
