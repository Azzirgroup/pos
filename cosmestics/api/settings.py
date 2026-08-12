"""Everything configurable, in one screen.

The shop's POS settings and the till's own POS Profile lived in the desk, which
is a place a shop manager either cannot reach or will not find. This exposes the
handful of fields that actually get changed — where stock is drawn from, what
the till sells at, which Mode of Payment each M-Pesa channel books to — and
leaves the rest to ERPNext.

Two boundaries worth keeping:

* **Fields are allow-listed, not passed through.** `save_pos_settings` writes
  only the fieldnames declared below, so a value the browser was never offered
  cannot be smuggled onto the Single. The same rule as `documents.py` and
  `master.py`.
* **Editing a POS Profile requires the write permission on it.** Reading is
  offered to any cashier so the till can say where it sells from; changing it is
  not, because a profile decides the warehouse every sale draws down.
"""

import frappe
from frappe import _

#: Shop-wide till configuration. Anything not here is not writable from the app.
POS_SETTINGS_FIELDS = (
	"mode_cash",
	"mode_mpesa",
	"mode_mpesa_send",
	"mode_mpesa_paybill",
	"mode_mpesa_withdraw",
	"mode_card",
	"selling_price_list",
	"notify_material_request",
	"whatsapp_group_jid",
	"whatsapp_sender",
	# Not `neighbour_supplier_group` any more — which shops the till offers
	# mid-sale is now a checkbox on the Supplier itself
	# (`cosmestics_is_neighbour_shop`), not a single shop-wide group setting.
	"default_source_warehouse",
	"default_expense_account",
	"require_shift_to_sell",
)

#: POS Profile fields a shop actually retargets. Deliberately excludes the
#: payment methods table and the accounting defaults — those are structural, and
#: a half-filled form here would break selling rather than configure it.
PROFILE_FIELDS = (
	"warehouse",
	"selling_price_list",
	"customer",
	"currency",
	"disabled",
	"hide_images",
	"hide_unavailable_items",
	"allow_rate_change",
	"allow_discount_change",
	"print_receipt_on_order",
	# Where a shortfall a cashier is named for is charged. It lives on the
	# profile rather than in one company-wide setting because two branches of the
	# same shop can answer "do staff carry the loss" differently.
	"cosmestics_short_account",
)

#: What the user can set for themselves. Kept small on purpose: this is a till,
#: not a profile page.
USER_FIELDS = ("full_name", "mobile_no", "language", "time_zone")


@frappe.whitelist()
def get() -> dict:
	"""Everything the settings screen renders, in one round trip."""
	settings = frappe.get_single("Cosmestics POS Settings")
	user = frappe.get_doc("User", frappe.session.user)

	return {
		"pos": {f: settings.get(f) for f in POS_SETTINGS_FIELDS},
		"pos_meta": _field_meta("Cosmestics POS Settings", POS_SETTINGS_FIELDS),
		"can_edit_pos": _can_write("Cosmestics POS Settings"),
		"user": {f: user.get(f) for f in USER_FIELDS},
		"user_meta": _field_meta("User", USER_FIELDS),
		"pin": {
			# Never the hash, and never the digits — there are none stored. All the
			# screen needs to know is whether a PIN exists, so it can offer
			# "change" rather than "set" and say what unticking the box will do.
			"has_pin": bool(user.get("cosmestics_pin_hash")),
			"enabled": bool(user.get("cosmestics_pin_login")),
		},
		"profiles": _profiles(),
		"can_edit_profile": _can_write("POS Profile"),
		"company": frappe.defaults.get_user_default("Company")
		or frappe.defaults.get_global_default("company"),
	}


def _profiles() -> list:
	"""POS Profiles this user can sell on, each with its editable fields.

	Mirrors `shift.get_profiles` — a profile the user cannot open a shift on is
	not one they should be reconfiguring from the till.
	"""
	from cosmestics.api.shift import get_profiles

	out = []
	for row in get_profiles():
		doc = frappe.get_doc("POS Profile", row["name"])
		out.append(
			{
				"name": doc.name,
				"company": doc.company,
				"values": {f: doc.get(f) for f in PROFILE_FIELDS if doc.meta.has_field(f)},
				# Which users this till is bound to. Shown because "why can I not
				# see this profile" is answered by exactly this list.
				"users": [u.user for u in (doc.get("applicable_for_users") or [])],
				"mine": frappe.session.user
				in [u.user for u in (doc.get("applicable_for_users") or [])],
			}
		)
	return out


