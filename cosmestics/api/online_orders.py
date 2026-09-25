"""Staff side of online orders: the queue in the staff app, and the actions
that move an order along (see `cosmestics.online_orders` for the workflow).

Open to anyone who can work with Sales Orders — the counter and store staff
who pack and send orders out — and the System Manager.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from cosmestics import online_orders as oo
from cosmestics import shop

STAFF_ROLES = {"System Manager", "Sales User", "Sales Manager", "Stock User", "Cosmestics Store Keeper"}
QUEUE = (oo.RECEIVED, oo.PROCESSING, oo.OUT, oo.PICKUP, oo.COMPLETE, oo.CANCELLED, oo.DRAFT)


def _require_staff():
	if not STAFF_ROLES.intersection(frappe.get_roles()):
		frappe.throw(_("You are not allowed to handle online orders"), frappe.PermissionError)


def _row(so) -> dict:
	delivery_item = oo.settings().get("shop_delivery_item")
	goods = [r for r in so.items if r.item_code != delivery_item]
	log = sorted(so.get("cosmestics_status_log") or [], key=lambda r: r.changed_at)
	since = log[-1].changed_at if log else so.modified
	return {
		"name": so.name,
		"status": so.cosmestics_order_status,
		"customer": so.customer,
		"customer_name": so.customer_name,
		"phone": so.get("cosmestics_contact_phone"),
		"fulfilment": so.get("cosmestics_fulfilment"),
		"area": so.get("cosmestics_delivery_area"),
		"total": flt(so.grand_total),
		"total_label": shop.money(so.grand_total),
		"count": sum(cint(r.qty) for r in goods),
		"paid_at": str(so.cosmestics_paid_at) if so.get("cosmestics_paid_at") else None,
		"receipt": so.get("cosmestics_mpesa_receipt"),
		"since": str(since),
		"seconds_in_status": int((now_datetime() - since).total_seconds()) if since else None,
		"next": list(oo.TRANSITIONS.get(so.cosmestics_order_status, ())),
	}


@frappe.whitelist()
def list_orders(status: str | None = None, search: str | None = None, limit: int = 100) -> dict:
	_require_staff()
	filters = {"cosmestics_online_order": 1}
	if status:
		filters["cosmestics_order_status"] = status
	else:
		# The working queue: paid and not yet finished.
		filters["cosmestics_order_status"] = ("in", (oo.RECEIVED, oo.PROCESSING, oo.OUT, oo.PICKUP))
	or_filters = None
	if search:
		like = f"%{search.strip()}%"
		or_filters = {"name": ("like", like), "customer_name": ("like", like), "cosmestics_contact_phone": ("like", like)}
	names = frappe.get_all(
		"Sales Order",
		filters=filters,
		or_filters=or_filters,
		pluck="name",
		order_by="cosmestics_paid_at asc, creation asc" if not status else "modified desc",
		limit_page_length=cint(limit) or 100,
	)
	counts = dict(
		frappe.db.sql(
			"""select cosmestics_order_status, count(*) from `tabSales Order`
			where cosmestics_online_order = 1 and cosmestics_order_status in %s
			group by cosmestics_order_status""",
			[QUEUE],
		)
	)
	return {
		"orders": [_row(frappe.get_doc("Sales Order", n)) for n in names],
		"counts": {s: cint(counts.get(s)) for s in QUEUE},
	}


@frappe.whitelist()
def get_order(name: str) -> dict:
	_require_staff()
	so = frappe.get_doc("Sales Order", name)
	if not so.cosmestics_online_order:
		frappe.throw(_("{0} is not an online order").format(name))
	delivery_item = oo.settings().get("shop_delivery_item")
	products = shop.snapshot()["products"]
	lines = [
		{
			"item_code": r.item_code,
			"name": (products.get(r.item_code) or {}).get("name") or r.item_name,
			"image": (products.get(r.item_code) or {}).get("image") or r.image,
			"qty": cint(r.qty),
			"rate_label": shop.money(r.rate),
			"amount_label": shop.money(r.amount),
		}
		for r in so.items
		if r.item_code != delivery_item
	]
	invoice = frappe.db.get_value("Sales Invoice Item", {"sales_order": so.name, "docstatus": 1}, "parent")
	return _row(so) | {
		"lines": lines,
		"address": so.get("cosmestics_delivery_address"),
		"landmark": so.get("cosmestics_landmark"),
		"note": so.get("cosmestics_customer_note"),
		"delivery_fee_label": shop.money(so.get("cosmestics_delivery_fee")),
		"invoice": invoice,
		"delivery": so.get("cosmestics_delivery"),
		"timeline": oo.timeline(so),
	}


@frappe.whitelist(methods=["POST"])
def advance(
	name: str,
	to: str,
	rider: str | None = None,
	rider_name: str | None = None,
	courier: str | None = None,
	note: str | None = None,
) -> dict:
	"""Move an order to `to`. Going out for delivery or ready for pickup bills
	it; going out for delivery also puts it on the rider's worklist."""
	_require_staff()
	so = frappe.get_doc("Sales Order", name, for_update=True)
	if not so.cosmestics_online_order:
		frappe.throw(_("{0} is not an online order").format(name))
	current = so.cosmestics_order_status
	if to not in oo.TRANSITIONS.get(current, ()):
		frappe.throw(_("An order that is {0} cannot move to {1}").format(_(current), _(to)))

	message = _("{0} is now {1}").format(so.name, _(to))
	if to == oo.OUT:
		if so.cosmestics_fulfilment != "Delivery":
			frappe.throw(_("This order is for pickup"))
		if not (rider or (rider_name or "").strip()):
			frappe.throw(_("Choose the rider taking it"))
		invoice = oo.bill(so)
		delivery = oo.create_delivery(so, invoice, rider=rider, rider_name=rider_name, courier=courier)
		# Billing updates the order (per cent billed), so work on the fresh copy.
		so.reload()
		so.cosmestics_delivery = delivery
		note = note or _("Billed on {0}, with {1}").format(invoice, rider_name or rider)
		message = _("{0} billed and sent out for delivery").format(so.name)
	elif to == oo.PICKUP:
		invoice = oo.bill(so)
		so.reload()
		note = note or _("Billed on {0}").format(invoice)
	elif to == oo.COMPLETE and so.cosmestics_fulfilment == "Pickup":
		note = note or _("Collected from the shop")
	elif to == oo.COMPLETE and so.get("cosmestics_delivery"):
		if frappe.db.get_value("Cosmestics Delivery", so.cosmestics_delivery, "status") != "Delivered":
			from cosmestics.api.deliveries import set_delivery_status

			set_delivery_status(so.cosmestics_delivery, "Delivered")
			so.reload()
			if so.cosmestics_order_status == oo.COMPLETE:
				return get_order(so.name) | {"message": message}
	elif to == oo.CANCELLED:
		if not (note or "").strip():
			frappe.throw(_("Say why the order is cancelled"))
		if so.docstatus == 1:
			so.update_status("Closed")
			so.reload()
		if so.get("cosmestics_paid_at"):
			message = _("{0} cancelled. Refund the M-Pesa payment {1} to the customer.").format(
				so.name, so.get("cosmestics_mpesa_receipt") or ""
			)

	oo.set_status(so, to, note=note)
	so.flags.ignore_permissions = True
	so.save()
	return get_order(so.name) | {"message": message}
