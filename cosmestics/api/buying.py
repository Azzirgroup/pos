"""Buying stock in, in two hands.

The shop's own purchasing loop, and the reason it exists is a complaint: the
generic document hub could raise a Purchase Invoice, but doing it meant knowing
that a purchase *is* a Purchase Invoice, that it wants `update_stock`, and that
submitting is irreversible. Staff were asked to be accountants.

What they actually do is simpler and has two people in it:

1. **The manager posts the purchase.** Supplier, what was bought, what it cost.
   It saves as a **draft** — nothing is received, nothing is owed, and it can be
   corrected as many times as it takes.
2. **The store keeper counter-checks it against what turned up**, adjusts the
   quantities where the delivery was short or over, and **confirms**. Confirming
   is what submits the invoice: the stock lands and the payable is booked in one
   act, by the person who actually saw the cartons.

Nobody can do both halves unless they hold both roles — see
`cosmestics.permissions` for why those roles are this app's own rather than
ERPNext's.

## Why a Purchase Invoice with `update_stock`, and not a Receipt plus a bill

One document, one confirmation, one thing to explain. A Purchase Receipt would
leave the goods "received but not billed" and the money owed invisible until
somebody raised a second document nobody in this shop is going to raise. The
same reasoning as `sourcing._make_purchase_invoice`, which buys from the shop
next door the same way.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from cosmestics.permissions import (
	PURCHASE_MANAGER,
	STORE_KEEPER,
	is_purchase_manager,
	is_store_keeper,
	require,
)

#: What a row is waiting for, in the shop's words rather than `docstatus`.
PENDING = "Pending confirmation"
CONFIRMED = "Confirmed"
CANCELLED = "Cancelled"

STAGE_BY_DOCSTATUS = {0: PENDING, 1: CONFIRMED, 2: CANCELLED}


def _company() -> str:
	company = (
		frappe.defaults.get_user_default("Company")
		or frappe.defaults.get_global_default("company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)
	if not company:
		frappe.throw(_("No default company is set"))
	return company


def _warehouse() -> str:
	"""Where bought stock lands — the same one the till sells out of.

	Resolved through `pos.selling_warehouse` rather than looked up here, for the
	reason spelled out in `sourcing._sourcing_warehouse`: goods received into a
	warehouse the till does not sell from are goods the shop cannot find.
	"""
	from cosmestics.api.pos import selling_warehouse

	warehouse = selling_warehouse()
	if not warehouse:
		frappe.throw(
			_(
				"No warehouse to receive stock into. Give this till's POS Profile a "
				"warehouse, or set a Sourcing Warehouse in Settings."
			)
		)
	return warehouse


# --------------------------------------------------------------------------
# Reading the day
# --------------------------------------------------------------------------


@frappe.whitelist()
def day_purchases(on_date: str | None = None, search: str | None = None, limit: int = 200) -> dict:
	"""Everything bought on one day, and what each one is waiting for.

	Defaults to **today**, which is the whole change: the screen used to open on
	the last thirty days and a manager checking what came in this morning had to
	read past a month to find it. Pass `on_date` to page back — that is what the
	calendar on the screen sends.

	Neighbour purchases are listed alongside the rest rather than filtered out.
	They are real purchases with real money against them, and a "total purchase
	cost" that quietly omits them is a figure that does not reconcile with the
	payables it sits next to. They carry `neighbour: true` so the row can say so.
	"""
	day = getdate(on_date) if on_date else getdate(nowdate())
	company = _company()

	filters = {
		"company": company,
		"docstatus": ("<", 2),
		"is_return": 0,
		"posting_date": day,
	}

	or_filters = None
	if search:
		or_filters = [
			{"name": ("like", f"%{search}%")},
			{"supplier": ("like", f"%{search}%")},
			{"supplier_name": ("like", f"%{search}%")},
			{"bill_no": ("like", f"%{search}%")},
		]

	rows = frappe.get_all(
		"Purchase Invoice",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"supplier",
			"supplier_name",
			"posting_date",
			"bill_no",
			"grand_total",
			"outstanding_amount",
			"docstatus",
			"status",
			"owner",
			"modified",
			"remarks",
		],
		order_by="docstatus asc, modified desc",
		limit_page_length=min(max(cint(limit) or 200, 1), 500),
	)

	names = [r.name for r in rows]
	lines = _line_summaries(names)
	neighbours = _neighbour_suppliers({r.supplier for r in rows})

	out = []
	for r in rows:
		summary = lines.get(r.name) or {"text": "", "count": 0, "qty": 0.0}
		out.append(
			{
				"name": r.name,
				"supplier": r.supplier,
				"supplier_name": r.supplier_name or r.supplier,
				"posting_date": str(r.posting_date),
				"bill_no": r.bill_no,
				"grand_total": flt(r.grand_total),
				"outstanding": flt(r.outstanding_amount),
				"docstatus": r.docstatus,
				"stage": STAGE_BY_DOCSTATUS.get(r.docstatus, r.status),
				"status": r.status,
				"posted_by": r.owner,
				"remarks": r.remarks,
				"items": summary["text"],
				"item_count": summary["count"],
				"total_qty": summary["qty"],
				"neighbour": r.supplier in neighbours,
			}
		)

	pending = [r for r in out if r["docstatus"] == 0]
	confirmed = [r for r in out if r["docstatus"] == 1]

	return {
		"rows": out,
		"date": str(day),
		"is_today": day == getdate(nowdate()),
		"totals": {
			# Every purchase posted on this day, whether or not it is confirmed —
			# "how many purchases today" is a question about activity, not about
			# what has cleared.
			"count": len(out),
			# Confirmed only. A draft has bought nothing yet: counting it as cost
			# would have the figure fall when a short delivery is corrected down,
			# which reads as money appearing out of nowhere.
			"cost": flt(sum(r["grand_total"] for r in confirmed)),
			"pending": len(pending),
			"confirmed": len(confirmed),
			"pending_value": flt(sum(r["grand_total"] for r in pending)),
			# The standing figure, not the day's. What the shop owes its suppliers
			# does not reset at midnight, and a card that said "owed today" would
			# read zero on the morning after the invoice that matters.
			"owed": _owed_to_suppliers(company),
		},
		"can": {
			"post": is_purchase_manager(),
			"confirm": is_store_keeper(),
		},
	}


def _owed_to_suppliers(company: str) -> float:
	total = frappe.db.sql(
		"""select sum(outstanding_amount) from `tabPurchase Invoice`
		   where docstatus = 1 and company = %s and outstanding_amount > 0""",
		(company,),
	)
	return flt(total[0][0] if total and total[0] else 0)


def _line_summaries(names: list) -> dict:
	"""What each purchase bought, in one query rather than one per row."""
	if not names:
		return {}

	out = {}
	for row in frappe.get_all(
		"Purchase Invoice Item",
		filters={"parent": ("in", names)},
		fields=["parent", "item_name", "qty"],
		order_by="idx asc",
		limit_page_length=0,
	):
		acc = out.setdefault(row.parent, {"parts": [], "count": 0, "qty": 0.0})
		acc["count"] += 1
		acc["qty"] += flt(row.qty)
		if len(acc["parts"]) < 4:
			acc["parts"].append(f"{flt(row.qty):g} × {row.item_name}")

	for name, acc in out.items():
		more = acc["count"] - len(acc["parts"])
		acc["text"] = ", ".join(acc["parts"]) + (f" +{more} more" if more > 0 else "")

	return out


def _neighbour_suppliers(suppliers: set) -> set:
	if not suppliers:
		return set()
	return set(
		frappe.get_all(
			"Supplier",
			filters={"name": ("in", list(suppliers)), "cosmestics_is_neighbour_shop": 1},
			pluck="name",
		)
	)


@frappe.whitelist()
def get_purchase(name: str) -> dict:
	"""One purchase, opened for reading, editing or counter-checking.

	The same payload serves all three. Which of them the caller may actually do
	is `can`, resolved here from the role and the document's state together —
	the screen should not have to know that a submitted invoice cannot be edited
	or that only today's can be reopened.
	"""
	doc = frappe.get_doc("Purchase Invoice", name)
	doc.check_permission("read")

	return {
		"name": doc.name,
		"supplier": doc.supplier,
		"supplier_name": doc.supplier_name or doc.supplier,
		"posting_date": str(doc.posting_date),
		"bill_no": doc.bill_no,
		"remarks": doc.remarks,
		"docstatus": doc.docstatus,
		"stage": STAGE_BY_DOCSTATUS.get(doc.docstatus, doc.status),
		"status": doc.status,
		"grand_total": flt(doc.grand_total),
		"outstanding": flt(doc.outstanding_amount),
		"posted_by": doc.owner,
		"items": [
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"qty": flt(row.qty),
				"rate": flt(row.rate),
				"amount": flt(row.amount),
				"uom": row.uom or row.stock_uom,
			}
			for row in doc.items
		],
		"can": {
			"edit": doc.docstatus == 0 and is_purchase_manager(),
			"confirm": doc.docstatus == 0 and is_store_keeper(),
			"delete": doc.docstatus == 0 and is_purchase_manager(),
			"reopen": _reopenable(doc) and is_purchase_manager(),
		},
	}


def _reopenable(doc) -> bool:
	"""Whether a confirmed purchase may still be pulled back for correction.

	Only today's, and only while nothing has been paid against it. The shop
	asked to be able to fix what was received "for that day", and that boundary
	is the right one: a purchase from last week has been counted in a closing,
	possibly paid, and unpicking it is a job for the desk with somebody watching.
	"""
	return (
		doc.docstatus == 1
		and not doc.get("is_return")
		and getdate(doc.posting_date) == getdate(nowdate())
		and flt(doc.outstanding_amount) >= flt(doc.grand_total)
	)


# --------------------------------------------------------------------------
# Posting, correcting, confirming
# --------------------------------------------------------------------------


def _clean_lines(items, keep_zeros: bool = False) -> list:
	"""The lines a caller sent, with the rubbish taken out.

	`keep_zeros` is the difference between the two ways lines arrive, and
	dropping it was a bug worth naming. A **manager** editing a purchase has
	sent the whole document, so a line at zero is a line they removed and it can
	go. A **store keeper** counting is saying something about each line, and zero
	is the most important thing they can say — "none of this arrived". Filtering
	those out before `_apply_counted_quantities` sees them meant the loop never
	found the item, left the original quantity alone, and the shop confirmed
	receipt of goods that were never delivered.
	"""
	if isinstance(items, str):
		items = frappe.parse_json(items)

	cleaned = []
	for row in items or []:
		code = (row.get("item_code") or "").strip()
		qty = flt(row.get("qty"))
		if not code:
			continue
		if qty <= 0 and not keep_zeros:
			continue
		cleaned.append({"item_code": code, "qty": max(qty, 0), "rate": flt(row.get("rate"))})

	if not any(row["qty"] > 0 for row in cleaned):
		frappe.throw(_("Add at least one item with a quantity above zero"))
	return cleaned


@frappe.whitelist(methods=["POST"])
def create_purchase(
	supplier: str,
	items: list | str,
	posting_date: str | None = None,
	bill_no: str | None = None,
	remarks: str | None = None,
) -> dict:
	"""Post a purchase, as a draft, for the store keeper to check against.

	Deliberately **not** submitted. Everywhere else in this app a document is
	submitted the moment it is raised, because a cashier at a counter has
	finished the thing they were doing. Here they have not: the goods are on a
	van, or in boxes nobody has opened, and the whole point of the review the
	shop asked for is that somebody counts them first.
	"""
	require(PURCHASE_MANAGER, _("Only a purchase manager can post a purchase."))

	supplier = (supplier or "").strip()
	if not supplier:
		frappe.throw(_("Choose the supplier"))
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("{0} is not a supplier").format(supplier))

	lines = _clean_lines(items)
	warehouse = _warehouse()

	doc = frappe.new_doc("Purchase Invoice")
	doc.company = _company()
	doc.supplier = supplier
	doc.posting_date = getdate(posting_date) if posting_date else nowdate()
	doc.set_posting_time = 1
	# Receives the stock and books the payable in one submit — see the module
	# docstring.
	doc.update_stock = 1
	doc.set_warehouse = warehouse
	doc.bill_no = bill_no
	doc.remarks = remarks

	for line in lines:
		doc.append("items", {**line, "warehouse": warehouse})

	doc.insert()

	return get_purchase(doc.name) | {
		"message": _("{0} saved — waiting for the store to confirm what arrived").format(doc.name)
	}


@frappe.whitelist(methods=["POST"])
def update_purchase(name: str, values: dict | str) -> dict:
	"""Correct a purchase that has not been confirmed yet.

	Open to the manager who raised it and to the store keeper who is checking
	it, but not to the same extent: the manager may change anything, while the
	store keeper may only change **quantities**. That split is the arrangement
	the shop described — the store says what turned up, not what it should have
	cost — and it is enforced here rather than by hiding fields, because a
	hidden field is not a rule.
	"""
	if isinstance(values, str):
		values = frappe.parse_json(values)
	values = values or {}

	doc = frappe.get_doc("Purchase Invoice", name)
	doc.check_permission("write")

	if doc.docstatus != 0:
		frappe.throw(
			_("{0} has already been confirmed. Reopen it first if it needs correcting.").format(name)
		)

	manager = is_purchase_manager()
	if not manager and not is_store_keeper():
		frappe.throw(
			_("Only a purchase manager or a store keeper can change a purchase."),
			frappe.PermissionError,
		)

	if manager:
		if values.get("supplier"):
			if not frappe.db.exists("Supplier", values["supplier"]):
				frappe.throw(_("{0} is not a supplier").format(values["supplier"]))
			doc.supplier = values["supplier"]
		if values.get("posting_date"):
			doc.posting_date = getdate(values["posting_date"])
			doc.set_posting_time = 1
		for field in ("bill_no", "remarks"):
			if field in values:
				doc.set(field, values[field])

	if "items" in values:
		lines = _clean_lines(values["items"])
		if manager:
			warehouse = doc.set_warehouse or _warehouse()
			doc.items = []
			for line in lines:
				doc.append("items", {**line, "warehouse": warehouse})
		else:
			# Re-read keeping the zeros — see `_clean_lines`. A store keeper's zero
			# means "none of this came", and it has to reach the loop below to say
			# so.
			_apply_counted_quantities(doc, _clean_lines(values["items"], keep_zeros=True))

	doc.save()

	return get_purchase(doc.name) | {"message": _("{0} updated").format(doc.name)}


def _apply_counted_quantities(doc, lines: list):
	"""Take the store keeper's count, and nothing else from it.

	Quantities only, matched by item. A line they did not send is left alone
	rather than deleted — the sheet may be showing a filtered view, and a
	silently dropped line is stock the shop paid for and cannot account for. To
	remove a line outright the store keeper sets it to zero, which the loop
	below does explicitly.
	"""
	counted = {row["item_code"]: flt(row["qty"]) for row in lines}

	keep = []
	for row in doc.items:
		if row.item_code in counted:
			row.qty = counted[row.item_code]
		if flt(row.qty) > 0:
			keep.append(row)

	if not keep:
		frappe.throw(
			_(
				"Nothing on {0} was received. Delete the purchase rather than "
				"confirming an empty one."
			).format(doc.name)
		)

	doc.items = keep
	for idx, row in enumerate(doc.items, start=1):
		row.idx = idx


@frappe.whitelist(methods=["POST"])
def confirm_purchase(name: str, items: list | str | None = None, remarks: str | None = None) -> dict:
	"""The store keeper says this is what arrived, and the purchase becomes real.

	Confirming submits the invoice, which is the moment the stock lands on the
	shelf and the money starts being owed. Quantities may be adjusted in the
	same call — that is the ordinary case, not the exception, because a delivery
	that matches the order exactly is the lucky one.
	"""
	require(STORE_KEEPER, _("Only a store keeper can confirm what arrived."))

	doc = frappe.get_doc("Purchase Invoice", name)
	doc.check_permission("submit")

	if doc.docstatus != 0:
		frappe.throw(_("{0} has already been confirmed").format(name))

	if items:
		_apply_counted_quantities(doc, _clean_lines(items, keep_zeros=True))
	if remarks:
		doc.remarks = remarks

	# Saved before submitting rather than submitted straight from the adjusted
	# in-memory document: the totals and the tax rows are recalculated on save,
	# and submitting an unsaved change books the old total against the new
	# quantities.
	doc.save()
	doc.submit()

	return get_purchase(doc.name) | {
		"message": _("{0} confirmed — {1} received").format(
			doc.name, frappe.format_value(flt(doc.grand_total), {"fieldtype": "Currency"})
		)
	}


@frappe.whitelist(methods=["POST"])
def reopen_purchase(name: str) -> dict:
	"""Pull today's confirmed purchase back for correction.

	Cancelled and amended rather than edited in place, because ERPNext will not
	edit a submitted document and pretending otherwise would mean unpicking a
	stock ledger by hand. The amendment is a **new draft** carrying everything
	the original had, named `…-1`, and the original stays in the ledger
	cancelled — which is the honest record: the shop did confirm a wrong figure,
	and then corrected it.

	Restricted to today and to purchases nothing has been paid against; see
	`_reopenable`.
	"""
	require(PURCHASE_MANAGER, _("Only a purchase manager can reopen a purchase."))

	doc = frappe.get_doc("Purchase Invoice", name)
	doc.check_permission("cancel")

	if not _reopenable(doc):
		frappe.throw(
			_(
				"{0} cannot be reopened — only a purchase confirmed today and not yet "
				"paid for. Raise a return against it instead."
			).format(name)
		)

	doc.cancel()

	amended = frappe.copy_doc(doc)
	amended.amended_from = doc.name
	amended.docstatus = 0
	amended.set_posting_time = 1
	amended.posting_date = nowdate()
	amended.insert()

	return get_purchase(amended.name) | {
		"message": _("{0} reopened as {1} — correct it and have the store confirm again").format(
			doc.name, amended.name
		)
	}


@frappe.whitelist(methods=["POST"])
def delete_purchase(name: str) -> dict:
	"""Throw away a draft that should not have been posted.

	Drafts only, so nothing in the ledger is being erased — a draft Purchase
	Invoice has received no stock and booked no payable. A confirmed one is
	reopened and corrected instead.
	"""
	require(PURCHASE_MANAGER, _("Only a purchase manager can delete a purchase."))

	doc = frappe.get_doc("Purchase Invoice", name)
	doc.check_permission("delete")

	if doc.docstatus != 0:
		frappe.throw(_("{0} has been confirmed, so it cannot be deleted").format(name))

	frappe.delete_doc("Purchase Invoice", name)

	return {"name": name, "message": _("{0} deleted").format(name)}


# --------------------------------------------------------------------------
# Filling the form
# --------------------------------------------------------------------------


@frappe.whitelist()
def search_suppliers(search: str | None = None, limit: int = 20) -> list:
	"""Suppliers to buy from, for the link field on the purchase form.

	Its own endpoint rather than a generic "search any doctype": that would be a
	whitelisted way to read every table in the system through one parameter.
	"""
	filters = {"disabled": 0}
	or_filters = (
		[{"name": ("like", f"%{search}%")}, {"supplier_name": ("like", f"%{search}%")}]
		if search
		else None
	)
	rows = frappe.get_all(
		"Supplier",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "supplier_name"],
		order_by="supplier_name asc",
		limit_page_length=min(max(cint(limit) or 20, 1), 50),
	)
	return [{"value": r.name, "label": r.supplier_name or r.name} for r in rows]


@frappe.whitelist()
def search_purchase_items(search: str | None = None, limit: int = 20) -> list:
	"""Stock items, with the last price paid already filled in.

	The rate comes back with the row because the alternative is a second round
	trip the moment a line is added, and because "what did we pay for this last
	time" is the number the person typing actually wants — they correct it when
	the supplier has changed it, which is far less often than they retype it.
	"""
	filters = {"disabled": 0, "is_stock_item": 1}
	or_filters = (
		[{"item_code": ("like", f"%{search}%")}, {"item_name": ("like", f"%{search}%")}]
		if search
		else None
	)
	rows = frappe.get_all(
		"Item",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "item_name", "stock_uom"],
		order_by="item_name asc",
		limit_page_length=min(max(cint(limit) or 20, 1), 50),
	)

	rates = _last_purchase_rates([r.name for r in rows])

	return [
		{
			"value": r.name,
			"label": r.item_name or r.name,
			"item_code": r.name,
			"item_name": r.item_name or r.name,
			"uom": r.stock_uom,
			"rate": rates.get(r.name, 0.0),
		}
		for r in rows
	]


def _last_purchase_rates(codes: list) -> dict:
	"""The most recent rate actually paid for each item, in one query."""
	if not codes:
		return {}

	rows = frappe.db.sql(
		"""select pii.item_code, pii.rate
		   from `tabPurchase Invoice Item` pii
		   join `tabPurchase Invoice` pi on pi.name = pii.parent
		   where pi.docstatus = 1 and pi.is_return = 0
		     and pii.item_code in %(codes)s
		   order by pi.posting_date desc, pi.creation desc""",
		{"codes": tuple(codes)},
		as_dict=True,
	)

	out = {}
	for row in rows:
		out.setdefault(row.item_code, flt(row.rate))
	return out
