"""One line of an online order's history: which status, from when, and who
moved it there. The next line's time is when it left — that difference is
what the customer's tracking page shows as time spent in each stage."""

from frappe.model.document import Document


class CosmesticsOrderStatusLog(Document):
	pass
