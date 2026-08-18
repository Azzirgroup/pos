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
from frappe.utils import add_days, cint, flt, nowdate

from cosmestics.api.search import search_rows

#: How long a till quote stands unless the cashier says otherwise. Short on
#: purpose: a cosmetics shop reprices often, and a quote that outlives its price
#: list is a promise the shop cannot keep.
DEFAULT_VALID_DAYS = 14

#: ERPNext's own words for a quotation nobody is waiting on any more.
#:
#: `Ordered` and `Partially Ordered` are set by ERPNext when a Sales Order is
#: raised against the quote, and by this app's own `mark_converted` — which
#: fills in `ordered_qty` and lets ERPNext reach the conclusion itself, rather
#: than forcing the status, because a forced one silently reverts on the next
#: save (see the note there).
#:
#: `Lost` and `Closed` are a quote the shop has given up on. Both belong with
#: the sold ones: the counter list answers "what have we promised that is still
#: outstanding", and all four of these are answers to a different question.
FINISHED_STATUSES = ("Ordered", "Partially Ordered", "Lost", "Closed")


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
	"""The customer a nameless quote is raised against.

	## The bug this replaces

	It used to ask for `POS Profile` with `{"disabled": 0}` — *any* enabled
	profile, whichever the database happened to return first — and then, failing
	that, for `Customer` with `{"disabled": 0}`, which is **the first customer
	row in the table**. On a shop with a thousand customers that is an arbitrary
	real person, and quoting a walk-in printed their name on the quotation. It
	is the sort of wrong that reads as a mix-up rather than as a bug: the name is
	plausible, it is somebody the shop knows, and nothing on screen says where it
	came from.

	So: this till's own profile first, from the open shift — a warehouse and a
	default customer are properties of the counter, and a second branch's
	profile is not an answer to a question about this one. Then the app's shared
	walk-in customer, which is the same party a walk-in *sale* is booked
	against; a quote and the sale it becomes naming different people is the next
	version of this same complaint.

	Never an arbitrary row. If neither can be resolved the caller says so and
	asks for a customer, which is a question a cashier can answer.
	"""
	from cosmestics.api.pos import _active_pos_profile
	from cosmestics.api.pos import _walk_in_customer as till_walk_in

	profile = _active_pos_profile()
	if profile:
		customer = frappe.db.get_value("POS Profile", profile, "customer")
		if customer:
			return customer

	# No shift open — a quote can perfectly well be given before anybody counts
	# the drawer. A single enabled profile is unambiguous; several are not, and
	# picking between them is exactly the guess that put a stranger's name on a
	# quotation.
	profiles = frappe.get_all(
		"POS Profile", filters={"disabled": 0}, pluck="name", limit_page_length=2
	)
	if len(profiles) == 1:
		customer = frappe.db.get_value("POS Profile", profiles[0], "customer")
		if customer:
			return customer

	try:
		return till_walk_in()
	except Exception:
		# Creating the walk-in customer can fail on a site with no customer group
		# or territory set up. Returning nothing makes the caller ask for a
		# customer by name, which is recoverable; guessing one is not.
		frappe.log_error("Could not resolve a walk-in customer to quote to", "Cosmetics POS")
		return None


