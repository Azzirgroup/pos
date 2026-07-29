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
	"neighbour_supplier_group",
	"default_source_warehouse",
	"default_expense_account",
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

	if changed:
		doc.save(ignore_permissions=True)

	return {"saved": changed, "message": _("Your details were updated") if changed else _("Nothing changed")}


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
	):
		meta = frappe.get_meta(doctype)
		for fieldname in fields:
			df = meta.get_field(fieldname)
			if df and df.fieldtype == "Link" and df.options:
				out.add(df.options)
	return out
