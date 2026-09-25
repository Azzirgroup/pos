"""The signed-in customer's cart, checkout and orders.

The cart *is* the order: an unsubmitted online Sales Order in status Draft
(see `cosmestics.online_orders`). Adding to the cart edits it; checkout fills
in how it is fulfilled; paying (see `shop_payments`) submits it. So a customer
can leave a half-built order and come back to it from any device, and staff
can see abandoned carts for what they are.

Every endpoint resolves the customer from the shop session
(`shop_account.current_customer`) and only ever touches that customer's own
orders. Quantities are checked against `online_orders.available`, which nets
off other customers' held carts, so the shop never promises stock it does
not have.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from cosmestics import online_orders as oo
from cosmestics import shop
from cosmestics.api.shop_account import (
	current_customer,
	normalise_phone,
	require_shop_request,
	valid_phone,
)

MAX_LINE_QTY = 50


def _cart_name(customer: str) -> str | None:
	return frappe.db.get_value(
		"Sales Order",
		{
			"customer": customer,
			"docstatus": 0,
			"cosmestics_online_order": 1,
			"cosmestics_order_status": oo.DRAFT,
		},
		"name",
		order_by="modified desc",
	)


def _own_order(name: str, customer: str):
	so = frappe.get_doc("Sales Order", name)
	if not so.cosmestics_online_order or so.customer != customer:
		raise frappe.DoesNotExistError(_("Order not found"))
	return so


def _product(code: str) -> dict:
	"""A product the shop actually sells online, from the catalog snapshot."""
	p = shop.snapshot()["products"].get(code)
	if not p or p.get("has_variants") or flt(p.get("price")) <= 0:
		frappe.throw(_("That product is not available online"))
	return p


def _delivery_item() -> str:
	return oo.settings().get("shop_delivery_item") or "ONLINE-DELIVERY"


def cart_payload(so=None, customer: str | None = None) -> dict:
	"""The cart as the shop app renders it."""
	s = oo.settings()
	areas = frappe.get_all(
		"Cosmestics Delivery Area",
		filters={"enabled": 1},
		fields=["name", "area_name", "fee", "eta"],
		order_by="sort_order asc, area_name asc",
	)
	flat_fee = flt(s.get("shop_delivery_fee"))
	base = {
		# With no Delivery Areas, delivery is one option at the shop's flat fee.
		"flat_fee": flat_fee,
		"flat_fee_label": shop.money(flat_fee) if flat_fee else "Free",
		"areas": [{"name": a.name, "label": a.area_name, "fee": flt(a.fee), "fee_label": shop.money(a.fee), "eta": a.eta} for a in areas],
		"pickup_note": s.get("shop_pickup_note") or "",
		"hold_minutes": oo.hold_minutes(),
		"currency": shop.snapshot()["currency"],
	}
	if not so:
		return base | {"order": None, "lines": [], "count": 0, "subtotal": 0, "total": 0, "delivery_fee": 0}

	delivery_item = _delivery_item()
	goods = [r for r in so.items if r.item_code != delivery_item]
	avail = oo.available([r.item_code for r in goods], exclude_order=so.name)
	products = shop.snapshot()["products"]
	lines = []
	for r in goods:
		p = products.get(r.item_code) or {}
		lines.append(
			{
				"item_code": r.item_code,
				"name": p.get("name") or r.item_name,
				"image": p.get("image") or r.image,
				"url": shop.product_url(p) if p else None,
				"qty": cint(r.qty),
				"rate": flt(r.rate),
				"rate_label": shop.money(r.rate),
				"amount": flt(r.amount),
				"amount_label": shop.money(r.amount),
				"available": avail.get(r.item_code, 0),
				"short": cint(r.qty) > avail.get(r.item_code, 0),
			}
		)
	subtotal = sum(line["amount"] for line in lines)
	fee = flt(so.get("cosmestics_delivery_fee"))
	return base | {
		"order": so.name,
		"lines": lines,
		"count": sum(line["qty"] for line in lines),
		"subtotal": subtotal,
		"subtotal_label": shop.money(subtotal),
		"delivery_fee": fee,
		"delivery_fee_label": shop.money(fee),
		"total": flt(so.grand_total),
		"total_label": shop.money(so.grand_total),
		"fulfilment": so.get("cosmestics_fulfilment") or "Delivery",
		"area": so.get("cosmestics_delivery_area"),
		"address": so.get("cosmestics_delivery_address") or "",
		"landmark": so.get("cosmestics_landmark") or "",
		"phone": so.get("cosmestics_contact_phone") or "",
		"note": so.get("cosmestics_customer_note") or "",
		"has_short": any(line["short"] for line in lines),
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def cart() -> dict:
	customer = current_customer()
	if not customer:
		return cart_payload() | {"signed_in": False}
	name = _cart_name(customer)
	return cart_payload(frappe.get_doc("Sales Order", name) if name else None) | {"signed_in": True}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def availability(item_codes: str) -> dict:
	"""{item_code: units a customer can still add}, for product pages and
	steppers. Public — it says no more than the product page's stock badge."""
	codes = [c for c in frappe.parse_json(item_codes or "[]") if isinstance(c, str)][:60]
	customer = current_customer()
	own = _cart_name(customer) if customer else None
	return oo.available(codes, exclude_order=own)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def set_line(item_code: str, qty: int | str, add: int | str = 0) -> dict:
	"""Set (or with `add`, increase) the quantity of one product in the cart.
	Zero removes it; an empty cart is deleted rather than kept."""
	require_shop_request()
	customer = current_customer(required=True)
	product = _product(item_code)
	qty = cint(qty)

	name = _cart_name(customer)
	so = frappe.get_doc("Sales Order", name) if name else oo.new_draft(customer)
	row = next((r for r in so.items if r.item_code == item_code), None)
	if cint(add):
		qty = (cint(row.qty) if row else 0) + qty
	qty = max(0, min(qty, MAX_LINE_QTY))

	if qty:
		can = oo.available([item_code], exclude_order=so.name if name else None).get(item_code, 0)
		if qty > can:
			if can <= 0:
				frappe.throw(_("{0} is out of stock right now").format(product["name"]))
			frappe.throw(_("Only {0} of {1} available").format(can, product["name"]))

	if row and qty:
		row.qty = qty
		row.rate = product["price"]
	elif row and not qty:
		so.remove(row)
	elif qty:
		so.append(
			"items",
			{
				"item_code": item_code,
				"qty": qty,
				"rate": product["price"],
				"delivery_date": so.delivery_date,
				"warehouse": so.set_warehouse,
			},
		)

	delivery_item = _delivery_item()
	if not any(r.item_code != delivery_item for r in so.items):
		if name:
			with oo.as_shop():
				frappe.delete_doc("Sales Order", name, ignore_permissions=True, force=True)
		return cart_payload()

	with oo.as_shop():
		so.save()
	return cart_payload(so)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def set_fulfilment(
	fulfilment: str,
	area: str | None = None,
	address: str | None = None,
	landmark: str | None = None,
	phone: str | None = None,
	note: str | None = None,
) -> dict:
	"""Checkout step one: pickup, or delivery to an area (whose fee is added
	to the order as its own line)."""
	require_shop_request()
	customer = current_customer(required=True)
	name = _cart_name(customer)
	if not name:
		frappe.throw(_("Your cart is empty"))
	so = frappe.get_doc("Sales Order", name)

	if fulfilment not in ("Delivery", "Pickup"):
		frappe.throw(_("Choose delivery or pickup"))
	phone = normalise_phone(phone or "") or frappe.db.get_value("Customer", customer, "cosmestics_shop_phone")
	if not valid_phone(phone):
		frappe.throw(_("Enter a phone number we can call about this order"))

	fee = 0
	if fulfilment == "Delivery":
		if len((address or "").strip()) < 5:
			frappe.throw(_("Enter the delivery address"))
		if frappe.db.exists("Cosmestics Delivery Area", {"enabled": 1}):
			row = frappe.db.get_value("Cosmestics Delivery Area", {"name": area, "enabled": 1}, ["name", "fee"], as_dict=True)
			if not row:
				frappe.throw(_("Choose where to deliver to"))
			fee = flt(row.fee)
			so.cosmestics_delivery_area = row.name
		else:
			# No areas set up: one delivery option at the flat fee.
			fee = flt(oo.settings().get("shop_delivery_fee"))
			so.cosmestics_delivery_area = None
		so.cosmestics_delivery_address = address.strip()
		so.cosmestics_landmark = (landmark or "").strip() or None
	else:
		so.cosmestics_delivery_area = None
		so.cosmestics_delivery_address = None
		so.cosmestics_landmark = None

	so.cosmestics_fulfilment = fulfilment
	so.cosmestics_contact_phone = phone
	so.cosmestics_customer_note = (note or "").strip()[:500] or None
	so.cosmestics_delivery_fee = fee

	delivery_item = _delivery_item()
	fee_row = next((r for r in so.items if r.item_code == delivery_item), None)
	if fee and fee_row:
		fee_row.rate = fee
		fee_row.qty = 1
	elif fee:
		so.append("items", {"item_code": delivery_item, "qty": 1, "rate": fee, "delivery_date": so.delivery_date})
	elif fee_row:
		so.remove(fee_row)

	with oo.as_shop():
		so.save()
	return cart_payload(so)


