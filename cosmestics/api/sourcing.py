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
from frappe.utils import add_days, flt, nowdate


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
				f"Could not record the till movement for {inv['name']}", "Cosmetics POS"
			)

	return recorded


#: How the money comes back when goods do. Anything else is refused rather than
#: guessed at — see `return_to_neighbour`.
REFUND_METHODS = ("account", "cash")


@frappe.whitelist(methods=["POST"])
def return_to_neighbour(
	invoice: str,
	lines: list | str | None = None,
	reason: str | None = None,
	refund_method: str = "account",
	refund_mode: str | None = None,
) -> dict:
	"""Send stock back to the shop it was bought from.

	Trade between neighbouring shops runs both ways: what was bought to complete
	a sale that then fell through goes back, and the debt for it has to go with
	it. Until now the purchase could be made from the till but never undone, so
	the payable stood against goods sitting on the wrong shelf.

	A **return Purchase Invoice** rather than a cancellation. Cancelling would
	erase the fact that the goods were ever received, which is wrong — they were,
	and for a while they were on our shelf. A return records the movement in the
	other direction, leaves both documents in the ledger, and nets the payable
	down by exactly what went back.

	## Where the money goes, which is the part the till has to ask about

	`refund_method='account'` leaves it between the two shops: the return nets
	the payable down, so the next thing bought from them is that much cheaper to
	settle. This is right for the usual arrangement, where neighbours run a tab
	and square up at the end of the week — and it is the only option at all when
	the purchase was never paid for, because there is no money to hand back.

	`refund_method='cash'` is the shop next door handing the money back over the
	counter. It marks the return paid through `refund_mode` — the Mode of
	Payment, which is what picks the account the money lands in — and tells the
	open shift that cash came *in*, so the drawer is expected to hold that much
	more at closing. Without that last part the count would come up over by
	exactly the refund and read as an unexplained surplus.

	`lines` is [{item_code, qty}] for a partial return; omit it to send back
	everything on the invoice.
	"""
	if isinstance(lines, str):
		lines = frappe.parse_json(lines)

	if refund_method not in REFUND_METHODS:
		frappe.throw(_("{0} is not a way to take a refund").format(refund_method))

	original = frappe.get_doc("Purchase Invoice", invoice)
	if original.docstatus != 1:
		frappe.throw(_("{0} is not a submitted purchase").format(invoice))
	if original.get("is_return"):
		frappe.throw(_("{0} is already a return").format(invoice))

	_assert_neighbour(original.supplier)

	# What is still returnable: what came in, less whatever already went back.
	returned = _already_returned(invoice)
	wanted = {r["item_code"]: flt(r.get("qty")) for r in (lines or [])}

	doc = frappe.new_doc("Purchase Invoice")
	doc.supplier = original.supplier
	doc.company = original.company
	doc.posting_date = nowdate()
	doc.set_posting_time = 1
	doc.is_return = 1
	doc.return_against = original.name
	# Mirrors the original: it received stock, so the return has to issue it back
	# out or the shelf keeps goods that are no longer ours.
	doc.update_stock = original.update_stock
	doc.set_warehouse = original.set_warehouse
	doc.remarks = reason or _("Returned to {0}").format(original.supplier)

	for row in original.items:
		available = flt(row.qty) - returned.get(row.item_code, 0)
		qty = wanted.get(row.item_code, available) if lines else available
		if qty <= 0:
			continue
		if qty > available:
			frappe.throw(
				_("Only {0} of {1} is still returnable on {2}").format(
					available, row.item_code, invoice
				)
			)
		doc.append(
			"items",
			{
				"item_code": row.item_code,
				# Negative, which is what makes it a return to ERPNext.
				"qty": -abs(qty),
				"rate": flt(row.rate),
				"warehouse": row.warehouse,
				"purchase_invoice_item": row.name,
			},
		)

	if not doc.items:
		frappe.throw(_("Nothing left to return on {0}").format(invoice))

	mode = None
	if refund_method == "account":
		# Book the debit note against the original rather than against itself,
		# which is what "comes off what you owe them" means. ERPNext defaults the
		# other way — the return carries its own negative outstanding and the
		# purchase still reads as fully owed, so the shop next door appears to be
		# owed money for goods sitting back on their shelf until somebody runs a
		# payment reconciliation. It flips itself back if the return is worth more
		# than is still owed, which is the one case where netting cannot work.
		doc.update_outstanding_for_self = 0

	if refund_method == "cash":
		mode = refund_mode or original.mode_of_payment or _default_mode_of_payment(original.company)
		doc.set_missing_values()
		doc.calculate_taxes_and_totals()
		_assert_cash_is_owed_back(original, abs(flt(doc.grand_total)))
		doc.is_paid = 1
		doc.mode_of_payment = mode
		doc.cash_bank_account = _paid_from_account(original.company, mode)
		# Set explicitly, and negative to match the document: ERPNext never fills
		# `paid_amount` itself on a Purchase Invoice — the desk form does it in
		# JavaScript — and an is_paid invoice with a zero paid amount books no
		# payment at all while still reporting itself as settled.
		doc.paid_amount = flt(doc.rounded_total or doc.grand_total)

	doc.insert()
	doc.submit()

	total = abs(flt(doc.grand_total))
	movement = _record_till_refund(doc, mode, total) if refund_method == "cash" else None

	return {
		"name": doc.name,
		"against": original.name,
		"supplier": doc.supplier,
		# Negative on the document; reported as a positive magnitude because the
		# cashier is being told how much went back, not signing a ledger.
		"total": total,
		"items": len(doc.items),
		"refund_method": refund_method,
		"refund_mode": mode,
		"movement": movement,
	}


