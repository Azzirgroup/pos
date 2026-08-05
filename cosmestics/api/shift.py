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
from frappe.utils import flt, getdate, now_datetime, nowdate


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

	profiles = frappe.get_all("POS Profile", filters=filters, fields=["name", "company"])

	# Every tender each till accepts, so the opening screen collects a float for
	# the same list the closing screen will ask the cashier to count. They used
	# to disagree: opening offered three hard-coded modes, closing offered
	# whatever the profile actually accepts — so a float counted into M-Pesa
	# Paybill at eight in the morning had nowhere to be declared, and the till
	# closed short by exactly that amount with no explanation on the screen.
	for profile in profiles:
		profile["modes"] = _profile_modes(profile["name"])

	return profiles


def _profile_modes(pos_profile: str) -> list:
	"""The modes a till accepts, in the order the profile lists them.

	Deduplicated for the same reason `_till_modes` is: on a shop that has not
	split the M-Pesa channels they all resolve to the generic mode, and asking a
	cashier to count one drawer three times is worse than not asking.
	"""
	return [b["mode_of_payment"] for b in _default_balances(pos_profile)]


def _user_profiles() -> list:
	"""POS Profiles this user can transact against.

	Explicit `POS Profile User` rows when the profile lists any, otherwise
	every enabled profile for the company — the same fallback `get_profiles`
	uses, so a one-till shop that never bothered to list users still works.
	"""
	user = frappe.session.user
	allowed = frappe.get_all(
		"POS Profile User", filters={"user": user, "parenttype": "POS Profile"}, pluck="parent"
	)
	if allowed:
		return allowed

	company = frappe.defaults.get_user_default("Company")
	filters = {"disabled": 0}
	if company:
		filters["company"] = company
	return frappe.get_all("POS Profile", filters=filters, pluck="name")


def _shared_open_shift():
	"""The open shift on a POS Profile this user shares with someone else.

	ERPNext allows only one open `POS Opening Entry` per profile at a time
	(`check_open_pos_exists`), regardless of who opened it. A profile with
	several `applicable_for_users` therefore has exactly one open shift,
	belonging to whichever of them started it first — everyone else on that
	profile sells against that same shift rather than being locked out until
	it closes.
	"""
	profiles = _user_profiles()
	if not profiles:
		return None
	return frappe.db.get_value(
		"POS Opening Entry",
		{"pos_profile": ("in", profiles), "docstatus": 1, "status": "Open"},
		"name",
	)


