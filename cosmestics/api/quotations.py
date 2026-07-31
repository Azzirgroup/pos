"""Quotations raised at the till, and loaded back into it.

A customer who asks "how much for all this?" and walks away with a number is a
sale that has not happened yet. Until now the only way to keep that cart was to
hold it, which lives in the browser and dies with the tab — so the answer was
either re-rung from memory or lost.

A Quotation is the ERPNext document for exactly this, so it is used rather than
invented: it prints, it carries a validity date, and the accounts team already
knows what one is.

Two directions, deliberately symmetric:

* `create` turns the cart into a Quotation.
* `get` turns a Quotation back into cart lines — the same shape `pos.submit_sale`
  accepts, so a quote becomes a sale without anything being retyped.

Prices are **taken from the quote, not re-fetched**. That is the whole promise of
quoting: the customer was given a number and comes back expecting it. A price
list that moved in between is the shop's problem, not something to spring on
them at the counter — and the margin is still visible because the cost is not.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, nowdate

#: How long a till quote stands unless the cashier says otherwise. Short on
#: purpose: a cosmetics shop reprices often, and a quote that outlives its price
#: list is a promise the shop cannot keep.
DEFAULT_VALID_DAYS = 14


@frappe.whitelist(methods=["POST"])
def create(
	items: list | str,
	customer: str | None = None,
	valid_days: int = DEFAULT_VALID_DAYS,
	notes: str | None = None,
) -> dict:
	"""Turn the current cart into a Quotation.

	`items` is the cart's own shape — [{item_code, qty, rate, discount_pct}] —
	so the till does not have to translate anything on the way out.
	"""
	if isinstance(items, str):
		items = frappe.parse_json(items)

	if not items:
		frappe.throw(_("Nothing to quote — the cart is empty"))

	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default(
		"company"
	)

	party_type, party = _resolve_party(customer, settings)

	doc = frappe.new_doc("Quotation")
	doc.company = company
	doc.transaction_date = nowdate()
	doc.valid_till = add_days(nowdate(), int(valid_days or DEFAULT_VALID_DAYS))
	# "Sales" rather than "Shopping Cart": this is a price given across a counter,
	# not a webshop basket, and the two take different paths through ERPNext.
	doc.order_type = "Sales"
	doc.quotation_to = party_type
	doc.party_name = party

	if settings.selling_price_list:
		doc.selling_price_list = settings.selling_price_list

	for row in items:
		qty = flt(row.get("qty"))
		if qty <= 0:
			continue
		doc.append(
			"items",
			{
				"item_code": row.get("item_code"),
				"qty": qty,
				# The rate the customer was actually quoted, discount included.
				# Sending the list price and a separate discount would let
				# ERPNext re-derive one of them and change the total.
				"rate": flt(row.get("rate")) * (1 - flt(row.get("discount_pct")) / 100),
			},
		)

	if not doc.items:
		frappe.throw(_("Nothing to quote — every line had no quantity"))

	if notes:
		doc.terms = notes

	doc.insert()
	doc.submit()

	return {
		"name": doc.name,
		"customer": doc.party_name,
		"grand_total": flt(doc.grand_total),
		"valid_till": str(doc.valid_till),
		"items": len(doc.items),
	}


#: What a Quotation may be raised to. `quotation_to` is a Link to DocType, so
#: these are doctype names rather than labels, and `party_name` is a Dynamic Link
#: validated against whichever one is chosen.
PARTY_TYPES = ("Customer", "Lead", "Prospect")


def _resolve_party(customer: str | None, settings) -> tuple[str, str]:
	"""Work out what the party actually *is*, rather than assuming.

	This used to hardcode `quotation_to = "Customer"` and hand it whatever the
	till passed. On a site with the CRM app that is wrong often enough to matter:
	a Lead reaches the party field through perfectly ordinary use, and the insert
	then dies on `Could not find Party: CRM-LEAD-…` — a link validation error
	naming a record that exists, just not in the doctype it was being looked up
	in. Deriving the type from the record means a lead can be quoted, which is
	what a lead is *for*.

	Falls back to the till's default customer when nothing usable was given: a
	walk-in asking for a price has no record, and creating a Customer for
	somebody who may never come back fills the master list with ghosts.
	"""
	if customer:
		for party_type in PARTY_TYPES:
			if frappe.db.exists(party_type, customer):
				return party_type, customer
		# Named somebody who is not a party of any kind. Falling through to the
		# walk-in would quote a different customer than the cashier chose, so
		# this says so instead.
		frappe.throw(_("{0} is not a customer, lead or prospect").format(customer))

	default = _walk_in_customer(settings)
	if not default:
		frappe.throw(_("Choose a customer — this site has no default till customer to quote to"))
	return "Customer", default


def _walk_in_customer(settings) -> str | None:
	"""The customer a nameless quote is raised against."""
	profile = frappe.db.get_value("POS Profile", {"disabled": 0}, "customer")
	if profile:
		return profile
	return frappe.db.get_value("Customer", {"disabled": 0}, "name")


@frappe.whitelist()
def list_quotations(
	days: int = 30, status: str | None = None, search: str | None = None, limit: int = 50
) -> dict:
	"""Quotations raised recently, newest first.

	`status` is 'open', 'expired' or 'ordered'. Open is the default because a
	quote that has already been converted or lapsed is history — the one being
	looked for is almost always the one the customer is standing there holding.
	"""
	filters = {
		"docstatus": 1,
		"transaction_date": (">=", add_days(nowdate(), -int(days or 30))),
	}

	if status == "open":
		filters["status"] = ("in", ["Draft", "Open", "Replied"])
	elif status == "expired":
		filters["status"] = "Expired"
	elif status == "ordered":
		filters["status"] = "Ordered"

	or_filters = None
	if search:
		or_filters = {
			"name": ("like", f"%{search}%"),
			"party_name": ("like", f"%{search}%"),
			"customer_name": ("like", f"%{search}%"),
		}

	rows = frappe.get_all(
		"Quotation",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"party_name",
			"customer_name",
			"transaction_date",
			"valid_till",
			"grand_total",
			"status",
			"total_qty",
		],
		order_by="transaction_date desc, creation desc",
		limit=min(int(limit or 50), 200),
	)

	today = nowdate()
	out = []
	for r in rows:
		out.append(
			{
				"name": r.name,
				"customer": r.customer_name or r.party_name,
				"customer_id": r.party_name,
				"date": str(r.transaction_date),
				"valid_till": str(r.valid_till) if r.valid_till else None,
				"grand_total": flt(r.grand_total),
				"total_qty": flt(r.total_qty),
				"status": r.status,
				# Computed rather than trusted: ERPNext only flips a quotation to
				# Expired when its scheduler runs, so a quote that lapsed this
				# morning still reads Open until then.
				"expired": bool(r.valid_till and str(r.valid_till) < today),
			}
		)

	return {
		"rows": out,
		"totals": {
			"count": len(out),
			"value": flt(sum(r["grand_total"] for r in out)),
			"open": len([r for r in out if not r["expired"] and r["status"] != "Ordered"]),
		},
	}


@frappe.whitelist()
def print_url(name: str, print_format: str | None = None) -> dict:
	"""A printable quotation, through ERPNext's own print engine.

	The same route the documents hub uses: a customer handed a quote should get
	the shop's letterhead and tax lines, not a screen rendering that happens to
	look similar.
	"""
	if not frappe.has_permission("Quotation", "print"):
		frappe.throw(_("Not permitted to print quotations"), frappe.PermissionError)
	if not frappe.db.exists("Quotation", name):
		frappe.throw(_("Quotation {0} not found").format(name), frappe.DoesNotExistError)

	params = [
		f"doctype={frappe.utils.quoted('Quotation')}",
		f"name={frappe.utils.quoted(name)}",
		"no_letterhead=0",
		"trigger_print=1",
	]
	if print_format:
		params.append(f"format={frappe.utils.quoted(print_format)}")

	return {"url": frappe.utils.get_url("/printview?" + "&".join(params))}


@frappe.whitelist(methods=["POST"])
def send_whatsapp(name: str, to: str, sender: str | None = None) -> dict:
	"""Send a quotation to the customer, as the real PDF.

	A quote is a promise about prices, and a customer holding a screenshot of a
	summary has no way to hold the shop to it. The document itself goes.
	"""
	from cosmestics.api import notifications

	if not frappe.db.exists("Quotation", name):
		frappe.throw(_("Quotation {0} not found").format(name), frappe.DoesNotExistError)
	if not to:
		frappe.throw(_("Say where to send it"))

	doc = frappe.get_doc("Quotation", name)
	sent = notifications.send_document(
		"Quotation", name, to, message=format_quotation(doc), sender=sender
	)

	return {
		"sent": bool(sent),
		"message": _("Quotation sent to {0}").format(to)
		if sent
		else _("Could not send — check the WhatsApp settings"),
	}


def format_quotation(doc) -> str:
	"""The quote as a table, for the covering message.

	Mirrors the stock request: the customer is reading this on a phone and wants
	the prices, not the document metadata.
	"""
	from cosmestics.api.notifications import _table, app_url

	rows = []
	for item in doc.items:
		name = item.item_name or item.item_code
		rows.append(
			[
				f"{flt(item.qty):g}",
				name if len(name) <= 22 else name[:21] + "…",
				f"{flt(item.rate):,.0f}",
				f"{flt(item.amount):,.0f}",
			]
		)

	lines = [
		"*Quotation*",
		f"{doc.name} · {doc.customer_name or doc.party_name}",
		"",
		_table(["Qty", "Item", "Rate", "Amount"], rows),
		f"Total: {flt(doc.grand_total):,.0f}",
	]
	if doc.valid_till:
		lines.append(f"Valid until {doc.valid_till}")
	lines.append("")
	lines.append(app_url("/documents/quotation"))

	return "\n".join(lines)


@frappe.whitelist()
def get(name: str) -> dict:
	"""One quotation, as cart lines.

	The returned `items` are the shape the cart holds, so loading a quote is a
	straight assignment rather than a translation the till has to get right.

	Items that are no longer sellable are reported separately instead of being
	dropped silently — a quote whose lines quietly vanish is worse than one that
	says which line cannot be honoured.
	"""
	doc = frappe.get_doc("Quotation", name)
	if not frappe.has_permission("Quotation", "read", doc=doc.name):
		frappe.throw(_("You do not have permission to open {0}").format(name))

	items = []
	unavailable = []
	for row in doc.items:
		sellable = frappe.db.get_value(
			"Item", row.item_code, ["item_name", "is_sales_item", "disabled", "stock_uom"], as_dict=True
		)
		if not sellable or sellable.disabled or not sellable.is_sales_item:
			unavailable.append({"item_code": row.item_code, "item_name": row.item_name})
			continue

		items.append(
			{
				"item_code": row.item_code,
				"item_name": sellable.item_name or row.item_name,
				"qty": flt(row.qty),
				# The quoted rate, honoured as quoted. Re-pricing here would make
				# the quote a suggestion rather than a promise.
				"rate": flt(row.rate),
				"uom": row.uom or sellable.stock_uom,
			}
		)

	return {
		"name": doc.name,
		"customer": doc.customer_name or doc.party_name,
		# Only handed back when the party really is a Customer. A quote raised to
		# a Lead is legitimate, but a Sales Invoice cannot be — so loading one
		# into the cart must not silently seat a Lead in the customer slot and
		# fail at checkout instead.
		"customer_id": doc.party_name if doc.quotation_to == "Customer" else None,
		"party_type": doc.quotation_to,
		"date": str(doc.transaction_date),
		"valid_till": str(doc.valid_till) if doc.valid_till else None,
		"grand_total": flt(doc.grand_total),
		"status": doc.status,
		"expired": bool(doc.valid_till and str(doc.valid_till) < nowdate()),
		"items": items,
		"unavailable": unavailable,
	}
