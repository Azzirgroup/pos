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


def _reachable_number(party: str) -> str | None:
	"""A number this party can actually be reached on.

	Not `Customer.mobile_no` alone. On ERPNext that field is filled from the
	party's *primary contact*, so a customer whose number was typed against a
	Contact — which is most of them — reads as having no number at all. The
	statement's WhatsApp button went grey for those, and on a phone there is no
	tooltip to explain why, so it simply looked broken.

	`contact_numbers` already looks everywhere a shop keeps a number; the first
	it finds is the one the shop would have picked.
	"""
	from cosmestics.api.notifications import contact_numbers

	try:
		numbers = contact_numbers(party=party).get("numbers") or []
	except Exception:
		return None
	return numbers[0]["number"] if numbers else None


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
		"mobile_no": _reachable_number(party),
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


# --------------------------------------------------------------------------
# The printed statement
# --------------------------------------------------------------------------


def _letter_head(company: str | None) -> dict:
	"""The shop's own letterhead, the one its invoices already carry.

	Read from ERPNext rather than drawn here: a statement that does not look
	like the shop's other paperwork is one a customer has to be told is genuine.
	Falls back to the company's name, so a site with no letterhead set up still
	sends something headed.
	"""
	name = None
	if company:
		name = frappe.db.get_value("Company", company, "default_letter_head")
	name = name or frappe.db.get_value("Letter Head", {"is_default": 1, "disabled": 0}, "name")
	if not name:
		return {"header": f"<h2 style='margin:0'>{frappe.utils.escape_html(company or '')}</h2>", "footer": ""}
	row = frappe.db.get_value("Letter Head", name, ["content", "footer"], as_dict=True) or {}
	return {
		"header": _balanced(row.get("content")),
		"footer": _balanced(row.get("footer")),
	}


def _balanced(html: str | None) -> str:
	"""Letterhead HTML with every tag closed.

	A letter head is written in a rich-text editor and is routinely left
	unbalanced — most often a `<table>` with no `</table>`. Dropped into a page
	as-is, the HTML parser never closes it, so **the whole statement below it**
	becomes content of that table: the ledger is squeezed into the letterhead's
	own width, the columns collapse on top of each other, and the PDF that
	reaches the customer is unreadable. The `</div>` around it cannot help —
	inside an open table a stray close tag is ignored.

	Parsing and re-serialising closes what the shop left open, and changes
	nothing about a letterhead that was already well formed.
	"""
	markup = html or ""
	if not markup.strip():
		return ""
	try:
		from bs4 import BeautifulSoup

		# `html.parser` keeps this a fragment: the others wrap it in
		# `<html><body>`, which cannot be embedded mid-page.
		soup = BeautifulSoup(markup, "html.parser")
		# A statement is a printed sheet. Script in it does nothing in a PDF and
		# runs for real in the print frame, which is a letterhead reaching
		# further than a letterhead should.
		for tag in soup.find_all("script"):
			tag.decompose()
		return soup.decode()
	except Exception:
		frappe.log_error("Could not tidy the letter head", "Cosmetics POS")
		return markup


def statement_html(
	party_type: str, party: str, from_date: str | None = None, to_date: str | None = None
) -> str:
	"""The statement as a printable page, headed like the shop's invoices."""
	data = statement(party_type, party, from_date, to_date)
	head = _letter_head(data.get("company"))

	def money(value):
		return frappe.utils.fmt_money(flt(value), currency=data.get("currency"))

	rows = "".join(
		f"<tr><td>{r['posting_date']}</td><td>{frappe.utils.escape_html(r['voucher_type'])}</td>"
		f"<td class='doc'>{frappe.utils.escape_html(r['voucher_no'])}</td>"
		f"<td class='n'>{money(r['charged']) if r['charged'] else ''}</td>"
		f"<td class='n'>{money(r['settled']) if r['settled'] else ''}</td>"
		f"<td class='n'>{money(r['balance'])}</td></tr>"
		for r in data["rows"]
	)
	contact = " · ".join(x for x in (data.get("mobile_no"), data.get("email_id"), data.get("location")) if x)
	charged_label = _("Billed") if party_type == "Customer" else _("Billed to us")

	summary = [(_("Opening"), money(data["opening"])), (_("Closing"), money(data["closing"]))]
	if data.get("credit_limit"):
		summary.append((_("Credit limit"), money(data["credit_limit"])))
	sum_cells = "".join(
		f"<td><span class='k'>{label}</span><span class='v'>{value}</span></td>"
		for label, value in summary
	)

	return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{_("Statement")} — {frappe.utils.escape_html(data['title'])}</title>
