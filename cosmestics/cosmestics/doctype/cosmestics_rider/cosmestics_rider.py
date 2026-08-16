"""Whoever actually carries the goods to the customer.

A tiny master, and deliberately its own rather than a Link to Supplier or
Employee. A boda rider a shop uses three times a week is neither: making one a
Supplier puts a person into the purchasing ledger who will never be billed, and
making one an Employee needs a company, a joining date and a payroll answer the
shop does not have. All the till needs is a name, a number and who they ride
for, kept somewhere it can be picked from a list instead of retyped — a phone
number typed from memory at a counter is the one field on a delivery that
silently fails.
"""

import frappe
from frappe.model.document import Document


class CosmesticsRider(Document):
	def validate(self):
		self.rider_name = (self.rider_name or "").strip()
		self.phone = (self.phone or "").strip() or None
		self.courier = (self.courier or "").strip() or None


@frappe.whitelist()
def search_riders(search: str | None = None, limit: int = 20) -> list:
	"""Riders the till can hand a delivery to.

	Disabled ones are left out: the point of the flag is that they stop being
	offered, while the deliveries they already made keep pointing at them.
	"""
	filters = {"disabled": 0}
	or_filters = None
	if search:
		or_filters = [
			{"rider_name": ("like", f"%{search}%")},
			{"phone": ("like", f"%{search}%")},
			{"courier": ("like", f"%{search}%")},
		]

	rows = frappe.get_all(
		"Cosmestics Rider",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "rider_name", "phone", "courier", "vehicle"],
		order_by="modified desc",
		limit_page_length=min(max(int(limit or 20), 1), 50),
	)
	return [
		{
			"value": r.name,
			# The number is the half a cashier is checking they picked the right
			# person by — two riders called John is the ordinary case.
			"label": " · ".join(filter(None, [r.rider_name, r.phone, r.courier])),
			"rider_name": r.rider_name,
			"phone": r.phone,
			"courier": r.courier,
			"vehicle": r.vehicle,
		}
		for r in rows
	]


@frappe.whitelist(methods=["POST"])
def create_rider(
	rider_name: str, phone: str | None = None, courier: str | None = None, vehicle: str | None = None
) -> dict:
	"""Add a rider from the till, mid-sale.

	The customer is standing there and the rider is outside; sending the cashier
	to a back-office screen to create the record first is how the field ends up
	blank instead.
	"""
	rider_name = (rider_name or "").strip()
	if not rider_name:
		frappe.throw(frappe._("Name the rider"))

	if frappe.db.exists("Cosmestics Rider", rider_name):
		doc = frappe.get_doc("Cosmestics Rider", rider_name)
		# Filling in blanks rather than overwriting: somebody re-adding a rider
		# who already exists is supplying detail, not correcting it.
		if phone and not doc.phone:
			doc.phone = phone
		if courier and not doc.courier:
			doc.courier = courier
		if vehicle and not doc.vehicle:
			doc.vehicle = vehicle
		doc.save()
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Cosmestics Rider",
				"rider_name": rider_name,
				"phone": phone,
				"courier": courier,
				"vehicle": vehicle,
			}
		)
		doc.insert()

	return {
		"value": doc.name,
		"label": " · ".join(filter(None, [doc.rider_name, doc.phone, doc.courier])),
		"rider_name": doc.rider_name,
		"phone": doc.phone,
		"courier": doc.courier,
		"vehicle": doc.vehicle,
	}
