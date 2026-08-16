"""One order going to one address.

Distinct from `Cosmestics Delivery Trip`, which is the *run* — a driver, a van
and several stops. This is the drop itself: who it goes to, where, which rider
has it, and where it has got to. A shop tracking "what is going out today" is
asking about drops, not runs, and a child row on a trip cannot be listed,
filtered or printed on its own.

Not submittable, on purpose. The whole life of a delivery is its status moving
Pending → Dispatched → Delivered (or Failed), and a submitted document that must
still change is a document that needs `allow_on_submit` on every field it has.
Nothing here touches stock or a ledger — the Sales Invoice behind it already
did both — so there is nothing a docstatus would be protecting.

## The dispatch timestamp

`dispatched_at` is stamped here, from the transition, and is read-only
everywhere else. That is the field the shop actually asked for: a time typed in
afterwards is the time somebody remembered, and the reason to record a dispatch
at all is to be able to say how long a drop took.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

#: The order a delivery moves through. Anything else is refused rather than
#: guessed at — the list view is only useful if the words mean one thing.
STATUSES = ("Pending", "Dispatched", "Delivered", "Failed")


class CosmesticsDelivery(Document):
	def validate(self):
		self.stamp_status_times()
		self.fill_from_invoice()

	def stamp_status_times(self):
		"""Times follow the status, never the other way round.

		Set on the way *in* to a state and deliberately not cleared on the way
		out: a delivery moved back to Pending because the rider came back still
		left at the time it says it left, and losing that is losing the only
		record of the first attempt.
		"""
		if self.status == "Dispatched" and not self.dispatched_at:
			self.dispatched_at = now_datetime()

		if self.status == "Delivered":
			# A drop that is marked delivered without ever having been marked
			# dispatched still left the shop — the cashier simply updated it once
			# rather than twice.
			if not self.dispatched_at:
				self.dispatched_at = now_datetime()
			if not self.delivered_at:
				self.delivered_at = now_datetime()

	def fill_from_invoice(self):
		"""Carry across what the sale already knows.

		Only into blanks. The address on the delivery is the one the customer
		gave at the counter, and it is routinely not the one on their record —
		overwriting it from the invoice would quietly send the parcel to the
		wrong place.
		"""
		if not self.sales_invoice:
			return

		invoice = frappe.db.get_value(
			"Sales Invoice",
			self.sales_invoice,
			["customer", "customer_name", "grand_total", "company"],
			as_dict=True,
		)
		if not invoice:
			return

		self.customer = self.customer or invoice.customer
		self.customer_name = self.customer_name or invoice.customer_name or invoice.customer
		self.company = self.company or invoice.company
		# Always the invoice's, since it is a read-only mirror of it rather than
		# something anybody types.
		self.amount = invoice.grand_total

	def on_update(self):
		"""Tell the customer and the manager when it goes out.

		Best-effort and after the write, exactly like the material-request
		notice: a bridge that is asleep must never stop a rider leaving. The
		flag is set inside the same transaction so a save that is retried does
		not send the message twice.
		"""
		if self.status != "Dispatched":
			return
		if self.get("_dispatch_notified"):
			return

		previous = self.get_doc_before_save()
		if previous and previous.status == "Dispatched":
			return

		self._dispatch_notified = True

		from cosmestics.api.notifications import queue_delivery_dispatch_notice

		queue_delivery_dispatch_notice(self.name)
