"""Several orders going out on one run.

ERPNext's own Delivery Trip exists for exactly this, but its stops point at
Delivery Notes — a document this shop never raises, since a POS sale posts a
Sales Invoice with stock already deducted. Mapping a Delivery Note off that
invoice just to satisfy the link would very likely deduct the same stock a
second time, since the invoice already moved it. This is a plain custom
doctype instead, holding invoices directly, so there is no double-deduction
risk to reason about.

Kept deliberately simple: this is a logistics record — who took what out, and
whether it made it — not an accounting one. It touches no stock and no
ledger; the Sales Invoices attached to it already carry both.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class CosmesticsDeliveryTrip(Document):
	def validate(self):
		if not self.invoices:
			frappe.throw(_("Add at least one invoice to the trip"))

		seen = set()
		total = 0
		for row in self.invoices:
			if row.sales_invoice in seen:
				frappe.throw(_("{0} is on this trip twice").format(row.sales_invoice))
			seen.add(row.sales_invoice)

			docstatus = frappe.db.get_value("Sales Invoice", row.sales_invoice, "docstatus")
			if docstatus is None:
				frappe.throw(_("{0} is not a Sales Invoice").format(row.sales_invoice))
			if docstatus != 1:
				frappe.throw(_("{0} is not submitted").format(row.sales_invoice))

			total += flt(row.amount)

		self.total_amount = total

	def on_submit(self):
		# Draft is what a trip is called before it leaves; submitting is the
		# driver actually pulling out, so the status should say so without a
		# separate click.
		if self.status == "Draft":
			self.db_set("status", "Dispatched")

	def on_cancel(self):
		self.db_set("status", "Cancelled")


@frappe.whitelist()
def mark_delivered(name: str, invoice: str, delivered: int = 1):
	"""Tick one stop off, without opening the whole trip to edit it.

	A driver or manager updating progress mid-run needs this to be one tap,
	not a form. `ignore_permissions` is not used — the caller must be able to
	write to the trip, same as editing it any other way.
	"""
	doc = frappe.get_doc("Cosmestics Delivery Trip", name)
	doc.check_permission("write")

	row = next((r for r in doc.invoices if r.sales_invoice == invoice), None)
	if not row:
		frappe.throw(_("{0} is not on this trip").format(invoice))

	row.delivered = 1 if int(delivered) else 0
	row.db_update()

	if doc.invoices and all(r.delivered for r in doc.invoices) and doc.docstatus == 1:
		doc.db_set("status", "Completed")
	elif doc.status == "Completed" and not all(r.delivered for r in doc.invoices):
		doc.db_set("status", "Dispatched")

	return {"name": name, "invoice": invoice, "delivered": bool(row.delivered), "status": doc.status}
