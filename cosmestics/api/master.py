"""Creating the records a shop actually needs to create.

A cosmetics shop opens a new customer account at the counter, adds the supplier
next door when it first buys from them, and puts a new line on the shelf the day
it arrives. Sending someone to the ERPNext desk for that means leaving the till,
so the handful of fields those records really need live here.

Deliberately **not** a reimplementation of ERPNext's forms. Each type exposes the
fields a shop fills in and nothing else; everything beyond that is left to the
desk, and `desk_url` points there. A partial form that creates a valid record
beats a complete one nobody finishes — and it cannot drift, because the fields
it omits are simply defaulted by ERPNext as they always were.

As with `documents.py`, a caller reaches a doctype only through a registry key,
so no caller-supplied string becomes a doctype name.
"""

import frappe
from frappe import _
from frappe.utils import cint, get_url

MASTERS = [
	{
		"key": "customer",
		"doctype": "Customer",
		"label": "Customer",
		"icon": "users",
		"title_field": "customer_name",
		"fields": [
			{"fieldname": "customer_name", "label": "Name", "type": "text", "required": True},
			{"fieldname": "mobile_no", "label": "Phone", "type": "text"},
			{"fieldname": "email_id", "label": "Email", "type": "text"},
			{"fieldname": "customer_group", "label": "Group", "type": "link", "options": "Customer Group"},
			{"fieldname": "territory", "label": "Territory", "type": "link", "options": "Territory"},
		],
	},
	{
		"key": "supplier",
		"doctype": "Supplier",
		"label": "Supplier",
		"icon": "truck",
		"title_field": "supplier_name",
		"fields": [
			{"fieldname": "supplier_name", "label": "Name", "type": "text", "required": True},
			{"fieldname": "mobile_no", "label": "Phone", "type": "text"},
			{"fieldname": "supplier_group", "label": "Group", "type": "link", "options": "Supplier Group"},
		],
		# The one group that makes a supplier appear at the till. Called out
		# because "buy from neighbour does nothing" is almost always an empty
		# group rather than a broken feature.
		"hint": "Put shops you buy from mid-sale in the neighbour supplier group, or they will not be offered at the till.",
	},
	{
		"key": "item",
		"doctype": "Item",
		"label": "Item",
		"icon": "package",
		"title_field": "item_name",
		"fields": [
			{"fieldname": "item_code", "label": "Code", "type": "text", "required": True},
			{"fieldname": "item_name", "label": "Name", "type": "text", "required": True},
			{"fieldname": "item_group", "label": "Group", "type": "link", "options": "Item Group", "required": True},
			{"fieldname": "stock_uom", "label": "Unit", "type": "link", "options": "UOM"},
			{"fieldname": "brand", "label": "Brand", "type": "link", "options": "Brand"},
			{"fieldname": "opening_price", "label": "Selling price", "type": "currency"},
		],
		"defaults": {"is_stock_item": 1, "is_sales_item": 1, "is_purchase_item": 1},
	},
	{
		"key": "warehouse",
		"doctype": "Warehouse",
		"label": "Warehouse",
		"icon": "boxes",
		"title_field": "warehouse_name",
		"fields": [
			{"fieldname": "warehouse_name", "label": "Name", "type": "text", "required": True},
			{"fieldname": "parent_warehouse", "label": "Under", "type": "link", "options": "Warehouse"},
		],
	},
	{
		"key": "account",
		"doctype": "Account",
		"label": "Account",
		"icon": "landmark",
		"title_field": "account_name",
		"fields": [
			{"fieldname": "account_name", "label": "Name", "type": "text", "required": True},
			{"fieldname": "parent_account", "label": "Under", "type": "link", "options": "Account", "required": True},
			{
				"fieldname": "account_type",
				"label": "Type",
				"type": "select",
				"options": ["", "Bank", "Cash", "Receivable", "Payable", "Income Account", "Expense Account", "Stock", "Tax"],
			},
		],
	},
]


def _entry(key: str) -> dict:
	for m in MASTERS:
		if m["key"] == key:
			return m
	frappe.throw(_("Unknown record type: {0}").format(key), frappe.DoesNotExistError)