def _field_meta(doctype: str, fieldnames) -> dict:
	"""Labels, types and link targets read from the DocType.

	Read rather than repeated, so a field relabelled in the desk relabels here —
	the same rule the documents hub follows.
	"""
	meta = frappe.get_meta(doctype)
	out = {}
	for fieldname in fieldnames:
		df = meta.get_field(fieldname)
		if not df:
			continue
		out[fieldname] = {
			"label": _(df.label or fieldname),
			"fieldtype": df.fieldtype,
			"options": df.options,
			"description": _(df.description) if df.description else None,
		}
	return out


def _can_write(doctype: str) -> bool:
	return bool(frappe.has_permission(doctype, "write"))


@frappe.whitelist(methods=["POST"])
def save_pos_settings(values: dict | str) -> dict:
	"""Write the shop-wide till configuration."""
	if isinstance(values, str):
		values = frappe.parse_json(values)

	if not _can_write("Cosmestics POS Settings"):
		frappe.throw(_("You do not have permission to change the till settings"))

	doc = frappe.get_single("Cosmestics POS Settings")
	changed = []
	for field in POS_SETTINGS_FIELDS:
		if field not in values:
			continue
		new = values[field]
		if doc.get(field) != new:
			doc.set(field, new)
			changed.append(field)

	if changed:
		doc.save()

	return {"saved": changed, "message": _("{0} settings updated").format(len(changed)) if changed else _("Nothing changed")}


@frappe.whitelist(methods=["POST"])
def save_profile(name: str, values: dict | str) -> dict:
	"""Retarget the POS Profile this till sells on.

	`warehouse` is the field that matters and the reason this is permission
	checked rather than offered to everyone: it decides which stock every sale
	on this till draws down.
	"""
	if isinstance(values, str):
		values = frappe.parse_json(values)

	if not _can_write("POS Profile"):
		frappe.throw(_("You do not have permission to change a till profile"))

	allowed = {p["name"] for p in _profiles()}
	if name not in allowed:
		# The profile list is the boundary: a caller-supplied name never becomes
		# a document this user was not already entitled to open a shift on.
		frappe.throw(_("{0} is not a till you can configure").format(name))

	doc = frappe.get_doc("POS Profile", name)
	changed = []
	for field in PROFILE_FIELDS:
		if field not in values or not doc.meta.has_field(field):
			continue
		if doc.get(field) != values[field]:
			doc.set(field, values[field])
			changed.append(field)

	if changed:
		doc.save()

	return {"saved": changed, "message": _("{0} updated").format(name) if changed else _("Nothing changed")}


@frappe.whitelist(methods=["POST"])
def create_profile(profile_name: str, values: dict | str | None = None) -> dict:
	"""Add a till.

	A second counter, a new branch, a phone used as a till at the door — all of
	them need a POS Profile, and until now that meant the desk. The form here is
	the same short list `save_profile` writes, plus the two things a profile
	cannot exist without: a company and a name.

	Two things are done for the shop rather than asked of it, because getting
	either wrong produces a till that looks configured and cannot sell:

	- **The payment methods table.** A POS Profile with no payment method
	  refuses every sale, and the error names a child table a shopkeeper has
	  never heard of. Seeded from the modes this app already maps.
	- **The user.** Whoever creates a till is put on it, so they can open a shift
	  on it immediately rather than meeting "no POS profile available".
	"""
	if isinstance(values, str):
		values = frappe.parse_json(values)
	values = values or {}

	if not _can_write("POS Profile"):
		frappe.throw(_("You do not have permission to add a till"))

	profile_name = (profile_name or "").strip()
	if not profile_name:
		frappe.throw(_("Give the till a name"))
	if frappe.db.exists("POS Profile", profile_name):
		frappe.throw(_("A till called {0} already exists").format(profile_name))

	company = values.get("company") or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw(_("No company to create this till under"))

	doc = frappe.new_doc("POS Profile")
	doc.name = profile_name
	doc.company = company
	for field in PROFILE_FIELDS:
		if field in values and doc.meta.has_field(field) and values[field] not in (None, ""):
			doc.set(field, values[field])

	for mode in _till_modes(company):
		doc.append("payments", {"mode_of_payment": mode, "default": 1 if mode == _cash_mode() else 0})

	doc.append("applicable_for_users", {"user": frappe.session.user})
	_fill_profile_defaults(doc, company)
	doc.insert()

	return {
		"name": doc.name,
		"message": _("{0} created — you can open a shift on it now").format(doc.name),
	}