@frappe.whitelist()
def list_quotations(
	days: int = 30,
	status: str | None = None,
	search: str | None = None,
	limit: int = 50,
	today_only: int = 0,
	include_sold: int = 0,
) -> dict:
	"""Quotations raised recently, newest first.

	`status` is 'open', 'expired' or 'ordered'. Open is the default because a
	quote that has already been converted or lapsed is history — the one being
	looked for is almost always the one the customer is standing there holding.

	`today_only` narrows to quotes raised today, which is what a cashier at a
	till actually wants: a quote from last week is a back-office concern, and
	the one they are being asked about was given this morning.
	"""
	filters = {
		"docstatus": 1,
		"transaction_date": (">=", add_days(nowdate(), -int(days or 30))),
	}

	if cint(today_only):
		filters["transaction_date"] = nowdate()

	# Asking for the sold ones is asking to see them, whatever `include_sold`
	# happens to say. Without this the two filters cancel out and the "ordered"
	# tab is always empty — the one selection whose entire purpose is the rows
	# the default hides.
	if status == "ordered":
		include_sold = 1

	# A quote that has become a sale is finished business. It stays readable in
	# the desk — and via `include_sold` — but the counter list is about promises
	# still outstanding, and leaving sold ones in it was the complaint.
	#
	# **Two tests, because there are two ways a quote gets taken up.** The custom
	# field is set when the till turns one into a Sales Invoice, which is the
	# path this app owns. It is *not* set when somebody raises a Sales Order
	# against the quote in the desk, or closes it as lost — ERPNext moves the
	# status and knows nothing about our field. Checking only the field left
	# those sitting in the counter list for ever with no way to clear them,
	# which is indistinguishable, from behind the counter, from the till's own
	# conversion having failed.
	if not cint(include_sold):
		filters["cosmestics_converted_invoice"] = ("is", "not set")
		filters["status"] = ("not in", FINISHED_STATUSES)

	if status == "open":
		filters["status"] = ("in", ["Draft", "Open", "Replied"])
	elif status == "expired":
		filters["status"] = "Expired"
	elif status == "ordered":
		filters["status"] = "Ordered"

	SEARCH_FIELDS = ["name", "party_name", "customer_name"]

	def _fetch(or_filters, page_length):
		return frappe.get_all(
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
				# Who gave the price. A customer ringing back asks for the person,
				# not the number, and the shop needs to know whose sale it becomes.
				"owner",
			],
			order_by="transaction_date desc, creation desc",
			limit=page_length,
		)

	rows = search_rows(_fetch, search, SEARCH_FIELDS, min(int(limit or 50), 200))

	today = nowdate()
	# One lookup for every salesperson on the page rather than one per row.
	owners = {r.owner for r in rows if r.owner}
	names = dict(
		frappe.get_all(
			"User", filters={"name": ("in", list(owners))}, fields=["name", "full_name"], as_list=True
		)
	) if owners else {}

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
				"salesperson": names.get(r.owner) or r.owner,
				# The login id as well as the display name. Two staff sharing a
				# full name, or a user with none set, make the chip alone
				# ambiguous — and "the quote says the wrong person raised it" is
				# not answerable without knowing which account it was actually
				# created under.
				"raised_by": r.owner,
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


@frappe.whitelist(methods=["POST"])
def merge(
	names: list | str,
	customer: str | None = None,
	valid_days: int | None = None,
	notes: str | None = None,
) -> dict:
	"""Combine several quotes into one, and close the originals.

	A customer who was quoted three times over a fortnight wants one number to
	agree to, not three to reconcile. This raises a new quotation holding every
	line, then closes the sources as Lost with a reason naming the replacement —
	so the history stays readable rather than three quotes silently going quiet.

	## The rules, and why

	* **One name on the result.** Quotes for different people can be merged — a
	  household or a business often collects several under different names — but
	  the merged document carries exactly one, so `customer` says which. Asked
	  for rather than guessed: picking the first would put a stranger's name on
	  somebody's bill. It must be one of the names already on these quotes.
	* **Same item at the same price is one line.** Two quotes for three lipsticks
	  each become one line of six, which is what a merged bill is for.
	* **Same item at *different* prices stays two lines.** The shop quoted both,
	  and silently picking one would change a price somebody was given. Which to
	  honour is a decision for a person, and they can edit the merged quote.
	* A new document rather than growing the oldest, because every source keeps
	  its own number and a customer holding any of them can be told what replaced
	  it.
	"""
	if isinstance(names, str):
		names = frappe.parse_json(names)

	names = list(dict.fromkeys(names or []))
	if len(names) < 2:
		frappe.throw(_("Pick at least two quotations to merge"))

	docs = []
	for n in names:
		doc = frappe.get_doc("Quotation", n)
		doc.check_permission("write")
		if doc.docstatus != 1:
			frappe.throw(_("{0} is not a submitted quotation").format(n))
		if doc.status not in CLOSEABLE:
			frappe.throw(_("{0} is {1} and cannot be merged").format(n, doc.status))
		docs.append(doc)

	# Who the merged quote is for. Quotes raised for different people *can* be
	# merged — a household or a business often collects several under different
	# names — but which name the single document carries is a decision only the
	# shop can make, so it is asked for rather than guessed.
	parties = list(dict.fromkeys((d.quotation_to, d.party_name) for d in docs))

	if len(parties) > 1:
		if not customer:
			frappe.throw(
				_("These quotations are for {0}. Choose which one the merged quote is for.").format(
					", ".join(p for _t, p in parties)
				),
				title=_("Which customer?"),
			)
		chosen = next((p for p in parties if p[1] == customer), None)
		if not chosen:
			# Restricted to the parties actually involved: merging three quotes onto
			# a fourth, unrelated name would produce a document nobody was quoted.
			frappe.throw(
				_("{0} is not one of the customers on these quotations").format(customer)
			)
	else:
		chosen = parties[0]

	companies = {d.company for d in docs}
	if len(companies) > 1:
		frappe.throw(_("These quotations belong to different companies"))

	# (item, rate) -> qty. Keyed on the pair so a price the customer was actually
	# given is never quietly replaced by another one.
	combined: dict = {}
	for d in docs:
		for row in d.items:
			key = (row.item_code, flt(row.rate))
			combined[key] = combined.get(key, 0) + flt(row.qty)

	party_type, party = chosen

	merged = frappe.new_doc("Quotation")
	merged.company = docs[0].company
	merged.transaction_date = nowdate()
	merged.valid_till = add_days(nowdate(), int(valid_days or DEFAULT_VALID_DAYS))
	merged.order_type = "Sales"
	merged.quotation_to = party_type
	merged.party_name = party
	if docs[0].selling_price_list:
		merged.selling_price_list = docs[0].selling_price_list

	for (item_code, rate), qty in combined.items():
		merged.append("items", {"item_code": item_code, "qty": qty, "rate": rate})

	trail = _("Merged from {0}").format(", ".join(names))
	others = [p for _t, p in parties if p != party]
	if others:
		# Named on the document, because a quote closed under somebody else's name
		# is the one thing here that is not obvious from the numbers alone.
		trail += "\n" + _("Also covers quotations raised for {0}").format(", ".join(others))
	merged.terms = f"{notes}\n\n{trail}" if notes else trail

	merged.insert()
	merged.submit()

	for d in docs:
		# Closed the same way a single quote is, so nothing downstream has to know
		# these were merged rather than lost normally.
		d.declare_enquiry_lost([], [], detailed_reason=_("Merged into {0}").format(merged.name))

	return {
		"name": merged.name,
		"customer": merged.party_name,
		"grand_total": flt(merged.grand_total),
		"valid_till": str(merged.valid_till),
		"items": len(merged.items),
		"merged_from": names,
		"customers": [p for _t, p in parties],
	}