@frappe.whitelist()
def get_open_shift():
	"""The shift this user is transacting against, with its opening floats.

	Their own, if they started one. Otherwise the shift they share with
	someone else on the same POS Profile (see `_shared_open_shift`). None if
	neither.
	"""
	name = (
		frappe.db.get_value(
			"POS Opening Entry",
			{"user": frappe.session.user, "docstatus": 1, "status": "Open"},
			"name",
		)
		or _shared_open_shift()
	)
	if not name:
		return None

	doc = frappe.get_doc("POS Opening Entry", name)
	return {
		"name": doc.name,
		"pos_profile": doc.pos_profile,
		"company": doc.company,
		"user": doc.user,
		# So the till can say whose shift it is when it is not the viewer's own.
		"shared": doc.user != frappe.session.user,
		"period_start_date": str(doc.period_start_date),
		# ERPNext refuses to post an `is_pos` invoice against an opening entry
		# from an earlier day — `validate_pos_opening_entry` throws "Outdated POS
		# Opening Entry". Reported here so the till can say so before a sale is
		# attempted: found at checkout, it fails *after* the customer has paid,
		# with a message that does not name the fix.
		"outdated": getdate(doc.period_start_date) < getdate(nowdate()),
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
	if existing and existing.get("shared"):
		frappe.throw(
			_(
				"{0} already has an open shift ({1}), started by {2}. Sell against that "
				"shift instead of opening a new one."
			).format(existing["pos_profile"], existing["name"], existing.get("user"))
		)
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

	end = now_datetime()
	data = _shift_invoices(shift["pos_profile"], shift["period_start_date"], end)

	opening = {b["mode_of_payment"]: flt(b["opening_amount"]) for b in shift["balances"]}
	taken = {p["mode_of_payment"]: flt(p["amount"]) for p in data.get("payments", [])}
	# Money that left the drawer without being a sale — a till expense, or cash
	# handed to the shop next door. Same arithmetic as the two terms above, in
	# the opposite direction.
	movements = _movements(shift["name"])
	paid_out = _paid_out_by_mode(movements)

	rows = []
	# Every mode the till can take money through, not only the ones that did.
	# A mode with no float and no sales still has to be counted — otherwise a
	# cashier who took one Paybill payment on a mode the shift never listed has
	# nowhere to declare it, and the drawer reconciles against a figure that
	# quietly excludes it.
	for mode in {*opening, *taken, *paid_out, *_till_modes(shift)}:
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


def _till_modes(shift) -> list:
	"""Every Mode of Payment this till accepts.

	Read from the shift's own POS Profile, which is what the shop said this
	counter takes — including the M-Pesa channels split out separately, which is
	the whole reason they were split. Falling back to the configured modes keeps
	a site with no profile payment methods working.

	Deduplicated: on a shop that has not split the channels they all resolve to
	the generic M-Pesa mode, and asking a cashier to count the same drawer three
	times is worse than not asking at all.
	"""
	modes = frappe.get_all(
		"POS Payment Method",
		filters={"parent": shift.get("pos_profile")},
		pluck="mode_of_payment",
	)

	if not modes:
		from cosmestics.api.pos import _mode_map

		settings = frappe.get_cached_doc("Cosmestics POS Settings")
		modes = [m for m in _mode_map(settings).values() if m]

	return list(dict.fromkeys(modes))


def _movements(shift_name):
	"""Submitted till movements for one shift, newest first."""
	return _movements_for([shift_name]).get(shift_name, [])


def _movements_for(shift_names):
	"""Movements for several shifts at once, grouped by shift.

	One query rather than one per shift. `list_recent_shifts` returns up to
	fifty, and calling the single-shift version in that loop meant fifty round
	trips to answer a screen that shows a table — the page took visibly longer
	the more history a shop had, which is exactly backwards.
	"""
	if not shift_names:
		return {}

	rows = frappe.get_all(
		"Cosmestics Shift Movement",
		filters={"shift": ("in", list(shift_names)), "docstatus": 1},
		fields=[
			"shift",
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

	grouped = {}
	for row in rows:
		grouped.setdefault(row.shift, []).append(row)
	return grouped


def _paid_out_by_mode(movements):
	"""Per mode, the *net* these movements took out of the drawer.

	Net, because money moves both ways: a Neighbour Refund is cash handed back
	over the counter when goods went next door, so it counts against what was
	paid out. Returned as one figure rather than two because every caller wants
	the same thing — how much less than the sales the drawer should hold — and
	both the closing summary and `close_shift` read it from here, so the two can
	never disagree about it.

	A mode can end up negative, which is correct: refund more than you paid out
	on that mode and the drawer should hold more than the sales alone say.

	Shorts are excluded: a short is found by counting, so subtracting it from
	the expectation would make the count agree with itself and the discrepancy
	would vanish exactly when it is being recorded.
	"""
	from cosmestics.cosmestics.doctype.cosmestics_shift_movement.cosmestics_shift_movement import (
		CASH_IN_TYPES,
		PAID_OUT_TYPES,
	)

	out = {}
	for m in movements:
		if m.movement_type in PAID_OUT_TYPES:
			sign = 1
		elif m.movement_type in CASH_IN_TYPES:
			sign = -1
		else:
			continue
		out[m.mode_of_payment] = out.get(m.mode_of_payment, 0) + sign * flt(m.amount)
	return out


def _movement_summary(movements):
	from cosmestics.cosmestics.doctype.cosmestics_shift_movement.cosmestics_shift_movement import (
		CASH_IN_TYPES,
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
	cash_in = [r for r in rows if r["movement_type"] in CASH_IN_TYPES]
	shorts = [r for r in rows if r["movement_type"] == "Short"]

	return {
		"rows": rows,
		"count": len(rows),
		# Net, to match the expected amounts: a refund from next door is cash
		# that came back, so a screen showing gross paid-out beside a netted
		# expectation would look like the two disagreed.
		"paid_out_total": flt(
			sum(r["amount"] for r in paid_out) - sum(r["amount"] for r in cash_in)
		),
		"cash_in_total": flt(sum(r["amount"] for r in cash_in)),
		"expense_total": flt(sum(r["amount"] for r in rows if r["movement_type"] == "Expense")),
		"neighbour_cash_total": flt(
			sum(r["amount"] for r in rows if r["movement_type"] == "Neighbour Purchase")
		),
		"neighbour_refund_total": flt(
			sum(r["amount"] for r in rows if r["movement_type"] == "Neighbour Refund")
		),
		"credit_payment_total": flt(
			sum(r["amount"] for r in rows if r["movement_type"] == "Credit Payment")
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
	suppliers = frappe.get_all("Supplier", filters={"cosmestics_is_neighbour_shop": 1}, pluck="name")
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


def _shift_invoices(pos_profile, start, end):
	"""Every sale tied to this shift's profile in the window, any cashier.

	ERPNext's own `get_invoices` scopes to one `owner`, on the assumption that
	a shift belongs to whoever opened it. That breaks the moment a shift is
	shared (`_shared_open_shift`): only one `POS Opening Entry` is ever open
	per profile, so a sale tagged with that profile during this window belongs
	to this shift by construction, whoever rang it up. Mirrors ERPNext's own
	`build_invoice_query`, with the `owner` condition dropped.
	"""
	from frappe.query_builder import functions as fn
	from frappe.query_builder.custom import ConstantColumn

	from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import get_payments, get_taxes

	invoice_doctype = frappe.db.get_single_value("POS Settings", "invoice_type")

	def _query(doctype):
		dt = frappe.qb.DocType(doctype)
		q = (
			frappe.qb.from_(dt)
			.select(
				dt.name,
				dt.customer,
				dt.posting_date,
				dt.grand_total,
				dt.net_total,
				dt.total_qty,
				dt.total_taxes_and_charges,
				dt.change_amount,
				dt.account_for_change_amount,
				dt.is_return,
				dt.return_against,
				fn.Timestamp(dt.posting_date, dt.posting_time).as_("timestamp"),
				ConstantColumn(doctype).as_("doctype"),
			)
			.where(
				(dt.docstatus == 1)
				& (dt.is_pos == 1)
				& (dt.pos_profile == pos_profile)
				& (
					(fn.Timestamp(dt.posting_date, dt.posting_time) >= start)
					& (fn.Timestamp(dt.posting_date, dt.posting_time) <= end)
				)
			)
		)
		if doctype == "POS Invoice":
			q = q.where(fn.IfNull(dt.consolidated_invoice, "").eq(""))
		else:
			q = q.where((dt.is_created_using_pos == 1) & fn.IfNull(dt.pos_closing_entry, "").eq(""))
		return q

	query = _query("Sales Invoice")
	if invoice_doctype == "POS Invoice":
		query = query + _query("POS Invoice")
	query = query.orderby(query.timestamp)
	invoices = query.run(as_dict=1)

	return {"invoices": invoices, "payments": get_payments(invoices), "taxes": get_taxes(invoices)}


def _build_closing_entry(opening, data, end):
	"""Same shape as ERPNext's `make_closing_entry_from_opening`, built from
	`data` already scoped to the shift's profile rather than to one user —
	see `_shift_invoices`. Reimplemented rather than called: the ERPNext
	helper's own invoice lookup is hardwired to `owner == opening_entry.user`,
	which is exactly wrong for a shift shared between cashiers.
	"""
	closing_entry = frappe.new_doc("POS Closing Entry")
	closing_entry.pos_opening_entry = opening.name
	closing_entry.period_start_date = opening.period_start_date
	closing_entry.period_end_date = end
	closing_entry.pos_profile = opening.pos_profile
	closing_entry.user = opening.user
	closing_entry.company = opening.company
	closing_entry.grand_total = 0
	closing_entry.net_total = 0
	closing_entry.total_quantity = 0
	closing_entry.total_taxes_and_charges = 0

	pos_invoices = []
	sales_invoices = []
	taxes = [
		frappe._dict({"account_head": tx.account_head, "amount": tx.tax_amount})
		for tx in data.get("taxes")
	]
	payments = [
		frappe._dict(
			{"mode_of_payment": p.mode_of_payment, "opening_amount": 0, "expected_amount": p.amount}
		)
		for p in data.get("payments")
	]

	for d in data.get("invoices"):
		invoice = "pos_invoice" if d.doctype == "POS Invoice" else "sales_invoice"
		invoice_data = frappe._dict(
			{
				invoice: d.name,
				"posting_date": d.posting_date,
				"grand_total": d.grand_total,
				"customer": d.customer,
				"is_return": d.is_return,
				"return_against": d.return_against,
			}
		)
		(pos_invoices if d.doctype == "POS Invoice" else sales_invoices).append(invoice_data)

		closing_entry.grand_total += flt(d.grand_total)
		closing_entry.net_total += flt(d.net_total)
		closing_entry.total_quantity += flt(d.total_qty)
		closing_entry.total_taxes_and_charges += flt(d.total_taxes_and_charges)

	closing_entry.set("pos_invoices", pos_invoices)
	closing_entry.set("sales_invoices", sales_invoices)
	closing_entry.set("payment_reconciliation", payments)
	closing_entry.set("taxes", taxes)

	return closing_entry


@frappe.whitelist(methods=["POST"])
def close_shift(counted: list | str | None = None, shorts: list | str | None = None):
	"""Close the shift against what the cashier physically counted.

	`counted` is [{mode_of_payment, closing_amount}]. Anything not counted is
	assumed to match expectation, so a quiet till closes in one tap.

	`shorts` is [{mode_of_payment, person, amount, reason}] — who each shortfall
	is against, and how much of it each. `amount` is optional; people named
	without one share what is left evenly. Whatever nobody is named for is
	recorded as an unattributed short rather than dropped, so the amounts always
	add up to the difference — see `_record_shorts`.

	ERPNext's closing entry books the difference on the document and posts
	nothing to the ledger, so each short raises its own Journal Entry. Recorded
	after the entry submits, so a rejected close leaves no orphan attribution
	behind.
	"""
	if isinstance(counted, str):
		counted = frappe.parse_json(counted)
	if isinstance(shorts, str):
		shorts = frappe.parse_json(shorts)

	shift = get_open_shift()
	if not shift:
		frappe.throw(_("No open shift"))

	counted_map = {c["mode_of_payment"]: flt(c.get("closing_amount")) for c in (counted or [])}
	# Cash already taken out of the drawer this shift. The builder below only
	# knows about sales, so without this the expected amount would ask the
	# cashier to produce money that was legitimately spent hours ago.
	paid_out = _paid_out_by_mode(_movements(shift["name"]))

	# Gathers the shift's invoices, totals, taxes and per-mode payment rows —
	# scoped to the profile rather than to whoever opened it, so a co-cashier's
	# sales on a shared shift are not silently dropped from the close.
	opening = frappe.get_doc("POS Opening Entry", shift["name"])
	end = now_datetime()
	data = _shift_invoices(opening.pos_profile, opening.period_start_date, end)
	doc = _build_closing_entry(opening, data, end)
	doc.posting_date = nowdate()
	doc.posting_time = end.strftime("%H:%M:%S")

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
	"""Account for every shortfall, in full, against whoever carries it.

	## The invariant

	For each mode that came up short, the amounts recorded here add up to
	*exactly* the difference. Not "as much as somebody was named for" — the whole
	thing. What nobody is named for becomes one unattributed short, which books
	to the company's account instead of a person's.

	That invariant is the point of the rewrite. Before it, naming a person filed
	the *entire* mode shortfall against them — so two people named on one mode
	were each charged the full amount, and 500 missing became 1,000 owed. Naming
	nobody recorded nothing at all, and the money left the drawer having never
	existed on the books.

	## Splitting

	`shorts` is [{mode_of_payment, person, amount, reason}]. `amount` is
	optional: entries without one share whatever is left on that mode evenly,
	which is the common case — two people on the counter, nobody knows which of
	them, so they split it. Entries with an amount are honoured first, because
	somebody who says "it was my 200" has given information an even split would
	throw away.

	Over-attribution is refused rather than scaled down. If the named amounts
	come to more than the shortfall, one of them is wrong, and quietly shrinking
	them to fit would hide which.
	"""
	by_mode = {
		r.mode_of_payment: abs(flt(r.difference))
		for r in closing.payment_reconciliation
		if flt(r.difference) < 0
	}
	if not by_mode:
		return []

	claims = {}
	for entry in shorts or []:
		mode = entry.get("mode_of_payment")
		if mode not in by_mode:
			# A name against a mode that then balanced. Dropped rather than filed
			# as a debt that does not exist.
			continue
		person = (entry.get("person") or "").strip()
		if not person:
			continue
		claims.setdefault(mode, []).append(
			{
				"person": person,
				"amount": flt(entry.get("amount")) if entry.get("amount") not in (None, "") else None,
				"reason": entry.get("reason"),
				# Whose account this one lands in. Optional: without it the short
				# goes to the till's own short account, which is the right answer
				# for a shop that keeps one "owed by staff" account. A shop that
				# keeps an account per person tags it here.
				"account": entry.get("account") or None,
			}
		)

	recorded = []
	for mode, shortfall in by_mode.items():
		for row in _split(mode, shortfall, claims.get(mode, []), closing):
			recorded.append(_write_short(shift, closing, mode, row))

	return recorded


def _split(mode, shortfall, claims, closing):
	"""Turn "these people, this much missing" into lines that add up.

	Returns [{person, amount, reason, unattributed}] summing to `shortfall`.
	"""
	stated = [c for c in claims if c["amount"] is not None]
	unstated = [c for c in claims if c["amount"] is None]

	claimed = flt(sum(c["amount"] for c in stated))
	if claimed > shortfall + 0.005:
		frappe.throw(
			_("{0} attributed on {1} is more than the {2} actually missing").format(
				frappe.format_value(claimed, {"fieldtype": "Currency"}),
				mode,
				frappe.format_value(shortfall, {"fieldtype": "Currency"}),
			)
		)

	lines = [
		{
			"person": c["person"],
			"amount": flt(c["amount"]),
			"reason": c["reason"],
			"account": c.get("account"),
			"unattributed": 0,
		}
		for c in stated
		if flt(c["amount"]) > 0
	]

	remaining = flt(shortfall - claimed, 2)

	if unstated and remaining > 0:
		# An even split, with the rounding remainder on the first person rather
		# than lost. Three people and 100 missing is 33.34 / 33.33 / 33.33, and
		# the total is still 100 — which is the whole invariant.
		each = flt(remaining / len(unstated), 2)
		for i, c in enumerate(unstated):
			amount = each if i else flt(remaining - each * (len(unstated) - 1), 2)
			if amount <= 0:
				continue
			lines.append(
				{
					"person": c["person"],
					"amount": amount,
					"reason": c["reason"],
					"account": c.get("account"),
					"unattributed": 0,
				}
			)
		remaining = 0

	if remaining > 0.005:
		# Nobody named for this part. Recorded anyway, and said out loud — a
		# shortfall that is written off is a fact the shop should be able to see
		# and add up, not an absence of records.
		lines.append(
			{
				"person": None,
				"amount": remaining,
				"reason": _("Shortfall on {0} nobody was named for").format(closing.name),
				# Never tagged: nobody is named, so there is no "their account" to
				# tag. It goes to the company's write-off account by definition.
				"account": None,
				"unattributed": 1,
			}
		)

	return lines


def _write_short(shift, closing, mode, row):
	doc = frappe.new_doc("Cosmestics Shift Movement")
	doc.shift = shift["name"]
	doc.movement_type = "Short"
	doc.mode_of_payment = mode
	doc.amount = row["amount"]
	doc.person = row["person"]
	doc.unattributed = row["unattributed"]
	# Reuses the movement's existing account field, which is "where this books
	# to" for an expense and means exactly the same thing here. A second Link to
	# Account holding the same idea would be one more field to keep in step.
	doc.expense_account = row.get("account")
	doc.reason = row["reason"] or _("Shortfall on {0}").format(closing.name)
	doc.insert()
	doc.submit()

	return {
		"name": doc.name,
		"mode_of_payment": mode,
		"amount": flt(doc.amount),
		"person": doc.person,
		"unattributed": bool(doc.unattributed),
		"account": doc.expense_account,
		# What it posted, which is new — a short used to be a note with no ledger
		# entry behind it.
		"journal_entry": doc.reference_name,
	}


# ---------------------------------------------------------------------------
# Money out of the drawer during the shift
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_recent_shifts(limit: int = 10, mine: int = 1, include_open: int = 1) -> dict:
	"""Previous shifts — one row per submitted POS Closing Entry, newest first.

	The shift screen could only ever show the one in front of you, so "what did
	I close at yesterday?" — asked at the start of most days — meant leaving the
	till for the desk.

	**Driven from the closing entry, not the opening one.** An opening marked
	Closed whose closing entry was later cancelled would otherwise appear here as
	a shift that took nothing and balanced perfectly, which is a fabricated row.
	Starting from the closing entry means every row on this screen is a real
	close that still stands.

	Shifts still open are listed too, from the opening side, because a manager
	asking "whose till is still running" is asking this screen. They carry
	`open: true` and no closing figures — a shift that has not been counted has
	no difference and no shorts, and inventing zeroes for them would put a
	perfectly balanced row next to real ones.

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

	# One query for every shift's movements, not one per shift.
	movements = _movements_for([c.pos_opening_entry for c in closings])

	rows = []
	for c in closings:
		summary = _movement_summary(movements.get(c.pos_opening_entry, []))

		rows.append(
			{
				"name": c.pos_opening_entry,
				"open": False,
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

	if int(include_open or 0):
		rows = _open_shift_rows(int(mine or 0)) + rows

	return {
		"rows": rows,
		"count": len(rows),
		"totals": {
			"shifts": len(rows),
			"open": len([r for r in rows if r["open"]]),
			"taken": flt(sum(r["grand_total"] for r in rows)),
			"paid_out": flt(sum(r["paid_out"] for r in rows)),
			"short": flt(sum(r["short_total"] for r in rows)),
			"unbalanced": len([r for r in rows if abs(r["difference"]) >= 0.005]),
		},
	}


def _open_shift_rows(mine: int) -> list:
	"""Shifts still running, in the same shape as the closed ones.

	Taken from the opening entry with no closing figures, because there are
	none: nothing has been counted. What *is* known — who is on it, since when,
	and what has come out of the drawer — is the part a manager wants.
	"""
	filters = {"docstatus": 1, "status": "Open"}
	if mine:
		filters["user"] = frappe.session.user

	openings = frappe.get_all(
		"POS Opening Entry",
		filters=filters,
		fields=["name", "user", "pos_profile", "period_start_date"],
		order_by="period_start_date desc",
		limit=20,
	)
	if not openings:
		return []

	movements = _movements_for([o.name for o in openings])

	rows = []
	for o in openings:
		summary = _movement_summary(movements.get(o.name, []))
		rows.append(
			{
				"name": o.name,
				"open": True,
				"closing": None,
				"user": o.user,
				"pos_profile": o.pos_profile,
				"opened": str(o.period_start_date) if o.period_start_date else None,
				"closed": None,
				# Nothing has been counted, so there is nothing to report as taken
				# or short. The activity view has the real figures for an open
				# shift; a row here would be a guess.
				"grand_total": 0,
				"total_quantity": 0,
				"difference": 0,
				"paid_out": summary["paid_out_total"],
				"expenses": summary["expense_total"],
				"shorts": [],
				"short_total": 0,
				"assigned_to": [],
				"_tone": "warn",
			}
		)
	return rows


@frappe.whitelist()
def shift_activity(shift: str) -> dict:
	"""Everything that happened on one shift, open or closed.

	The list answers "which shift"; this answers "what happened on it" — every
	tender taken, every movement out of the drawer, the credit sales, the
	neighbour purchases and, when it has been closed, what was counted against
	what was expected.

	Works for a shift that is still running, which is the case the closing entry
	cannot serve: there is no closing document to read, so the figures come from
	the same `get_invoices` the live closing screen uses.
	"""
	opening = frappe.get_doc("POS Opening Entry", shift)
	end = opening.period_end_date or now_datetime()

	# The same call the live closing screen makes, scoped to the profile rather
	# than to whoever opened it — a manager reading a shared shift must see
	# every cashier's invoices on it, not just the opener's.
	data = _shift_invoices(opening.pos_profile, opening.period_start_date, end)
	movements = _movements(opening.name)
	summary = _movement_summary(movements)

	taken = {}
	for p in data.get("payments", []):
		taken[p["mode_of_payment"]] = flt(taken.get(p["mode_of_payment"], 0)) + flt(p["amount"])

	paid_out = _paid_out_by_mode(movements)
	opening_amounts = {b.mode_of_payment: flt(b.opening_amount) for b in opening.balance_details}

	# What was actually counted, when it has been counted at all.
	closing = frappe.db.get_value(
		"POS Closing Entry", {"pos_opening_entry": shift, "docstatus": 1}, "name"
	)
	counted = {}
	if closing:
		for d in frappe.get_all(
			"POS Closing Entry Detail",
			filters={"parent": closing},
			fields=["mode_of_payment", "closing_amount", "expected_amount", "difference"],
		):
			counted[d.mode_of_payment] = {
				"closing_amount": flt(d.closing_amount),
				"difference": flt(d.difference),
			}

	modes = []
	for mode in {*opening_amounts, *taken, *paid_out, *counted}:
		expected = opening_amounts.get(mode, 0) + taken.get(mode, 0) - paid_out.get(mode, 0)
		row = counted.get(mode) or {}
		modes.append(
			{
				"mode_of_payment": mode,
				"opening_amount": opening_amounts.get(mode, 0),
				"taken": taken.get(mode, 0),
				"paid_out": paid_out.get(mode, 0),
				"expected_amount": expected,
				"counted": row.get("closing_amount"),
				"difference": row.get("difference"),
			}
		)
	modes.sort(key=lambda r: r["mode_of_payment"])

	invoices = data.get("invoices", [])
	return {
		"shift": {
			"name": opening.name,
			"user": opening.user,
			"pos_profile": opening.pos_profile,
			"company": opening.company,
			"opened": str(opening.period_start_date),
			"closed": str(opening.period_end_date) if opening.period_end_date else None,
			"open": opening.status == "Open",
			"closing": closing,
		},
		"modes": modes,
		"invoice_count": len(invoices),
		"grand_total": flt(sum(flt(i.get("grand_total")) for i in invoices)),
		"movements": summary,
		"credit": _credit_summary(opening.period_start_date, end),
		"neighbour": _neighbour_summary(opening.period_start_date, end),
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
	neighbours = frappe.get_all(
		"Supplier", filters={"cosmestics_is_neighbour_shop": 1}, pluck="name", order_by="name asc"
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
	if movement_type not in ("Expense", "Neighbour Purchase"):
		# Shorts are attributed at closing, against a difference that has actually
		# been counted — see `_record_shorts`. A Neighbour Refund is only ever
		# raised alongside the return invoice that justifies it (see
		# `sourcing.return_to_neighbour`); allowing it from here would let anyone
		# with till access add cash to the drawer's expectation out of nothing.
		frappe.throw(_("{0} is not something you can record during a shift").format(movement_type))

	return post_movement(
		movement_type=movement_type,
		amount=amount,
		mode_of_payment=mode_of_payment,
		reason=reason,
		person=person,
		party=party,
		expense_account=expense_account,
	)


def post_movement(
	movement_type: str,
	amount: float,
	mode_of_payment: str | None = None,
	reason: str | None = None,
	person: str | None = None,
	party: str | None = None,
	expense_account: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict:
	"""Write the movement. Not whitelisted — see `record_movement` for why.

	This is the path for movements the *server* raises on the back of a document
	it has just written, which is why it takes a reference and asks no questions
	about the type.
	"""
	shift = get_open_shift()
	if not shift:
		frappe.throw(_("Open a shift before recording money out of the till"))

	doc = frappe.new_doc("Cosmestics Shift Movement")
	doc.shift = shift["name"]
	doc.movement_type = movement_type
	doc.mode_of_payment = mode_of_payment or _cash_mode(shift)
	doc.amount = flt(amount)
	doc.reason = reason
	doc.person = person
	doc.party = party
	doc.expense_account = expense_account
	doc.reference_doctype = reference_doctype
	doc.reference_name = reference_name
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
