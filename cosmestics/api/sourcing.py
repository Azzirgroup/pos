"""Buying from a neighbouring shop to complete a sale the shelf cannot.

The customer is at the counter, so this has to be quick and it has to be
correct: the goods are genuinely purchased and resold, which means a real
purchase document, a real cost, and therefore a real margin.

A Purchase Invoice with `update_stock=1` is used rather than a Purchase
Receipt. One document both receives the stock (so the sale can consume it) and
books what is owed to the neighbour. A Purchase Receipt alone would leave the
goods "received but not billed" and the payable invisible.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate


@frappe.whitelist(methods=["POST"])
def receive_from_neighbours(lines: list | str, company: str | None = None, paid: int = 0):
	"""Receive neighbour-sourced goods so the POS sale can be completed.

	`lines` is a list of {item_code, qty, buy_rate, supplier}. One invoice is
	created per supplier — you settle with each shop separately.

	Must be called *before* the sale is submitted, otherwise the Sales Invoice
	has no stock to draw down.
	"""
	if isinstance(lines, str):
		lines = frappe.parse_json(lines)

	if not lines:
		return {"invoices": []}

	company = company or frappe.defaults.get_user_default("Company")
	warehouse = _sourcing_warehouse(company)

	by_supplier = {}
	for row in lines:
		supplier = row.get("supplier")
		if not supplier:
			frappe.throw(_("Every sourced line needs a supplier"))
		by_supplier.setdefault(supplier, []).append(row)

	created = []
	for supplier, rows in by_supplier.items():
		created.append(_make_purchase_invoice(supplier, rows, company, warehouse, paid))

	# Paying the neighbour in cash empties the drawer by exactly this much, and
	# nothing in the sales figures says so. Recorded against the shift so the
	# closing count is measured against what should actually be there.
	movements = _record_till_payments(created) if int(paid or 0) else []

	return {"invoices": created, "movements": movements}


def _record_till_payments(invoices):
	"""Tell the open shift that cash went out of the drawer for these invoices.

	Silent when no shift is open: sourcing has to work at a counter that has not
	opened one, and refusing the purchase to protect a reconciliation nobody is
	doing would block the sale that prompted it.
	"""
	from cosmestics.api.shift import get_open_shift, record_movement

	if not get_open_shift():
		return []

	recorded = []
	for inv in invoices:
		if flt(inv.get("total")) <= 0:
			continue
		try:
			recorded.append(
				record_movement(
					movement_type="Neighbour Purchase",
					amount=flt(inv["total"]),
					party=inv["supplier"],
					reason=_("Paid {0} for {1}").format(inv["supplier"], inv["name"]),
				)
			)
		except Exception:
			# The goods and the payable are already posted and the customer is
			# waiting. A drawer figure that has to be corrected at closing is a
			# far smaller problem than a sale that fails here.
			frappe.log_error(
				f"Could not record the till movement for {inv['name']}", "Cosmestics POS"
			)

	return recorded


def _make_purchase_invoice(supplier, rows, company, warehouse, paid):
	_ensure_supplier(supplier)

	pi = frappe.new_doc("Purchase Invoice")
	pi.supplier = supplier
	pi.company = company
	pi.posting_date = nowdate()
	pi.set_posting_time = 1
	# Receives stock and books the payable in a single submit.
	pi.update_stock = 1
	pi.set_warehouse = warehouse
	pi.remarks = _("Sourced at the till to complete a walk-in sale")

	for row in rows:
		qty = flt(row.get("qty"))
		rate = flt(row.get("buy_rate"))
		if qty <= 0:
			continue
		pi.append(
			"items",
			{
				"item_code": row.get("item_code"),
				"qty": qty,
				"rate": rate,
				"warehouse": warehouse,
			},
		)

	if not pi.items:
		frappe.throw(_("No sourced lines with a quantity above zero"))

	# Left unpaid by default. Sourcing happens with a customer at the counter,
	# and whether the cashier actually handed money over next door — or the two
	# shops settle at the end of the week, which is the usual arrangement — is
	# not something the till can know. Booking it as paid invented a cash
	# movement that never appeared in the drawer, so the payable now stands until
	# somebody records the payment against it.
	if int(paid or 0):
		pi.is_paid = 1
		pi.mode_of_payment = _default_mode_of_payment(company)
		pi.cash_bank_account = _paid_from_account(company, pi.mode_of_payment)

	pi.insert()
	pi.submit()

	return {"name": pi.name, "supplier": supplier, "total": flt(pi.grand_total)}


def _ensure_supplier(supplier):
	"""Make sure the shop we just bought from exists as a Supplier.

	Created rather than refused. The customer is at the counter and the goods
	have already changed hands — refusing the purchase because nobody had added
	the shop next door to a master list beforehand blocks a sale that has, in
	every practical sense, already happened.

	It lands in the neighbour group, which is where it belongs and where the till
	will offer it next time, so this fills the list in as the shop actually
	trades rather than demanding it be filled in up front.
	"""
	if frappe.db.exists("Supplier", supplier):
		return

	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	group = settings.neighbour_supplier_group or frappe.db.get_value(
		"Supplier Group", {"is_group": 0}, "name"
	)
	if not group:
		frappe.throw(
			_("{0} is not a supplier, and there is no supplier group to file it under.").format(
				supplier
			)
		)

	doc = frappe.new_doc("Supplier")
	doc.supplier_name = supplier
	doc.supplier_group = group
	doc.supplier_type = "Company"
	doc.insert(ignore_permissions=True)


def _sourcing_warehouse(company):
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	if settings.default_source_warehouse:
		return settings.default_source_warehouse

	warehouse = frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name"
	)
	if not warehouse:
		frappe.throw(_("Set a Sourcing Warehouse in Cosmestics POS Settings"))
	return warehouse


def _default_mode_of_payment(company):
	mode = frappe.db.get_value("Mode of Payment", {"type": "Cash", "enabled": 1}, "name")
	if not mode:
		frappe.throw(_("No enabled Cash mode of payment found"))
	return mode


def _paid_from_account(company, mode_of_payment):
	account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mode_of_payment, "company": company},
		"default_account",
	)
	if not account:
		account = frappe.db.get_value("Company", company, "default_cash_account")
	if not account:
		frappe.throw(
			_("Set a default account for {0} in {1}").format(mode_of_payment, company)
		)
	return account
