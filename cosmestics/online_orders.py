"""The online order workflow, in one place.

An online order is a **Sales Order** with `cosmestics_online_order` set. Its
life is `cosmestics_order_status`:

    Draft ──pay──▶ Order Received ──▶ Processing ──▶ Out for Delivery ──▶ Complete
                                                  └─▶ Ready for Pickup ─┘
    (Draft / Order Received / Processing ──▶ Cancelled)

* **Draft** is the customer's cart: an unsubmitted Sales Order they add to and
  change. Its lines *hold* stock for `shop_hold_minutes` after their last
  change, so two customers cannot both pay for the last one.
* **Order Received** happens only when M-Pesa confirms payment: the order is
  submitted (reserving its stock the ERPNext way) and a Payment Entry is made
  against it as an advance.
* **Out for Delivery / Ready for Pickup** is when it is **billed**: a Sales
  Invoice is raised from the order with the advance allocated and stock
  taken, and for delivery a Cosmestics Delivery is created — so it lands on
  the rider's Deliveries worklist like any other.
* **Complete** when the rider marks the delivery Delivered (automatic, see
  `on_delivery_update`) or the customer collects.

Every change appends a row to `cosmestics_status_log` (status, from when, by
whom). The customer's tracking page reads those rows to show how long the
order spent in each stage.
"""

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, flt, now_datetime, nowdate

DRAFT = "Draft"
RECEIVED = "Order Received"
PROCESSING = "Processing"
OUT = "Out for Delivery"
PICKUP = "Ready for Pickup"
COMPLETE = "Complete"
CANCELLED = "Cancelled"

TRANSITIONS = {
	DRAFT: (RECEIVED, CANCELLED),
	RECEIVED: (PROCESSING, CANCELLED),
	PROCESSING: (OUT, PICKUP, CANCELLED),
	OUT: (COMPLETE,),
	PICKUP: (COMPLETE,),
	COMPLETE: (),
	CANCELLED: (),
}

#: What the customer and staff see for each status, and what it means.
DESCRIPTIONS = {
	DRAFT: "Your cart - add, change or remove items, then pay to place the order.",
	RECEIVED: "Payment received. The shop has your order.",
	PROCESSING: "Your items are being picked and packed.",
	OUT: "On the way to you with our rider.",
	PICKUP: "Packed and waiting for you at the shop.",
	COMPLETE: "Delivered - enjoy!",
	CANCELLED: "This order was cancelled.",
}


def flow(fulfilment: str | None) -> list:
	"""The stages an order passes through, for the tracking page."""
	last = PICKUP if fulfilment == "Pickup" else OUT
	return [DRAFT, RECEIVED, PROCESSING, last, COMPLETE]


@contextmanager
def as_shop():
	"""Run ERPNext document work for a shopper as the system.

	Shoppers are not Frappe users — they are Guest to the framework — and
	ERPNext checks permissions deep inside a Sales Order save (item details,
	price lists). The shop's own endpoints decide what a customer may touch
	(their own orders only); this lets the document machinery then do its job.
	"""
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		yield
	finally:
		frappe.set_user(user)


def settings():
	return frappe.get_cached_doc("Cosmestics POS Settings")


def hold_minutes() -> int:
	return cint(settings().get("shop_hold_minutes")) or 30


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def set_status(doc, status: str, note: str | None = None, by: str | None = None, force: bool = False):
	"""Move an online order to `status`, logging it. Refuses a move the
	workflow does not allow unless `force` (used for the very first Draft)."""
	current = doc.get("cosmestics_order_status") or None
	if current == status and not force:
		return doc
	if not force and current and status not in TRANSITIONS.get(current, ()):
		frappe.throw(_("An order that is {0} cannot move to {1}").format(_(current), _(status)))

	doc.cosmestics_order_status = status
	doc.append(
		"cosmestics_status_log",
		{
			"status": status,
			"changed_at": now_datetime(),
			"changed_by": by or _actor(),
			"note": note,
		},
	)
	return doc


def _actor() -> str:
	user = frappe.session.user if frappe.session else "Guest"
	if user in ("Guest", "Administrator"):
		return "Shop"
	return frappe.utils.get_fullname(user) or user


def timeline(doc) -> list:
	"""[{status, description, state, entered_at, left_at, seconds}] for the
	order's flow. `seconds` is how long it stayed (so far, for the current
	one); the client turns it into "2 days 4 hours"."""
	log = sorted(doc.get("cosmestics_status_log") or [], key=lambda r: r.changed_at)
	entered = {}
	for i, row in enumerate(log):
		left = log[i + 1].changed_at if i + 1 < len(log) else None
		entered[row.status] = (row.changed_at, left, row.changed_by, row.note)

	current = doc.cosmestics_order_status
	now = now_datetime()
	stages = flow(doc.cosmestics_fulfilment)
	if current == CANCELLED:
		stages = [s for s in stages if s in entered] + [CANCELLED]
	reached = stages.index(current) if current in stages else -1

	out = []
	for i, status in enumerate(stages):
		at, left, by, note = entered.get(status, (None, None, None, None))
		if status == current:
			state = "current" if current not in (COMPLETE, CANCELLED) else "done"
		elif i < reached or (at and left):
			state = "done"
		else:
			state = "upcoming"
		seconds = None
		if at:
			end = left or (now if state == "current" else None)
			seconds = int((end - at).total_seconds()) if end else None
		out.append(
			{
				"status": status,
				"description": DESCRIPTIONS.get(status, ""),
				"state": state,
				"entered_at": str(at) if at else None,
				"left_at": str(left) if left else None,
				"seconds": seconds,
				"by": by,
				"note": note,
			}
		)
	return out


