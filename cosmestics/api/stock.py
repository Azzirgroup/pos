"""Stock actions raised from the till."""

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, nowdate


@frappe.whitelist()
def warehouse_qtys(item_codes: list | str, warehouse: str) -> dict:
	"""Actual stock of each item in one named warehouse.

	For the material-request sheet: a cashier picking "Request from" a branch
	should see what that branch actually holds before asking for more of it
	than it has — the request still goes through either way, but a number on
	screen beats finding out from whoever reads the WhatsApp message.
	"""
	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)

	if not item_codes or not warehouse:
		return {}

	rows = frappe.get_all(
		"Bin",
		filters={"item_code": ("in", item_codes), "warehouse": warehouse},
		fields=["item_code", "actual_qty"],
	)
	return {r.item_code: flt(r.actual_qty) for r in rows}


@frappe.whitelist()
def item_stock(item_codes: list | str, warehouse: str | None = None) -> dict:
	"""What the shop holds of each item, for a form that is asking for more.

	**Why not `warehouse_qtys`.** That one answers a narrower question — how
	much is in *this* named store — and returns nothing at all when no warehouse
	is chosen. On the material request form the source warehouse is optional (a
	Purchase request has no source; the supplier is the source), so a stock
	figure that disappears the moment the field is blank is a figure nobody can
	rely on. This falls back to the balance everywhere, which is the number that
	answers "do we actually need this?".

	Returns per item: the balance in the named warehouse where one was given,
	the total across every warehouse, and how much is already on order. Labelled
	rather than reduced to one number, because "we have none here but forty in
	the back" and "we have none anywhere" are different answers and the person
	raising the request needs to tell them apart.
	"""
	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)

	item_codes = [c for c in (item_codes or []) if c]
	if not item_codes:
		return {}

	# One query for every warehouse, then split — a per-item query is an N+1 on
	# a form where a line is added every few seconds.
	rows = frappe.get_all(
		"Bin",
		filters={"item_code": ("in", item_codes)},
		fields=["item_code", "warehouse", "actual_qty", "ordered_qty", "reserved_qty"],
		limit_page_length=0,
	)

	out = {
		code: {"here": None, "total": 0.0, "ordered": 0.0, "reserved": 0.0, "warehouse": warehouse}
		for code in item_codes
	}

	for row in rows:
		entry = out.get(row.item_code)
		if entry is None:
			continue
		entry["total"] += flt(row.actual_qty)
		entry["ordered"] += flt(row.ordered_qty)
		entry["reserved"] += flt(row.reserved_qty)
		if warehouse and row.warehouse == warehouse:
			entry["here"] = flt(row.actual_qty)

	# A named warehouse with no Bin row holds none of it — distinct from no
	# warehouse having been named, which is what `None` means.
	if warehouse:
		for entry in out.values():
			if entry["here"] is None:
				entry["here"] = 0.0

	# The unit the figure is in. A balance of "12" means nothing next to a
	# quantity typed in cartons.
	uoms = dict(
		frappe.get_all(
			"Item",
			filters={"name": ("in", item_codes)},
			fields=["name", "stock_uom"],
			as_list=True,
		)
	)
	for code, entry in out.items():
		entry["uom"] = uoms.get(code)

	return out


@frappe.whitelist(methods=["POST"])
def request_transfer(
	items: list | str,
	from_warehouse: str | None = None,
	to_warehouse: str | None = None,
	company: str | None = None,
) -> dict:
	"""Raise a Material Transfer request for stock held at another branch.

	`items` is a list of {item_code, qty, from_warehouse}. Different lines can
	each name their own branch — a shop with more than one place to ask does
	not always want everything from the same one. The top-level
	`from_warehouse` is only a fallback for a line that does not name its own,
	kept for callers with a single source for the whole request.

	Submitted immediately — a draft sitting in a queue helps nobody when a
	customer is standing at the counter, and the WhatsApp notification fires
	off `on_submit`.
	"""
	if isinstance(items, str):
		items = frappe.parse_json(items)

	if not items:
		frappe.throw(_("No items to request"))

	company = company or frappe.defaults.get_user_default("Company")
	to_warehouse = to_warehouse or _default_warehouse(company)

	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Material Transfer"
	mr.company = company
	mr.transaction_date = nowdate()
	# Same-day: the customer is waiting, not scheduling a replenishment.
	mr.schedule_date = nowdate()
	# Only meaningful when every line agrees — set as a convenience default for
	# the desk to show, never relied on for what actually gets requested.
	warehouses_used = {row.get("from_warehouse") or from_warehouse for row in items}
	if len(warehouses_used) == 1:
		mr.set_from_warehouse = next(iter(warehouses_used))

	for row in items:
		qty = flt(row.get("qty"))
		if qty <= 0:
			continue
		row_from = row.get("from_warehouse") or from_warehouse
		if not row_from:
			frappe.throw(_("Select which branch to request {0} from").format(row.get("item_code")))
		if row_from == to_warehouse:
			frappe.throw(_("Source and target branch cannot be the same"))
		mr.append(
			"items",
			{
				"item_code": row.get("item_code"),
				"qty": qty,
				"warehouse": to_warehouse,
				"from_warehouse": row_from,
				"schedule_date": nowdate(),
			},
		)

	if not mr.items:
		frappe.throw(_("No items with a quantity above zero"))

	mr.insert()
	mr.submit()

	from cosmestics.api.notifications import status as whatsapp_status

	# Whether anybody will actually be told. The submit hook queues the message,
	# so this cannot report delivery — but it can report whether delivery is even
	# possible, which is the difference between "on its way" and "nobody will
	# ever see this". The till used to say "sent to WhatsApp" either way.
	return {"name": mr.name, "items": len(mr.items), "whatsapp": whatsapp_status()}


def _default_warehouse(company):
	"""Where requested stock should be delivered to: this till's own shelf.

	Shared with the sale rather than resolved again. Requesting a transfer *into*
	a warehouse the till does not sell from is a request that arrives and changes
	nothing — the shelf the cashier is standing at is still empty.

	The old fallback of "any non-group warehouse on the company" could do exactly
	that, and silently.
	"""
	from cosmestics.api.pos import selling_warehouse

	warehouse = selling_warehouse()
	if not warehouse:
		frappe.throw(
			_(
				"No warehouse to request stock into. Give this till's POS Profile a "
				"warehouse, or set a Sourcing Warehouse in Settings."
			)
		)
	return warehouse
