"""Stock actions raised from the till."""

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, nowdate


@frappe.whitelist()
def warehouse_qtys(item_codes: list | str, warehouse: str) -> dict:
	"""Actual stock of each item in one named warehouse.

	For the material-request sheet: a cashier picking "Request from" a branch
	should see what that branch actually holds before asking for more of it
	than it has — the request still goes through either way, but a number on
	screen beats finding out from whoever reads the WhatsApp message.
	"""
	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)

	if not item_codes or not warehouse:
		return {}

	rows = frappe.get_all(
		"Bin",
		filters={"item_code": ("in", item_codes), "warehouse": warehouse},
		fields=["item_code", "actual_qty"],
	)
	return {r.item_code: flt(r.actual_qty) for r in rows}


@frappe.whitelist()
def item_stock(item_codes: list | str, warehouse: str | None = None) -> dict:
	"""What the shop holds of each item, for a form that is asking for more.

	**Why not `warehouse_qtys`.** That one answers a narrower question — how
	much is in *this* named store — and returns nothing at all when no warehouse
	is chosen. On the material request form the source warehouse is optional (a
	Purchase request has no source; the supplier is the source), so a stock
	figure that disappears the moment the field is blank is a figure nobody can
	rely on. This falls back to the balance everywhere, which is the number that
	answers "do we actually need this?".

	Returns per item: the balance in the named warehouse where one was given,
	the total across every warehouse, and how much is already on order. Labelled
	rather than reduced to one number, because "we have none here but forty in
	the back" and "we have none anywhere" are different answers and the person
	raising the request needs to tell them apart.
	"""
	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)

	item_codes = [c for c in (item_codes or []) if c]
	if not item_codes:
		return {}

	# One query for every warehouse, then split — a per-item query is an N+1 on
	# a form where a line is added every few seconds.
	rows = frappe.get_all(
		"Bin",
		filters={"item_code": ("in", item_codes)},
		fields=["item_code", "warehouse", "actual_qty", "ordered_qty", "reserved_qty"],
		limit_page_length=0,
	)

	out = {
		code: {"here": None, "total": 0.0, "ordered": 0.0, "reserved": 0.0, "warehouse": warehouse}
		for code in item_codes
	}

	for row in rows:
		entry = out.get(row.item_code)
		if entry is None:
			continue
		entry["total"] += flt(row.actual_qty)
		entry["ordered"] += flt(row.ordered_qty)
		entry["reserved"] += flt(row.reserved_qty)
		if warehouse and row.warehouse == warehouse:
			entry["here"] = flt(row.actual_qty)

	# A named warehouse with no Bin row holds none of it — distinct from no
	# warehouse having been named, which is what `None` means.
	if warehouse:
		for entry in out.values():
			if entry["here"] is None:
				entry["here"] = 0.0

	# The unit the figure is in. A balance of "12" means nothing next to a
	# quantity typed in cartons.
	uoms = dict(
		frappe.get_all(
			"Item",
			filters={"name": ("in", item_codes)},
			fields=["name", "stock_uom"],
			as_list=True,
		)
	)
	for code, entry in out.items():
		entry["uom"] = uoms.get(code)

	return out


