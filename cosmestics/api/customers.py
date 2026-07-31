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

	# One query for every balance on screen. This used to run one per customer,
	# and the search behind it fires as the cashier types — twenty round trips
	# per keystroke, at a counter, on a shop's connection.
	owed = _outstanding_for([r["name"] for r in rows])
	for row in rows:
		row["outstanding"] = owed.get(row["name"], 0)

	return rows


def _outstanding_for(customers) -> dict:
	"""What each of several customers owes, in one query.

	Grouped in SQL rather than fetched per customer: the caller is a
	search-as-you-type box, so the per-customer version turned every keystroke
	into as many round trips as there were results.

	Customers with nothing outstanding are simply absent from the result — the
	caller defaults them to zero, which is the same answer without a row.
	"""
	if not customers:
		return {}

	placeholders = ", ".join(["%s"] * len(customers))
	rows = frappe.db.sql(
		f"""select customer, sum(outstanding_amount) as owed
		    from `tabSales Invoice`
		    where docstatus = 1 and outstanding_amount > 0
		      and customer in ({placeholders})
		    group by customer""",
		tuple(customers),
		as_dict=True,
	)
	return {r.customer: flt(r.owed) for r in rows}


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


@frappe.whitelist()
def ledger(customer: str, days: int = 365) -> dict:
	"""One customer's account: what they were billed, what they paid, what is left.

	Read from GL Entry rather than from invoices, so a payment, a credit note, a
	journal adjustment and an opening balance all appear — anything that moved
	the customer's balance shows up here, which is the whole point of a ledger. A
	statement built from Sales Invoices alone silently omits the payments and
	then disagrees with the outstanding figure beside it.

	The running balance is carried forward from before the window, so the closing
	figure is the real one even when only the last month is shown.
	"""
	from frappe.utils import add_days, cint, flt, nowdate

	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("{0} does not exist").format(customer), frappe.DoesNotExistError)

	days = cint(days)
	start = add_days(nowdate(), -days) if days > 0 else None

	conditions = ["gle.is_cancelled = 0", "gle.party_type = 'Customer'", "gle.party = %(customer)s"]
	values = {"customer": customer, "start": start}

	company = frappe.defaults.get_global_default("company")
	if company:
		conditions.append("gle.company = %(company)s")
		values["company"] = company

	where = " and ".join(conditions)

	# Everything before the window, collapsed into one opening figure.
	opening = 0.0
	if start:
		row = frappe.db.sql(
			f"""select sum(gle.debit) - sum(gle.credit) as balance
			    from `tabGL Entry` gle
			    where {where} and gle.posting_date < %(start)s""",
			values,
			as_dict=True,
		)[0]
		opening = flt(row.balance)

	rows = frappe.db.sql(
		f"""select gle.posting_date, gle.voucher_type, gle.voucher_no,
		           gle.debit, gle.credit, gle.remarks
		    from `tabGL Entry` gle
		    where {where} {"and gle.posting_date >= %(start)s" if start else ""}
		    order by gle.posting_date asc, gle.creation asc""",
		values,
		as_dict=True,
	)

	balance = opening
	entries = []
	for r in rows:
		balance += flt(r.debit) - flt(r.credit)
		entries.append(
			{
				"posting_date": str(r.posting_date),
				"voucher_type": r.voucher_type,
				"voucher_no": r.voucher_no,
				"billed": flt(r.debit),
				"paid": flt(r.credit),
				"balance": balance,
			}
		)

	return {
		"customer": customer,
		"customer_name": frappe.db.get_value("Customer", customer, "customer_name") or customer,
		"mobile_no": frappe.db.get_value("Customer", customer, "mobile_no"),
		"opening": opening,
		"closing": balance,
		"columns": [
			{"label": _("Date"), "key": "posting_date", "type": "text"},
			{"label": _("Type"), "key": "voucher_type", "type": "text"},
			{"label": _("Document"), "key": "voucher_no", "type": "text"},
			{"label": _("Billed"), "key": "billed", "type": "currency"},
			{"label": _("Paid"), "key": "paid", "type": "currency"},
			{"label": _("Balance"), "key": "balance", "type": "currency"},
		],
		"rows": entries,
		"period": {"from": str(start) if start else None, "to": nowdate(), "days": days},
	}