def _summary(so) -> dict:
	delivery_item = _delivery_item()
	goods = [r for r in so.items if r.item_code != delivery_item]
	products = shop.snapshot()["products"]
	return {
		"name": so.name,
		"status": so.cosmestics_order_status,
		"date": str(so.transaction_date),
		"placed_at": str(so.cosmestics_paid_at) if so.get("cosmestics_paid_at") else None,
		"total": flt(so.grand_total),
		"total_label": shop.money(so.grand_total),
		"count": sum(cint(r.qty) for r in goods),
		"fulfilment": so.get("cosmestics_fulfilment"),
		"images": [
			(products.get(r.item_code) or {}).get("image") or r.image for r in goods[:4]
		],
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def my_orders() -> list:
	customer = current_customer(required=True)
	names = frappe.get_all(
		"Sales Order",
		filters={"customer": customer, "cosmestics_online_order": 1, "docstatus": ("!=", 2)},
		pluck="name",
		order_by="creation desc",
		limit_page_length=50,
	)
	return [_summary(frappe.get_doc("Sales Order", n)) for n in names]


@frappe.whitelist(allow_guest=True, methods=["GET"])
def order(name: str) -> dict:
	"""One order with its tracking timeline."""
	customer = current_customer(required=True)
	so = _own_order(name, customer)
	delivery_item = _delivery_item()
	products = shop.snapshot()["products"]
	lines = []
	for r in so.items:
		if r.item_code == delivery_item:
			continue
		p = products.get(r.item_code) or {}
		lines.append(
			{
				"name": p.get("name") or r.item_name,
				"image": p.get("image") or r.image,
				"url": shop.product_url(p) if p else None,
				"qty": cint(r.qty),
				"rate_label": shop.money(r.rate),
				"amount_label": shop.money(r.amount),
			}
		)
	subtotal = sum(flt(r.amount) for r in so.items if r.item_code != delivery_item)
	return _summary(so) | {
		"lines": lines,
		"subtotal_label": shop.money(subtotal),
		"delivery_fee_label": shop.money(so.get("cosmestics_delivery_fee")),
		"address": so.get("cosmestics_delivery_address"),
		"area": so.get("cosmestics_delivery_area"),
		"landmark": so.get("cosmestics_landmark"),
		"phone": so.get("cosmestics_contact_phone"),
		"note": so.get("cosmestics_customer_note"),
		"receipt": so.get("cosmestics_mpesa_receipt"),
		"pickup_note": oo.settings().get("shop_pickup_note") or "",
		"timeline": oo.timeline(so),
		"server_now": str(frappe.utils.now_datetime()),
		"is_cart": so.cosmestics_order_status == oo.DRAFT,
	}