@frappe.whitelist(methods=["POST"])
def request_transfer(
	items: list | str,
	from_warehouse: str | None = None,
	to_warehouse: str | None = None,
	company: str | None = None,
) -> dict:
	"""Raise a Material Transfer request for stock held at another branch.

	`items` is a list of {item_code, qty, from_warehouse}. Different lines can
	each name their own branch — a shop with more than one place to ask does
	not always want everything from the same one. The top-level
	`from_warehouse` is only a fallback for a line that does not name its own,
	kept for callers with a single source for the whole request.

	Submitted immediately — a draft sitting in a queue helps nobody when a
	customer is standing at the counter, and the WhatsApp notification fires
	off `on_submit`.
	"""
	if isinstance(items, str):
		items = frappe.parse_json(items)

	if not items:
		frappe.throw(_("No items to request"))

	company = company or frappe.defaults.get_user_default("Company")
	to_warehouse = to_warehouse or _default_warehouse(company)

	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Material Transfer"
	mr.company = company
	mr.transaction_date = nowdate()
	# Same-day: the customer is waiting, not scheduling a replenishment.
	mr.schedule_date = nowdate()
	# Only meaningful when every line agrees — set as a convenience default for
	# the desk to show, never relied on for what actually gets requested.
	warehouses_used = {row.get("from_warehouse") or from_warehouse for row in items}
	if len(warehouses_used) == 1:
		mr.set_from_warehouse = next(iter(warehouses_used))

	for row in items:
		qty = flt(row.get("qty"))
		if qty <= 0:
			continue
		row_from = row.get("from_warehouse") or from_warehouse
		if not row_from:
			frappe.throw(_("Select which branch to request {0} from").format(row.get("item_code")))
		if row_from == to_warehouse:
			frappe.throw(_("Source and target branch cannot be the same"))
		mr.append(
			"items",
			{
				"item_code": row.get("item_code"),
				"qty": qty,
				"warehouse": to_warehouse,
				"from_warehouse": row_from,
				"schedule_date": nowdate(),
			},
		)

	if not mr.items:
		frappe.throw(_("No items with a quantity above zero"))

	mr.insert()
	mr.submit()

	from cosmestics.api.notifications import status as whatsapp_status

	# Whether anybody will actually be told. The submit hook queues the message,
	# so this cannot report delivery — but it can report whether delivery is even
	# possible, which is the difference between "on its way" and "nobody will
	# ever see this". The till used to say "sent to WhatsApp" either way.
	return {"name": mr.name, "items": len(mr.items), "whatsapp": whatsapp_status()}


def _default_warehouse(company):
	"""Where requested stock should be delivered to: this till's own shelf.

	Shared with the sale rather than resolved again. Requesting a transfer *into*
	a warehouse the till does not sell from is a request that arrives and changes
	nothing — the shelf the cashier is standing at is still empty.

	The old fallback of "any non-group warehouse on the company" could do exactly
	that, and silently.
	"""
	from cosmestics.api.pos import selling_warehouse

	warehouse = selling_warehouse()
	if not warehouse:
		frappe.throw(
			_(
				"No warehouse to request stock into. Give this till's POS Profile a "
				"warehouse, or set a Sourcing Warehouse in Settings."
			)
		)
	return warehouse


def _other_stores(exclude: str | None) -> list:
	"""The shop's other stores: [{name, label}].

	The same rule the till uses for branches (`catalog._warehouses`): a
	warehouse that holds stock of anything. That keeps out the empty
	Work-In-Progress and Finished-Goods places ERPNext creates, while still
	listing a branch that happens to have none of *this* item — "none there
	either" is an answer the counter needs too.
	"""
	from cosmestics.api.catalog import _warehouses

	return _warehouses(exclude)


def elsewhere_qtys(item_codes: list, here: str | None) -> dict:
	"""{item_code: qty held in every other store}. Positive balances only —
	a negative bin somewhere is a counting problem, not stock to offer."""
	stores = [w["name"] for w in _other_stores(here)]
	if not stores or not item_codes:
		return {}
	rows = frappe.db.sql(
		"""select item_code, sum(actual_qty) as qty
		   from tabBin
		   where warehouse in %(stores)s and item_code in %(codes)s and actual_qty > 0
		   group by item_code""",
		{"stores": stores, "codes": item_codes},
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}


