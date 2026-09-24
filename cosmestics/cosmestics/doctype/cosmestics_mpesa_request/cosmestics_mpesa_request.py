"""One M-Pesa payment prompt sent to a customer's phone for an online order.

The audit trail for every STK push: what was asked, what Safaricom answered,
and — once paid — the receipt that the Sales Order's Payment Entry carries.
Written by `cosmestics.api.shop_payments`; not meant to be edited by hand.
"""

from frappe.model.document import Document


class CosmesticsMpesaRequest(Document):
	pass