@frappe.whitelist()
def list_types() -> list:
	"""The types this user may create, with their fields.

	Filtered by permission rather than shown-and-then-failing: offering a
	cashier an "Add account" button that throws on save is worse than not
	offering it.
	"""
	out = []
	for m in MASTERS:
		if not frappe.has_permission(m["doctype"], "create"):
			continue
		out.append(
			{
				"key": m["key"],
				"doctype": m["doctype"],
				"label": m["label"],
				"icon": m["icon"],
				"fields": m["fields"],
				"hint": m.get("hint"),
			}
		)
	return out


@frappe.whitelist()
def options(key: str, fieldname: str, search: str | None = None, limit: int = 20) -> list:
	"""Values for one link field on one form.

	Scoped to the field being filled rather than a generic "search any doctype"
	endpoint — that would be a way to read any table in the system through a
	whitelisted method.
	"""
	entry = _entry(key)
	field = next((f for f in entry["fields"] if f["fieldname"] == fieldname), None)
	if not field or field["type"] != "link":
		frappe.throw(_("{0} is not a link field on {1}").format(fieldname, entry["label"]))

	target = field["options"]
	filters = {}
	meta = frappe.get_meta(target)
	# Group nodes cannot hold records, so offering them only produces a failed save.
	if meta.has_field("is_group"):
		filters["is_group"] = 0
	if meta.has_field("disabled"):
		filters["disabled"] = 0
	if meta.has_field("company") and frappe.defaults.get_global_default("company"):
		filters["company"] = frappe.defaults.get_global_default("company")
	if search:
		filters["name"] = ("like", f"%{search}%")

	# Warehouses are the exception: a parent warehouse *must* be a group.
	if key == "warehouse" and fieldname == "parent_warehouse":
		filters["is_group"] = 1

	return [
		{"label": r, "value": r}
		for r in frappe.get_all(
			target, filters=filters, pluck="name", order_by="name asc", limit_page_length=cint(limit)
		)
	]


@frappe.whitelist(methods=["POST"])
def create(key: str, values: dict | str) -> dict:
	"""Create one record from the quick-add form.

	Inserted through `frappe.get_doc(...).insert()` with permissions intact, so
	ERPNext's own mandatory-field and naming rules apply exactly as they do in
	the desk. Only the registry's own fieldnames are copied across — a value the
	form does not declare cannot be smuggled onto the document.
	"""
	if isinstance(values, str):
		values = frappe.parse_json(values)
	values = values or {}

	entry = _entry(key)
	doctype = entry["doctype"]

	allowed = {f["fieldname"] for f in entry["fields"]}
	missing = [
		f["label"] for f in entry["fields"] if f.get("required") and not str(values.get(f["fieldname"]) or "").strip()
	]
	if missing:
		frappe.throw(_("Fill in: {0}").format(", ".join(missing)))

	doc = frappe.new_doc(doctype)
	for fieldname, value in values.items():
		# `opening_price` is ours, not the Item's — handled after the insert.
		if fieldname in allowed and fieldname != "opening_price" and value not in (None, ""):
			doc.set(fieldname, value)

	for fieldname, value in (entry.get("defaults") or {}).items():
		doc.set(fieldname, value)

	if doctype == "Warehouse" and frappe.defaults.get_global_default("company"):
		doc.company = frappe.defaults.get_global_default("company")
	if doctype == "Account":
		doc.company = frappe.db.get_value("Account", doc.parent_account, "company")

	doc.insert()

	price = values.get("opening_price")
	if doctype == "Item" and price:
		_set_opening_price(doc.name, price)

	return {
		"key": key,
		"doctype": doctype,
		"name": doc.name,
		"title": doc.get(entry["title_field"]) or doc.name,
		"desk_url": get_url(f"/app/{frappe.scrub(doctype).replace('_', '-')}/{doc.name}"),
		"message": _("{0} created").format(doc.get(entry["title_field"]) or doc.name),
	}


def _set_opening_price(item_code: str, price):
	"""A new item with no price cannot be sold at the till, so the form asks for
	one and it is written as a normal Item Price."""
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	price_list = settings.selling_price_list or frappe.db.get_value(
		"Price List", {"selling": 1, "enabled": 1}, "name"
	)
	if not price_list:
		return

	doc = frappe.new_doc("Item Price")
	doc.item_code = item_code
	doc.price_list = price_list
	doc.price_list_rate = price
	doc.insert()