def _assert_cash_is_owed_back(original, amount):
	"""Refuse to take cash back that was never handed over.

	A purchase still on the tab has nothing to refund — sending goods back just
	reduces what is owed. Taking cash for it as well would have the shop next
	door paying us for stock we never paid them for, and the drawer would come up
	over with nothing to explain it.
	"""
	paid = flt(original.grand_total) - flt(original.outstanding_amount)
	already_back = _cash_already_refunded(original.name)
	left = flt(paid - already_back)

	if left <= 0:
		frappe.throw(
			_(
				"{0} has not been paid for, so there is no cash to take back. "
				"Send the stock back against the account instead — it comes off what you owe."
			).format(original.name)
		)
	if amount > left + 0.005:
		frappe.throw(
			_(
				"Only {0} of {1} was paid in cash, so that is the most that can come "
				"back. Return the rest against the account."
			).format(frappe.format_value(left, {"fieldtype": "Currency"}), original.name)
		)


def _cash_already_refunded(invoice: str) -> float:
	"""What earlier returns against this purchase already took back in cash."""
	rows = frappe.get_all(
		"Purchase Invoice",
		filters={"return_against": invoice, "docstatus": 1, "is_return": 1, "is_paid": 1},
		pluck="grand_total",
	)
	return flt(sum(abs(flt(r)) for r in rows))


def _record_till_refund(doc, mode, total):
	"""Tell the open shift that cash came back in for this return.

	The mirror of `_record_till_payments`, and silent in the same way when no
	shift is open: the goods and the refund are already posted, and a drawer
	figure that has to be corrected at closing beats a return that fails after
	the money has changed hands.
	"""
	from cosmestics.api.shift import get_open_shift, post_movement

	if total <= 0 or not get_open_shift():
		return None

	try:
		return post_movement(
			movement_type="Neighbour Refund",
			amount=total,
			mode_of_payment=mode,
			party=doc.supplier,
			reason=_("{0} refunded for {1}").format(doc.supplier, doc.name),
			reference_doctype="Purchase Invoice",
			reference_name=doc.name,
		)
	except Exception:
		frappe.log_error(f"Could not record the till refund for {doc.name}", "Cosmetics POS")
		return None


@frappe.whitelist(methods=["POST"])
def neighbour_customer(supplier: str) -> dict:
	"""The Customer record for a neighbouring shop, created if it has none.

	Trade between neighbours runs both ways — they sell to us when we are short,
	and we sell to them when they are. ERPNext keeps buying and selling parties
	in separate doctypes, so a shop we buy from cannot be sold to until it also
	exists as a Customer. Rather than making a cashier notice that and go create
	one, this pairs them on first use.

	Named identically on purpose: two records for one shop that do not share a
	name is how a debt gets chased twice, or not at all.
	"""
	_assert_neighbour(supplier)

	if frappe.db.exists("Customer", supplier):
		return {"customer": supplier, "created": False}

	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	if not group:
		frappe.throw(_("No customer group exists to file {0} under").format(supplier))

	doc = frappe.new_doc("Customer")
	doc.customer_name = supplier
	doc.customer_group = group
	if territory:
		doc.territory = territory
	doc.customer_type = "Company"
	# Created by the till on behalf of a cashier who is mid-sale, so permissions
	# are bypassed for the same reason `_ensure_supplier` does: refusing here
	# blocks a sale that is already happening.
	doc.insert(ignore_permissions=True)

	return {"customer": doc.name, "created": True}


