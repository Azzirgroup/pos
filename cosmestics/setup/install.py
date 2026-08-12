"""Install-time setup.

Split into two very different jobs, deliberately:

* `setup_prerequisites` creates the structural records the app cannot work
  without (the neighbour Supplier Group, POS settings defaults). Always safe,
  always runs, idempotent.
* demo catalog seeding is a separate, guarded step — see `cosmestics.setup.demo`.
  Writing 62 products into somebody's live shop because they installed an app
  would be unforgivable, so it only happens on a site that has no items yet, or
  when explicitly asked for.
"""

import frappe
from frappe import _

NEIGHBOUR_GROUP = "Neighbour Shop"
DEFAULT_NEIGHBOUR = "Neighbour Shop (Walk-in)"
MPESA_MODE = "M-Pesa"

# M-Pesa reaches a Kenyan shop three ways, and each one settles differently: a
# Send Money lands in the till's own wallet, a Paybill in the business account,
# and an agent Withdraw takes cash *out* of the drawer. They are three Modes of
# Payment rather than three labels on one, because a shift that cannot tell them
# apart cannot be reconciled against what is actually in each account.
MPESA_CHANNELS = (
	("mode_mpesa_send", "M-Pesa Send Money"),
	("mode_mpesa_paybill", "M-Pesa Paybill"),
	("mode_mpesa_withdraw", "M-Pesa Withdraw"),
)


def after_install():
	setup_prerequisites()
	from cosmestics.setup.demo import maybe_seed_demo

	maybe_seed_demo()
	frappe.db.commit()


def after_migrate():
	# Prerequisites only. Migrations must never invent transactional data.
	setup_prerequisites()
	frappe.db.commit()


def setup_prerequisites():
	group = ensure_neighbour_supplier_group()
	ensure_neighbour_shop_field()
	ensure_default_neighbour(group)
	ensure_mpesa_mode_of_payment()
	ensure_mpesa_channel_modes()
	apply_settings_defaults(group)
	# Must run after the settings map the till's buttons onto real modes.
	ensure_mode_of_payment_accounts()
	ensure_pos_profile_payment_methods()
	ensure_pos_settings()
	ensure_partial_payment_allowed()
	ensure_short_account_field()
	ensure_shift_cashier_field()
	ensure_pin_login_fields()
	ensure_quote_conversion_fields()
	ensure_app_icon()
	# Must run after the field exists, and after `group` is known so a site
	# upgrading from the group-only scheme keeps its existing neighbours.
	backfill_neighbour_shop_flag(group)


def ensure_short_account_field():
	"""Give POS Profile somewhere to say where a till shortfall is charged.

	A Custom Field rather than a setting on this app's own doctype because the
	answer genuinely differs per till: a branch whose staff carry the loss and a
	branch that writes it off are the same shop with two POS Profiles, and one
	company-wide account cannot express that.

	Created here rather than shipped as a fixture so it survives a migrate on a
	site that already has the app — see `after_migrate`.
	"""
	if not frappe.db.exists("DocType", "POS Profile"):
		return

	if frappe.db.exists("Custom Field", {"dt": "POS Profile", "fieldname": "cosmestics_short_account"}):
		return

	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	create_custom_field(
		"POS Profile",
		{
			"fieldname": "cosmestics_short_account",
			"label": "Till Short Account",
			"fieldtype": "Link",
			"options": "Account",
			"insert_after": "write_off_account",
			"description": (
				"Where a shortfall a cashier is named for is charged — usually a "
				"receivable from staff. Anything nobody is named for goes to the "
				"Unattributed Short Account in Cosmetics POS Settings."
			),
		},
	)