@frappe.whitelist()
def item_everywhere(item_code: str) -> dict:
	"""One item's balance in every store, for the card's quick view.

	The till only ever showed its own shelf, so a product that was out at the
	counter read "Out" even with a carton of it in the back store — and the
	sale was lost to a blind spot, not to a shortage.
	"""
	from cosmestics.api.pos import selling_warehouse
	from cosmestics.permissions import is_store_keeper

	item = frappe.db.get_value("Item", item_code, ["name", "item_name", "stock_uom"], as_dict=True)
	if not item:
		frappe.throw(_("{0} not found").format(item_code), frappe.DoesNotExistError)

	here = selling_warehouse()
	bins = dict(
		frappe.get_all(
			"Bin", filters={"item_code": item_code}, fields=["warehouse", "actual_qty"], as_list=True
		)
	)

	stores = []
	if here:
		label = frappe.db.get_value("Warehouse", here, "warehouse_name") or here
		stores.append({"warehouse": here, "label": label, "qty": flt(bins.get(here)), "is_here": True})
	others = [
		{"warehouse": w["name"], "label": w["label"], "qty": flt(bins.get(w["name"])), "is_here": False}
		for w in _other_stores(here)
	]
	# Stores that hold some first — they are the ones worth asking.
	others.sort(key=lambda r: (-r["qty"], r["label"]))
	stores.extend(others)

	return {
		"item_code": item.name,
		"item_name": item.item_name,
		"uom": item.stock_uom,
		"here": here,
		"stores": stores,
		"total": sum(r["qty"] for r in stores if r["qty"] > 0),
		"elsewhere": sum(r["qty"] for r in others if r["qty"] > 0),
		"can_reconcile": is_store_keeper(),
	}


@frappe.whitelist(methods=["POST"])
def reconcile_stock(item_code: str, qty: float, warehouse: str | None = None, reason: str | None = None) -> dict:
	"""Set a store's balance to what was actually counted.

	A Stock Reconciliation, which is ERPNext's own document for "the shelf says
	X": it posts the difference, not the figure, and keeps the valuation rate the
	stock already carries. Limited to the store keeper — a count is a claim about
	the shop's assets, and the person who counts deliveries is the one trusted to
	make it. The document permission is the role check; a store keeper is not
	also expected to hold stock rights on the desk.
	"""
	from cosmestics.api.pos import selling_warehouse
	from cosmestics.permissions import STORE_KEEPER, require

	require(STORE_KEEPER, _("Only a store keeper can reconcile stock."))

	qty = flt(qty)
	if qty < 0:
		frappe.throw(_("A counted quantity cannot be negative"))
	warehouse = warehouse or selling_warehouse()
	if not warehouse:
		frappe.throw(_("Choose which store was counted"))
	if not frappe.db.exists("Item", item_code):
		frappe.throw(_("{0} not found").format(item_code))

	company = frappe.db.get_value("Warehouse", warehouse, "company")
	before = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))
	if abs(before - qty) < 1e-9:
		frappe.throw(_("{0} already shows {1} — nothing to reconcile.").format(warehouse, qty))

	rate = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"))
	if not rate:
		rate = flt(frappe.db.get_value("Item", item_code, "valuation_rate"))
	if not rate:
		rate = flt(
			frappe.db.get_value(
				"Stock Ledger Entry",
				{"item_code": item_code, "is_cancelled": 0, "valuation_rate": (">", 0)},
				"valuation_rate",
				order_by="posting_date desc, posting_time desc, creation desc",
			)
		)

	doc = frappe.new_doc("Stock Reconciliation")
	doc.company = company
	doc.purpose = "Stock Reconciliation"
	doc.posting_date = nowdate()
	doc.set_posting_time = 0
	row = {"item_code": item_code, "warehouse": warehouse, "qty": qty}
	if rate:
		row["valuation_rate"] = rate
	else:
		# Nothing has ever given this item a value; count it without inventing one.
		row["allow_zero_valuation_rate"] = 1
	doc.append("items", row)
	submit_stock_count(
		doc,
		allow_negative=before < 0,
		note=_("Counted from the till by {0}: {1} → {2}{3}").format(
			frappe.utils.get_fullname(frappe.session.user), before, qty, f" — {reason}" if reason else ""
		),
	)

	return {
		"name": doc.name,
		"item_code": item_code,
		"warehouse": warehouse,
		"before": before,
		"qty": qty,
		"message": _("{0}: {1} → {2} at {3} ({4})").format(item_code, before, qty, warehouse, doc.name),
	}



