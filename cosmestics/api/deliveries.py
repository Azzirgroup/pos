"""Getting goods to the customer — the drop, and the run it goes out on.

Two documents, and the distinction is the whole design:

* **Cosmestics Delivery** is one order going to one address. It carries the
  rider, the address, the customer's number, the instructions and the status,
  and it is what a shop means by "today's deliveries".
* **Cosmestics Delivery Trip** is the *run* — one driver, one van, several
  drops. A plain custom doctype rather than ERPNext's own Delivery Trip; see
  the module docstring on the doctype itself for why (its stops want a Delivery
  Note, and this shop's sales never raise one).

A delivery does not need a trip. Most do not: a boda rider takes one parcel to
one address and comes back. Trips exist for the days a van goes out loaded, and
a delivery joins one by naming it.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, get_url, now_datetime, nowdate, quoted

from cosmestics.cosmestics.doctype.cosmestics_delivery.cosmestics_delivery import STATUSES


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


@frappe.whitelist(methods=["POST"])
def create_delivery(
	rider: str | None = None,
	rider_name: str | None = None,
	rider_phone: str | None = None,
	courier: str | None = None,
	vehicle: str | None = None,
	contact_phone: str | None = None,
	address: str | None = None,
	landmark: str | None = None,
	map_location: str | None = None,
	delivery_instructions: str | None = None,
	sales_invoice: str | None = None,
	customer: str | None = None,
	customer_name: str | None = None,
	status: str = "Pending",
	trip: str | None = None,
) -> dict:
	"""Record where one order is going, and who is taking it.

	Raised from the pay sheet at the moment the sale is rung up. That timing is
	the point: the customer is standing there saying the address, and an hour
	later it is remembered wrong or not at all.

	## Why the rider can be named rather than picked

	`rider` is a link to a `Cosmestics Rider`, and the field is mandatory — a
	delivery whose rider is a free-text name cannot be phoned when it goes
	missing. But making the cashier leave the sale to create the record first is
	how the field ends up holding "boda guy". So a bare `rider_name` creates or
	finds the rider here, which is the same thing the "+" button in the sheet
	does, for callers that have a name and no id.

	Created **Pending** by default. Dispatching is a separate, deliberate act:
	it stamps the time and messages the customer, and neither should happen
	because a sale was completed.
	"""
	from cosmestics.cosmestics.doctype.cosmestics_rider.cosmestics_rider import create_rider

	if status not in STATUSES:
		frappe.throw(_("{0} is not a delivery status").format(status))

	if not rider:
		if not (rider_name or "").strip():
			frappe.throw(_("Name the rider"))
		rider = create_rider(
			rider_name=rider_name, phone=rider_phone, courier=courier, vehicle=vehicle
		)["value"]

	company = _company()
	if not company:
		frappe.throw(_("No default company is set"))

	if sales_invoice and not frappe.db.exists("Sales Invoice", sales_invoice):
		frappe.throw(_("{0} not found").format(sales_invoice))

	doc = frappe.new_doc("Cosmestics Delivery")
	doc.company = company
	doc.delivery_date = nowdate()
	doc.status = status
	doc.rider = rider
	doc.sales_invoice = sales_invoice
	doc.customer = customer
	doc.trip = trip

	# Only what was actually supplied. The rest is fetched from the rider by the
	# doctype's own `fetch_from`, and overwriting those with blanks here would
	# undo it.
	for field, value in (
		# Who the parcel is for, written down as a name.
		#
		# The form only ever asked for a phone number, on the assumption that a
		# delivery raised from the pay sheet already carries a Customer link. Most
		# do; the ones typed in by hand for a caller do not, and those rows read
		# "Walk-in" on the worklist with a number beside them — which is nothing to
		# go on when a rider asks who they are looking for.
		("customer_name", customer_name),
		("rider_name", rider_name),
		("rider_phone", rider_phone),
		("courier", courier),
		("vehicle", vehicle),
		("contact_phone", contact_phone),
		("address", address),
		("landmark", landmark),
		("map_location", map_location),
		("delivery_instructions", delivery_instructions),
	):
		if value not in (None, ""):
			doc.set(field, value)

	_fill_rider_details(doc, rider)
	if not doc.contact_phone:
		doc.contact_phone = _customer_phone(doc.customer or customer, sales_invoice)

	doc.insert()

	return _delivery_row(doc) | {
		"message": _("Delivery {0} recorded for {1}").format(
			doc.name, doc.customer_name or doc.customer or _("the customer")
		)
	}


def _fill_rider_details(doc, rider):
	"""Copy the rider's own details onto the drop where it has none.

	`fetch_from` does this in the desk form, driven by the client script; a
	document built server-side never runs it. Without this a delivery created
	from the till had a rider link and a blank rider phone, which is precisely
	the field the dispatch notice needs.
	"""
	row = frappe.db.get_value(
		"Cosmestics Rider", rider, ["rider_name", "phone", "courier", "vehicle"], as_dict=True
	)
	if not row:
		return
	doc.rider_name = doc.rider_name or row.rider_name
	doc.rider_phone = doc.rider_phone or row.phone
	doc.courier = doc.courier or row.courier
	doc.vehicle = doc.vehicle or row.vehicle


def _customer_phone(customer, sales_invoice=None) -> str | None:
	"""The number to ring about this parcel.

	The customer's own record first, then whatever the invoice carries. Returned
	rather than required so the field can be pre-filled and then corrected —
	the person receiving a delivery is often not the person who paid for it.
	"""
	if customer:
		for field in ("mobile_no", "phone"):
			if frappe.get_meta("Customer").has_field(field):
				value = frappe.db.get_value("Customer", customer, field)
				if value:
					return value

	if sales_invoice:
		return frappe.db.get_value("Sales Invoice", sales_invoice, "contact_mobile") or None

	return None


def _delivery_row(doc) -> dict:
	return {
		"name": doc.name,
		"status": doc.status,
		"delivery_date": str(doc.delivery_date) if doc.delivery_date else None,
		"customer": doc.customer,
		"customer_name": doc.customer_name or doc.customer,
		"sales_invoice": doc.sales_invoice,
		"amount": flt(doc.amount),
		"rider": doc.rider,
		"rider_name": doc.rider_name,
		"rider_phone": doc.rider_phone,
		"courier": doc.courier,
		"vehicle": doc.vehicle,
		"contact_phone": doc.contact_phone,
		"address": doc.address,
		"landmark": doc.landmark,
		"map_location": doc.map_location,
		"delivery_instructions": doc.delivery_instructions,
		"dispatched_at": str(doc.dispatched_at) if doc.dispatched_at else None,
		"delivered_at": str(doc.delivered_at) if doc.delivered_at else None,
		"trip": doc.trip,
	}


@frappe.whitelist()
def list_deliveries(
	on_date: str | None = None,
	days: int = 7,
	status: str | None = None,
	search: str | None = None,
	limit: int = 100,
) -> dict:
	"""What is going out, and what has gone.

	Defaults to a week rather than a day. "Today's deliveries" is the question
	the status column answers, and a list that empties at midnight loses the
	drop that went out at 6pm and has not been marked delivered yet — which is
	the one somebody is chasing in the morning.

	`on_date` narrows to a single day for the shop that does want exactly that.
	"""
	filters = {}
	company = _company()
	if company:
		filters["company"] = company

	if on_date:
		filters["delivery_date"] = on_date
	else:
		filters["delivery_date"] = (">=", add_days(nowdate(), -max(cint(days) or 7, 0)))

	if status:
		if status not in STATUSES:
			frappe.throw(_("{0} is not a delivery status").format(status))
		filters["status"] = status

	or_filters = None
	if search:
		or_filters = [
			{"name": ("like", f"%{search}%")},
			{"customer_name": ("like", f"%{search}%")},
			{"rider_name": ("like", f"%{search}%")},
			{"sales_invoice": ("like", f"%{search}%")},
			{"address": ("like", f"%{search}%")},
		]

	rows = frappe.get_all(
		"Cosmestics Delivery",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"status",
			"delivery_date",
			"customer",
			"customer_name",
			"sales_invoice",
			"amount",
			"rider",
			"rider_name",
			"rider_phone",
			"courier",
			"vehicle",
			"contact_phone",
			"address",
			"landmark",
			"map_location",
			"delivery_instructions",
			"dispatched_at",
			"delivered_at",
			"trip",
		],
		order_by="delivery_date desc, creation desc",
		limit_page_length=min(max(cint(limit) or 100, 1), 500),
	)

	# Pending first within a day: the list is a worklist, and a delivered drop
	# is history sitting on top of one nobody has taken yet. Sorted here rather
	# than in `order_by` because expressing it in SQL means a `FIELD(...)` call
	# in an order clause Frappe is entitled to reject as unsafe — and a list
	# that 500s is worse than one in a slightly different order.
	rank = {s: i for i, s in enumerate(("Pending", "Dispatched", "Failed", "Delivered"))}
	rows.sort(key=lambda r: (str(r["delivery_date"] or ""), -rank.get(r["status"], 9)), reverse=True)

	for r in rows:
		r["delivery_date"] = str(r["delivery_date"]) if r["delivery_date"] else None
		r["dispatched_at"] = str(r["dispatched_at"]) if r["dispatched_at"] else None
		r["delivered_at"] = str(r["delivered_at"]) if r["delivered_at"] else None

	counts = {s: 0 for s in STATUSES}
	for r in rows:
		counts[r["status"]] = counts.get(r["status"], 0) + 1

	# Counted from the rows rather than queried again. When the screen is on
	# today — which is where it now opens — this is simply `count`; the separate
	# figure matters on the days somebody has paged back, where "how many went
	# out today" is still the question the card is asked.
	today = nowdate()
	today_count = sum(1 for r in rows if r["delivery_date"] == today)

	return {
		"rows": rows,
		"statuses": list(STATUSES),
		"today": today,
		"totals": {
			"count": len(rows),
			"today": today_count,
			"value": flt(sum(flt(r["amount"]) for r in rows)),
			**counts,
		},
	}


@frappe.whitelist(methods=["POST"])
def set_delivery_status(name: str, status: str) -> dict:
	"""Move a delivery along.

	The timestamps and the dispatch notice are the doctype's own business — see
	`CosmesticsDelivery.stamp_status_times` and `on_update` — so this only has
	to say which state it is going to. That keeps a status changed from the desk
	behaving exactly like one changed from the till.
	"""
	if status not in STATUSES:
		frappe.throw(_("{0} is not a delivery status").format(status))

	doc = frappe.get_doc("Cosmestics Delivery", name)
	doc.check_permission("write")

	if doc.status == status:
		return _delivery_row(doc) | {"message": _("{0} is already {1}").format(name, _(status))}

	doc.status = status
	doc.save()

	return _delivery_row(doc) | {
		"message": _("{0} marked {1}").format(name, _(status)),
	}


@frappe.whitelist(methods=["POST"])
def update_delivery(name: str, values: dict | str) -> dict:
	"""Correct a drop that is already recorded.

	Allow-listed rather than passed through, the same rule the rest of the app
	follows: a caller can fix the address or the rider, and cannot reach in and
	rewrite the amount or the timestamps, which are records of what happened
	rather than fields anybody decides.
	"""
	if isinstance(values, str):
		values = frappe.parse_json(values)
	values = values or {}

	editable = (
		"customer",
		"customer_name",
		"rider",
		"rider_name",
		"rider_phone",
		"courier",
		"vehicle",
		"contact_phone",
		"address",
		"landmark",
		"map_location",
		"delivery_instructions",
		"delivery_date",
		"trip",
		# Editable here as well as through `set_delivery_status`, because the edit
		# sheet asks about the whole drop at once — a status corrected in the same
		# breath as an address should not need a second round trip. It still goes
		# through the doctype, so the timestamps and the dispatch notice behave
		# identically either way.
		"status",
	)

	doc = frappe.get_doc("Cosmestics Delivery", name)
	doc.check_permission("write")

	if "status" in values and values["status"] not in STATUSES:
		frappe.throw(_("{0} is not a delivery status").format(values["status"]))

	changed = []
	for field in editable:
		if field not in values:
			continue
		if doc.get(field) != values[field]:
			doc.set(field, values[field])
			changed.append(field)

	if changed:
		doc.save()

	return _delivery_row(doc) | {
		"changed": changed,
		"message": _("{0} updated").format(name) if changed else _("Nothing changed"),
	}


@frappe.whitelist(methods=["POST"])
def delete_delivery(name: str) -> dict:
	"""Remove a drop that should never have been recorded.

	A delivery is not a ledger entry — nothing is posted by raising one — so a
	duplicate typed in twice at a busy counter is rubbish on a worklist rather
	than a correction that has to be traceable. Deleting is the honest fix.

	One that has already gone out is a different matter: `dispatched_at` is a
	record of a rider leaving with a parcel and a message the customer has
	already received, and erasing it would leave the shop unable to answer where
	the goods went. Those are marked Failed instead, which is what the button
	beside this one does.
	"""
	doc = frappe.get_doc("Cosmestics Delivery", name)
	doc.check_permission("delete")

	if doc.dispatched_at or doc.status in ("Dispatched", "Delivered"):
		frappe.throw(
			_(
				"{0} has already gone out, so it cannot be deleted. Mark it failed "
				"instead — that keeps the record of where it went."
			).format(name)
		)

	frappe.delete_doc("Cosmestics Delivery", name)

	return {"name": name, "message": _("{0} deleted").format(name)}


@frappe.whitelist()
def get_delivery(name: str) -> dict:
	"""One drop, in full.

	The list already carries every field this returns — it is read fresh so the
	detail sheet cannot show a row that changed under it while the page sat
	open, which on a shared till is a matter of minutes.
	"""
	doc = frappe.get_doc("Cosmestics Delivery", name)
	doc.check_permission("read")
	return _delivery_row(doc) | {
		"owner": doc.owner,
		"creation": str(doc.creation),
		"modified": str(doc.modified),
	}


@frappe.whitelist()
def delivery_print_url(name: str, print_format: str | None = None) -> dict:
	"""The slip that gets taped to the carton.

	Rendered by ERPNext's print engine rather than drawn in the browser, for the
	same reason the receipt is: it carries the shop's letterhead and it matches
	what the desk would print for the same record. The shop asked for this to
	replace writing the address on the box by hand, so the format leads with the
	address and the rider rather than with document metadata — see
	`install.ensure_delivery_print_format`.
	"""
	if not frappe.db.exists("Cosmestics Delivery", name):
		frappe.throw(_("{0} not found").format(name), frappe.DoesNotExistError)
	frappe.get_doc("Cosmestics Delivery", name).check_permission("read")

	if not print_format:
		try:
			print_format = frappe.get_cached_doc("Cosmestics POS Settings").get(
				"delivery_print_format"
			)
		except Exception:
			print_format = None

	params = [
		f"doctype={quoted('Cosmestics Delivery')}",
		f"name={quoted(name)}",
		"trigger_print=1",
		"no_letterhead=0",
	]
	if print_format:
		params.append(f"format={quoted(print_format)}")

	return {
		"name": name,
		"url": get_url("/printview?" + "&".join(params)),
		"formats": frappe.get_all(
			"Print Format",
			filters={"doc_type": "Cosmestics Delivery", "disabled": 0},
			pluck="name",
			order_by="name asc",
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