@frappe.whitelist()
def list_neighbours() -> dict:
	"""Neighbouring shops, and whether each can already be sold to.

	`sellable` says a Customer record exists. The till shows the rest anyway and
	pairs them on selection — the list is about who is next door, not about which
	doctypes happen to exist yet.
	"""
	group = frappe.db.get_single_value("Cosmestics POS Settings", "neighbour_supplier_group")
	if not group:
		return {"rows": [], "reason": "No neighbour supplier group is configured."}

	suppliers = frappe.get_all(
		"Supplier", filters={"supplier_group": group}, pluck="name", order_by="name asc"
	)
	customers = set(
		frappe.get_all("Customer", filters={"name": ("in", suppliers)}, pluck="name")
	) if suppliers else set()

	return {
		"rows": [{"name": s, "sellable": s in customers} for s in suppliers],
		"reason": None if suppliers else "No shops are registered in the neighbour group yet.",
	}


def _assert_neighbour(supplier: str):
	"""Only neighbour purchases may be returned from the till.

	A return to a wholesaler is ordinary purchasing with its own approvals; the
	till has no business issuing one, and this endpoint is reachable by any
	cashier.
	"""
	group = frappe.db.get_single_value("Cosmestics POS Settings", "neighbour_supplier_group")
	if not group:
		frappe.throw(_("No neighbour supplier group is configured"))
	if frappe.db.get_value("Supplier", supplier, "supplier_group") != group:
		frappe.throw(_("{0} is not a neighbouring shop").format(supplier))


def _already_returned(invoice: str) -> dict:
	"""Per item, how much of this invoice has gone back already.

	Without this a second return of the same line would sail through and the
	shop would end up owing a negative amount for goods it never had.
	"""
	rows = frappe.db.sql(
		"""select pii.item_code, sum(abs(pii.qty)) as qty
		   from `tabPurchase Invoice Item` pii
		   join `tabPurchase Invoice` pi on pi.name = pii.parent
		   where pi.docstatus = 1 and pi.is_return = 1 and pi.return_against = %s
		   group by pii.item_code""",
		(invoice,),
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}


@frappe.whitelist()
def returnable(invoice: str) -> dict:
	"""What is still on a neighbour purchase, ready to be sent back.

	Also says how the money can come back, before the cashier picks: cash is only
	on offer for a purchase that was actually paid for, and the modes are the
	ones this company has an account mapped for. Offering an option that then
	throws on submit is the same as not offering it, only slower.
	"""
	original = frappe.get_doc("Purchase Invoice", invoice)
	returned = _already_returned(invoice)

	items = []
	for row in original.items:
		available = flt(row.qty) - returned.get(row.item_code, 0)
		if available <= 0:
			continue
		items.append(
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"qty": available,
				"rate": flt(row.rate),
				"value": flt(row.rate) * available,
			}
		)

	paid_back = flt(
		flt(original.grand_total)
		- flt(original.outstanding_amount)
		- _cash_already_refunded(original.name)
	)
	modes = _refund_modes(original.company)

	return {
		"name": original.name,
		"supplier": original.supplier,
		"posting_date": str(original.posting_date),
		"grand_total": flt(original.grand_total),
		"outstanding": flt(original.outstanding_amount),
		"items": items,
		# How much of this was paid for and could therefore come back as cash.
		"refundable_cash": max(paid_back, 0),
		"can_cash": paid_back > 0,
		"cash_reason": None
		if paid_back > 0
		else _("This purchase is still on the tab, so there is no cash to take back."),
		"refund_modes": modes,
		# Back the way it was paid, which is what the shop next door will do.
		"default_refund_mode": original.mode_of_payment
		or (modes[0]["name"] if modes else None),
	}


def _refund_modes(company: str) -> list[dict]:
	"""Modes of payment the refund can arrive through, with where it lands.

	The account is not a separate question: it follows from the mode, through the
	same Mode of Payment Account mapping every other payment in the app uses. A
	cashier picking "M-PESA" has picked the account, which is why the till asks
	about the mode and not about the chart of accounts.

	Only modes with an account on this company are offered — the rest would fall
	back to the default cash account and quietly book a mobile-money refund as
	notes in the drawer.
	"""
	rows = frappe.get_all(
		"Mode of Payment Account",
		filters={"company": company},
		fields=["parent", "default_account"],
	)
	enabled = set(
		frappe.get_all(
			"Mode of Payment",
			filters={"enabled": 1, "name": ("in", [r.parent for r in rows])},
			pluck="name",
		)
	) if rows else set()

	return [
		{"name": r.parent, "account": r.default_account}
		for r in rows
		if r.parent in enabled and r.default_account
	]