def _fill_profile_defaults(doc, company):
	"""The fields ERPNext insists on that a shopkeeper cannot be asked for.

	`warehouse`, `write_off_account` and `write_off_cost_center` are mandatory on
	a POS Profile. The first is a real question and is on the form; the other two
	are accounting plumbing — a till's write-off account is the company's, always,
	and asking would be asking somebody to guess. Taken from the company, and
	refused with a plain sentence when the company has not set them, because a
	blank there is a real configuration gap rather than something to invent.
	"""
	if not doc.warehouse:
		from cosmestics.api.pos import selling_warehouse

		doc.warehouse = selling_warehouse() or frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name"
		)
	if not doc.warehouse:
		frappe.throw(_("Pick the warehouse this till sells from"))

	values = frappe.db.get_value(
		"Company", company, ["write_off_account", "cost_center", "default_cash_account"], as_dict=True
	) or frappe._dict()

	if not doc.write_off_account:
		doc.write_off_account = values.write_off_account
	if not doc.write_off_cost_center:
		doc.write_off_cost_center = values.cost_center

	missing = [
		label
		for field, label in (
			("write_off_account", _("a write-off account")),
			("write_off_cost_center", _("a cost centre")),
		)
		if not doc.get(field)
	]
	if missing:
		frappe.throw(
			_("{0} has no {1}. Set it on the Company before adding a till.").format(
				company, _(" and ").join(missing)
			)
		)


def _cash_mode():
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	return settings.mode_cash or frappe.db.get_value(
		"Mode of Payment", {"type": "Cash", "enabled": 1}, "name"
	)


def _till_modes(company):
	"""Modes this company can actually settle into.

	Only modes with an account mapped: a profile offering a tender that has
	nowhere to post is a sale that fails at submit, after the customer has paid.
	"""
	rows = frappe.get_all(
		"Mode of Payment Account",
		filters={"company": company},
		fields=["parent", "default_account"],
	)
	enabled = set(
		frappe.get_all(
			"Mode of Payment",
			filters={"enabled": 1, "name": ("in", [r.parent for r in rows])},
			pluck="name",
		)
	) if rows else set()
	modes = [r.parent for r in rows if r.parent in enabled and r.default_account]

	if not modes:
		frappe.throw(
			_(
				"No mode of payment has an account on {0}, so a till created here "
				"could not take money. Map one first."
			).format(company)
		)
	return list(dict.fromkeys(modes))


@frappe.whitelist(methods=["POST"])
def assign_profile(name: str, assign: int = 1) -> dict:
	"""Bind this till profile to the current user, or unbind it.

	A cashier who is not on a profile's user list cannot open a shift on it, and
	the resulting "no POS profile available" is the single most confusing thing
	the till can say. This is the one-tap fix for it.
	"""
	if not _can_write("POS Profile"):
		frappe.throw(_("You do not have permission to change a till profile"))

	doc = frappe.get_doc("POS Profile", name)
	if not doc.meta.has_field("applicable_for_users"):
		frappe.throw(_("This ERPNext version does not bind users to POS Profiles"))

	user = frappe.session.user
	existing = [u for u in doc.applicable_for_users if u.user == user]

	if int(assign or 0):
		if not existing:
			doc.append("applicable_for_users", {"user": user})
	else:
		# Never leave a profile with an empty user list: on ERPNext an empty list
		# means "everyone", so removing the last name silently widens access
		# instead of narrowing it.
		if existing and len(doc.applicable_for_users) > 1:
			doc.applicable_for_users = [u for u in doc.applicable_for_users if u.user != user]
		elif existing:
			frappe.throw(
				_("{0} is the only user on this till. Add another before removing yourself.").format(
					user
				)
			)

	doc.save()
	return {"name": doc.name, "assigned": bool(int(assign or 0))}


