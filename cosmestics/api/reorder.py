"""Reorder levels, configured per warehouse under a chosen parent.

ERPNext stores reorder rules on the Item as `Item Reorder` child rows, one per
warehouse. That is the right store — Stock Reposting and the auto Material
Request already read it — so this module writes there rather than inventing a
parallel table.

The parent/sub split matters operationally: a shop picks a region or branch
group as the parent, and every stocking location beneath it inherits the same
configuration screen. Reorder points differ per location (a back store holds
more than a counter), so the level is set per sub-warehouse, not on the parent.
"""

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_warehouse_tree():
	"""Group (parent) warehouses, each with its stocking children.

	Only groups that actually contain a leaf are returned — an empty branch is
	a dead option in the picker.
	"""
	company = frappe.defaults.get_global_default("company")
	filters = {"disabled": 0}
	if company:
		filters["company"] = company

	rows = frappe.get_all(
		"Warehouse",
		filters=filters,
		fields=["name", "warehouse_name", "is_group", "parent_warehouse", "warehouse_type", "company"],
		order_by="name asc",
	)

	children = {}
	for w in rows:
		if w.is_group or w.warehouse_type == "Transit":
			continue
		children.setdefault(w.parent_warehouse, []).append(
			{"name": w.name, "label": w.warehouse_name, "company": w.company}
		)

	parents = []
	for w in rows:
		if not w.is_group:
			continue
		kids = children.get(w.name, [])
		if not kids:
			continue
		parents.append(
			{
				"name": w.name,
				"label": w.warehouse_name,
				"company": w.company,
				"children": kids,
				"child_count": len(kids),
			}
		)

	# Leaves whose parent is not a group (or has none) would otherwise be
	# unreachable from this screen.
	orphans = [
		c
		for parent, kids in children.items()
		for c in kids
		if not any(p["name"] == parent for p in parents)
	]
	if orphans:
		parents.append(
			{
				"name": "__ungrouped__",
				"label": _("Ungrouped"),
				"company": company,
				"children": orphans,
				"child_count": len(orphans),
			}
		)

	return {"parents": parents, "default_parent": parents[0]["name"] if parents else None}


@frappe.whitelist()
def get_reorder_rows(parent_warehouse: str, search: str | None = None, only_below: int = 0):
	"""Every stocked item across the sub-warehouses of `parent_warehouse`.

	Returns one row per item/warehouse pair, with the current balance and any
	existing reorder rule, so the screen can show configured and unconfigured
	locations together.
	"""
	warehouses = _sub_warehouses(parent_warehouse)
	if not warehouses:
		return {"rows": [], "warehouses": []}

	item_filters = {"disabled": 0, "is_stock_item": 1}
	if search:
		item_filters["item_name"] = ("like", f"%{search}%")

	items = frappe.get_all(
		"Item",
		filters=item_filters,
		fields=["name as item_code", "item_name", "item_group", "stock_uom"],
		limit_page_length=0,
		order_by="item_name asc",
	)
	if not items:
		return {"rows": [], "warehouses": warehouses}

	codes = [i.item_code for i in items]
	balances = _balances(codes, warehouses)
	rules = _rules(codes, warehouses)

	rows = []
	for it in items:
		for wh in warehouses:
			key = (it.item_code, wh["name"])
			rule = rules.get(key)
			qty = flt(balances.get(key))
			level = flt(rule["warehouse_reorder_level"]) if rule else None
			below = level is not None and qty <= level

			if only_below and not below:
				continue

			rows.append(
				{
					"item_code": it.item_code,
					"item_name": it.item_name,
					"item_group": it.item_group,
					"uom": it.stock_uom,
					"warehouse": wh["name"],
					"warehouse_label": wh["label"],
					"actual_qty": qty,
					"reorder_level": level,
					"reorder_qty": flt(rule["warehouse_reorder_qty"]) if rule else None,
					"material_request_type": rule["material_request_type"] if rule else "Purchase",
					"configured": bool(rule),
					"below": below,
				}
			)

	return {"rows": rows, "warehouses": warehouses}