@frappe.whitelist()
def list_purchases(days: int = 30, status: str | None = None, limit: int = 200) -> dict:
	"""Everything bought from a neighbouring shop, and what is still owed.

	The till creates these one at a time with a customer waiting, and nothing
	afterwards ever showed them together. The closing summary lists the ones from
	the shift in front of you; this is the standing question — who have we been
	buying from, and what have we not settled.

	`status` is 'unpaid', 'paid' or None for both. Unpaid is the reason the
	screen exists, so it is the one worth filtering to.
	"""
	group = frappe.db.get_single_value("Cosmestics POS Settings", "neighbour_supplier_group")
	if not group:
		return _empty_purchases("No neighbour supplier group is configured.")

	suppliers = frappe.get_all("Supplier", filters={"supplier_group": group}, pluck="name")
	if not suppliers:
		return _empty_purchases("No shops are registered in the neighbour group yet.")

	filters = {
		"supplier": ("in", suppliers),
		"docstatus": 1,
		"posting_date": (">=", add_days(nowdate(), -int(days or 30))),
	}
	if status == "unpaid":
		filters["outstanding_amount"] = (">", 0)
	elif status == "paid":
		filters["outstanding_amount"] = ("<=", 0)

	rows = frappe.get_all(
		"Purchase Invoice",
		filters=filters,
		fields=[
			"name",
			"supplier",
			"posting_date",
			"grand_total",
			"outstanding_amount",
			"status",
			"owner",
		],
		order_by="posting_date desc, creation desc",
		limit=min(int(limit or 200), 500),
	)

	# The items are what makes a row recognisable — "Ksh 400 to the shop next
	# door" means nothing a week later without knowing what it bought.
	items = {}
	if rows:
		for it in frappe.get_all(
			"Purchase Invoice Item",
			filters={"parent": ("in", [r.name for r in rows])},
			fields=["parent", "item_name", "qty"],
			order_by="idx asc",
		):
			items.setdefault(it.parent, []).append(f"{flt(it.qty):g} × {it.item_name}")

	out = []
	for r in rows:
		out.append(
			{
				"name": r.name,
				"supplier": r.supplier,
				"posting_date": str(r.posting_date),
				"grand_total": flt(r.grand_total),
				"outstanding": flt(r.outstanding_amount),
				"status": r.status,
				"bought_by": r.owner,
				"items": ", ".join(items.get(r.name, [])[:4]),
			}
		)

	return {
		"rows": out,
		"totals": {
			"count": len(out),
			"spend": flt(sum(r["grand_total"] for r in out)),
			"owed": flt(sum(r["outstanding"] for r in out)),
			"shops": len({r["supplier"] for r in out}),
		},
		"suppliers": suppliers,
		"reason": None,
	}


def _empty_purchases(reason):
	"""An empty list with the reason it is empty.

	The same distinction `catalog.sourcing` makes: "nothing bought yet" and
	"this was never set up" look identical on screen and need different actions.
	"""
	return {
		"rows": [],
		"totals": {"count": 0, "spend": 0, "owed": 0, "shops": 0},
		"suppliers": [],
		"reason": reason,
	}


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
		# ERPNext leaves `paid_amount` to the desk form's JavaScript, so a
		# server-made invoice was marked paid while paying nothing: no payment
		# entry in the ledger, and `outstanding_amount` left at the full total
		# because `is_paid` suppresses the update. The shop then appeared to owe
		# money it had already handed over.
		pi.set_missing_values()
		pi.calculate_taxes_and_totals()
		pi.paid_amount = flt(pi.rounded_total or pi.grand_total)

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
	"""Where neighbour-bought goods land.

	Exactly where the sale will draw from, because the purchase receives stock
	that the invoice consumes seconds later. This used to resolve the warehouse
	itself and could therefore differ from the sale's — which is what produced

	    NegativeStockError: 2.0 units of Item … needed in Stores …

	naming the selling warehouse, while the goods sat in whichever warehouse a
	bare `get_value` happened to return first. On a real site that was a
	per-customer van.

	There is no separate answer to give: the two are the same question.
	"""
	from cosmestics.api.pos import selling_warehouse

	warehouse = selling_warehouse()
	if not warehouse:
		# Refusing beats guessing: stock received into an arbitrary warehouse is
		# stock the shop cannot sell and will not find.
		frappe.throw(
			_(
				"No warehouse to receive neighbour stock into. Give this till's POS "
				"Profile a warehouse, or set a Sourcing Warehouse in Settings."
			)
		)
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