# ---------------------------------------------------------------------------
# Stock available to the online shop
# ---------------------------------------------------------------------------


def available(item_codes, exclude_order: str | None = None) -> dict:
	"""{item_code: whole units a customer can still buy online}.

	Shelf stock in the shop's warehouse, less stock already promised to
	submitted orders (the Bin's reserved qty — paid online orders count here),
	less what other customers' carts are holding right now. `exclude_order`
	is the asking customer's own cart, which must not hold stock against
	itself.
	"""
	from cosmestics.shop import shop_warehouse

	codes = [c for c in set(item_codes or []) if c]
	if not codes:
		return {}
	warehouse = shop_warehouse()
	filters = {"item_code": ("in", codes)}
	if warehouse:
		filters["warehouse"] = warehouse
	shelf = {}
	for r in frappe.get_all(
		"Bin", filters=filters, fields=["item_code", "actual_qty", "reserved_qty"], limit_page_length=0
	):
		shelf[r.item_code] = shelf.get(r.item_code, 0) + flt(r.actual_qty) - flt(r.reserved_qty)

	since = add_to_date(now_datetime(), minutes=-hold_minutes())
	held = frappe.db.sql(
		"""
		select soi.item_code, sum(soi.stock_qty) as qty
		from `tabSales Order Item` soi
		join `tabSales Order` so on so.name = soi.parent
		where so.docstatus = 0 and so.cosmestics_online_order = 1
			and so.cosmestics_order_status = %(draft)s
			and so.modified >= %(since)s
			and so.name != %(exclude)s
			and soi.item_code in %(codes)s
		group by soi.item_code
		""",
		{"draft": DRAFT, "since": since, "exclude": exclude_order or "", "codes": codes},
		as_dict=True,
	)
	holds = {r.item_code: flt(r.qty) for r in held}
	return {c: max(0, int(shelf.get(c, 0) - holds.get(c, 0))) for c in codes}


# ---------------------------------------------------------------------------
# Billing and delivery (staff actions)
# ---------------------------------------------------------------------------


def bill(so) -> str:
	"""Raise the Sales Invoice for a paid online order: stock taken from the
	order's warehouse, the M-Pesa advance allocated against it. Returns the
	invoice name. Idempotent — an order already billed returns its invoice."""
	existing = frappe.db.get_value(
		"Sales Invoice Item", {"sales_order": so.name, "docstatus": 1}, "parent"
	)
	if existing:
		return existing

	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

	si = make_sales_invoice(so.name)
	si.update_stock = 1
	si.set_warehouse = so.set_warehouse
	for row in si.items:
		if not row.warehouse:
			row.warehouse = so.set_warehouse
	si.allocate_advances_automatically = 1
	si.remarks = _("Online order {0}").format(so.name)
	si.flags.ignore_permissions = True
	si.insert()
	try:
		si.submit()
	except frappe.ValidationError as e:
		frappe.throw(
			_("Could not bill {0}: {1}. If an item has just sold out at the till, restock it or change the order first.").format(
				so.name, frappe.utils.strip_html(str(e))
			)
		)
	return si.name


def create_delivery(
	so, invoice: str, rider: str | None = None, rider_name: str | None = None, courier: str | None = None
) -> str:
	"""A Cosmestics Delivery for the order, dispatched, on the rider's worklist."""
	if so.get("cosmestics_delivery"):
		return so.cosmestics_delivery
	from cosmestics.api.deliveries import create_delivery as make

	area = so.get("cosmestics_delivery_area")
	address = "\n".join(p for p in (so.get("cosmestics_delivery_address"), area and f"({area})") if p)
	courier = (
		courier
		or (rider and frappe.db.get_value("Cosmestics Rider", rider, "courier"))
		or "In-house"
	)
	row = make(
		rider=rider,
		rider_name=rider_name,
		courier=courier,
		contact_phone=so.get("cosmestics_contact_phone"),
		address=address,
		landmark=so.get("cosmestics_landmark"),
		delivery_instructions=so.get("cosmestics_customer_note"),
		sales_invoice=invoice,
		customer=so.customer,
		customer_name=so.customer_name,
		status="Dispatched",
	)
	return row["name"]


def on_delivery_update(doc, method=None):
	"""Cosmestics Delivery `on_update`: a delivery the rider marks Delivered
	completes the online order it carries."""
	if doc.status != "Delivered":
		return
	name = frappe.db.get_value(
		"Sales Order",
		{"cosmestics_delivery": doc.name, "cosmestics_order_status": OUT, "docstatus": 1},
		"name",
	)
	if not name:
		return
	so = frappe.get_doc("Sales Order", name)
	set_status(so, COMPLETE, note=_("Delivered by {0}").format(doc.rider_name or _("the rider")))
	so.flags.ignore_permissions = True
	so.save()


def new_draft(customer: str):
	"""An empty cart for `customer`, ready for its first line."""
	from cosmestics.shop import shop_settings, shop_warehouse

	company = frappe.defaults.get_global_default("company")
	so = frappe.new_doc("Sales Order")
	so.customer = customer
	so.company = company
	so.order_type = "Sales"
	so.transaction_date = nowdate()
	so.delivery_date = add_days(nowdate(), 2)
	so.selling_price_list = shop_settings().price_list
	so.set_warehouse = shop_warehouse()
	so.cosmestics_online_order = 1
	so.cosmestics_fulfilment = "Delivery"
	set_status(so, DRAFT, note=_("Cart started"), by="Customer", force=True)
	return so
