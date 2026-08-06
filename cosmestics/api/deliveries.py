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