@frappe.whitelist(methods=["POST"])
def save_user(values: dict | str) -> dict:
	"""Update the signed-in user's own details.

	Only ever the session user — a whitelisted endpoint that took a username
	would be a way to rename anybody on the site.
	"""
	if isinstance(values, str):
		values = frappe.parse_json(values)

	doc = frappe.get_doc("User", frappe.session.user)
	changed = []
	for field in USER_FIELDS:
		if field not in values:
			continue
		if doc.get(field) != values[field]:
			doc.set(field, values[field])
			changed.append(field)

	changed += _apply_pin(doc, values)

	if changed:
		doc.save(ignore_permissions=True)

	return {"saved": changed, "message": _("Your details were updated") if changed else _("Nothing changed")}


def _apply_pin(doc, values: dict) -> list:
	"""Let people set their own till PIN, rather than asking an administrator.

	The PIN was previously reachable only from the desk User form, which meant a
	shop had to have somebody with desk access set one for each cashier — and
	that person necessarily learned the PIN they were typing in. A secret a
	second person chose and knows is not much of a secret; one you set yourself,
	on your own account, from the till you use, is the same trade every password
	change makes.

	It stays safe because nothing here widens who can be changed: `save_user`
	only ever loads the session user, so this can no more set somebody else's
	PIN than it can rename them. The digits are not written either — the
	`validate` hook hashes them and blanks the field before the row is saved, and
	that hook also enforces four digits and refuses the obvious ones. See
	`cosmestics.api.pin`.
	"""
	changed = []

	pin = (values.get("pin") or "").strip()
	if pin:
		# Assigned, not compared: there is nothing to compare against. The stored
		# value is a hash, so "same PIN as before" is indistinguishable from a new
		# one and re-hashing it is harmless.
		doc.cosmestics_pin = pin
		changed.append("pin")

	if "pin_login" in values:
		wanted = 1 if values.get("pin_login") else 0
		if wanted and not pin and not doc.get("cosmestics_pin_hash"):
			# Silently allowing this produces a till that offers PIN sign-in and
			# then does not list you on it, which reads as a broken feature rather
			# than an unfinished setup.
			frappe.throw(_("Set a PIN first — there is nothing to sign in with yet."))
		if int(doc.get("cosmestics_pin_login") or 0) != wanted:
			doc.cosmestics_pin_login = wanted
			changed.append("pin_login")

	return changed


@frappe.whitelist()
def link_options(doctype: str, search: str | None = None, limit: int = 20) -> list:
	"""Options for one of the link fields this screen declares.

	Scoped to the doctypes the settings fields actually point at. A generic
	"search any doctype" endpoint would be a way to read any table on the site —
	the same reasoning as `master.link_options`.
	"""
	allowed = _linked_doctypes()
	if doctype not in allowed:
		frappe.throw(_("{0} is not a field this screen can fill").format(doctype))

	filters = {}
	meta = frappe.get_meta(doctype)
	if meta.has_field("disabled"):
		filters["disabled"] = 0
	if meta.has_field("is_group"):
		filters["is_group"] = 0
	if meta.has_field("company"):
		company = frappe.defaults.get_user_default("Company")
		if company:
			filters["company"] = company

	return frappe.get_all(
		doctype,
		filters=filters,
		or_filters={"name": ("like", f"%{search}%")} if search else None,
		fields=["name"],
		order_by="name asc",
		limit=min(int(limit or 20), 100),
	)


def _linked_doctypes() -> set:
	"""Every Link target named by the fields this screen exposes."""
	out = set()
	for doctype, fields in (
		("Cosmestics POS Settings", POS_SETTINGS_FIELDS),
		("POS Profile", PROFILE_FIELDS),
		# The user block asks for a Language too. Left out, this screen offered a
		# picker whose options endpoint then refused the very doctype it had just
		# asked for — "Language is not a field this screen can fill".
		("User", USER_FIELDS),
	):
		meta = frappe.get_meta(doctype)
		for fieldname in fields:
			df = meta.get_field(fieldname)
			if df and df.fieldtype == "Link" and df.options:
				out.add(df.options)
	return out