@frappe.whitelist(methods=["POST"])
def update(name: str, items: list | str, valid_days: int | None = None, notes: str | None = None) -> dict:
	"""Change a quote that already exists, keeping its number.

	Loading a quote into the cart, editing it and saving used to raise a *second*
	quotation — so a customer who asked for one more item ended up holding two
	documents with different numbers and different totals, and the shop had to
	work out which one it was honouring. That is the bug this fixes.

	## Why not simply re-save it

	`create` submits, because a quote that cannot be printed is not a quote. A
	submitted document's rows cannot be edited by assignment; ERPNext's own path
	for this is `update_child_qty_rate` — the "Update Items" button on the desk —
	which revalidates pricing and refuses changes that contradict what has
	already been ordered against the quote. Using it means a quote edited at the
	till and one edited at the desk end up in the same state, and the number the
	customer is holding stays the number.

	Amending (cancel, then `-1`) would be the other option and is exactly what
	was complained about: it produces a second document.

	Rows are matched to the existing ones **by item code**, so an unchanged line
	keeps its child row rather than being deleted and re-added — which would
	churn the row names a Sales Order later points at.
	"""
	if isinstance(items, str):
		items = frappe.parse_json(items)

	doc = frappe.get_doc("Quotation", name)
	doc.check_permission("write")

	if doc.docstatus != 1:
		frappe.throw(_("{0} is not a submitted quotation").format(name))
	if doc.status not in CLOSEABLE:
		frappe.throw(
			_("{0} is {1} and can no longer be edited.").format(name, doc.status)
		)

	lines = [row for row in (items or []) if flt(row.get("qty")) > 0]
	if not lines:
		frappe.throw(_("Nothing to quote — every line had no quantity"))

	# Existing rows by item, so an untouched line keeps its identity. Only the
	# first row per item is reused: the cart merges by item, so it cannot produce
	# two lines of the same code at the same unit anyway.
	existing = {}
	for row in doc.items:
		existing.setdefault(row.item_code, row.name)

	trans_items = []
	for idx, row in enumerate(lines, start=1):
		code = row.get("item_code")
		rate = flt(row.get("rate")) * (1 - flt(row.get("discount_pct")) / 100)
		entry = {
			"item_code": code,
			"qty": flt(row.get("qty")),
			"rate": rate,
			"idx": idx,
			# Blank for a line that was not on the quote before — ERPNext reads a
			# missing docname as "this is new".
			"docname": existing.get(code, ""),
		}
		trans_items.append(entry)

	from erpnext.controllers.accounts_controller import update_child_qty_rate

	try:
		update_child_qty_rate("Quotation", frappe.as_json(trans_items), name)
	except (frappe.ValidationError, frappe.PermissionError):
		# ERPNext refusing the edit for a reason it has already worded — "cannot
		# update rate as item X is already ordered", and the like. Those read
		# perfectly well at a counter; wrapping them would bury the sentence
		# somebody needs.
		raise
	except Exception as e:
		# Anything else is a crash inside `update_child_qty_rate`, which walks a
		# long path of ERPNext's own bookkeeping. It arrives at the till as
		# "Internal Server Error" with the reason left in a log nobody at a
		# counter can open — the same failure `documents.create_document`
		# already learned to translate, and for the same reason: the quote is
		# unchanged either way, so this only decides whether the person standing
		# in front of the customer is told anything useful.
		frappe.log_error(
			f"quotations.update({name}) failed\nlines={len(lines)}\n{frappe.get_traceback()}",
			"Cosmetics POS",
		)
		frappe.throw(
			_("Could not update {0}: {1}").format(name, str(e)[:200] or type(e).__name__)
		)

	doc.reload()

	# `valid_till` and `terms` are not `allow_on_submit`, so the document refuses
	# them through the normal path. Written directly because extending a quote's
	# life is the commonest reason to edit one, and refusing it would send the
	# cashier back to raising a second quotation — the very thing this avoids.
	changes = {}
	if valid_days:
		changes["valid_till"] = add_days(nowdate(), int(valid_days))
	if notes is not None:
		changes["terms"] = notes
	if changes:
		doc.db_set(changes, update_modified=True)
		doc.reload()

	return {
		"name": doc.name,
		"customer": doc.party_name,
		"grand_total": flt(doc.grand_total),
		"valid_till": str(doc.valid_till) if doc.valid_till else None,
		"items": len(doc.items),
		"updated": True,
	}


