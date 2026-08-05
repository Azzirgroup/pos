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
from frappe.utils import cint, flt, get_url

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
			# Independent of Group — see `cosmestics_is_neighbour_shop` on the
			# Supplier doctype. A wholesaler and a neighbour shop can carry the
			# same group; this is the actual fact the till checks.
			{"fieldname": "cosmestics_is_neighbour_shop", "label": "Neighbour shop", "type": "checkbox"},
		],
		# Called out because "buy from neighbour does nothing" is almost always
		# this left unchecked rather than a broken feature.
		"hint": "Check Neighbour shop for shops you buy from mid-sale, or they will not be offered at the till.",
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
			# Barcode is a child table on Item, not a field, so it is handled the
			# same way `opening_price` is: shown as one box because a shop scanning
			# a product has exactly one number printed on it, and written to the
			# `barcodes` table after the insert.
			{"fieldname": "barcode", "label": "Barcode", "type": "text"},
		],
		"defaults": {"is_stock_item": 1, "is_sales_item": 1, "is_purchase_item": 1},
	},
	{
		# Categories, which a shop reorganises far more often than it adds
		# warehouses — and which every item form asks for, so a shopkeeper who
		# needs a new one should not have to leave the app to make it.
		"key": "item_group",
		"doctype": "Item Group",
		"label": "Item group",
		"icon": "boxes",
		"title_field": "item_group_name",
		"fields": [
			{"fieldname": "item_group_name", "label": "Name", "type": "text", "required": True},
			{
				"fieldname": "parent_item_group",
				"label": "Under",
				"type": "link",
				"options": "Item Group",
			},
		],
		"defaults": {"is_group": 0},
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
def list_records(key: str, search: str | None = None, limit: int = 100) -> dict:
	"""Existing records of one type, so the screen shows what is already there.

	A create-only screen makes people add duplicates: nobody can see that the
	customer they are about to add is already on file. The columns are the same
	fields the form asks for, so the list and the form describe a record the
	same way.
	"""
	entry = _entry(key)
	doctype = entry["doctype"]
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("You may not view {0}").format(_(doctype)), frappe.PermissionError)

	meta = frappe.get_meta(doctype)
	shown = [
		f
		for f in entry["fields"]
		if f["fieldname"] not in VIRTUAL_FIELDS and meta.has_field(f["fieldname"])
	]

	fields = ["name"]
	for f in shown:
		if f["fieldname"] not in fields:
			fields.append(f["fieldname"])

	filters = {}
	if meta.has_field("disabled"):
		filters["disabled"] = 0
	if meta.has_field("company") and frappe.defaults.get_global_default("company"):
		filters["company"] = frappe.defaults.get_global_default("company")

	or_filters = None
	if search:
		or_filters = {"name": ("like", f"%{search}%")}
		title = entry["title_field"]
		if meta.has_field(title):
			or_filters[title] = ("like", f"%{search}%")

	rows = frappe.get_all(
		doctype,
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by="modified desc",
		limit_page_length=min(max(cint(limit) or 100, 1), 500),
	)

	columns = [{"label": _("ID"), "key": "name", "type": "text"}] + [
		{
			"label": f["label"],
			"key": f["fieldname"],
			"type": "currency" if f["type"] == "currency" else "text",
		}
		for f in shown
	]

	return {
		"key": key,
		"doctype": doctype,
		"label": entry["label"],
		"columns": columns,
		"rows": rows,
		"total": frappe.db.count(doctype, filters),
		"can_create": frappe.has_permission(doctype, "create"),
	}


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
		# `opening_price` and `barcode` are ours, not the Item's — both are
		# handled after the insert, one as an Item Price and one as a child row.
		if fieldname in allowed and fieldname not in VIRTUAL_FIELDS and value not in (None, ""):
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

	barcode = (values.get("barcode") or "").strip()
	if doctype == "Item" and barcode:
		_set_barcode(doc.name, barcode)

	return {
		"key": key,
		"doctype": doctype,
		"name": doc.name,
		"title": doc.get(entry["title_field"]) or doc.name,
		"desk_url": get_url(f"/app/{frappe.scrub(doctype).replace('_', '-')}/{doc.name}"),
		"message": _("{0} created").format(doc.get(entry["title_field"]) or doc.name),
	}


