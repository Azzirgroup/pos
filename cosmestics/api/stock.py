"""Stock actions raised from the till."""

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, nowdate


@frappe.whitelist(methods=["POST"])
def request_transfer(
	items: list | str,
	from_warehouse: str,
	to_warehouse: str | None = None,
	company: str | None = None,
):
	"""Raise a Material Transfer request for stock held at another branch.

	`items` is a list of {item_code, qty}. Submitted immediately — a draft sitting
	in a queue helps nobody when a customer is standing at the counter, and the
	WhatsApp notification fires off `on_submit`.
	"""
	if isinstance(items, str):
		items = frappe.parse_json(items)

	if not items:
		frappe.throw(_("No items to request"))

	if not from_warehouse:
		frappe.throw(_("Select the branch to request from"))

	company = company or frappe.defaults.get_user_default("Company")
	to_warehouse = to_warehouse or _default_warehouse(company)

	if from_warehouse == to_warehouse:
		frappe.throw(_("Source and target branch cannot be the same"))

	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Material Transfer"
	mr.company = company
	mr.transaction_date = nowdate()
	# Same-day: the customer is waiting, not scheduling a replenishment.
	mr.schedule_date = nowdate()
	mr.set_from_warehouse = from_warehouse

	for row in items:
		qty = flt(row.get("qty"))
		if qty <= 0:
			continue
		mr.append(
			"items",
			{
				"item_code": row.get("item_code"),
				"qty": qty,
				"warehouse": to_warehouse,
				"from_warehouse": from_warehouse,
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
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	if settings.default_source_warehouse:
		return settings.default_source_warehouse

	warehouse = frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name"
	)
	if not warehouse:
		frappe.throw(_("No warehouse configured for {0}").format(company))
	return warehouse