def ensure_shift_cashier_field():
	"""Give a till shift somewhere to say who is on it.

	ERPNext's POS Opening Entry names one cashier. A counter with two people
	behind it needs a list, so both POS entries get a `cosmestics_cashiers`
	table — the opening entry to declare the roster, the closing entry to keep a
	record of it on the document a manager actually reads.

	A Custom Field rather than a fork of the doctype, so ERPNext keeps owning its
	own schema and an upgrade cannot silently drop this. Created here rather than
	as a fixture so it survives a migrate on a site that already has the app —
	see `after_migrate`.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	targets = (
		(
			"POS Opening Entry",
			"Everyone selling against this shift. The first row owns it; the rest "
			"settle their sales on the same closing entry.",
		),
		(
			"POS Closing Entry",
			"Who was on the shift being closed. Copied from the opening entry; "
			"editing it here does not change whose sales are settled.",
		),
	)

	for doctype, description in targets:
		if not frappe.db.exists("DocType", doctype):
			continue

		if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": "cosmestics_cashiers"}):
			create_custom_field(
				doctype,
				{
					"fieldname": "cosmestics_cashiers",
					"label": "Cashiers",
					"fieldtype": "Table",
					"options": "Cosmestics Shift Cashier",
					"insert_after": "user",
					"description": description,
				},
			)

		hide_single_cashier_field(doctype)


def ensure_quote_conversion_fields():
	"""Record which sale a quotation became.

	ERPNext has nowhere to put this. A quotation is marked Ordered from
	`Quotation Item.ordered_qty`, which only a Sales Order fills in — and this
	till posts Sales Invoices directly, with no order in between. `Sales Invoice
	Item` carries a `sales_order` link and nothing for a quotation, so a quote
	sold at the counter left no trace on itself and stayed Open for ever.

	So the link is stored here. `quotations.mark_converted` writes it and also
	fills `ordered_qty`, so ERPNext's own status rule reaches "Ordered" by
	itself rather than being overwritten with it.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	fields = [
		{
			"fieldname": "cosmestics_converted_invoice",
			"label": "Sold As",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"insert_after": "status",
			"read_only": 1,
			"no_copy": 1,
			"allow_on_submit": 1,
			"description": "The till sale this quotation became.",
		},
		{
			"fieldname": "cosmestics_converted_on",
			"label": "Sold On",
			"fieldtype": "Datetime",
			"insert_after": "cosmestics_converted_invoice",
			"read_only": 1,
			"no_copy": 1,
			"allow_on_submit": 1,
		},
	]
	for field in fields:
		if frappe.db.exists("Custom Field", {"dt": "Quotation", "fieldname": field["fieldname"]}):
			continue
		create_custom_field("Quotation", field)


def ensure_app_icon():
	"""Keep the desk's app icon pointing where `add_to_apps_screen` says.

	The icon on the desk is a **Desktop Icon row**, written once when the app is
	installed. The hook only seeds it — editing the hook afterwards changes what a
	*fresh* install gets and leaves every existing site clicking through to the
	old destination, with nothing on screen to suggest why.

	That is exactly what happened here: the tile kept opening the till long after
	the hook said dashboard, and the title stayed on a name the app no longer
	used. So the row is reconciled against the hook on every migrate.

	Only the fields the hook owns are touched. Anything a shop has changed itself
	— where the icon sits, whether it is hidden — is left alone.
	"""
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return

	entries = frappe.get_hooks("add_to_apps_screen", app_name="cosmestics") or []
	if not entries:
		return
	wanted = entries[0]

	title = wanted.get("title")

	for name in frappe.get_all("Desktop Icon", filters={"app": "cosmestics"}, pluck="name"):
		# Desktop Icon is `autoname: field:label`, so the label *is* the primary
		# key. Assigning it and saving looks like it works and silently reverts —
		# the only way to retitle one is to rename the document.
		if title and name != title and not frappe.db.exists("Desktop Icon", title):
			frappe.rename_doc("Desktop Icon", name, title, force=True)
			name = title

		icon = frappe.get_doc("Desktop Icon", name)
		changed = False
		for field, value in (("link", wanted.get("route")), ("logo_url", wanted.get("logo"))):
			if value and icon.get(field) != value:
				icon.set(field, value)
				changed = True
		if changed:
			icon.save(ignore_permissions=True)

	# The desk reads icons from a cache keyed per user, not from the table.
	from frappe.desk.doctype.desktop_icon.desktop_icon import clear_desktop_icons_cache

	frappe.cache.delete_key("desktop_icons")
	frappe.cache.delete_key("bootinfo")
	clear_desktop_icons_cache()