# --------------------------------------------------------------------------
# Transfer approval
# --------------------------------------------------------------------------

PENDING, APPROVED, REJECTED = "Pending", "Approved", "Rejected"


def mark_transfer_pending(doc, method=None):
	"""Hooked on Material Request `before_submit`: a transfer waits for approval.

	On the document rather than in `request_transfer`, so a request raised from
	the form, the Documents screen or the desk waits exactly the same way.
	"""
	if doc.material_request_type == "Material Transfer" and not doc.get("cosmestics_approval"):
		doc.cosmestics_approval = PENDING


def _pending_transfer(name):
	doc = frappe.get_doc("Material Request", name)
	if doc.docstatus != 1:
		frappe.throw(_("{0} is not a submitted request").format(name))
	if doc.material_request_type != "Material Transfer":
		frappe.throw(_("{0} is not a request to move stock").format(name))
	if doc.get("cosmestics_approval") != PENDING:
		frappe.throw(
			_("{0} is not waiting for approval ({1})").format(name, doc.get("cosmestics_approval") or _("no approval needed"))
		)
	return doc


def can_approve_transfers(user=None) -> bool:
	from cosmestics.permissions import is_store_keeper

	return is_store_keeper(user)


@frappe.whitelist(methods=["POST"])
def approve_transfer(name: str) -> dict:
	"""Approve a transfer request and move the stock, in one step.

	The Stock Entry comes from ERPNext's own mapper, so each line leaves the
	store the request named and lands where it asked; it is submitted at once,
	because approving *is* the decision to move. If the source store does not
	have the stock, the submit refuses and nothing is approved.
	"""
	from erpnext.stock.doctype.material_request.material_request import make_stock_entry
	from cosmestics.permissions import STORE_KEEPER, require

	require(STORE_KEEPER, _("Only a store keeper can approve a stock transfer."))
	doc = _pending_transfer(name)

	entry = make_stock_entry(doc.name)
	for row in entry.items:
		row.s_warehouse = row.s_warehouse or doc.get("set_from_warehouse")
		if not row.s_warehouse:
			frappe.throw(_("{0} does not say which store {1} comes from").format(doc.name, row.item_code))
	if not entry.items:
		frappe.throw(_("Nothing is left to move on {0}").format(doc.name))
	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()

	doc.db_set(
		{
			"cosmestics_approval": APPROVED,
			"cosmestics_approved_by": frappe.session.user,
			"cosmestics_moved_by": entry.name,
		}
	)
	doc.add_comment("Comment", _("Approved by {0}; stock moved on {1}").format(frappe.utils.get_fullname(), entry.name))
	return {
		"name": doc.name,
		"stock_entry": entry.name,
		"approval": APPROVED,
		"message": _("{0} approved — stock moved ({1})").format(doc.name, entry.name),
	}


@frappe.whitelist(methods=["POST"])
def reject_transfer(name: str, reason: str | None = None) -> dict:
	"""Turn a transfer request down. The request is stopped, not cancelled, so
	it stays on record with who refused it and why."""
	from cosmestics.permissions import STORE_KEEPER, require

	require(STORE_KEEPER, _("Only a store keeper can reject a stock transfer."))
	doc = _pending_transfer(name)

	doc.db_set({"cosmestics_approval": REJECTED, "cosmestics_approved_by": frappe.session.user})
	doc.reload()
	doc.flags.ignore_permissions = True
	doc.update_status("Stopped")
	doc.add_comment(
		"Comment",
		_("Rejected by {0}{1}").format(frappe.utils.get_fullname(), f": {reason.strip()}" if (reason or "").strip() else ""),
	)
	return {"name": doc.name, "approval": REJECTED, "message": _("{0} rejected").format(doc.name)}