<style>
  /* Paper first. The page used to carry a 28px body margin and no page rule,
     so the printer added its own on top of it and the sheet sat low and left.
     One margin, declared here, and the body has none. */
  @page {{ size: A4; margin: 14mm 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: system-ui, "Helvetica Neue", Arial, sans-serif;
    font-size: 11.5px; color: #1a1a1a; margin: 0;
    /* Header bands and rules are the alignment cues on a long statement, and
       browsers drop background colour from print by default. */
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }}
  .head {{ border-bottom: 2px solid #1a1a1a; padding-bottom: 8px; margin-bottom: 12px; }}
  /* A letterhead is somebody else's HTML, often with a logo sized for screen.
     Left to itself it pushes the page wider than the paper and every column
     after it sits off the edge. */
  .head img {{ max-width: 100%; height: auto; }}
  .head table {{ width: 100% !important; }}
  h1 {{ font-size: 16px; margin: 10px 0 2px; }}
  .muted {{ color: #666; font-size: 11px; }}
  /* A table, not flexbox. `display:flex` is ignored outright by the PDF engine
     the shop's statements are rendered with, which stacked these three figures
     down the left margin instead of setting them in a row. */
  .sum {{ width: auto; margin: 10px 0 0; border-collapse: collapse; }}
  .sum td {{ padding: 0 28px 0 0; border: 0; vertical-align: top; }}
  .sum .k {{ display: block; font-size: 10.5px; color: #666; }}
  .sum .v {{ display: block; font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }}
  /* Fixed layout with a colgroup: the columns are then the same width on every
     page, which is what makes a three-page statement read as one document. */
  /* `!important` on the structural rules only.
     A letter head can carry its own <style>, and because it is written into
     the body it comes after this block and wins on order — one `table {{ width:
     200px }}` in a letterhead and the ledger is a ribbon down the page. These
     are the rules that decide whether the sheet is readable at all; everything
     cosmetic below is still the shop's to override. */
  table.ledger {{ width: 100% !important; border-collapse: collapse; margin-top: 12px;
                  table-layout: fixed !important; font-size: 11.5px !important; }}
  th, td {{ padding: 5px 6px !important; border-bottom: 1px solid #e0e0e0; text-align: left;
            font-size: inherit !important; }}
  th {{ background: #f4f4f4; font-size: 10.5px; text-transform: uppercase; letter-spacing: .02em; }}
  /* Repeated at the top of every printed page. Without this the second page of
     a long statement is a wall of figures with nothing saying which column is
     which — the usual complaint about a statement that will not sit straight. */
  thead {{ display: table-header-group; }}
  tfoot {{ display: table-footer-group; }}
  tr {{ page-break-inside: avoid; break-inside: avoid; }}
  .n {{ text-align: right !important; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .doc {{ font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
  .brought td {{ font-style: italic; color: #555; }}
  tfoot td {{ font-weight: 700; border-top: 2px solid #1a1a1a; border-bottom: 0; }}
  .foot {{ margin-top: 16px; padding-top: 8px; border-top: 1px solid #e0e0e0;
           color: #666; font-size: 10.5px; page-break-inside: avoid; }}
</style></head><body>
  <div class="head">{head['header']}</div>
  <h1>{frappe.utils.escape_html(data['title'])}</h1>
  <div class="muted">{_("Statement of account")} · {data['from_date']} {_("to")} {data['to_date']}</div>
  <div class="muted">{frappe.utils.escape_html(contact)}</div>
  <table class="sum"><tr>{sum_cells}</tr></table>
  <table class="ledger">
    <colgroup>
      <col style="width:13%"><col style="width:17%"><col style="width:26%">
      <col style="width:15%"><col style="width:14%"><col style="width:15%">
    </colgroup>
    <thead><tr><th>{_("Date")}</th><th>{_("Type")}</th><th>{_("Document")}</th>
      <th class="n">{charged_label}</th><th class="n">{_("Paid")}</th><th class="n">{_("Balance")}</th></tr></thead>
    <tbody>
      <tr class="brought"><td colspan="5">{_("Balance brought forward")}</td><td class="n">{money(data['opening'])}</td></tr>
      {rows}
    </tbody>
    <tfoot><tr><td colspan="5">{_("Balance due")}</td><td class="n">{money(data['closing'])}</td></tr></tfoot>
  </table>
  <div class="foot">{head['footer']}</div>
</body></html>"""


@frappe.whitelist()
def statement_print(
    party_type: str, party: str, from_date: str | None = None, to_date: str | None = None
) -> dict:
	"""The printable statement, rendered on the server so print and WhatsApp
	send exactly the same page."""
	return {"html": statement_html(party_type, party, from_date, to_date)}


#: What a customer reads when the statement arrives. Their own wording.
STATEMENT_MESSAGE = (
	"Please find your attached running statement. Thank you for doing business with us"
)


def _remember_number(party_type: str, party: str, number: str):
	"""Put a number typed at the counter onto the record.

	Quietly: the cashier asked to send a statement, not to edit a customer, and
	a failure here must not lose them the send they did ask for.
	"""
	try:
		if not frappe.has_permission(party_type, "write", doc=party):
			return
		if frappe.get_meta(party_type).has_field("mobile_no"):
			frappe.db.set_value(party_type, party, "mobile_no", number)
	except Exception:
		frappe.log_error(f"Could not save {number} on {party}", "Cosmetics POS")


@frappe.whitelist(methods=["POST"])
def send_statement(
	party_type: str,
	party: str,
	from_date: str | None = None,
	to_date: str | None = None,
	to: str | None = None,
	message: str | None = None,
) -> dict:
	"""WhatsApp the statement as a PDF, to the number on the record."""
	from cosmestics.api.notifications import send_file, send_text

	data = statement(party_type, party, from_date, to_date)
	number = (to or data.get("mobile_no") or "").strip()
	if not number:
		frappe.throw(
			_("{0} has no phone number on file. Add one on the record and send it again.").format(
				data["title"]
			)
		)
	# A number typed into the send box is worth keeping: the next statement, and
	# every receipt after it, then has somewhere to go.
	if to and not _reachable_number(party):
		_remember_number(party_type, party, number)

	body = (message or "").strip() or _(STATEMENT_MESSAGE)
	html = statement_html(party_type, party, from_date, to_date)
	url = _publish_statement_pdf(html, f"Statement-{party}-{data['to_date']}")

	if not url:
		# The figures still reach them, which beats silence.
		sent = send_text(number, f"{body}\n\n{data['title']}: {frappe.utils.fmt_money(flt(data['closing']), currency=data.get('currency'))}")
		return {"sent": bool(sent), "attached": False, "to": number,
			"message": _("Statement could not be rendered; the balance was sent as a message instead.")}

	sent = send_file(number, body, url, f"statement-{frappe.scrub(party)}.pdf")
	return {
		"sent": bool(sent),
		"attached": True,
		"to": number,
		"message": _("Statement sent to {0}").format(number)
		if sent
		else _("WhatsApp would not take the statement — check the Error Log"),
	}


def _publish_statement_pdf(html: str, title: str) -> str | None:
	"""Render the statement and expose it for the bridge to fetch.

	Public, like every other file the bridge collects: waclient pulls it over
	plain HTTP with no session, so a private file would come back as a login
	page. Unguessable, and deleted is not attempted — a statement is the
	customer's own figures, and the link is what they are being sent.
	"""
	content = _render_pdf(html)
	if content is None:
		return None
	try:
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{frappe.scrub(title)}.pdf",
				"content": content,
				"is_private": 0,
			}
		).insert(ignore_permissions=True)
		return frappe.utils.get_url(doc.file_url)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Cosmetics POS")
		return None


def _render_pdf(html: str):
	"""HTML to PDF, by whichever renderer this site actually has.

	Frappe v16 ships two: wkhtmltopdf and a headless-Chrome generator. Which one
	is present depends on the host — Frappe Cloud has both, a laptop often has
	neither — so both are tried rather than assuming, and the caller falls back
	to sending the figures as text if neither answers.
	"""
	from frappe.utils.pdf import get_pdf

	try:
		return get_pdf(html)
	except Exception:
		pass
	try:
		from frappe.utils.pdf import get_chrome_pdf

		return get_chrome_pdf(None, html, {}, None, pdf_generator="chrome")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Cosmetics POS")
		return None
