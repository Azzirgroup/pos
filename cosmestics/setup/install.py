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
MPESA_MODE = "M-Pesa"


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
	ensure_mpesa_mode_of_payment()
	apply_settings_defaults(group)
	# Must run after the settings map the till's three buttons onto real modes.
	ensure_mode_of_payment_accounts()
	ensure_pos_settings()
	ensure_partial_payment_allowed()


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
	modes = [m for m in (settings.mode_cash, settings.mode_mpesa, settings.mode_card) if m]

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

	# Map the till's three buttons onto real Modes of Payment. Configurable
	# rather than hardcoded so a shop can point "Card" at its own acquirer.
	for field, mode in (
		("mode_cash", "Cash"),
		("mode_mpesa", MPESA_MODE),
		("mode_card", "Credit Card"),
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
