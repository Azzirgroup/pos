"""Bundling several sales onto one delivery run.

Cosmestics Delivery Trip is a plain custom doctype rather than ERPNext's own
Delivery Trip — see the module docstring on the doctype itself for why: its
stops want a Delivery Note, and this shop's sales never raise one.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime


def _company() -> str | None:
	return (
		frappe.defaults.get_user_default("Company")
		or frappe.defaults.get_global_default("company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)


@frappe.whitelist()
def search_invoices(search: str | None = None, limit: int = 20) -> list:
	"""Submitted sales, for picking which ones go on a trip.

	Shows exactly what a cashier needs to recognise the right one — the
	invoice number, who it is for, and how much — not the whole document.
	"""
	filters = {"docstatus": 1, "is_pos": 1}
	company = _company()
	if company:
		filters["company"] = company

	or_filters = None
	if search:
		or_filters = [
			{"name": ("like", f"%{search}%")},
			{"customer_name": ("like", f"%{search}%")},
			{"customer": ("like", f"%{search}%")},
		]

	rows = frappe.get_all(
		"Sales Invoice",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "customer", "customer_name", "grand_total"],
		order_by="posting_date desc, creation desc",
		limit_page_length=min(max(int(limit or 20), 1), 100),
	)
	return [
		{
			"name": r.name,
			"customer": r.customer_name or r.customer,
			"grand_total": flt(r.grand_total),
		}
		for r in rows
	]


@frappe.whitelist(methods=["POST"])
def create_trip(
	driver_name: str,
	invoices: list | str,
	driver_phone: str | None = None,
	vehicle: str | None = None,
	departure_time: str | None = None,
) -> dict:
	"""Raise and dispatch a trip in one step.

	Submitted immediately, the same reasoning as everywhere else a cashier or
	manager is standing at a counter rather than filling in a desk form: a
	trip sitting as a draft is a driver who has already left with nobody
	having recorded what they took.
	"""
	if isinstance(invoices, str):
		invoices = frappe.parse_json(invoices)

	if not driver_name or not str(driver_name).strip():
		frappe.throw(_("Name the driver"))
	if not invoices:
		frappe.throw(_("Add at least one invoice to the trip"))

	company = _company()
	if not company:
		frappe.throw(_("No default company is set"))

	doc = frappe.new_doc("Cosmestics Delivery Trip")
	doc.company = company
	doc.driver_name = driver_name
	doc.driver_phone = driver_phone
	doc.vehicle = vehicle
	# A `datetime-local` input sends "YYYY-MM-DDTHH:mm" — `get_datetime` parses
	# that (and most other reasonable formats) into what a Datetime field
	# actually wants, rather than trusting the browser's string verbatim.
	doc.departure_time = get_datetime(departure_time) if departure_time else now_datetime()

	for row in invoices:
		if not row.get("sales_invoice"):
			continue
		doc.append("invoices", {"sales_invoice": row["sales_invoice"]})

	doc.insert()
	doc.submit()

	return {
		"name": doc.name,
		"status": doc.status,
		"total_amount": flt(doc.total_amount),
		"invoice_count": len(doc.invoices),
		"message": _("{0} dispatched with {1} invoice(s)").format(doc.name, len(doc.invoices)),
	}


@frappe.whitelist(methods=["POST"])
def add_stop(
	sales_invoice: str,
	driver_name: str,
	destination: str | None = None,
	driver_phone: str | None = None,
	vehicle: str | None = None,
	contact_phone: str | None = None,
	trip: str | None = None,
) -> dict:
	"""Put a sale on a delivery run, at the moment it is rung up.

	`create_trip` assembles a run afterwards, from the Deliveries screen, by
	picking invoices somebody has to go and find. That is the right shape for a
	manager planning a route, and the wrong one for the counter: the cashier is
	standing with the customer who is telling them the address, and if it is not
	captured now it is captured from memory an hour later or not at all.

	## Joining rather than always creating

	A driver does several drops in one run. A second sale for the same driver on
	the same day therefore joins the trip already open for them instead of
	raising a parallel one — otherwise a three-stop round becomes three "trips"
	and the whole point of grouping is lost. `trip` forces a specific one when
	the shop is running two vehicles under one name.

	Trips stay **draft** while stops are still being added; `create_trip`'s
	submit-immediately reasoning does not apply here, because the run has not
	left yet. Dispatching is a separate, deliberate act.
	"""
	driver_name = (driver_name or "").strip()
	if not driver_name:
		frappe.throw(_("Name the driver"))
	if not frappe.db.exists("Sales Invoice", sales_invoice):
		frappe.throw(_("{0} not found").format(sales_invoice))

	company = _company()
	if not company:
		frappe.throw(_("No default company is set"))

	invoice = frappe.db.get_value(
		"Sales Invoice", sales_invoice, ["customer", "customer_name", "grand_total"], as_dict=True
	)

	doc = None
	if trip:
		doc = frappe.get_doc("Cosmestics Delivery Trip", trip)
		if doc.docstatus != 0:
			frappe.throw(_("{0} has already been dispatched").format(trip))
	else:
		# Today's open run for this driver, if there is one.
		existing = frappe.db.get_value(
			"Cosmestics Delivery Trip",
			{
				"docstatus": 0,
				"driver_name": driver_name,
				"company": company,
				"departure_time": (">=", frappe.utils.today() + " 00:00:00"),
			},
			"name",
		)
		if existing:
			doc = frappe.get_doc("Cosmestics Delivery Trip", existing)

	if not doc:
		doc = frappe.new_doc("Cosmestics Delivery Trip")
		doc.company = company
		doc.driver_name = driver_name
		doc.departure_time = now_datetime()

	# Details given later fill in blanks rather than overwrite what is set: the
	# first stop usually carries the vehicle, and a later one leaving it empty
	# should not erase it.
	doc.driver_phone = doc.driver_phone or driver_phone
	doc.vehicle = doc.vehicle or vehicle

	already = {r.sales_invoice for r in doc.invoices}
	if sales_invoice not in already:
		doc.append(
			"invoices",
			{
				"sales_invoice": sales_invoice,
				"customer": invoice.customer_name or invoice.customer,
				"destination": destination,
				"contact_phone": contact_phone,
				"amount": flt(invoice.grand_total),
			},
		)

	doc.save()

	return {
		"trip": doc.name,
		"stops": len(doc.invoices),
		"driver": doc.driver_name,
		"total_amount": flt(doc.total_amount),
		"message": _("{0} added to {1} — {2} stop(s)").format(
			sales_invoice, doc.name, len(doc.invoices)
		),
	}


@frappe.whitelist()
def open_trips(limit: int = 10) -> list:
	"""Runs still being loaded, so a second sale can join one."""
	company = _company()
	filters = {"docstatus": 0}
	if company:
		filters["company"] = company
	rows = frappe.get_all(
		"Cosmestics Delivery Trip",
		filters=filters,
		fields=["name", "driver_name", "vehicle", "total_amount"],
		order_by="modified desc",
		limit_page_length=min(max(int(limit or 10), 1), 50),
	)
	for r in rows:
		r["stops"] = frappe.db.count("Cosmestics Delivery Trip Invoice", {"parent": r.name})
	return rows