def ensure_pin_login_fields():
	"""Let a cashier be given a four-digit PIN for the till.

	Three fields, and the split matters. `cosmestics_pin` is only ever typed
	into — `cosmestics.api.pin.hash_user_pin` hashes it and blanks it before the
	document is saved, so the digits are never written anywhere. The hash lives
	in its own read-only field, and the checkbox is a separate deliberate act:
	setting a PIN and permitting its use are two decisions, and a shop should be
	able to revoke the second without destroying the first.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	fields = [
		{
			"fieldname": "cosmestics_pin_section",
			"label": "Till PIN",
			"fieldtype": "Section Break",
			"insert_after": "username",
			"collapsible": 1,
		},
		{
			"fieldname": "cosmestics_pin_login",
			"label": "Allow PIN sign-in at the till",
			"fieldtype": "Check",
			"insert_after": "cosmestics_pin_section",
			"description": (
				"Lets this person sign in at the POS with their PIN instead of a "
				"password. Signs them in as themselves — it grants nothing extra."
			),
		},
		{
			"fieldname": "cosmestics_pin",
			"label": "PIN (4 digits)",
			"fieldtype": "Password",
			"insert_after": "cosmestics_pin_login",
			"depends_on": "eval:doc.cosmestics_pin_login",
			"description": (
				"Type four digits and save. The PIN is hashed immediately and cannot "
				"be read back — to change it, type a new one."
			),
		},
		{
			"fieldname": "cosmestics_pin_hash",
			"label": "PIN Hash",
			"fieldtype": "Data",
			"insert_after": "cosmestics_pin",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			# Never a search key, never in a report, never exported by accident.
			"print_hide": 1,
		},
	]

	for field in fields:
		if frappe.db.exists("Custom Field", {"dt": "User", "fieldname": field["fieldname"]}):
			continue
		create_custom_field("User", field)


def hide_single_cashier_field(doctype: str):
	"""Take ERPNext's one-cashier field off the form.

	It cannot be deleted — `user` is `reqd`, and the closing entry, the
	cancellation guard and every standard POS report read it. But leaving it
	beside the Cashiers table puts two controls on screen asking the same
	question, with nothing saying which one decides. That is a worse form than
	either control alone.

	So it is hidden and derived: the table is what a person fills in, and
	`before_validate` on the entry keeps `user` equal to the first row (see
	`cosmestics.overrides.pos_opening_entry`). The value is still there, still
	correct, and still exactly what ERPNext expects to find.

	A Property Setter rather than an edit to the DocType, so ERPNext keeps owning
	its own schema and this is one row to delete if the shop ever wants the field
	back.
	"""
	frappe.make_property_setter(
		{
			"doctype": doctype,
			"fieldname": "user",
			"property": "hidden",
			"value": 1,
			"property_type": "Check",
		},
		is_system_generated=True,
		validate_fields_for_doctype=False,
	)


def ensure_neighbour_shop_field():
	"""Give Supplier its own way to say "this is a shop we buy from mid-sale".

	A Custom Field rather than the Supplier Group, which is what this used to
	be inferred from: a shop's group is its own real classification (a
	wholesaler is still a wholesaler), and forcing every neighbour into one
	particular group to make it discoverable at the till overwrote whatever
	that classification should have been. This is independent of it — a
	neighbour can carry any group, or none.

	Created here rather than shipped as a fixture so it survives a migrate on
	a site that already has the app — see `after_migrate`.
	"""
	if not frappe.db.exists("DocType", "Supplier"):
		return

	if frappe.db.exists("Custom Field", {"dt": "Supplier", "fieldname": "cosmestics_is_neighbour_shop"}):
		return

	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	create_custom_field(
		"Supplier",
		{
			"fieldname": "cosmestics_is_neighbour_shop",
			"label": "Neighbour Shop",
			"fieldtype": "Check",
			"insert_after": "supplier_group",
			"description": (
				"Offered as a source when a cashier runs out of stock mid-sale. "
				"Independent of Supplier Group — check this regardless of what "
				"group the shop is otherwise classified under."
			),
		},
	)


def backfill_neighbour_shop_flag(group: str | None):
	"""One-time migration for a site upgrading from the group-only scheme.

	Every existing supplier in the (now legacy) neighbour group is flagged,
	once, so switching the till's own lookups over to the new field does not
	silently drop shops that were already working. Idempotent: only ever sets
	the flag, never clears it, so a shop that unchecked it on purpose stays
	unchecked on the next migrate.
	"""
	if not group or not frappe.db.exists("DocType", "Supplier"):
		return
	if not frappe.db.has_column("Supplier", "cosmestics_is_neighbour_shop"):
		return

	frappe.db.set_value(
		"Supplier",
		{"supplier_group": group, "cosmestics_is_neighbour_shop": 0},
		"cosmestics_is_neighbour_shop",
		1,
	)


def ensure_pos_settings():
	"""Keep POS Settings on Sales Invoice.

	ERPNext's `validate_created_using_pos` hard-throws "Transactions using Sales
	Invoice in POS are disabled" when this is set to POS Invoice — which would
	break every sale this app makes, since it posts Sales Invoices by design.
	"""
	if not frappe.db.exists("DocType", "POS Settings"):
		return

	if frappe.db.get_single_value("POS Settings", "invoice_type") != "Sales Invoice":
		frappe.db.set_single_value("POS Settings", "invoice_type", "Sales Invoice")


def ensure_partial_payment_allowed():
	"""Let the till take part-payments.

	Without this ERPNext raises PartialPaymentValidationError on any sale where
	paid_amount is under the total. The balance still lands on the customer's
	account as outstanding, so nothing is written off.
	"""
	if not frappe.db.exists("DocType", "POS Profile"):
		return

	for name in frappe.get_all("POS Profile", filters={"disabled": 0}, pluck="name"):
		if not frappe.db.get_value("POS Profile", name, "allow_partial_payment"):
			frappe.db.set_value("POS Profile", name, "allow_partial_payment", 1)


def ensure_mode_of_payment_accounts():
	"""Give every till payment mode a company account.

	POS Opening Entry refuses to save if any mode in its opening balances lacks
	a Mode of Payment Account for the company, so a shift cannot be started
	otherwise. ERPNext ships Cash and Credit Card with no account mapped on a
	fresh company, which is exactly the case that breaks.
	"""
	if not frappe.db.exists("DocType", "Mode of Payment"):
		return

	company = frappe.defaults.get_global_default("company")
	if not company:
		return

	settings = frappe.get_single("Cosmestics POS Settings")
	fields = ["mode_cash", "mode_mpesa", "mode_card", *[f for f, _label in MPESA_CHANNELS]]
	modes = {settings.get(f) for f in fields if settings.get(f)}

	for mode in modes:
		_ensure_mode_account(mode, company)


def _ensure_mode_account(mode: str, company: str):
	existing = frappe.db.get_value(
		"Mode of Payment Account", {"parent": mode, "company": company}, "default_account"
	)
	if existing:
		return

	account = _account_for_mode(mode, company)
	if not account:
		return

	doc = frappe.get_doc("Mode of Payment", mode)
	doc.append("accounts", {"company": company, "default_account": account})
	doc.save(ignore_permissions=True)


def _account_for_mode(mode: str, company: str) -> str | None:
	"""Route by mode type. Card settlements land in a bank account, not the
	drawer, so mapping everything to cash would misstate both."""
	mode_type = frappe.db.get_value("Mode of Payment", mode, "type")
	cash = frappe.db.get_value("Company", company, "default_cash_account")
	bank = frappe.db.get_value("Company", company, "default_bank_account")

	if mode_type == "Cash":
		return cash or bank
	return bank or cash


def ensure_mpesa_mode_of_payment() -> str | None:
	"""ERPNext ships Cash, Credit Card, Cheque, Wire Transfer and Bank Draft, but
	no M-Pesa — which is how most Kenyan retail actually gets paid.

	Type is "Bank", not "Cash": that is accurate for mobile money, and it also
	stops ERPNext offering change on an M-Pesa payment (change is only computed
	for Cash-type rows).
	"""
	if not frappe.db.exists("DocType", "Mode of Payment"):
		return None

	if frappe.db.exists("Mode of Payment", MPESA_MODE):
		return MPESA_MODE

	doc = frappe.new_doc("Mode of Payment")
	doc.mode_of_payment = MPESA_MODE
	doc.type = "Bank"
	doc.enabled = 1
	doc.insert(ignore_permissions=True)
	# The company account is mapped by ensure_mode_of_payment_accounts(), which
	# handles every till mode uniformly rather than special-casing this one.
	return doc.name


def ensure_mpesa_channel_modes() -> list:
	"""Create a Mode of Payment per M-Pesa channel.

	All "Bank" type, like the generic M-Pesa mode: that is accurate for mobile
	money and it stops ERPNext offering change on them, since change is only
	computed for Cash-type rows.

	Withdraw is the odd one — an agent withdrawal hands physical cash across the
	counter — but it is still money moving through the M-Pesa float rather than
	through the drawer's own takings, so it is tracked with the other two and
	against its own account.
	"""
	if not frappe.db.exists("DocType", "Mode of Payment"):
		return []

	created = []
	for _field, label in MPESA_CHANNELS:
		if frappe.db.exists("Mode of Payment", label):
			continue
		doc = frappe.new_doc("Mode of Payment")
		doc.mode_of_payment = label
		doc.type = "Bank"
		doc.enabled = 1
		doc.insert(ignore_permissions=True)
		created.append(doc.name)

	return created


def ensure_pos_profile_payment_methods():
	"""Offer every till mode on the POS Profile.

	The opening-float screen is seeded from the profile's payment methods, so a
	channel missing here is a channel the cashier is never asked to count — and
	its takings then land in the closing entry as an unexplained difference.
	"""
	if not frappe.db.exists("DocType", "POS Payment Method"):
		return

	settings = frappe.get_single("Cosmestics POS Settings")
	fields = ["mode_cash", "mode_mpesa", "mode_card", *[f for f, _label in MPESA_CHANNELS]]
	wanted = [settings.get(f) for f in fields if settings.get(f)]
	if not wanted:
		return

	for name in frappe.get_all("POS Profile", filters={"disabled": 0}, pluck="name"):
		profile = frappe.get_doc("POS Profile", name)
		existing = {row.mode_of_payment for row in profile.payments}
		missing = [m for m in wanted if m not in existing]
		if not missing:
			continue

		for mode in missing:
			profile.append("payments", {"mode_of_payment": mode, "default": 0})

		# A profile with no default payment refuses to save, and one of ours may
		# be the first row it has ever had.
		if not any(row.default for row in profile.payments):
			profile.payments[0].default = 1

		profile.save(ignore_permissions=True)


def ensure_neighbour_supplier_group() -> str | None:
	"""Create the Supplier Group that neighbouring shops belong to.

	Returns the group name, or None when ERPNext is absent (the Link field then
	simply stays empty rather than blowing up the install).
	"""
	if not frappe.db.exists("DocType", "Supplier Group"):
		return None

	if frappe.db.exists("Supplier Group", NEIGHBOUR_GROUP):
		return NEIGHBOUR_GROUP

	parent = _supplier_group_root()

	doc = frappe.new_doc("Supplier Group")
	doc.supplier_group_name = NEIGHBOUR_GROUP
	if parent:
		doc.parent_supplier_group = parent
	doc.is_group = 0
	doc.insert(ignore_permissions=True)

	return doc.name


def ensure_default_neighbour(group: str | None) -> str | None:
	"""One real Supplier to attribute a mid-sale purchase to.

	The group on its own is not enough. A cashier who is out of stock with a
	customer waiting has to pick *a supplier* — and if none exists, the purchase
	is refused and the sale cannot complete. That is the worst possible moment to
	discover a setup gap, so a generic shop is created up front and can be
	renamed, or ignored once real neighbours are added.
	"""
	if not group or not frappe.db.exists("DocType", "Supplier"):
		return None

	if frappe.db.exists("Supplier", DEFAULT_NEIGHBOUR):
		return DEFAULT_NEIGHBOUR

	# Only seed when there is genuinely no neighbour yet: a shop that has
	# already added its real ones does not want a placeholder beside them.
	if frappe.db.count("Supplier", {"cosmestics_is_neighbour_shop": 1, "disabled": 0}):
		return None

	doc = frappe.new_doc("Supplier")
	doc.supplier_name = DEFAULT_NEIGHBOUR
	doc.supplier_group = group
	doc.supplier_type = "Company"
	if frappe.db.has_column("Supplier", "cosmestics_is_neighbour_shop"):
		doc.cosmestics_is_neighbour_shop = 1
	doc.insert(ignore_permissions=True)
	return doc.name


def _supplier_group_root() -> str | None:
	"""Find the tree root by structure, not by name.

	Two traps here, both verified against a live site:

	1. The root's name is translated ("All Supplier Groups"), and for Warehouse
	   it is company-suffixed ("All Warehouses - A"), so matching on the name is
	   unreliable.
	2. The parent field is NULL on some trees and '' on others. A filter of
	   `("in", ("", None))` silently misses the NULL case, because SQL `IN`
	   never matches NULL. `("is", "not set")` compiles to `IFNULL(f,'')=''`
	   and catches both.
	"""
	return frappe.db.get_value(
		"Supplier Group",
		{"is_group": 1, "parent_supplier_group": ("is", "not set")},
		"name",
	)


def apply_settings_defaults(group: str | None):
	"""Fill in POS settings that could not be expressed as field defaults.

	`neighbour_supplier_group` is a Link, and a Link default naming a record
	that does not exist yet fails validation on every save — which is exactly
	the LinkValidationError this function exists to prevent.
	"""
	settings = frappe.get_single("Cosmestics POS Settings")
	dirty = False

	if group and not settings.neighbour_supplier_group:
		settings.neighbour_supplier_group = group
		dirty = True

	# Also self-heals: an earlier build could store a Transit warehouse here, and
	# selling out of goods-in-transit is silently wrong rather than loudly wrong.
	if not settings.default_source_warehouse or not _is_sellable_warehouse(
		settings.default_source_warehouse, None
	):
		warehouse = _default_warehouse()
		if warehouse:
			settings.default_source_warehouse = warehouse
			dirty = True

	# Map the till's buttons onto real Modes of Payment. Configurable rather than
	# hardcoded so a shop can point "Card" at its own acquirer, or aim a channel
	# at an account it already reconciles against.
	for field, mode in (
		("mode_cash", "Cash"),
		("mode_mpesa", MPESA_MODE),
		("mode_card", "Credit Card"),
		*MPESA_CHANNELS,
	):
		if not settings.get(field) and frappe.db.exists("Mode of Payment", mode):
			settings.set(field, mode)
			dirty = True

	if not settings.selling_price_list:
		price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
		if price_list:
			settings.selling_price_list = price_list
			dirty = True

	if dirty:
		settings.save(ignore_permissions=True)


def _default_warehouse() -> str | None:
	"""Pick a warehouse the till can actually sell out of.

	Naively taking the first non-group warehouse picks "Goods In Transit" on a
	standard ERPNext chart (verified on a live site) — stock the shop does not
	physically have. Prefer the configured stock default, then a normal storage
	warehouse, and never a Transit one.
	"""
	if not frappe.db.exists("DocType", "Warehouse"):
		return None

	company = frappe.defaults.get_global_default("company")

	configured = frappe.db.get_single_value("Stock Settings", "default_warehouse")
	if configured and _is_sellable_warehouse(configured, company):
		return configured

	filters = {"is_group": 0, "disabled": 0}
	if company:
		filters["company"] = company

	# Transit is excluded in Python, not SQL. `warehouse_type != 'Transit'` as a
	# filter drops every row where the type is NULL — which is most of them —
	# because a NULL comparison is NULL, not true. Same trap as the tree roots.
	candidates = [
		w
		for w in frappe.get_all(
			"Warehouse", filters=filters, fields=["name", "warehouse_name", "warehouse_type"]
		)
		if w.warehouse_type != "Transit"
	]
	if not candidates:
		return None

	# "Stores" is ERPNext's conventional on-hand warehouse.
	for w in candidates:
		if w.warehouse_name == "Stores":
			return w.name

	return candidates[0].name


def _is_sellable_warehouse(name, company) -> bool:
	row = frappe.db.get_value(
		"Warehouse", name, ["is_group", "disabled", "warehouse_type", "company"], as_dict=True
	)
	if not row or row.is_group or row.disabled or row.warehouse_type == "Transit":
		return False
	return not company or row.company == company
