"""Completing a sale at the till.

Creates a Sales Invoice with `is_pos=1` and `update_stock=1` — real-time stock
and GL on every sale, which is the model this shop chose over day-end
consolidation.

Order matters: neighbour-sourced lines must be purchased and received *before*
the invoice is submitted, otherwise there is no stock for the sale to draw down
and the submit fails on negative stock.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate, nowtime

WALK_IN_CUSTOMER = "Walk-in Customer"


@frappe.whitelist(methods=["POST"])
def submit_sale(
	items: list | str,
	payment: dict | str,
	customer: str | None = None,
	company: str | None = None,
):
	"""Turn a cart into a submitted Sales Invoice.

	`items`   — [{item_code, qty, rate, discount_pct, sourced: {supplier, buy_rate}}]
	`payment` — {method: cash|mpesa|card, tendered, change, reference}

	Returns {invoice, grand_total, change, paid_amount, purchases}.
	"""
	if isinstance(items, str):
		items = frappe.parse_json(items)
	if isinstance(payment, str):
		payment = frappe.parse_json(payment)

	if not items:
		frappe.throw(_("Cannot complete a sale with an empty cart"))

	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	company = company or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw(_("No company configured"))

	# 1. Buy the neighbour-sourced lines first so the stock exists.
	purchases = []
	sourced = [i for i in items if i.get("sourced")]
	if sourced:
		from cosmestics.api.sourcing import receive_from_neighbours

		result = receive_from_neighbours(
			lines=[
				{
					"item_code": i["item_code"],
					"qty": flt(i["qty"]),
					"buy_rate": flt(i["sourced"]["buy_rate"]),
					"supplier": i["sourced"]["supplier"],
				}
				for i in sourced
			],
			company=company,
		)
		purchases = result.get("invoices", [])

	# 2. The sale itself.
	invoice = _build_invoice(items, payment, customer, company, settings)

	return {
		"invoice": invoice.name,
		"grand_total": flt(invoice.grand_total),
		"paid_amount": flt(invoice.paid_amount),
		"change": flt(invoice.change_amount),
		"outstanding": flt(invoice.outstanding_amount),
		"purchases": purchases,
	}


def _build_invoice(items, payment, customer, company, settings):
	method = (payment or {}).get("method", "cash")
	is_credit = method == "credit"

	if is_credit and not customer:
		# The whole point of a credit sale is knowing who owes you.
		frappe.throw(_("Select a customer before completing a credit sale"))

	si = frappe.new_doc("Sales Invoice")
	si.company = company
	si.customer = customer or _walk_in_customer()
	si.posting_date = nowdate()
	# posting_time must be stamped explicitly. POS Closing Entry selects invoices
	# on TIMESTAMP(posting_date, posting_time) between the shift's start and end;
	# leaving the time unset puts the invoice at 00:00 and the shift never sees it.
	si.posting_time = nowtime()
	si.set_posting_time = 1
	si.update_stock = 1

	# A credit sale puts nothing in the drawer, so it is deliberately not a POS
	# invoice: it stays out of shift reconciliation and lives in the customer's
	# ledger as an outstanding balance instead. It is reported separately on the
	# closing screen so the cashier still sees it.
	si.is_pos = 0 if is_credit else 1

	if not is_credit:
		# Both fields are required for the shift to see the sale: POS Closing
		# Entry filters on owner + is_pos + pos_profile + the hidden
		# `is_created_using_pos` flag. Miss either and the shift reconciles
		# against zero sales while the invoices sit there looking correct.
		#
		# Only tagged when a shift is actually open — ERPNext refuses an invoice
		# flagged `is_created_using_pos` with no matching POS Opening Entry, and
		# a shop must never be unable to sell just because nobody opened a shift.
		# Such a sale is still a valid POS invoice, it simply reconciles nowhere.
		profile = _active_pos_profile()
		if profile:
			si.pos_profile = profile
			si.is_created_using_pos = 1

	if settings.selling_price_list:
		si.selling_price_list = settings.selling_price_list

	warehouse = settings.default_source_warehouse
	if warehouse:
		si.set_warehouse = warehouse

	for row in items:
		si.append(
			"items",
			{
				"item_code": row["item_code"],
				"qty": flt(row["qty"]),
				"rate": flt(row["rate"]),
				"discount_percentage": flt(row.get("discount_pct")),
				"warehouse": warehouse,
			},
		)

	si.set_missing_values()
	# Totals must be current before the payment row is sized against them.
	si.calculate_taxes_and_totals()

	if not is_credit:
		_attach_payment(si, payment, settings, company, customer)

	if payment.get("reference"):
		si.remarks = _("{0} ref: {1}").format(
			payment.get("method", "").upper(), payment["reference"]
		)

	si.insert()
	si.submit()
	return si


def _attach_payment(si, payment, settings, company, customer):
	"""Record how the customer actually paid.

	Supports three shapes:

	* one method for the whole bill (the common case)
	* split tender — several methods on one sale, via `parts`
	* partial payment — the parts total less than the bill, leaving an
	  outstanding balance on the customer's account

	Cash rows carry the *tendered* amount rather than the amount due, because
	ERPNext derives `change_amount` itself from `paid_amount` exceeding the
	total, and only when a payment row is of type Cash.
	"""
	total = flt(si.rounded_total or si.grand_total)
	parts = _payment_parts(payment, total)

	paid = 0.0
	has_cash = False

	for part in parts:
		mode = _mode_of_payment(part["method"], settings)
		amount = flt(part["amount"])
		if amount <= 0:
			continue

		if part["method"] == "cash":
			has_cash = True

		si.append(
			"payments",
			{
				"mode_of_payment": mode,
				"amount": amount,
				"account": _payment_account(mode, company),
				"reference_no": part.get("reference"),
			},
		)
		paid += amount

	if not si.get("payments"):
		frappe.throw(_("Enter at least one payment"))

	# Only meaningful when something is actually over-tendered in cash.
	if has_cash and paid > total:
		si.account_for_change_amount = frappe.get_cached_value(
			"Company", company, "default_cash_account"
		)

	if paid < total:
		_validate_partial(si, customer, total, paid)


def _payment_parts(payment, total) -> list:
	"""Normalise the payload into a list of {method, amount, reference}.

	`parts` is the split-tender form. A bare {method, tendered} is the single
	-method form and is upgraded here so the rest of the code has one shape to
	deal with.
	"""
	payment = payment or {}
	parts = payment.get("parts")

	if parts:
		return [
			{
				"method": p.get("method", "cash"),
				"amount": flt(p.get("amount")),
				"reference": p.get("reference"),
			}
			for p in parts
		]

	method = payment.get("method", "cash")
	tendered = flt(payment.get("tendered"))
	# Cash may be over-tendered (change follows); other methods settle exactly.
	amount = tendered if method == "cash" and tendered > 0 else total

	return [{"method": method, "amount": amount, "reference": payment.get("reference")}]


def _validate_partial(si, customer, total, paid):
	"""A part-paid sale is a debt, so it needs someone to owe it and a profile
	that permits it. ERPNext raises PartialPaymentValidationError otherwise, and
	its message does not say where to turn the setting on."""
	if not customer:
		frappe.throw(
			_("{0} of {1} is unpaid. Select a customer — someone has to owe the balance.").format(
				frappe.format_value(total - paid, {"fieldtype": "Currency"}),
				frappe.format_value(total, {"fieldtype": "Currency"}),
			)
		)

	if si.pos_profile and not frappe.db.get_value(
		"POS Profile", si.pos_profile, "allow_partial_payment"
	):
		frappe.throw(
			_(
				"Partial payment is not enabled for POS Profile {0}. "
				"Tick 'Allow Partial Payment' on it to accept part-payments."
			).format(si.pos_profile)
		)


def _mode_of_payment(method, settings) -> str:
	mapping = {
		"cash": settings.mode_cash,
		"mpesa": settings.mode_mpesa,
		"card": settings.mode_card,
	}
	mode = mapping.get(method)
	if not mode:
		frappe.throw(
			_("No Mode of Payment mapped for {0}. Set it in Cosmestics POS Settings.").format(
				method
			)
		)
	return mode


def _payment_account(mode, company) -> str | None:
	account = frappe.db.get_value(
		"Mode of Payment Account", {"parent": mode, "company": company}, "default_account"
	)
	return account or frappe.db.get_value("Company", company, "default_cash_account")


def _active_pos_profile() -> str | None:
	"""POS Profile of the user's open shift, if any."""
	return frappe.db.get_value(
		"POS Opening Entry",
		{"user": frappe.session.user, "docstatus": 1, "status": "Open"},
		"pos_profile",
	)


def _walk_in_customer() -> str:
	"""Most sales have no named customer, so one is kept for the till."""
	if frappe.db.exists("Customer", WALK_IN_CUSTOMER):
		return WALK_IN_CUSTOMER

	doc = frappe.new_doc("Customer")
	doc.customer_name = WALK_IN_CUSTOMER
	doc.customer_type = "Individual"
	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	if group:
		doc.customer_group = group
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	if territory:
		doc.territory = territory
	doc.insert(ignore_permissions=True)
	return doc.name