def _sub_warehouses(parent: str) -> list:
	company = frappe.defaults.get_global_default("company")
	filters = {"disabled": 0, "is_group": 0}
	if company:
		filters["company"] = company

	if parent and parent != "__ungrouped__":
		filters["parent_warehouse"] = parent

	rows = frappe.get_all(
		"Warehouse", filters=filters, fields=["name", "warehouse_name", "warehouse_type"]
	)
	return [
		{"name": r.name, "label": r.warehouse_name}
		for r in rows
		if r.warehouse_type != "Transit"
	]


def _balances(codes, warehouses) -> dict:
	rows = frappe.get_all(
		"Bin",
		filters={"item_code": ("in", codes), "warehouse": ("in", [w["name"] for w in warehouses])},
		fields=["item_code", "warehouse", "actual_qty"],
		limit_page_length=0,
	)
	return {(r.item_code, r.warehouse): r.actual_qty for r in rows}


def _rules(codes, warehouses) -> dict:
	rows = frappe.get_all(
		"Item Reorder",
		filters={"parent": ("in", codes), "warehouse": ("in", [w["name"] for w in warehouses])},
		fields=[
			"parent",
			"warehouse",
			"warehouse_reorder_level",
			"warehouse_reorder_qty",
			"material_request_type",
		],
		limit_page_length=0,
	)
	return {(r.parent, r.warehouse): r for r in rows}


@frappe.whitelist(methods=["POST"])
def save_reorder_rules(rules: list | str):
	"""Upsert reorder rules. `rules` is
	[{item_code, warehouse, reorder_level, reorder_qty, material_request_type}].

	A level of None or blank removes the rule — that is how a location is taken
	out of auto-reordering, and it has to be distinguishable from a level of 0.
	"""
	if isinstance(rules, str):
		rules = frappe.parse_json(rules)

	touched = {}
	for r in rules or []:
		touched.setdefault(r["item_code"], []).append(r)

	saved = 0
	for item_code, item_rules in touched.items():
		doc = frappe.get_doc("Item", item_code)
		changed = False

		for r in item_rules:
			warehouse = r["warehouse"]
			level = r.get("reorder_level")
			existing = next((d for d in doc.reorder_levels if d.warehouse == warehouse), None)

			if level in (None, ""):
				if existing:
					doc.remove(existing)
					changed = True
				continue

			qty = flt(r.get("reorder_qty"))
			if qty <= 0:
				frappe.throw(
					_("{0} at {1}: reorder quantity must be more than zero").format(
						item_code, warehouse
					)
				)

			if existing:
				existing.warehouse_reorder_level = flt(level)
				existing.warehouse_reorder_qty = qty
				existing.material_request_type = r.get("material_request_type") or "Purchase"
			else:
				doc.append(
					"reorder_levels",
					{
						"warehouse": warehouse,
						"warehouse_reorder_level": flt(level),
						"warehouse_reorder_qty": qty,
						"material_request_type": r.get("material_request_type") or "Purchase",
					},
				)
			changed = True

		if changed:
			doc.save(ignore_permissions=True)
			saved += 1

	frappe.db.commit()
	return {"items_updated": saved}


@frappe.whitelist(methods=["POST"])
def copy_levels(from_warehouse: str, to_warehouses: list | str, overwrite: int = 0):
	"""Clone one location's reorder rules onto its siblings.

	Setting levels item-by-item across a dozen branches is the tedious part of
	this screen; this is the shortcut that makes it usable.
	"""
	if isinstance(to_warehouses, str):
		to_warehouses = frappe.parse_json(to_warehouses)

	source = frappe.get_all(
		"Item Reorder",
		filters={"warehouse": from_warehouse},
		fields=[
			"parent",
			"warehouse_reorder_level",
			"warehouse_reorder_qty",
			"material_request_type",
		],
		limit_page_length=0,
	)
	if not source:
		frappe.throw(_("{0} has no reorder levels to copy").format(from_warehouse))

	copied = 0
	for row in source:
		doc = frappe.get_doc("Item", row.parent)
		dirty = False
		for wh in to_warehouses:
			existing = next((d for d in doc.reorder_levels if d.warehouse == wh), None)
			if existing and not overwrite:
				continue
			if existing:
				existing.warehouse_reorder_level = row.warehouse_reorder_level
				existing.warehouse_reorder_qty = row.warehouse_reorder_qty
				existing.material_request_type = row.material_request_type
			else:
				doc.append(
					"reorder_levels",
					{
						"warehouse": wh,
						"warehouse_reorder_level": row.warehouse_reorder_level,
						"warehouse_reorder_qty": row.warehouse_reorder_qty,
						"material_request_type": row.material_request_type,
					},
				)
			dirty = True
			copied += 1
		if dirty:
			doc.save(ignore_permissions=True)

	frappe.db.commit()
	return {"rules_copied": copied}


