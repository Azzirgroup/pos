"""Customer lookup for the till.

Only needed for credit sales and loyalty; a cash sale stays anonymous. Kept
small on purpose — the search runs on every keystroke in the customer sheet.
"""

import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def search(query: str | None = None, limit: int = 20):
	"""Match on name or phone, with each customer's current balance owed.

	The balance is the number that matters at the counter: it is what tells the
	cashier whether to extend more credit.
	"""
	query = (query or "").strip()

	filters = {"disabled": 0}
	or_filters = None
	if query:
		or_filters = {
			"name": ("like", f"%{query}%"),
			"customer_name": ("like", f"%{query}%"),
			"mobile_no": ("like", f"%{query}%"),
		}

	rows = frappe.get_all(
		"Customer",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "customer_name", "mobile_no"],
		limit_page_length=int(limit),
		order_by="modified desc",
	)

	for row in rows:
		row["outstanding"] = _outstanding(row["name"])

	return rows


def _outstanding(customer) -> float:
	"""Aggregated in raw SQL: Frappe rejects function strings like
	`sum(outstanding_amount)` in `get_all`/`get_value` fields, and a customer can
	have too many invoices to want them all pulled into Python."""
	value = frappe.db.sql(
		"""select sum(outstanding_amount) from `tabSales Invoice`
		   where customer = %s and docstatus = 1 and outstanding_amount > 0""",
		customer,
	)
	return flt(value[0][0] if value and value[0] else 0)


@frappe.whitelist(methods=["POST"])
def create(customer_name: str, mobile_no: str | None = None):
	"""Create a customer mid-sale, with as little ceremony as possible."""
	customer_name = (customer_name or "").strip()
	if not customer_name:
		frappe.throw(_("Customer name is required"))

	if frappe.db.exists("Customer", customer_name):
		return {"name": customer_name, "customer_name": customer_name, "outstanding": _outstanding(customer_name)}

	doc = frappe.new_doc("Customer")
	doc.customer_name = customer_name
	doc.customer_type = "Individual"
	doc.mobile_no = mobile_no

	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	if group:
		doc.customer_group = group
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	if territory:
		doc.territory = territory

	doc.insert(ignore_permissions=True)

	return {
		"name": doc.name,
		"customer_name": doc.customer_name,
		"mobile_no": doc.mobile_no,
		"outstanding": 0.0,
	}
