"""Who owes the shop, and whom the shop owes — one screen for each.

Receivables and Payables used to be two routes onto the same report view, and
the view never noticed the route changing: opening Payables straight after
Receivables kept the customer list on screen under a Payables heading. They are
now one list shaped for the job — contact details, credit limit, what is owed —
with a statement a click away, driven by `party_type` so the two can never
drift apart again.

Balances are read from the General Ledger rather than summed from invoices, so
payments on account, credit notes and journal adjustments all count. That is
the figure the statement ends on, and the list must agree with it.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

PARTY_TYPES = {
	"Customer": {
		"title": "customer_name",
		"kind": "customer_type",
		"group": "customer_group",
		"invoice": "Sales Invoice",
		# A customer's balance is what they owe us: debit minus credit.
		"sign": 1,
	},
	"Supplier": {
		"title": "supplier_name",
		"kind": "supplier_type",
		"group": "supplier_group",
		"invoice": "Purchase Invoice",
		# A supplier's is what we owe them: credit minus debit.
		"sign": -1,
	},
}


def _spec(party_type: str) -> dict:
	spec = PARTY_TYPES.get(party_type)
	if not spec:
		frappe.throw(_("{0} is not a party this screen lists").format(party_type))
	return spec


def _company() -> str | None:
	return frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")


def _balances(party_type: str, company: str | None) -> dict:
	"""{party: balance} in the direction that matters for this party type."""
	sign = _spec(party_type)["sign"]
	rows = frappe.db.sql(
		f"""select party, sum(debit) - sum(credit) as balance
		    from `tabGL Entry`
		    where is_cancelled = 0 and party_type = %(pt)s
		    {"and company = %(company)s" if company else ""}
		    group by party""",
		{"pt": party_type, "company": company},
		as_dict=True,
	)
	return {r.party: sign * flt(r.balance) for r in rows}


def _open_invoices(party_type: str, company: str | None) -> dict:
	spec = _spec(party_type)
	field = frappe.scrub(party_type)
	rows = frappe.db.sql(
		f"""select `{field}` as party, count(name) as n
		    from `tab{spec["invoice"]}`
		    where docstatus = 1 and outstanding_amount > 0
		    {"and company = %(company)s" if company else ""}
		    group by `{field}`""",
		{"company": company},
		as_dict=True,
	)
	return {r.party: cint(r.n) for r in rows}


def _credit_limits(names: list, company: str | None) -> dict:
	if not names:
		return {}
	filters = {"parenttype": "Customer", "parent": ("in", names)}
	if company:
		filters["company"] = company
	return {
		r.parent: flt(r.credit_limit)
		for r in frappe.get_all(
			"Customer Credit Limit", filters=filters, fields=["parent", "credit_limit"], limit_page_length=0
		)
	}


def _locations(party_type: str, rows: list) -> dict:
	"""City from the primary address where there is one, else the territory or country."""
	field = "customer_primary_address" if party_type == "Customer" else "supplier_primary_address"
	addresses = {r.get(field) for r in rows if r.get(field)}
	cities = {}
	if addresses:
		cities = dict(
			frappe.get_all(
				"Address", filters={"name": ("in", list(addresses))}, fields=["name", "city"], as_list=True
			)
		)
	out = {}
	for r in rows:
		out[r.name] = cities.get(r.get(field)) or r.get("territory") or r.get("country") or None
	return out


def _party_fields(party_type: str) -> list:
	spec = _spec(party_type)
	fields = ["name", spec["title"], "mobile_no", "email_id", spec["kind"], "disabled"]
	meta = frappe.get_meta(party_type)
	for f in ("customer_primary_address", "supplier_primary_address", "territory", "country"):
		if meta.has_field(f):
			fields.append(f)
	return fields


def _row(party_type, r, balance, invoices, limit, location):
	spec = _spec(party_type)
	outstanding = max(balance, 0)
	row = {
		"name": r.name,
		"title": r.get(spec["title"]) or r.name,
		"mobile_no": r.get("mobile_no"),
		"email_id": r.get("email_id"),
		"location": location,
		"party_kind": r.get(spec["kind"]),
		"outstanding": outstanding,
		# Money held for them: an advance, an overpayment, a credit note.
		"advance": max(-balance, 0),
		"invoices": invoices,
	}
	if party_type == "Customer":
		row["credit_limit"] = limit or None
		row["available_credit"] = (limit - outstanding) if limit else None
	return row


@frappe.whitelist()
def list_parties(
	party_type: str = "Customer",
	search: str | None = None,
	owing_only: int = 0,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""One page of customers or suppliers, the ones with a balance first."""
	spec = _spec(party_type)
	frappe.has_permission(party_type, "read", throw=True)
	company = _company()

	filters = {"disabled": 0}
	or_filters = None
	if search:
		like = f"%{search.strip()}%"
		or_filters = {"name": ("like", like), spec["title"]: ("like", like), "mobile_no": ("like", like)}

	parties = frappe.get_list(
		party_type,
		filters=filters,
		or_filters=or_filters,
		fields=_party_fields(party_type),
		limit_page_length=0,
	)

	balances = _balances(party_type, company)
	invoices = _open_invoices(party_type, company)
	if cint(owing_only):
		parties = [p for p in parties if balances.get(p.name, 0) > 0.005]

	parties.sort(key=lambda p: (-balances.get(p.name, 0), (p.get(spec["title"]) or p.name).lower()))
	total = len(parties)
	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or 20, 1), 200)
	page = parties[start : start + page_length]

	limits = _credit_limits([p.name for p in page], company) if party_type == "Customer" else {}
	locations = _locations(party_type, page)

	return {
		"party_type": party_type,
		"rows": [
			_row(
				party_type,
				p,
				balances.get(p.name, 0),
				invoices.get(p.name, 0),
				limits.get(p.name, 0),
				locations.get(p.name),
			)
			for p in page
		],
		"total": total,
		"start": start,
		"page_length": page_length,
		"total_outstanding": sum(max(b, 0) for n, b in balances.items()),
		"owing": sum(1 for b in balances.values() if b > 0.005),
	}


