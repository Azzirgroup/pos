"""A place the shop delivers online orders to, and what that costs.

Checkout lists the enabled areas with their fee and delivery time; the fee is
added to the Sales Order as its own line. Pickup from the shop is always
offered and always free, so it is not an area.
"""

from frappe.model.document import Document


class CosmesticsDeliveryArea(Document):
	def validate(self):
		self.area_name = (self.area_name or "").strip()
		if (self.fee or 0) < 0:
			self.fee = 0
