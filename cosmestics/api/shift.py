"""Opening and closing a till shift.

Uses ERPNext's own POS Opening Entry / POS Closing Entry rather than a custom
doctype, so the shift shows up in standard reports and the accounting team sees
what they expect.

This works with `is_pos=1` Sales Invoices because ERPNext's `get_invoices`
always queries Sales Invoice (POS Invoice is only added when POS Settings says
so). The catch is `build_invoice_query`, which filters on `owner`, `is_pos`,
*and* `pos_profile` — so every invoice the till writes must carry the profile of
the shift it belongs to, or the closing entry will find nothing.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowdate


@frappe.whitelist()
def get_profiles():
	"""POS Profiles this user is allowed to open a shift on.

	Falls back to every enabled profile for the company when no explicit user
	mapping exists — a one-till shop should not have to configure that.
	"""
	user = frappe.session.user
	company = frappe.defaults.get_user_default("Company")

	allowed = frappe.get_all(
		"POS Profile User", filters={"user": user, "parenttype": "POS Profile"}, pluck="parent"
	)

	filters = {"disabled": 0}
	if company:
		filters["company"] = company
	if allowed:
		filters["name"] = ("in", allowed)

	return frappe.get_all("POS Profile", filters=filters, fields=["name", "company"])


@frappe.whitelist()
def get_open_shift():
	"""The user's currently open shift, with its opening floats. None if closed."""
	name = frappe.db.get_value(
		"POS Opening Entry",
		{"user": frappe.session.user, "docstatus": 1, "status": "Open"},
		"name",
	)
	if not name:
		return None

	doc = frappe.get_doc("POS Opening Entry", name)
	return {
		"name": doc.name,
		"pos_profile": doc.pos_profile,
		"company": doc.company,
		"period_start_date": str(doc.period_start_date),
		"balances": [
			{"mode_of_payment": b.mode_of_payment, "opening_amount": flt(b.opening_amount)}
			for b in doc.balance_details
		],
	}


@frappe.whitelist(methods=["POST"])
def open_shift(pos_profile: str, balances: list | str | None = None):
	"""Start a shift with the cash float already in the drawer."""
	if isinstance(balances, str):
		balances = frappe.parse_json(balances)

	existing = get_open_shift()
	if existing:
		frappe.throw(
			_("You already have an open shift ({0}). Close it before starting another.").format(
				existing["name"]
			)
		)

	company = frappe.db.get_value("POS Profile", pos_profile, "company")
	if not company:
		frappe.throw(_("{0} is not a valid POS Profile").format(pos_profile))

	doc = frappe.new_doc("POS Opening Entry")
	doc.pos_profile = pos_profile
	doc.company = company
	doc.user = frappe.session.user
	doc.period_start_date = now_datetime()
	doc.posting_date = nowdate()

	for row in balances or _default_balances(pos_profile):
		doc.append(
			"balance_details",
			{
				"mode_of_payment": row["mode_of_payment"],
				"opening_amount": flt(row.get("opening_amount")),
			},
		)

	if not doc.balance_details:
		frappe.throw(_("Add at least one payment mode to open a shift"))

	doc.insert()
	doc.submit()

	return get_open_shift()


def _default_balances(pos_profile):
	"""Seed the opening screen from the profile's configured payment modes."""
	modes = frappe.get_all(
		"POS Payment Method", filters={"parent": pos_profile}, pluck="mode_of_payment"
	)
	if not modes:
		settings = frappe.get_cached_doc("Cosmestics POS Settings")
		modes = [m for m in (settings.mode_cash, settings.mode_mpesa, settings.mode_card) if m]
	return [{"mode_of_payment": m, "opening_amount": 0} for m in modes]