@frappe.whitelist()
def statement(
	party_type: str,
	party: str,
	from_date: str | None = None,
	to_date: str | None = None,
) -> dict:
	"""A party's account between two dates, with the balance carried in.

	Every figure on the dialog — credit limit, running balance, available
	credit — comes from here, so the tiles and the statement under them cannot
	disagree.
	"""
	spec = _spec(party_type)
	doc = frappe.get_doc(party_type, party)
	doc.check_permission("read")
	company = _company()

	end = getdate(to_date) if to_date else getdate(nowdate())
	start = getdate(from_date) if from_date else getdate(add_days(end, -30))
	if start > end:
		start, end = end, start

	cond = "gle.is_cancelled = 0 and gle.party_type = %(pt)s and gle.party = %(party)s"
	if company:
		cond += " and gle.company = %(company)s"
	values = {"pt": party_type, "party": party, "company": company, "start": start, "end": end}
	sign = spec["sign"]

	opening = sign * flt(
		frappe.db.sql(
			f"select sum(gle.debit) - sum(gle.credit) from `tabGL Entry` gle where {cond} and gle.posting_date < %(start)s",
			values,
		)[0][0]
	)
	current = sign * flt(
		frappe.db.sql(f"select sum(gle.debit) - sum(gle.credit) from `tabGL Entry` gle where {cond}", values)[0][0]
	)

	entries = frappe.db.sql(
		f"""select gle.posting_date, gle.voucher_type, gle.voucher_no,
		           sum(gle.debit) as debit, sum(gle.credit) as credit
		    from `tabGL Entry` gle
		    where {cond} and gle.posting_date between %(start)s and %(end)s
		    group by gle.posting_date, gle.voucher_type, gle.voucher_no
		    order by gle.posting_date asc, min(gle.creation) asc""",
		values,
		as_dict=True,
	)

	balance = opening
	rows = []
	for e in entries:
		# "Charged" is what raises the balance for this party type: an invoice to
		# a customer, a bill from a supplier.
		charged = flt(e.debit) if sign > 0 else flt(e.credit)
		settled = flt(e.credit) if sign > 0 else flt(e.debit)
		balance += charged - settled
		rows.append(
			{
				"posting_date": str(e.posting_date),
				"voucher_type": e.voucher_type,
				"voucher_no": e.voucher_no,
				"charged": charged,
				"settled": settled,
				"balance": balance,
			}
		)

	limit = None
	if party_type == "Customer":
		limit = _credit_limits([party], company).get(party) or None

	outstanding = max(current, 0)
	location = _locations(party_type, [frappe._dict(doc.as_dict())]).get(party)

	return {
		"party_type": party_type,
		"party": party,
		"title": doc.get(spec["title"]) or party,
		"mobile_no": doc.get("mobile_no"),
		"email_id": doc.get("email_id"),
		"location": location,
		"party_kind": doc.get(spec["kind"]),
		"company": company,
		"currency": frappe.get_cached_value("Company", company, "default_currency") if company else None,
		"credit_limit": limit,
		"outstanding": outstanding,
		"advance": max(-current, 0),
		"available_credit": (limit - outstanding) if limit else None,
		"from_date": str(start),
		"to_date": str(end),
		"opening": opening,
		"closing": balance,
		"rows": rows,
		"can_set_credit_limit": party_type == "Customer" and frappe.has_permission("Customer", "write", doc=doc),
		"desk_url": f"/app/{frappe.scrub(party_type).replace('_', '-')}/{party}",
	}


@frappe.whitelist(methods=["POST"])
def set_credit_limit(customer: str, credit_limit: float) -> dict:
	"""Set, change or clear (0) a customer's credit limit for this company."""
	doc = frappe.get_doc("Customer", customer)
	doc.check_permission("write")
	company = _company()
	if not company:
		frappe.throw(_("No default company is set"))

	limit = flt(credit_limit)
	if limit < 0:
		frappe.throw(_("A credit limit cannot be negative"))

	row = next((r for r in doc.get("credit_limits") or [] if r.company == company), None)
	if limit == 0:
		if row:
			doc.remove(row)
	elif row:
		row.credit_limit = limit
	else:
		doc.append("credit_limits", {"company": company, "credit_limit": limit})
	doc.save()

	return {
		"customer": customer,
		"credit_limit": limit or None,
		"message": _("Credit limit for {0} set to {1}").format(
			doc.customer_name or customer,
			frappe.format_value(limit, {"fieldtype": "Currency"}) if limit else _("none"),
		),
	}
