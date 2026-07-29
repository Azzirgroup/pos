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
		from cosmestics.api.pos import _mode_map

		settings = frappe.get_cached_doc("Cosmestics POS Settings")
		# Deduplicated: the M-Pesa channels fall back to the generic mode on a
		# site that has not split them out, and asking a cashier to count the
		# same drawer three times is worse than not asking at all.
		modes = list(dict.fromkeys(m for m in _mode_map(settings).values() if m))
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
	# Money that left the drawer without being a sale — a till expense, or cash
	# handed to the shop next door. Same arithmetic as the two terms above, in
	# the opposite direction.
	movements = _movements(shift["name"])
	paid_out = _paid_out_by_mode(movements)

	rows = []
	for mode in {*opening, *taken, *paid_out}:
		open_amt = opening.get(mode, 0)
		out_amt = paid_out.get(mode, 0)
		rows.append(
			{
				"mode_of_payment": mode,
				"opening_amount": open_amt,
				"taken": taken.get(mode, 0),
				"paid_out": out_amt,
				"expected_amount": open_amt + taken.get(mode, 0) - out_amt,
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
		# Already subtracted above; listed so the cashier can see what the
		# reduction is made of rather than being handed a smaller number.
		"movements": _movement_summary(movements),
		# Goods that arrived from next door during this shift. The unpaid ones are
		# a debt opened at this counter and are the reason this block exists.
		"neighbour": _neighbour_summary(shift["period_start_date"], end),
	}


def _movements(shift_name):
	"""Submitted till movements for a shift, newest first."""
	return frappe.get_all(
		"Cosmestics Shift Movement",
		filters={"shift": shift_name, "docstatus": 1},
		fields=[
			"name",
			"movement_type",
			"mode_of_payment",
			"amount",
			"person",
			"party",
			"reason",
			"expense_account",
			"reference_doctype",
			"reference_name",
			"creation",
		],
		order_by="creation desc",
	)


def _paid_out_by_mode(movements):
	"""Per mode, what these movements took out of the drawer.

	Shorts are excluded: a short is found by counting, so subtracting it from
	the expectation would make the count agree with itself and the discrepancy
	would vanish exactly when it is being recorded.
	"""
	from cosmestics.cosmestics.doctype.cosmestics_shift_movement.cosmestics_shift_movement import (
		PAID_OUT_TYPES,
	)

	out = {}
	for m in movements:
		if m.movement_type not in PAID_OUT_TYPES:
			continue
		out[m.mode_of_payment] = out.get(m.mode_of_payment, 0) + flt(m.amount)
	return out


def _movement_summary(movements):
	from cosmestics.cosmestics.doctype.cosmestics_shift_movement.cosmestics_shift_movement import (
		PAID_OUT_TYPES,
	)

	rows = [
		{
			"name": m.name,
			"movement_type": m.movement_type,
			"mode_of_payment": m.mode_of_payment,
			"amount": flt(m.amount),
			"person": m.person,
			"party": m.party,
			"reason": m.reason,
			"reference_doctype": m.reference_doctype,
			"reference_name": m.reference_name,
			"at": str(m.creation),
		}
		for m in movements
	]
	paid_out = [r for r in rows if r["movement_type"] in PAID_OUT_TYPES]
	shorts = [r for r in rows if r["movement_type"] == "Short"]

	return {
		"rows": rows,
		"count": len(rows),
		"paid_out_total": flt(sum(r["amount"] for r in paid_out)),
		"expense_total": flt(sum(r["amount"] for r in rows if r["movement_type"] == "Expense")),
		"neighbour_cash_total": flt(
			sum(r["amount"] for r in rows if r["movement_type"] == "Neighbour Purchase")
		),
		"shorts": shorts,
		"short_total": flt(sum(r["amount"] for r in shorts)),
	}


def _neighbour_summary(start, end):
	"""Purchases from neighbouring shops during this shift.

	Windowed on `creation` for the same reason as `_credit_summary`: posting_date
	is a date and cannot tell two shifts on the same day apart.

	Split by whether the neighbour has been paid. An unpaid purchase is a real
	liability opened at this counter and nothing else in the app surfaces it
	again; a paid one is cash out of the drawer, already subtracted from the
	expected amounts through its movement record.
	"""
	group = frappe.db.get_single_value("Cosmestics POS Settings", "neighbour_supplier_group")
	if not group:
		return {"count": 0, "unpaid_count": 0, "unpaid": 0, "paid": 0, "invoices": []}

	suppliers = frappe.get_all("Supplier", filters={"supplier_group": group}, pluck="name")
	if not suppliers:
		return {"count": 0, "unpaid_count": 0, "unpaid": 0, "paid": 0, "invoices": []}

	rows = frappe.get_all(
		"Purchase Invoice",
		filters={
			"supplier": ("in", suppliers),
			"docstatus": 1,
			# Scoped to this cashier, as `_credit_summary` is. A shift belongs to
			# one person, and another till's purchase from the same shop is not
			# something this drawer has to answer for.
			"owner": frappe.session.user,
			"creation": ("between", [start, end]),
		},
		fields=["name", "supplier", "grand_total", "outstanding_amount", "is_paid"],
		order_by="creation desc",
	)

	return {
		"count": len(rows),
		"unpaid_count": len([r for r in rows if flt(r.outstanding_amount) > 0]),
		"unpaid": flt(sum(flt(r.outstanding_amount) for r in rows)),
		"paid": flt(sum(flt(r.grand_total) - flt(r.outstanding_amount) for r in rows)),
		"invoices": [
			{
				"name": r.name,
				"supplier": r.supplier,
				"total": flt(r.grand_total),
				"outstanding": flt(r.outstanding_amount),
			}
			for r in rows
		],
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
def close_shift(counted: list | str | None = None, shorts: list | str | None = None):
	"""Close the shift against what the cashier physically counted.

	`counted` is [{mode_of_payment, closing_amount}]. Anything not counted is
	assumed to match expectation, so a quiet till closes in one tap.

	`shorts` is [{mode_of_payment, person, reason}] — who each shortfall is
	against. ERPNext's closing entry books the difference but has nowhere to put
	a name, and a shortfall nobody is named on is a number nobody can act on.
	Recorded after the entry submits, so a rejected close leaves no orphan
	attribution behind.
	"""
	if isinstance(counted, str):
		counted = frappe.parse_json(counted)
	if isinstance(shorts, str):
		shorts = frappe.parse_json(shorts)

	from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import (
		make_closing_entry_from_opening,
	)

	shift = get_open_shift()
	if not shift:
		frappe.throw(_("No open shift"))

	counted_map = {c["mode_of_payment"]: flt(c.get("closing_amount")) for c in (counted or [])}
	# Cash already taken out of the drawer this shift. ERPNext's builder only
	# knows about sales, so without this the expected amount would ask the
	# cashier to produce money that was legitimately spent hours ago.
	paid_out = _paid_out_by_mode(_movements(shift["name"]))

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

	for mode in {*floats, *paid_out}:
		if mode not in rows:
			# A mode with a float, or money paid out of it, still has to be
			# counted even if nothing was sold on it.
			rows[mode] = doc.append(
				"payment_reconciliation",
				{"mode_of_payment": mode, "opening_amount": 0, "expected_amount": 0},
			)

	for mode, row in rows.items():
		row.opening_amount = floats.get(mode, 0)
		row.expected_amount = flt(row.expected_amount) + row.opening_amount - paid_out.get(mode, 0)
		row.closing_amount = counted_map.get(mode, row.expected_amount)
		row.difference = flt(row.closing_amount) - flt(row.expected_amount)

	doc.insert()
	doc.submit()

	attributed = _record_shorts(shift, doc, shorts)

	return {
		"name": doc.name,
		"status": doc.status,
		"grand_total": flt(doc.grand_total),
		"difference": sum(flt(r.difference) for r in doc.payment_reconciliation),
		"paid_out": flt(sum(paid_out.values())),
		"shorts_recorded": attributed,
	}


def _record_shorts(shift, closing, shorts):
	"""Put a name against each shortfall the cashier attributed.

	Only shortfalls: an overage is not somebody's debt, and asking who a surplus
	belongs to would invite a guess. Only modes that are actually short are
	recorded, so a name typed against a mode that then balanced is dropped
	rather than filed as a debt that does not exist.
	"""
	if not shorts:
		return []

	by_mode = {
		r.mode_of_payment: flt(r.difference)
		for r in closing.payment_reconciliation
		if flt(r.difference) < 0
	}

	recorded = []
	for entry in shorts:
		mode = entry.get("mode_of_payment")
		person = (entry.get("person") or "").strip()
		if not person or mode not in by_mode:
			continue

		doc = frappe.new_doc("Cosmestics Shift Movement")
		doc.shift = shift["name"]
		doc.movement_type = "Short"
		doc.mode_of_payment = mode
		doc.amount = abs(by_mode[mode])
		doc.person = person
		doc.reason = entry.get("reason") or _("Shortfall on {0}").format(closing.name)
		doc.reference_doctype = "POS Closing Entry"
		doc.reference_name = closing.name
		doc.insert()
		doc.submit()
		recorded.append(
			{"name": doc.name, "mode_of_payment": mode, "amount": flt(doc.amount), "person": person}
		)

	return recorded


# ---------------------------------------------------------------------------
# Money out of the drawer during the shift
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_recent_shifts(limit: int = 10, mine: int = 1) -> dict:
	"""Previous shifts — one row per submitted POS Closing Entry, newest first.

	The shift screen could only ever show the one in front of you, so "what did
	I close at yesterday?" — asked at the start of most days — meant leaving the
	till for the desk.

	**Driven from the closing entry, not the opening one.** An opening marked
	Closed whose closing entry was later cancelled would otherwise appear here as
	a shift that took nothing and balanced perfectly, which is a fabricated row.
	Starting from the closing entry means every row on this screen is a real
	close that still stands.

	The shift currently open is absent by construction: it has no closing entry
	yet. That is the point — this is history, and the open shift is read and
	settled at the till.

	Defaults to this cashier's own, as `pos.recent_sales` does: a shift belongs
	to a person, and everyone else's closings bury the one being looked for.
	"""
	filters = {"docstatus": 1}
	if int(mine or 0):
		filters["user"] = frappe.session.user

	closings = frappe.get_all(
		"POS Closing Entry",
		filters=filters,
		fields=[
			"name",
			"pos_opening_entry",
			"user",
			"pos_profile",
			"period_start_date",
			"period_end_date",
			"grand_total",
			"net_total",
			"total_quantity",
		],
		order_by="period_end_date desc, creation desc",
		limit=min(int(limit or 10), 50),
	)
	if not closings:
		return {
			"rows": [],
			"count": 0,
			"totals": {"shifts": 0, "taken": 0, "paid_out": 0, "short": 0, "unbalanced": 0},
		}

	# Summed in Python rather than SQL: Frappe rejects function strings like
	# `sum(difference)` in `get_all` fields, and this is at most fifty rows.
	differences = {}
	for d in frappe.get_all(
		"POS Closing Entry Detail",
		filters={"parent": ("in", [c.name for c in closings])},
		fields=["parent", "difference"],
	):
		differences[d.parent] = differences.get(d.parent, 0) + flt(d.difference)

	rows = []
	for c in closings:
		summary = _movement_summary(_movements(c.pos_opening_entry))

		rows.append(
			{
				"name": c.pos_opening_entry,
				"closing": c.name,
				"user": c.user,
				"pos_profile": c.pos_profile,
				"opened": str(c.period_start_date) if c.period_start_date else None,
				"closed": str(c.period_end_date) if c.period_end_date else None,
				"grand_total": flt(c.grand_total),
				"total_quantity": flt(c.total_quantity),
				"difference": flt(differences.get(c.name)),
				# What left the drawer that shift, so a closing that looks short
				# can be read against what was legitimately spent.
				"paid_out": summary["paid_out_total"],
				"expenses": summary["expense_total"],
				# The whole reason a short is recorded here rather than left on the
				# closing entry: it carries a name.
				"shorts": summary["shorts"],
				"short_total": summary["short_total"],
				"assigned_to": sorted({s["person"] for s in summary["shorts"] if s["person"]}),
			}
		)

	return {
		"rows": rows,
		"count": len(rows),
		"totals": {
			"shifts": len(rows),
			"taken": flt(sum(r["grand_total"] for r in rows)),
			"paid_out": flt(sum(r["paid_out"] for r in rows)),
			"short": flt(sum(r["short_total"] for r in rows)),
			"unbalanced": len([r for r in rows if abs(r["difference"]) >= 0.005]),
		},
	}


@frappe.whitelist()
def get_movement_options() -> dict:
	"""What the "money out" form needs to draw itself.

	Expense accounts are read from the chart of accounts rather than typed: a
	cashier should be choosing between "Transport" and "Repairs", not composing
	an account name that has to match one.
	"""
	shift = get_open_shift()
	company = (shift or {}).get("company") or frappe.defaults.get_user_default("Company")

	accounts = []
	if company:
		accounts = frappe.get_all(
			"Account",
			filters={
				"company": company,
				"is_group": 0,
				"disabled": 0,
				"root_type": "Expense",
			},
			fields=["name", "account_name"],
			order_by="account_name asc",
			limit=100,
		)

	modes = [b["mode_of_payment"] for b in (shift or {}).get("balances", [])]
	if not modes:
		modes = frappe.get_all(
			"Mode of Payment", filters={"enabled": 1}, pluck="name", order_by="name asc"
		)

	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	group = settings.neighbour_supplier_group
	neighbours = (
		frappe.get_all("Supplier", filters={"supplier_group": group}, pluck="name", order_by="name asc")
		if group
		else []
	)

	return {
		"shift": shift,
		"company": company,
		"modes": modes,
		"accounts": [{"name": a.name, "label": a.account_name or a.name} for a in accounts],
		"neighbours": neighbours,
		"default_expense_account": settings.default_expense_account,
	}


@frappe.whitelist()
def list_movements(shift_name: str | None = None) -> dict:
	"""Till movements for a shift — the open one unless another is named."""
	if not shift_name:
		shift = get_open_shift()
		if not shift:
			return {"rows": [], "count": 0, "paid_out_total": 0}
		shift_name = shift["name"]

	return _movement_summary(_movements(shift_name))


@frappe.whitelist(methods=["POST"])
def record_movement(
	movement_type: str,
	amount: float,
	mode_of_payment: str | None = None,
	reason: str | None = None,
	person: str | None = None,
	party: str | None = None,
	expense_account: str | None = None,
) -> dict:
	"""Record money leaving the drawer for something that is not a sale.

	Deliberately requires an open shift. A movement's whole purpose is to change
	what a shift should reconcile to, so one recorded outside a shift would be
	accounting nobody ever counts against.
	"""
	shift = get_open_shift()
	if not shift:
		frappe.throw(_("Open a shift before recording money out of the till"))

	if movement_type not in ("Expense", "Neighbour Purchase"):
		# Shorts are attributed at closing, against a difference that has actually
		# been counted — see `_record_shorts`.
		frappe.throw(_("{0} is not something you can record during a shift").format(movement_type))

	mode = mode_of_payment or _cash_mode(shift)

	doc = frappe.new_doc("Cosmestics Shift Movement")
	doc.shift = shift["name"]
	doc.movement_type = movement_type
	doc.mode_of_payment = mode
	doc.amount = flt(amount)
	doc.reason = reason
	doc.person = person
	doc.party = party
	doc.expense_account = expense_account
	doc.insert()
	doc.submit()

	return {
		"name": doc.name,
		"movement_type": doc.movement_type,
		"amount": flt(doc.amount),
		"mode_of_payment": doc.mode_of_payment,
		"reference_doctype": doc.reference_doctype,
		"reference_name": doc.reference_name,
	}


@frappe.whitelist(methods=["POST"])
def void_movement(name: str) -> dict:
	"""Cancel a movement recorded by mistake, and whatever it posted.

	Cancelled rather than deleted: the drawer was wrong for the minutes in
	between, and a shop that finds a discrepancy later needs to be able to see
	that an entry was made and reversed.
	"""
	doc = frappe.get_doc("Cosmestics Shift Movement", name)

	if doc.movement_type == "Short":
		frappe.throw(_("A short is attributed at closing and cannot be voided from the till"))

	shift = get_open_shift()
	if not shift or doc.shift != shift["name"]:
		frappe.throw(_("{0} does not belong to your open shift").format(name))

	doc.cancel()
	return {"name": doc.name, "cancelled": True}


def _cash_mode(shift):
	"""The mode a till expense comes out of unless told otherwise.

	The configured cash mode when the shift is counting it, otherwise the first
	mode on the shift — paying for a boda out of the card machine is not a thing,
	so guessing cash is right far more often than asking.
	"""
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	modes = [b["mode_of_payment"] for b in shift.get("balances", [])]

	if settings.mode_cash and settings.mode_cash in modes:
		return settings.mode_cash
	if modes:
		return modes[0]
	if settings.mode_cash:
		return settings.mode_cash

	frappe.throw(_("This shift has no payment modes to take money out of"))