@frappe.whitelist()
def get_record(key: str, name: str) -> dict:
	"""One record's current values, for editing.

	Only the fields the form declares are returned. A phone number typed at the
	counter is worth correcting there; the rest of the record belongs in the
	desk, and `desk_url` goes to it.
	"""
	entry = _entry(key)
	doc = frappe.get_doc(entry["doctype"], name)
	doc.check_permission("read")

	values = {
		f["fieldname"]: doc.get(f["fieldname"])
		for f in entry["fields"]
		if f["fieldname"] not in VIRTUAL_FIELDS
	}
	if entry["doctype"] == "Item":
		values["opening_price"] = _current_item_price(name)
		values["barcode"] = _current_barcode(name)

	return {
		"key": key,
		"doctype": entry["doctype"],
		"name": doc.name,
		"title": doc.get(entry["title_field"]) or doc.name,
		"values": values,
		"fields": entry["fields"],
		"can_write": frappe.has_permission(entry["doctype"], "write", doc=doc),
		"desk_url": get_url(f"/app/{frappe.scrub(entry['doctype']).replace('_', '-')}/{doc.name}"),
	}


@frappe.whitelist(methods=["POST"])
def update(key: str, name: str, values: dict | str) -> dict:
	"""Save edits to the fields this form owns.

	Deliberately narrow: only declared fieldnames are written, so a value the
	form never offered cannot be smuggled onto the record, and a field left out
	of the payload is left alone rather than blanked.
	"""
	if isinstance(values, str):
		values = frappe.parse_json(values)
	values = values or {}

	entry = _entry(key)
	doc = frappe.get_doc(entry["doctype"], name)

	allowed = {f["fieldname"] for f in entry["fields"]}
	missing = [
		f["label"]
		for f in entry["fields"]
		if f.get("required") and f["fieldname"] in values and not str(values[f["fieldname"]] or "").strip()
	]
	if missing:
		frappe.throw(_("These cannot be emptied: {0}").format(", ".join(missing)))

	changed = False
	for fieldname, value in values.items():
		if fieldname not in allowed or fieldname in VIRTUAL_FIELDS:
			continue
		if doc.get(fieldname) != value:
			doc.set(fieldname, value)
			changed = True

	if changed:
		doc.save()

	price = values.get("opening_price")
	if entry["doctype"] == "Item" and price not in (None, "") and flt(price) != flt(_current_item_price(name)):
		_set_opening_price(name, price)
		changed = True

	if entry["doctype"] == "Item" and "barcode" in values:
		barcode = (values.get("barcode") or "").strip()
		if barcode != (_current_barcode(name) or ""):
			_set_barcode(name, barcode)
			changed = True

	return {
		"key": key,
		"name": doc.name,
		"title": doc.get(entry["title_field"]) or doc.name,
		"changed": changed,
		"message": (
			_("{0} saved").format(doc.get(entry["title_field"]) or doc.name)
			if changed
			else _("Nothing changed")
		),
	}


def _current_item_price(item_code: str):
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	price_list = settings.selling_price_list
	if not price_list:
		return None
	return frappe.db.get_value(
		"Item Price", {"item_code": item_code, "price_list": price_list}, "price_list_rate"
	)


#: Fields the form shows that are not fields on the doctype.
#:
#: Both belong to an Item in a shop's mind and to somewhere else in ERPNext's
#: model: the selling price is an Item Price document, and the barcode is a row
#: in the Item's `barcodes` child table. Asking a shopkeeper to understand that
#: distinction to add a product is the reason this form exists at all.
VIRTUAL_FIELDS = {"opening_price", "barcode"}


def _current_barcode(item_code: str) -> str | None:
	"""The Item's first barcode, which is the one on the packet.

	First rather than all of them: the form shows one box, and a product with
	several barcodes is an edge case a shop handles in the desk. Reading the
	first keeps the form honest about what it will overwrite.
	"""
	return frappe.db.get_value(
		"Item Barcode", {"parent": item_code}, "barcode", order_by="idx asc"
	)


def _set_barcode(item_code: str, barcode: str):
	"""Put one barcode on an Item, replacing whatever the form was showing.

	Refuses a duplicate rather than letting ERPNext raise it on save: the same
	barcode on two items makes every scan of it ambiguous, and the till would
	pick whichever the query returned first.
	"""
	existing = frappe.db.get_value(
		"Item Barcode", {"barcode": barcode, "parent": ("!=", item_code)}, "parent"
	)
	if barcode and existing:
		frappe.throw(_("{0} is already the barcode for {1}").format(barcode, existing))

	doc = frappe.get_doc("Item", item_code)
	current = _current_barcode(item_code)
	if not barcode:
		# Cleared: drop the row rather than leaving an empty one, which ERPNext
		# would reject on the next save of this item.
		doc.barcodes = [row for row in doc.barcodes if row.barcode != current]
	elif doc.barcodes:
		doc.barcodes[0].barcode = barcode
	else:
		doc.append("barcodes", {"barcode": barcode})
	doc.save(ignore_permissions=True)


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