def pending_in(item_codes: list, warehouse: str | None) -> dict:
	"""{item_code: qty} already requested into `warehouse` and awaiting approval."""
	if not warehouse or not item_codes:
		return {}
	rows = frappe.db.sql(
		"""select mri.item_code, sum(mri.stock_qty) as qty
		   from `tabMaterial Request Item` mri
		   join `tabMaterial Request` mr on mr.name = mri.parent
		   where mr.docstatus = 1 and mr.material_request_type = 'Material Transfer'
		     and mr.cosmestics_approval = 'Pending'
		     and mri.warehouse = %(wh)s and mri.item_code in %(codes)s
		   group by mri.item_code""",
		{"wh": warehouse, "codes": item_codes},
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}


def store_qtys(item_codes: list, warehouses: list) -> dict:
	"""{item_code: {warehouse: qty}} for the given stores, non-zero only."""
	if not item_codes or not warehouses:
		return {}
	out = {}
	for r in frappe.get_all(
		"Bin",
		filters={"item_code": ("in", item_codes), "warehouse": ("in", warehouses), "actual_qty": ("!=", 0)},
		fields=["item_code", "warehouse", "actual_qty"],
		limit_page_length=0,
	):
		out.setdefault(r.item_code, {})[r.warehouse] = flt(r.actual_qty)
	return out


@frappe.whitelist(methods=["POST"])
def move_stock_here(item_code: str, from_warehouse: str, qty: float) -> dict:
	"""The card's "Move stock here": ask another store to send stock to this till.

	A Material Transfer request, submitted and waiting for the store keeper —
	nothing leaves the source store until it is approved.
	"""
	from cosmestics.api.pos import selling_warehouse

	here = selling_warehouse()
	if not here:
		frappe.throw(_("This till has no store of its own to move stock into"))
	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Choose how many to move"))
	available = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": from_warehouse}, "actual_qty"))
	if qty > available:
		frappe.throw(_("{0} only has {1} of this").format(from_warehouse, available))

	res = request_transfer(
		items=[{"item_code": item_code, "qty": qty, "from_warehouse": from_warehouse}],
		to_warehouse=here,
		company=frappe.db.get_value("Warehouse", here, "company"),
	)
	return res | {
		"item_code": item_code,
		"qty": qty,
		"from_warehouse": from_warehouse,
		"to_warehouse": here,
		"message": _("{0} raised — {1} × {2} from {3}, waiting for approval").format(
			res["name"], qty, item_code, from_warehouse
		),
	}


def submit_stock_count(doc, allow_negative: bool = False, note: str | None = None):
	"""Insert and submit a Stock Reconciliation the app has already authorised.

	ERPNext's reconciliation reads balances through a whitelisted helper that
	checks the *session user's* desk permissions (`get_stock_balance_for`),
	whatever flags the document carries — so a cashier or store keeper without
	desk stock rights is refused halfway through a count the app has already
	decided they may make.

	That one check is answered "yes" for the length of this call, and nothing
	else: **not** by switching the session user, which was the first version of
	this and a bad bug — `frappe.set_user` rewrites `session.sid`, so the till
	lost its login and every request after a count came back "not permitted".

	`allow_negative` lets a count lift a shelf that is below zero, which ERPNext
	otherwise refuses — the one case where the count can only end at or above 0.
	"""
	from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import StockReconciliation

	real_has_permission = frappe.has_permission

	def allow_stock_count(doctype=None, *args, **kwargs):
		if doctype == "Stock Reconciliation":
			return True
		return real_has_permission(doctype, *args, **kwargs)

	frappe.has_permission = allow_stock_count
	try:
		doc.flags.ignore_permissions = True
		doc.insert()
		if allow_negative:
			doc.update_stock_ledger = lambda allow_negative_stock=False: StockReconciliation.update_stock_ledger(
				doc, allow_negative_stock=True
			)
		doc.submit()
	finally:
		frappe.has_permission = real_has_permission
	# Stock Reconciliation has no remarks field, so the who-and-why is a comment.
	if note:
		doc.add_comment("Comment", note)
	return doc