@frappe.whitelist(methods=["POST"])
def mark_converted(name: str, invoice: str) -> dict:
	"""Record that a quote became a sale, and take it out of the open list.

	## Why this is not one `db_set`

	Setting `status = "Ordered"` directly does not stick. ERPNext derives that
	status from `Quotation Item.ordered_qty` (`is_fully_ordered`), and recomputes
	it on any later save — so a forced value survives until the next time
	anything touches the document, then silently reverts to Open.

	So the quantities are filled in and ERPNext's own rule is allowed to reach
	the conclusion. That also keeps the desk's reports honest: Quotation Trends
	and opportunity conversion read the same field.

	The invoice is recorded separately, because `ordered_qty` says *that* a quote
	was taken up and never *by what* — and at a till the answer is a Sales
	Invoice, which is not a document ERPNext ever expects a quotation to point
	at.
	"""
	doc = frappe.get_doc("Quotation", name)
	doc.check_permission("write")

	if not frappe.db.exists("Sales Invoice", invoice):
		frappe.throw(_("{0} not found").format(invoice))
	if doc.docstatus != 1:
		frappe.throw(_("{0} is not a submitted quotation").format(name))
	if doc.get("cosmestics_converted_invoice"):
		return {
			"name": name,
			"status": doc.status,
			"invoice": doc.get("cosmestics_converted_invoice"),
			"message": _("{0} was already sold as {1}").format(
				name, doc.get("cosmestics_converted_invoice")
			),
		}

	# Whole lines, not the part that happened to be sold. A cashier who drops a
	# line before taking payment is not leaving the rest of the quote live —
	# nobody comes back for the remainder of a counter quote, and a half-open
	# quotation sitting in the list for ever is the thing being fixed.
	for row in doc.items:
		frappe.db.set_value("Quotation Item", row.name, "ordered_qty", flt(row.qty), update_modified=False)

	doc.db_set(
		{
			"cosmestics_converted_invoice": invoice,
			"cosmestics_converted_on": frappe.utils.now_datetime(),
		},
		update_modified=False,
	)

	doc.reload()
	doc.set_status(update=True)

	return {
		"name": name,
		"status": doc.status,
		"invoice": invoice,
		"message": _("{0} sold as {1}").format(name, invoice),
	}


