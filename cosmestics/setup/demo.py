"""Demo catalog seeding.

Reads `cosmestics/data/catalog.json` — the same file the POS frontend imports —
so the demo you click through in the UI is exactly the demo in the database.

Seeding is guarded. `maybe_seed_demo()` refuses to touch a site that already
has items, because installing an app is not consent to have 62 products written
into a working shop. Force it with `bench --site X execute
cosmestics.setup.demo.seed_demo_data`, or suppress it entirely by setting
`cosmestics_seed_demo: 0` in site_config.json.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt

from cosmestics.setup.install import NEIGHBOUR_GROUP

STOCK_UOM = "Nos"
# Plausible cost basis for opening valuation; the demo has no purchase history.
COST_RATIO = 0.6


def load_catalog() -> dict:
	path = frappe.get_app_path("cosmestics", "data", "catalog.json")
	with open(path) as f:
		return json.load(f)


def maybe_seed_demo():
	"""Seed only when it is clearly safe, or explicitly requested."""
	flag = frappe.conf.get("cosmestics_seed_demo")

	if flag == 0:
		return

	if not flag and frappe.db.count("Item") > 0:
		frappe.msgprint(
			_(
				"Cosmestics: skipped demo catalog because this site already has items. "
				"Run <code>bench --site {0} execute cosmestics.setup.demo.seed_demo_data</code> "
				"to seed it anyway."
			).format(frappe.local.site),
			alert=True,
		)
		return

	seed_demo_data()


def seed_demo_data():
	"""Idempotent: safe to re-run, creates only what is missing."""
	if not frappe.db.exists("DocType", "Item"):
		frappe.throw(_("ERPNext is required to seed the Cosmestics demo catalog"))

	company = _company()
	if not company:
		frappe.throw(_("Create a Company before seeding the demo catalog"))

	catalog = load_catalog()

	created = {
		"item_groups": _seed_item_groups(catalog),
		"brands": _seed_brands(catalog),
		"warehouses": _seed_warehouses(catalog, company),
		"suppliers": _seed_neighbours(catalog),
		"items": _seed_items(catalog),
		"prices": _seed_prices(catalog),
	}

	created["stock_entry"] = _seed_opening_stock(catalog, company)

	frappe.db.commit()
	return created


def _company() -> str | None:
	return frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")


def _tree_root(doctype: str, parent_field: str) -> str | None:
	"""Locate a tree root structurally.

	`("is", "not set")` compiles to `IFNULL(field,'')=''`, which matters: the
	root's parent is NULL on Supplier Group and Warehouse but '' on Item Group,
	and a plain `IN ('', NULL)` filter misses the NULL rows entirely.
	"""
	return frappe.db.get_value(doctype, {"is_group": 1, parent_field: ("is", "not set")}, "name")


def _seed_item_groups(catalog) -> int:
	parent = _tree_root("Item Group", "parent_item_group")
	count = 0
	for cat in catalog["categories"]:
		if frappe.db.exists("Item Group", cat["name"]):
			continue
		doc = frappe.new_doc("Item Group")
		doc.item_group_name = cat["name"]
		if parent:
			doc.parent_item_group = parent
		doc.is_group = 0
		doc.insert(ignore_permissions=True)
		count += 1
	return count


def _seed_brands(catalog) -> int:
	if not frappe.db.exists("DocType", "Brand"):
		return 0
	count = 0
	for name in sorted({i["brand"] for i in catalog["items"]}):
		if frappe.db.exists("Brand", name):
			continue
		doc = frappe.new_doc("Brand")
		doc.brand = name
		doc.insert(ignore_permissions=True)
		count += 1
	return count


def _seed_warehouses(catalog, company) -> int:
	parent = _tree_root("Warehouse", "parent_warehouse")
	count = 0
	for wh in catalog["warehouses"]:
		# Match on warehouse_name, not the demo JSON's `name`. ERPNext appends the
		# company abbreviation on insert ("Shop Floor" → "Shop Floor - A"), so
		# checking the placeholder name would create duplicates on every re-run.
		if frappe.db.exists("Warehouse", {"warehouse_name": wh["label"], "company": company}):
			continue
		doc = frappe.new_doc("Warehouse")
		doc.warehouse_name = wh["label"]
		doc.company = company
		if parent:
			doc.parent_warehouse = parent
		doc.is_group = 0
		doc.insert(ignore_permissions=True)
		count += 1
	return count


def _seed_neighbours(catalog) -> int:
	count = 0
	for n in catalog["neighbours"]:
		if frappe.db.exists("Supplier", n["name"]):
			continue
		doc = frappe.new_doc("Supplier")
		doc.supplier_name = n["name"]
		if frappe.db.exists("Supplier Group", NEIGHBOUR_GROUP):
			doc.supplier_group = NEIGHBOUR_GROUP
		doc.supplier_type = "Company"
		doc.mobile_no = n.get("phone")
		doc.insert(ignore_permissions=True)
		count += 1
	return count


def _seed_items(catalog) -> int:
	_ensure_uom()
	count = 0
	for row in catalog["items"]:
		if frappe.db.exists("Item", row["item_code"]):
			continue
		doc = frappe.new_doc("Item")
		doc.item_code = row["item_code"]
		doc.item_name = row["item_name"]
		doc.item_group = row["category"]
		doc.stock_uom = STOCK_UOM
		doc.is_stock_item = 1
		doc.include_item_in_manufacturing = 0
		if frappe.db.exists("Brand", row["brand"]):
			doc.brand = row["brand"]
		doc.append("barcodes", {"barcode": row["barcode"], "barcode_type": "EAN"})
		doc.insert(ignore_permissions=True)
		count += 1
	return count


def _ensure_uom():
	if not frappe.db.exists("UOM", STOCK_UOM):
		doc = frappe.new_doc("UOM")
		doc.uom_name = STOCK_UOM
		doc.insert(ignore_permissions=True)


def _seed_prices(catalog) -> int:
	price_list = frappe.db.get_value(
		"Price List", {"selling": 1, "enabled": 1}, "name"
	) or frappe.db.get_value("Price List", {"selling": 1}, "name")

	if not price_list:
		return 0

	count = 0
	for row in catalog["items"]:
		exists = frappe.db.exists(
			"Item Price", {"item_code": row["item_code"], "price_list": price_list}
		)
		if exists:
			continue
		doc = frappe.new_doc("Item Price")
		doc.item_code = row["item_code"]
		doc.price_list = price_list
		doc.uom = STOCK_UOM
		doc.price_list_rate = row["price"]
		doc.insert(ignore_permissions=True)
		count += 1
	return count


def _seed_opening_stock(catalog, company) -> str | None:
	"""Receive opening stock so the demo is not uniformly out of stock.

	Items seeded with stock 0 are intentional — they are what exercises the
	out-of-stock and neighbour-sourcing flows at the till.
	"""
	warehouse = frappe.db.get_value("Warehouse", {"warehouse_name": "Shop Floor"}, "name")
	if not warehouse:
		warehouse = frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name"
		)
	if not warehouse:
		return None

	rows = [r for r in catalog["items"] if flt(r.get("stock")) > 0]
	if not rows:
		return None

	# Skip if this demo receipt has already been posted.
	if frappe.db.exists(
		"Stock Entry", {"remarks": ("like", "%Cosmestics demo opening stock%"), "docstatus": 1}
	):
		return None

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Receipt"
	se.company = company
	se.remarks = "Cosmestics demo opening stock"

	for row in rows:
		se.append(
			"items",
			{
				"item_code": row["item_code"],
				"qty": flt(row["stock"]),
				"t_warehouse": warehouse,
				"basic_rate": flt(row["price"]) * COST_RATIO,
				"uom": STOCK_UOM,
				"stock_uom": STOCK_UOM,
				"conversion_factor": 1,
			},
		)

	se.insert(ignore_permissions=True)
	se.submit()
	return se.name