@frappe.whitelist()
def get_closing_summary():
	"""What the till *should* hold right now, per payment mode.

	Expected = opening float + everything taken on that mode this shift. The
	cashier counts the drawer against this; the difference is the whole point of
	the exercise.
	"""
	shift = get_open_shift()
	if not shift:
		frappe.throw(_("No open shift"))

	from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import get_invoices

	end = now_datetime()
	data = get_invoices(
		start=shift["period_start_date"],
		end=end,
		pos_profile=shift["pos_profile"],
		user=frappe.session.user,
	)

	opening = {b["mode_of_payment"]: flt(b["opening_amount"]) for b in shift["balances"]}
	taken = {p["mode_of_payment"]: flt(p["amount"]) for p in data.get("payments", [])}

	rows = []
	for mode in {*opening, *taken}:
		open_amt = opening.get(mode, 0)
		rows.append(
			{
				"mode_of_payment": mode,
				"opening_amount": open_amt,
				"taken": taken.get(mode, 0),
				"expected_amount": open_amt + taken.get(mode, 0),
			}
		)
	rows.sort(key=lambda r: r["mode_of_payment"])

	invoices = data.get("invoices", [])

	return {
		"shift": shift,
		"period_end": str(end),
		"rows": rows,
		"invoice_count": len(invoices),
		"grand_total": sum(flt(i.get("grand_total")) for i in invoices),
		"total_quantity": sum(flt(i.get("total_qty")) for i in invoices),
		# Credit sales never touch the drawer, so they are excluded from the
		# expected amounts above and reported separately for visibility.
		"credit": _credit_summary(shift["period_start_date"], end),
	}


def _credit_summary(start, end):
	"""Unpaid sales taken during this shift.

	Aggregated in Python rather than SQL: Frappe rejects function strings like
	`count(name)` in `get_all` fields, and a shift has few enough credit sales
	that fetching them is cheaper than fighting the query builder.

	Windowed on `creation`, not `posting_date` — posting_date is a date, so it
	cannot distinguish two shifts on the same day.
	"""
	rows = frappe.get_all(
		"Sales Invoice",
		filters={
			"owner": frappe.session.user,
			"docstatus": 1,
			"is_pos": 0,
			"creation": ("between", [start, end]),
		},
		fields=["name", "customer", "grand_total", "outstanding_amount"],
	)

	return {
		"count": len(rows),
		"total": flt(sum(flt(r.grand_total) for r in rows)),
		"outstanding": flt(sum(flt(r.outstanding_amount) for r in rows)),
		"invoices": [
			{"name": r.name, "customer": r.customer, "outstanding": flt(r.outstanding_amount)}
			for r in rows
		],
	}


@frappe.whitelist(methods=["POST"])
def close_shift(counted: list | str | None = None):
	"""Close the shift against what the cashier physically counted.

	`counted` is [{mode_of_payment, closing_amount}]. Anything not counted is
	assumed to match expectation, so a quiet till closes in one tap.
	"""
	if isinstance(counted, str):
		counted = frappe.parse_json(counted)

	from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import (
		make_closing_entry_from_opening,
	)

	shift = get_open_shift()
	if not shift:
		frappe.throw(_("No open shift"))

	counted_map = {c["mode_of_payment"]: flt(c.get("closing_amount")) for c in (counted or [])}

	# ERPNext's own builder: it gathers the shift's invoices, totals, taxes and
	# per-mode payment rows. Reimplementing that by hand would drift from what
	# the standard POS reports expect.
	opening = frappe.get_doc("POS Opening Entry", shift["name"])
	doc = make_closing_entry_from_opening(opening)
	doc.posting_date = nowdate()
	doc.posting_time = now_datetime().strftime("%H:%M:%S")

	# It leaves opening_amount at 0, so the floats are overlaid here. ERPNext's
	# convention (pos_closing_entry.js) is expected = opening + taken.
	floats = {b.mode_of_payment: flt(b.opening_amount) for b in opening.balance_details}
	rows = {r.mode_of_payment: r for r in doc.payment_reconciliation}

	for mode, amount in floats.items():
		if mode not in rows:
			# A mode with a float but no sales still has to be counted.
			rows[mode] = doc.append(
				"payment_reconciliation",
				{"mode_of_payment": mode, "opening_amount": 0, "expected_amount": 0},
			)

	for mode, row in rows.items():
		row.opening_amount = floats.get(mode, 0)
		row.expected_amount = flt(row.expected_amount) + row.opening_amount
		row.closing_amount = counted_map.get(mode, row.expected_amount)
		row.difference = flt(row.closing_amount) - flt(row.expected_amount)

	doc.insert()
	doc.submit()

	return {
		"name": doc.name,
		"status": doc.status,
		"grand_total": flt(doc.grand_total),
		"difference": sum(flt(r.difference) for r in doc.payment_reconciliation),
	}