@frappe.whitelist()
def get_reorder_items(search: str | None = None, only_unconfigured: int = 0, limit: int = 200):
	"""One row per item, with how many locations already have a rule.

	The list is per item because reorder policy is an item-level decision; the
	per-warehouse numbers are set inside the item, not scanned across a flat
	grid of every item/warehouse pair.
	"""
	filters = {"disabled": 0, "is_stock_item": 1}
	if search:
		filters["item_name"] = ("like", f"%{search}%")

	items = frappe.get_all(
		"Item",
		filters=filters,
		fields=["name as item_code", "item_name", "item_group", "stock_uom"],
		order_by="item_name asc",
		limit_page_length=int(limit),
	)
	if not items:
		return []

	codes = [i.item_code for i in items]

	configured = {}
	for r in frappe.get_all(
		"Item Reorder",
		filters={"parent": ("in", codes)},
		fields=["parent", "warehouse", "warehouse_reorder_level"],
		limit_page_length=0,
	):
		configured.setdefault(r.parent, []).append(r)

	balances = {}
	for b in frappe.get_all(
		"Bin",
		filters={"item_code": ("in", codes)},
		fields=["item_code", "warehouse", "actual_qty"],
		limit_page_length=0,
	):
		balances[(b.item_code, b.warehouse)] = b.actual_qty

	rows = []
	for it in items:
		rules = configured.get(it.item_code, [])
		below = sum(
			1
			for r in rules
			if flt(balances.get((it.item_code, r.warehouse))) <= flt(r.warehouse_reorder_level)
		)
		if only_unconfigured and rules:
			continue
		rows.append(
			{
				"item_code": it.item_code,
				"item_name": it.item_name,
				"item_group": it.item_group,
				"uom": it.stock_uom,
				"configured_count": len(rules),
				"below_count": below,
				"total_stock": sum(
					flt(v) for (c, _w), v in balances.items() if c == it.item_code
				),
			}
		)

	return rows


@frappe.whitelist()
def get_item_reorder(item_code: str, parent_warehouse: str | None = None):
	"""Reorder configuration for ONE item, per sub-warehouse of the parent.

	Powers the per-item modal: pick a parent, and every stocking location under
	it appears with its own level, quantity and request type.
	"""
	item = frappe.db.get_value(
		"Item", item_code, ["item_name", "stock_uom"], as_dict=True
	)
	if not item:
		frappe.throw(_("{0} does not exist").format(item_code))

	tree = get_warehouse_tree()
	parent = parent_warehouse or tree.get("default_parent")
	warehouses = _sub_warehouses(parent) if parent else []

	rules = {
		r.warehouse: r
		for r in frappe.get_all(
			"Item Reorder",
			filters={"parent": item_code},
			fields=[
				"warehouse",
				"warehouse_reorder_level",
				"warehouse_reorder_qty",
				"material_request_type",
			],
			limit_page_length=0,
		)
	}

	balances = {
		b.warehouse: b.actual_qty
		for b in frappe.get_all(
			"Bin",
			filters={"item_code": item_code},
			fields=["warehouse", "actual_qty"],
			limit_page_length=0,
		)
	}

	rows = []
	for wh in warehouses:
		rule = rules.get(wh["name"])
		qty = flt(balances.get(wh["name"]))
		level = flt(rule["warehouse_reorder_level"]) if rule else None
		rows.append(
			{
				"warehouse": wh["name"],
				"warehouse_label": wh["label"],
				"actual_qty": qty,
				"reorder_level": level,
				"reorder_qty": flt(rule["warehouse_reorder_qty"]) if rule else None,
				"material_request_type": rule["material_request_type"] if rule else "Purchase",
				"configured": bool(rule),
				"below": level is not None and qty <= level,
			}
		)

	return {
		"item_code": item_code,
		"item_name": item.item_name,
		"uom": item.stock_uom,
		"parents": tree["parents"],
		"parent": parent,
		"rows": rows,
	}