def unmark_converted(invoice: str) -> list:
	"""Put a quote back in the list when its sale is undone.

	A cancelled invoice means the sale did not happen, so the promise stands
	again — leaving the quote marked Ordered would hide a live commitment from
	the counter. Reverses exactly what `mark_converted` wrote.
	"""
	names = frappe.get_all(
		"Quotation", filters={"cosmestics_converted_invoice": invoice}, pluck="name"
	)
	for name in names:
		doc = frappe.get_doc("Quotation", name)
		for row in doc.items:
			frappe.db.set_value("Quotation Item", row.name, "ordered_qty", 0, update_modified=False)
		doc.db_set(
			{"cosmestics_converted_invoice": None, "cosmestics_converted_on": None},
			update_modified=False,
		)
		doc.reload()
		doc.set_status(update=True)
	return names


def on_sales_invoice_cancel(doc, method=None):
	"""Hooked on Sales Invoice `on_cancel` — see `unmark_converted`.

	Best-effort: a quotation that cannot be reopened must never block the
	cancellation of an invoice, which is an accounting act.
	"""
	try:
		unmark_converted(doc.name)
	except Exception:
		frappe.log_error(
			f"Could not reopen the quotation behind {doc.name}", "Cosmetics POS"
		)


#: Statuses a quotation can still be closed from. `Ordered` and
#: `Partially Ordered` are excluded because ERPNext refuses them outright — a
#: quote that became a sale is not a quote anybody is still waiting on.
CLOSEABLE = ("Draft", "Open", "Replied", "Expired")


@frappe.whitelist(methods=["POST"])
def close(name: str, reason: str | None = None) -> dict:
	"""Stop chasing a quotation the customer is not coming back for.

	Recorded as **Lost**, which is ERPNext's word for it — there is no separate
	"Closed" status on a Quotation, and inventing one with a Custom Field would
	put a state in the app that none of ERPNext's own reporting understands.
	`declare_enquiry_lost` is what the desk calls too, so a quote closed here and
	one closed there end up identical.

	The reason is free text and optional. ERPNext's structured
	`Quotation Lost Reason` list is left empty deliberately: it throws on any
	value not already in that master, and a cashier told "invalid lost reason"
	while clearing a stale quote has no way to fix it.
	"""
	doc = frappe.get_doc("Quotation", name)
	doc.check_permission("write")

	if doc.docstatus == 2:
		frappe.throw(_("{0} is cancelled").format(name))
	if doc.status == "Lost":
		return {"name": name, "status": doc.status, "message": _("{0} is already closed").format(name)}
	if doc.status not in CLOSEABLE:
		frappe.throw(
			_("{0} is {1} and cannot be closed — it has already become an order.").format(
				name, doc.status
			)
		)

	# A draft was never given to anybody, so there is nothing to lose; cancelling
	# it is the honest record. ERPNext also refuses `Lost` on a docstatus 0 doc.
	if doc.docstatus == 0:
		doc.delete()
		return {"name": name, "status": "Deleted", "message": _("Draft {0} discarded").format(name)}

	doc.declare_enquiry_lost([], [], detailed_reason=reason or None)

	return {
		"name": name,
		"status": "Lost",
		"message": _("{0} closed").format(name),
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
	notifications._remember_failure(None)
	sent = notifications.send_document(
		"Quotation", name, to, message=format_quotation(doc), sender=sender
	)
	# The actual reason, the same way `notifications.share` reports one — an
	# expired token and a number that is not on WhatsApp both used to arrive as
	# "check the WhatsApp settings", and only one of them is about settings.
	reason = None if sent else notifications._last_failure()

	return {
		"sent": bool(sent),
		"reason": reason,
		"message": _("Quotation sent to {0}").format(to)
		if sent
		else _("Could not send: {0}").format(reason)
		if reason
		else _("Could not send — check the WhatsApp settings"),
	}


def format_quotation(doc) -> str:
	"""The quote as a table, for the covering message.

	Mirrors the stock request: the customer is reading this on a phone and wants
	the prices, not the document metadata.
	"""
	from cosmestics.api.notifications import _table

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

	# No link. This message goes to a customer, and the link pointed at the
	# shop's own documents screen — useless to them, and an invitation to a
	# login page that says which system the shop runs. Internal posts that do
	# want a link build their own; see `notifications.format_material_request`.
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
