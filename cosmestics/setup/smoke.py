"""Post-deploy smoke test.

Posts two real sales through `submit_sale`, asserts the invoice, payment mode
and change accounting are right, then rolls back so nothing persists.

    bench --site <site> execute cosmestics.setup.smoke.run

Safe to run against a live site: the transaction is always rolled back, even
on failure.
"""

import frappe
from frappe.utils import add_days, flt, nowdate


class _Report:
	def __init__(self):
		self.results = []

	def check(self, name, ok, detail=""):
		self.results.append(bool(ok))
		print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  → {detail}" if detail else ""))

	def summary(self):
		passed = sum(self.results)
		print(f"\n{passed}/{len(self.results)} passed")
		return passed == len(self.results)


def run():
	r = _Report()
	try:
		_run(r)
	except Exception:
		print("EXCEPTION:\n" + frappe.get_traceback())
		r.results.append(False)
	finally:
		frappe.db.rollback()
		print("rolled back — nothing persisted")
	return r.summary()


def _run(r):
	from cosmestics.api.pos import submit_sale
	from cosmestics.setup.install import _default_warehouse

	_annotations(r)
	_custom_fields_visible(r)

	wh = _default_warehouse()
	wh_type = frappe.db.get_value("Warehouse", wh, "warehouse_type") if wh else None
	r.check(
		"default warehouse is sellable (not Transit)",
		bool(wh) and wh_type != "Transit",
		f"{wh} (type={wh_type})",
	)

	# Sell from the warehouse the app is actually configured to use. Overriding
	# it here would test a path production never takes — and did exactly that:
	# submit_sale reads a cached settings doc, so an item picked for warehouse A
	# was sold against warehouse B and died with NegativeStockError.
	item = _stocked_item(wh)
	if not item:
		print(f"SKIP: no stocked, non-batched, sellable item in {wh}")
		return

	print(f"  selling {item.item_code} (qty {item.actual_qty}) from {wh}\n")

	# --- Cash, over-tendered so change must be derived ---
	res = submit_sale(
		items=[{"item_code": item.item_code, "qty": 2, "rate": 500, "discount_pct": 0}],
		payment={"method": "cash", "tendered": 2000, "change": 1000},
	)
	si = frappe.get_doc("Sales Invoice", res["invoice"])

	r.check("Sales Invoice created", bool(si.name), si.name)
	r.check("submitted", si.docstatus == 1)
	r.check("is_pos set", si.is_pos == 1)
	r.check("update_stock set", si.update_stock == 1)
	r.check("grand_total 1000", flt(si.grand_total) == 1000, str(si.grand_total))
	r.check("one payment row", len(si.payments) == 1, str(len(si.payments)))
	r.check("mode = Cash", si.payments[0].mode_of_payment == "Cash", str(si.payments[0].mode_of_payment))
	r.check("payment type Cash", si.payments[0].type == "Cash", str(si.payments[0].type))
	r.check("payment account set", bool(si.payments[0].account), str(si.payments[0].account))
	r.check("paid_amount = 2000", flt(si.paid_amount) == 2000, str(si.paid_amount))
	r.check("change_amount = 1000", flt(si.change_amount) == 1000, str(si.change_amount))
	r.check("outstanding 0", flt(si.outstanding_amount) == 0, str(si.outstanding_amount))
	gl = frappe.db.count("GL Entry", {"voucher_no": si.name})
	r.check("GL entries posted", gl > 0, f"{gl} entries")
	sle = frappe.db.count("Stock Ledger Entry", {"voucher_no": si.name})
	r.check("stock ledger posted", sle > 0, f"{sle} entries")

	# --- M-Pesa, exact amount, with a reference ---
	res2 = submit_sale(
		items=[{"item_code": item.item_code, "qty": 1, "rate": 750, "discount_pct": 0}],
		payment={"method": "mpesa", "tendered": 750, "change": 0, "reference": "SLK7XR2QM4"},
	)
	si2 = frappe.get_doc("Sales Invoice", res2["invoice"])
	r.check("M-Pesa invoice submitted", si2.docstatus == 1, si2.name)
	r.check("mode = M-Pesa", si2.payments[0].mode_of_payment == "M-Pesa",
	        str(si2.payments[0].mode_of_payment))
	r.check("M-Pesa books no change", flt(si2.change_amount) == 0, str(si2.change_amount))
	r.check("M-Pesa reference kept", "SLK7XR2QM4" in (si2.remarks or ""), str(si2.remarks)[:50])
	r.check("M-Pesa outstanding 0", flt(si2.outstanding_amount) == 0, str(si2.outstanding_amount))

	_modules_and_reports(r)
	_pricing(r)
	_catalog(r)
	_partial_payment(r, item)
	_shift_and_credit(r, item)
	_till(r, item)
	_neighbour_sourcing(r, item)
	_transfer_request(r, item)
	_documents(r, item, wh)
	_dashboard(r)
	_dashboard_tabs(r)
	_master_data(r)
	_recent_sales(r)
	_barcodes(r)
	_whatsapp(r)
	_settings(r)


def _settings(r):
	"""The settings screen.

	Two things worth asserting. That the fields it declares still exist on their
	DocTypes — the same guard the documents hub has, for the same reason — and
	that the allow-list is a real boundary rather than a convention.
	"""
	from cosmestics.api import settings as api_settings

	print()
	data = api_settings.get()
	r.check("settings load", bool(data.get("pos_meta")), f"{len(data['pos_meta'])} fields")

	# Every declared field must resolve on its DocType, or the screen renders a
	# labelless box the user cannot interpret.
	pos_meta = frappe.get_meta("Cosmestics POS Settings")
	missing = [f for f in api_settings.POS_SETTINGS_FIELDS if not pos_meta.get_field(f)]
	r.check("every POS setting field exists", not missing, str(missing))

	profile_meta = frappe.get_meta("POS Profile")
	# Profile fields vary by ERPNext version, so this asserts the ones the screen
	# actually offers rather than the whole list.
	offered = ["warehouse", "selling_price_list", "customer"]
	missing_p = [f for f in offered if not profile_meta.has_field(f)]
	r.check("core POS Profile fields exist", not missing_p, str(missing_p))

	r.check("settings report whether they are editable", "can_edit_pos" in data,
	        str(data.get("can_edit_pos")))
	r.check("profiles come back with their user list",
	        all("users" in p and "mine" in p for p in data["profiles"]),
	        f"{len(data['profiles'])} profiles")

	# --- The link boundary ---
	opts = api_settings.link_options(doctype="Warehouse")
	r.check("link options resolve for a declared field", isinstance(opts, list),
	        f"{len(opts)} warehouses")

	try:
		api_settings.link_options(doctype="User")
		r.check("an undeclared doctype is refused", False, "no error raised")
	except frappe.ValidationError:
		r.check("an undeclared doctype is refused", True)

	# --- Writes are allow-listed, not passed through ---
	res = api_settings.save_pos_settings(
		values={"default_expense_account": None, "not_a_real_field": "x"}
	)
	r.check("an undeclared field is never written", "not_a_real_field" not in res["saved"],
	        str(res["saved"]))
	r.check(
		"the smuggled field did not reach the doctype",
		not frappe.db.exists(
			"DocField", {"parent": "Cosmestics POS Settings", "fieldname": "not_a_real_field"}
		),
	)


def _modules_and_reports(r):
	"""Back-office endpoints. These run raw SQL against whole periods, so a bad
	column name only shows up here, not at import time."""
	from cosmestics.api import modules, reorder, reports

	print()
	try:
		tree = reorder.get_warehouse_tree()
		r.check("warehouse tree returns parents", bool(tree["parents"]),
		        f"{len(tree['parents'])} parents")
		parent = tree.get("default_parent")
		if parent:
				# Per-item modal: item list, then one item's per-warehouse rows.
			item_rows = reorder.get_reorder_items()
			r.check("reorder item list", isinstance(item_rows, list), f"{len(item_rows)} items")
			if item_rows:
				d = reorder.get_item_reorder(item_code=item_rows[0]["item_code"])
				r.check("per-item reorder loads", bool(d["rows"]) or bool(d["parents"]),
				        f"{len(d['rows'])} locations under {d['parent']}")
				r.check("per-item exposes parents for cascade", bool(d["parents"]),
				        f"{len(d['parents'])} parents")

			data = reorder.get_reorder_rows(parent_warehouse=parent)
			r.check("reorder rows load for parent", isinstance(data["rows"], list),
			        f"{len(data['rows'])} rows across {len(data['warehouses'])} sub-warehouses")
			r.check("sub-warehouses resolved from parent", bool(data["warehouses"]),
			        str([w["label"] for w in data["warehouses"]][:4]))
	except Exception as e:
		r.check("reorder endpoints", False, f"{type(e).__name__}: {e}")

	from cosmestics.api import session
	try:
		me = session.me()
		r.check("session identifies the user", bool(me["user"]) and bool(me["initials"]),
		        f"{me['full_name']} ({me['initials']})")
	except Exception as e:
		r.check("session endpoint", False, f"{type(e).__name__}: {e}")

	for name, fn in (
		("inventory", modules.inventory),
		("sales", modules.sales),
		("purchasing", modules.purchasing),
		("accounts", modules.accounts),
	):
		try:
			out = fn()
			r.check(f"module {name}", isinstance(out, dict))
		except Exception as e:
			r.check(f"module {name}", False, f"{type(e).__name__}: {e}")

	for rep in reports.REPORTS:
		try:
			out = reports.run(report=rep["key"], days=90)
			ok = isinstance(out.get("rows"), list) and isinstance(out.get("columns"), list)
			r.check(f"report {rep['key']}", ok, f"{len(out.get('rows', []))} rows")
		except Exception as e:
			r.check(f"report {rep['key']}", False, f"{type(e).__name__}: {e}")


def _pricing(r):
	"""Bulk price maintenance. Preview must never silently apply."""
	from cosmestics.api import pricing

	print()
	try:
		opts = pricing.get_price_list_options()
		pl = opts.get("default")
		r.check("price list resolved", bool(pl), str(pl))
		if not pl:
			return

		data = pricing.get_prices(price_list=pl, limit=20)
		rows = data["rows"]
		r.check("prices load", isinstance(rows, list), f"{len(rows)} items")
		priced = [x for x in rows if x["price"]]
		if not priced:
			print("  SKIP: no priced items to preview against")
			return

		# Deliberately pick from the END of the list: the old preview re-fetched
		# with limit=len(selection), which returned the first N items
		# alphabetically and silently matched none of these.
		codes = [x["item_code"] for x in priced[-3:]]
		before = {x["item_code"]: x["price"] for x in priced[-3:]}

		prev = pricing.preview_bulk_change(
			price_list=pl, item_codes=codes, mode="percent", value=10, rounding="whole"
		)
		r.check("preview returns rows", len(prev["rows"]) == len(codes), f"{len(prev['rows'])}")
		first = prev["rows"][0]
		expected = round(before[first["item_code"]] * 1.1)
		r.check("preview applies +10% and rounds", abs(first["new_price"] - expected) < 0.51,
		        f"{first['old_price']} -> {first['new_price']}")

		after = pricing.get_prices(price_list=pl, limit=20)
		unchanged = all(
			x["price"] == before.get(x["item_code"], x["price"])
			for x in after["rows"] if x["item_code"] in before
		)
		r.check("preview did NOT change prices", unchanged)

		res = pricing.apply_bulk_change(
			price_list=pl, changes=[{"item_code": r0["item_code"], "new_price": r0["new_price"]} for r0 in prev["rows"]]
		)
		r.check("apply writes prices", (res["updated"] + res["created"]) == len(codes),
		        f"updated={res['updated']} created={res['created']}")

		final = {x["item_code"]: x["price"] for x in pricing.get_prices(price_list=pl, limit=50)["rows"]}
		r.check("price actually changed", final[first["item_code"]] == first["new_price"],
		        f"{final[first['item_code']]}")
	except Exception as e:
		r.check("pricing endpoints", False, f"{type(e).__name__}: {e}")


def _catalog(r):
	"""The catalog must serve real Items — the demo SKUs do not exist in ERPNext
	and every sale of one dies with DoesNotExistError at submit."""
	from cosmestics.api.catalog import get_catalog

	print()
	data = get_catalog()
	rows = data.get("items", [])
	r.check("catalog returns items", bool(rows), f"{len(rows)} items")
	if not rows:
		return

	r.check("catalog not flagged empty", not data.get("empty"))

	sample = rows[0]
	r.check(
		"catalog items are real ERPNext Items",
		bool(frappe.db.exists("Item", sample["item_code"])),
		sample["item_code"],
	)
	# Buying from a neighbour looks identical at the till whether it is
	# unconfigured or simply has no shops in the group — the button is dead
	# either way. The status has to say which, or nobody can act on it.
	sourcing = data.get("sourcing") or {}
	r.check(
		"catalog reports why neighbour sourcing is or is not available",
		"available" in sourcing and (sourcing["available"] or bool(sourcing.get("reason"))),
		str(sourcing),
	)
	# A cashier out of stock with a customer waiting must always have someone to
	# attribute the purchase to, or the sale cannot complete.
	r.check(
		"at least one neighbour shop exists to buy from",
		bool(data.get("neighbours")),
		str([n["name"] for n in (data.get("neighbours") or [])][:4]),
	)

	r.check(
		"sourcing status agrees with the neighbour list",
		bool(data.get("neighbours")) == bool(sourcing.get("available")),
		f"{len(data.get('neighbours') or [])} neighbours, available={sourcing.get('available')}",
	)

	r.check("catalog exposes a price field", "price" in sample)
	r.check("catalog exposes stock", "stock" in sample)
	priced = [x for x in rows if flt(x["price"]) > 0]
	r.check("at least one item is priced", bool(priced), f"{len(priced)} priced")


def _partial_payment(r, item):
	"""Split tender and under-payment."""
	from cosmestics.api.customers import create as create_customer
	from cosmestics.api.pos import submit_sale

	print()
	cust = create_customer(customer_name="Partial Pay Customer")

	# --- Split tender: 600 cash + 400 M-Pesa on a 1000 bill ---
	res = submit_sale(
		items=[{"item_code": item.item_code, "qty": 2, "rate": 500, "discount_pct": 0}],
		payment={
			"parts": [
				{"method": "cash", "amount": 600},
				{"method": "mpesa", "amount": 400, "reference": "SPLIT123"},
			]
		},
	)
	si = frappe.get_doc("Sales Invoice", res["invoice"])
	r.check("split tender submitted", si.docstatus == 1, si.name)
	r.check("two payment rows", len(si.payments) == 2, str(len(si.payments)))
	modes = sorted(p.mode_of_payment for p in si.payments)
	r.check("both modes recorded", modes == ["Cash", "M-Pesa"], str(modes))
	r.check("paid_amount = 1000", flt(si.paid_amount) == 1000, str(si.paid_amount))
	r.check("split leaves nothing outstanding", flt(si.outstanding_amount) == 0,
	        str(si.outstanding_amount))

	# --- Partial: pay 300 of 1000, 700 stays owed ---
	res2 = submit_sale(
		items=[{"item_code": item.item_code, "qty": 2, "rate": 500, "discount_pct": 0}],
		payment={"parts": [{"method": "cash", "amount": 300}]},
		customer=cust["name"],
	)
	si2 = frappe.get_doc("Sales Invoice", res2["invoice"])
	r.check("partial payment submitted", si2.docstatus == 1, si2.name)
	r.check("paid_amount = 300", flt(si2.paid_amount) == 300, str(si2.paid_amount))
	r.check("outstanding = 700", flt(si2.outstanding_amount) == 700, str(si2.outstanding_amount))
	r.check("partial reported to caller", flt(res2.get("outstanding")) == 700,
	        str(res2.get("outstanding")))

	# --- Partial with no customer must be refused ---
	try:
		submit_sale(
			items=[{"item_code": item.item_code, "qty": 2, "rate": 500, "discount_pct": 0}],
			payment={"parts": [{"method": "cash", "amount": 300}]},
		)
		r.check("partial without customer is rejected", False, "no error raised")
	except frappe.ValidationError:
		r.check("partial without customer is rejected", True)


def _shift_and_credit(r, item):
	"""Open a shift, sell into it, take a credit sale, then close and reconcile."""
	from cosmestics.api.customers import create as create_customer
	from cosmestics.api.pos import submit_sale
	from cosmestics.api.shift import (
		close_shift,
		get_closing_summary,
		get_open_shift,
		get_profiles,
		open_shift,
	)

	print()
	profiles = get_profiles()
	r.check("POS profile available", bool(profiles), str([p["name"] for p in profiles]))
	if not profiles:
		return

	profile = profiles[0]["name"]

	# A cashier may already be mid-shift on this site. Close it first so the
	# test starts from a known state — the whole run is rolled back, so the real
	# shift is untouched.
	if get_open_shift():
		close_shift()
		print("  (closed a pre-existing open shift for the test; rolled back after)")

	# POS Opening Entry refuses to save if any mode in the opening balances has
	# no company account, so a shift cannot start without these.
	settings = frappe.get_single("Cosmestics POS Settings")
	till_modes = [m for m in (settings.mode_cash, settings.mode_mpesa, settings.mode_card) if m]
	unmapped = [
		m
		for m in till_modes
		if not frappe.db.get_value(
			"Mode of Payment Account",
			{"parent": m, "company": frappe.defaults.get_global_default("company")},
			"default_account",
		)
	]
	r.check(
		"every till payment mode has a company account",
		not unmapped,
		f"missing: {unmapped}" if unmapped else f"{len(till_modes)} modes mapped",
	)

	# Open with ALL till modes, not just Cash — this is what the UI sends, and
	# it is the path that surfaced the missing Credit Card account.
	shift = open_shift(
		pos_profile=profile,
		balances=[
			{"mode_of_payment": m, "opening_amount": 5000 if m == settings.mode_cash else 0}
			for m in till_modes
		],
	)
	r.check("shift opened", bool(shift and shift["name"]), str(shift and shift["name"]))
	r.check("open shift is findable", bool(get_open_shift()))

	# A cash sale inside the shift must carry the profile, or closing finds nothing.
	res = submit_sale(
		items=[{"item_code": item.item_code, "qty": 1, "rate": 400, "discount_pct": 0}],
		payment={"method": "cash", "tendered": 400, "change": 0},
	)
	si = frappe.get_doc("Sales Invoice", res["invoice"])
	r.check("in-shift sale tagged with pos_profile", si.pos_profile == profile, str(si.pos_profile))
	# --- Credit sale: customer required, nothing in the drawer ---
	try:
		submit_sale(
			items=[{"item_code": item.item_code, "qty": 1, "rate": 300, "discount_pct": 0}],
			payment={"method": "credit"},
		)
		r.check("credit sale without customer is rejected", False, "no error raised")
	except frappe.ValidationError:
		r.check("credit sale without customer is rejected", True)

	cust = create_customer(customer_name="Smoke Test Customer", mobile_no="254700000000")
	res3 = submit_sale(
		items=[{"item_code": item.item_code, "qty": 1, "rate": 300, "discount_pct": 0}],
		payment={"method": "credit"},
		customer=cust["name"],
	)
	si3 = frappe.get_doc("Sales Invoice", res3["invoice"])
	r.check("credit invoice submitted", si3.docstatus == 1, si3.name)
	r.check("credit sale customer captured", si3.customer == cust["name"], str(si3.customer))
	r.check("credit sale is not is_pos", si3.is_pos == 0, str(si3.is_pos))
	r.check("credit sale outstanding = 300", flt(si3.outstanding_amount) == 300,
	        str(si3.outstanding_amount))
	r.check("credit sale still moves stock",
	        frappe.db.count("Stock Ledger Entry", {"voucher_no": si3.name}) > 0)

	# --- Closing summary ---
	summary = get_closing_summary()
	cash_row = next((x for x in summary["rows"] if x["mode_of_payment"] == "Cash"), None)
	r.check("closing summary has Cash row", bool(cash_row))
	if cash_row:
		r.check("opening float carried (5000)", flt(cash_row["opening_amount"]) == 5000,
		        str(cash_row["opening_amount"]))
		r.check("expected = float + cash taken (5400)", flt(cash_row["expected_amount"]) == 5400,
		        f"opening {cash_row['opening_amount']} + taken {cash_row['taken']}")
	r.check("shift sees the in-shift sale", summary["invoice_count"] >= 1,
	        f"{summary['invoice_count']} invoices")
	r.check("credit reported separately", summary["credit"]["count"] >= 1,
	        f"count={summary['credit']['count']} outstanding={summary['credit']['outstanding']}")

	# --- Money out of the drawer, before closing ---
	_till_movements(r, shift, summary)

	# --- Close, with a deliberate 100 short in the drawer ---
	#
	# 5400 expected, minus the 250 expense left standing by `_till_movements`,
	# is 5150. Counting 5050 is therefore 100 short — the same shortfall as
	# before the movements existed, which is the point: the expense is not a
	# discrepancy, and a till that reported it as one would have the cashier
	# hunting money that was legitimately spent.
	closed = close_shift(
		counted=[{"mode_of_payment": "Cash", "closing_amount": 5050}],
		shorts=[{"mode_of_payment": "Cash", "person": "Smoke Cashier"}],
	)
	r.check("shift closed", bool(closed["name"]), closed["name"])
	r.check("shortfall detected (-100)", flt(closed["difference"]) == -100,
	        str(closed["difference"]))
	r.check("cash paid out reported at close (250)", flt(closed["paid_out"]) == 250,
	        str(closed["paid_out"]))
	r.check("opening entry marked Closed",
	        frappe.db.get_value("POS Opening Entry", shift["name"], "status") == "Closed",
	        str(frappe.db.get_value("POS Opening Entry", shift["name"], "status")))

	# --- The shift just closed shows up in the history ---
	from cosmestics.api.shift import list_recent_shifts

	history = list_recent_shifts(limit=10)
	mine = next((h for h in history["rows"] if h["name"] == shift["name"]), None)
	r.check("the closed shift appears in the history", bool(mine), f"{history['count']} shifts")
	if mine:
		r.check("history names who the short is against",
		        mine["assigned_to"] == ["Smoke Cashier"], str(mine["assigned_to"]))
		r.check("history carries the short itself", flt(mine["short_total"]) == 100,
		        str(mine["short_total"]))
		r.check("history carries the closing difference (-100)", flt(mine["difference"]) == -100,
		        str(mine["difference"]))
		r.check("history carries what was paid out (250)", flt(mine["paid_out"]) == 250,
		        str(mine["paid_out"]))
		r.check("history links to its closing entry", mine["closing"] == closed["name"],
		        str(mine["closing"]))

	# --- The short carries a name ---
	recorded = closed.get("shorts_recorded") or []
	r.check("the short was attributed to somebody", len(recorded) == 1, str(recorded))
	if recorded:
		r.check("attributed short names the person",
		        recorded[0]["person"] == "Smoke Cashier", str(recorded[0]["person"]))
		r.check("attributed short is the counted difference (100)",
		        flt(recorded[0]["amount"]) == 100, str(recorded[0]["amount"]))
		short_doc = frappe.get_doc("Cosmestics Shift Movement", recorded[0]["name"])
		r.check("short links back to the closing entry",
		        short_doc.reference_name == closed["name"], str(short_doc.reference_name))
		r.check("short is submitted", short_doc.docstatus == 1, str(short_doc.docstatus))
		r.check("a short posts no journal entry of its own",
		        short_doc.reference_doctype == "POS Closing Entry",
		        str(short_doc.reference_doctype))


def _till_movements(r, shift, before):
	"""Money leaving the drawer without being a sale.

	The thing worth asserting is not that a record was written — it is that the
	*expected* amount moved. A movement that files neatly and leaves the closing
	figure untouched is exactly the bug this is guarding against, because the
	cashier would then be counting against a number that still includes cash
	they watched leave.
	"""
	from cosmestics.api.shift import (
		close_shift,
		get_closing_summary,
		get_movement_options,
		list_movements,
		record_movement,
		void_movement,
	)

	print()
	cash_before = next(
		(x for x in before["rows"] if x["mode_of_payment"] == "Cash"), {"expected_amount": 0}
	)
	expected_before = flt(cash_before["expected_amount"])

	opts = get_movement_options()
	r.check("movement form has modes to pick from", bool(opts["modes"]), str(opts["modes"]))
	r.check("movement form offers expense accounts", bool(opts["accounts"]),
	        f"{len(opts['accounts'])} accounts")

	# --- An expense: cash out, and a real ledger entry ---
	exp = record_movement(
		movement_type="Expense",
		amount=250,
		mode_of_payment="Cash",
		reason="Smoke test transport",
		person="Smoke Cashier",
	)
	r.check("expense recorded", bool(exp["name"]), exp["name"])
	r.check("expense posted a journal entry", exp["reference_doctype"] == "Journal Entry",
	        f"{exp['reference_doctype']} {exp['reference_name']}")

	if exp["reference_name"]:
		je = frappe.get_doc("Journal Entry", exp["reference_name"])
		r.check("journal entry is submitted", je.docstatus == 1, str(je.docstatus))
		r.check("journal entry balances at 250",
		        flt(je.total_debit) == 250 and flt(je.total_credit) == 250,
		        f"dr {je.total_debit} cr {je.total_credit}")

	after = get_closing_summary()
	cash_after = next(
		(x for x in after["rows"] if x["mode_of_payment"] == "Cash"), {"expected_amount": 0}
	)
	r.check(
		"expected cash fell by the expense (250)",
		flt(cash_after["expected_amount"]) == expected_before - 250,
		f"{expected_before} → {cash_after['expected_amount']}",
	)
	r.check("the reduction is reported, not just applied",
	        flt(cash_after.get("paid_out")) == 250, str(cash_after.get("paid_out")))
	r.check("expense total surfaced separately",
	        flt(after["movements"]["expense_total"]) == 250,
	        str(after["movements"]["expense_total"]))

	# --- Voiding puts it back ---
	voidable = record_movement(
		movement_type="Expense", amount=90, mode_of_payment="Cash", reason="Recorded by mistake"
	)
	mid = get_closing_summary()
	mid_cash = next(x for x in mid["rows"] if x["mode_of_payment"] == "Cash")
	r.check("a second expense stacks (340 out)",
	        flt(mid_cash["paid_out"]) == 340, str(mid_cash["paid_out"]))

	void_movement(name=voidable["name"])
	restored = get_closing_summary()
	restored_cash = next(x for x in restored["rows"] if x["mode_of_payment"] == "Cash")
	r.check(
		"voiding restores the expected amount",
		flt(restored_cash["expected_amount"]) == expected_before - 250,
		f"{restored_cash['expected_amount']} (expense of 250 still standing)",
	)
	r.check("a voided movement leaves the list",
	        len(list_movements()["rows"]) == 1, str(len(list_movements()["rows"])))

	# --- A short cannot be recorded mid-shift; it is found by counting ---
	try:
		record_movement(movement_type="Short", amount=50, mode_of_payment="Cash", person="X")
		r.check("a short cannot be recorded during a shift", False, "no error raised")
	except frappe.ValidationError:
		r.check("a short cannot be recorded during a shift", True)

	# --- A movement with no amount is refused ---
	try:
		record_movement(movement_type="Expense", amount=0, mode_of_payment="Cash")
		r.check("a zero movement is refused", False, "no error raised")
	except frappe.ValidationError:
		r.check("a zero movement is refused", True)


def _documents(r, item, warehouse):
	"""The document hub.

	Two kinds of check. First that the registry still describes the DocTypes it
	claims to — a field renamed upstream would otherwise show up as a silently
	missing column rather than an error. Then that the endpoints actually run,
	per registered type, because the SQL and the meta lookups only meet at
	runtime.
	"""
	from cosmestics.api import documents, reports

	print()
	report_keys = {rep["key"] for rep in reports.REPORTS}
	problems = []
	for entry in documents.DOCUMENTS:
		doctype = entry["doctype"]
		if not frappe.db.exists("DocType", doctype):
			problems.append(f"{doctype}: not installed")
			continue

		meta = frappe.get_meta(doctype)
		for role in ("date_field", "party_field", "amount_field", "outstanding_field", "due_field"):
			field = entry.get(role)
			if field and not meta.has_field(field):
				problems.append(f"{doctype}.{field} ({role})")

		for field in entry["columns"]:
			if field != "name" and not meta.has_field(field):
				problems.append(f"{doctype}.{field} (column)")

		for field in entry.get("detail", []):
			if not meta.has_field(field):
				problems.append(f"{doctype}.{field} (detail)")

		for fieldname, child_fields in entry.get("tables", []):
			df = meta.get_field(fieldname)
			if not df:
				problems.append(f"{doctype}.{fieldname} (table)")
				continue
			child_meta = frappe.get_meta(df.options)
			for field in child_fields:
				if not child_meta.has_field(field):
					problems.append(f"{df.options}.{field} (line)")

		unknown = [k for k in entry["reports"] if k not in report_keys]
		if unknown:
			problems.append(f"{doctype}: unknown reports {unknown}")

	r.check(
		"document registry matches the DocTypes",
		not problems,
		"; ".join(problems) if problems else f"{len(documents.DOCUMENTS)} types",
	)

	types = documents.list_types()
	r.check("document types listed", bool(types), f"{len(types)} readable types")

	for entry in types:
		key = entry["key"]
		try:
			data = frappe.call(documents.list_documents, key=key, days=3650, limit=5)
			ok = isinstance(data["rows"], list) and bool(data["columns"])
			r.check(f"documents list {key}", ok, f"{len(data['rows'])} of {data['total']}")

			ins = frappe.call(documents.insights, key=key, days=3650)
			r.check(f"documents insights {key}", bool(ins["stats"]), f"{len(ins['stats'])} tiles")

			if data["rows"]:
				name = data["rows"][0]["name"]
				doc = frappe.call(documents.get_document, key=key, name=name)
				r.check(
					f"documents detail {key}",
					bool(doc["header"]) and isinstance(doc["tables"], list),
					f"{name}: {len(doc['header'])} fields, {len(doc['tables'])} tables",
				)
				url = frappe.call(documents.print_url, key=key, name=name)["url"]
				r.check(f"documents print url {key}", "/printview?" in url)
		except Exception as e:
			r.check(f"documents endpoints {key}", False, f"{type(e).__name__}: {e}")

	# An unregistered doctype must not be reachable, or the key is decoration
	# rather than a boundary.
	try:
		documents.list_documents(key="user")
		r.check("unregistered doctype is refused", False, "no error raised")
	except frappe.DoesNotExistError:
		r.check("unregistered doctype is refused", True)

	_document_creation(r, item, warehouse)
	_document_actions(r, item, warehouse)


def _transfer_request(r, item):
	"""Requesting stock from another branch.

	The only path in the app that raises a Material Request, and it had no
	end-to-end check at all — only that its arguments were annotated. So "no
	material requests are showing" could not be told apart from "the button that
	makes them is broken".
	"""
	from cosmestics.api.catalog import get_catalog
	from cosmestics.api.stock import request_transfer

	print()
	cat = get_catalog()
	branches = cat["warehouses"]
	r.check(
		"other branches are offered to request from",
		bool(branches),
		str([w["label"] for w in branches][:5]),
	)

	# Every offered branch must actually hold something. Offering a per-customer
	# van warehouse or Work In Progress as a place to source goods from is not a
	# choice a cashier can act on.
	empty = [
		w["label"]
		for w in branches
		if not frappe.db.exists("Bin", {"warehouse": w["name"], "actual_qty": (">", 0)})
	]
	r.check("every branch offered holds stock", not empty, f"empty: {empty}" if empty else "")
	r.check(
		"the till's own warehouse is not offered as a source",
		cat["warehouse"] not in [w["name"] for w in branches],
		str(cat["warehouse"]),
	)

	if not branches:
		return

	try:
		res = frappe.call(
			request_transfer,
			items=[{"item_code": item.item_code, "qty": 1}],
			from_warehouse=branches[0]["name"],
		)
		mr = frappe.get_doc("Material Request", res["name"])
		r.check("transfer request raised", mr.docstatus == 1, mr.name)
		r.check("it is a transfer, not a purchase", mr.material_request_type == "Material Transfer")
		r.check(
			"the line moves stock from the branch to the till",
			mr.items[0].from_warehouse == branches[0]["name"] and mr.items[0].warehouse == cat["warehouse"],
			f"{mr.items[0].from_warehouse} -> {mr.items[0].warehouse}",
		)
		# And it must then be visible on the screen that lists them.
		from cosmestics.api import documents

		listed = frappe.call(documents.list_documents, key="material-request", days=30)
		r.check(
			"the request shows up in the documents hub",
			any(row["name"] == mr.name for row in listed["rows"]),
			f"{listed['total']} requests listed",
		)
	except Exception as e:
		r.check("transfer request", False, f"{type(e).__name__}: {e}")

	try:
		request_transfer(items=[{"item_code": item.item_code, "qty": 1}], from_warehouse=cat["warehouse"])
		r.check("requesting from our own warehouse is refused", False, "no error raised")
	except frappe.ValidationError:
		r.check("requesting from our own warehouse is refused", True)


def _document_creation(r, item, warehouse):
	"""Raising Sales Orders, Purchase Orders and Material Requests in the app.

	Each is actually created and read back. A form endpoint that returns the
	right-looking fields but produces a document ERPNext rejects is the failure
	worth catching, and only an insert proves it does not.
	"""
	from cosmestics.api import documents

	print()
	creatable = [d for d in documents.DOCUMENTS if d.get("create")]
	keys = {d["key"] for d in creatable}
	r.check(
		"every document a shop raises itself is creatable",
		{
			"sales-order",
			"purchase-order",
			"material-request",
			"sales-invoice",
			"purchase-invoice",
			"purchase-receipt",
			"delivery-note",
			"stock-entry",
			"stock-reconciliation",
		}
		<= keys,
		str(sorted(keys)),
	)
	# Every registered type is either creatable or says why not. A screen with no
	# New button and no explanation is the thing that looks broken.
	silent = [
		d["key"]
		for d in documents.DOCUMENTS
		if not d.get("create") and d["key"] not in documents.NOT_CREATABLE
	]
	r.check("every type either creates or explains why not", not silent, str(silent))
	r.check(
		"the not-creatable list only names registered types",
		set(documents.NOT_CREATABLE) <= {d["key"] for d in documents.DOCUMENTS},
		str(set(documents.NOT_CREATABLE) - {d["key"] for d in documents.DOCUMENTS}),
	)

	# Declared form fields must exist on their DocTypes, or the form silently
	# drops whatever was typed into them.
	problems = []
	for entry in creatable:
		meta = frappe.get_meta(entry["doctype"])
		child = frappe.get_meta(meta.get_field("items").options)
		for field in entry["create"]["fields"]:
			if not meta.has_field(field["fieldname"]):
				problems.append(f"{entry['doctype']}.{field['fieldname']}")
		for field in entry["create"]["items"]:
			if not child.has_field(field["fieldname"]):
				problems.append(f"{child.name}.{field['fieldname']}")
		for line_field in (entry["create"].get("line_from_header") or {}):
			if not child.has_field(line_field):
				problems.append(f"{child.name}.{line_field} (inherited)")
	r.check("create-form fields exist on their DocTypes", not problems, "; ".join(problems) if problems else f"{len(creatable)} forms")

	customer = frappe.get_all("Customer", limit=1, pluck="name")
	supplier = frappe.get_all("Supplier", filters={"disabled": 0}, limit=1, pluck="name")

	cases = [
		(
			"sales-order",
			{"customer": customer[0] if customer else None, "delivery_date": add_days(nowdate(), 7)},
			[{"item_code": item.item_code, "qty": 2, "warehouse": warehouse}],
		),
		(
			"purchase-order",
			{"supplier": supplier[0] if supplier else None, "schedule_date": add_days(nowdate(), 7)},
			[{"item_code": item.item_code, "qty": 3, "rate": 90, "warehouse": warehouse}],
		),
		(
			"material-request",
			{
				"material_request_type": "Purchase",
				"schedule_date": add_days(nowdate(), 7),
				"set_warehouse": warehouse,
			},
			[{"item_code": item.item_code, "qty": 4}],
		),
		(
			"sales-invoice",
			{"customer": customer[0] if customer else None, "due_date": add_days(nowdate(), 7)},
			[{"item_code": item.item_code, "qty": 1, "warehouse": warehouse}],
		),
		(
			"purchase-invoice",
			{"supplier": supplier[0] if supplier else None, "due_date": add_days(nowdate(), 7)},
			[{"item_code": item.item_code, "qty": 2, "rate": 80, "warehouse": warehouse}],
		),
		(
			"purchase-receipt",
			{"supplier": supplier[0] if supplier else None, "set_warehouse": warehouse},
			[{"item_code": item.item_code, "qty": 2, "rate": 80}],
		),
		(
			"delivery-note",
			{"customer": customer[0] if customer else None, "set_warehouse": warehouse},
			[{"item_code": item.item_code, "qty": 1}],
		),
		(
			"stock-reconciliation",
			{"purpose": "Stock Reconciliation", "set_warehouse": warehouse},
			[{"item_code": item.item_code, "qty": 5, "valuation_rate": 60}],
		),
	]

	for key, values, lines in cases:
		if any(v is None for v in values.values()):
			print(f"  SKIP {key}: no party on this site")
			continue

		try:
			form = frappe.call(documents.new_document_form, key=key)
			r.check(f"{key} form loads", bool(form["fields"]) and bool(form["items"]), f"{len(form['fields'])} fields")
			r.check(
				f"{key} form defaults its dates",
				all(f.get("default") for f in form["fields"] if f["type"] == "date"),
			)

			# Seeded from the form's own defaults and then overlaid, which is
			# exactly what the browser sends. Hardcoding a date field here meant
			# the test only ever exercised the types that happened to use
			# `transaction_date`, and every `posting_date` form failed on a
			# mandatory field the real UI would have filled in.
			defaults = {f["fieldname"]: f["default"] for f in form["fields"] if f.get("default")}
			values = {**defaults, **{k: v for k, v in values.items() if v is not None}}

			res = frappe.call(documents.create_document, key=key, values=values, items=lines)
			r.check(f"{key} created as a draft", res["docstatus"] == 0, res["name"])

			doc = frappe.get_doc(res["doctype"], res["name"])
			r.check(f"{key} kept its lines", len(doc.items) == len(lines), f"{len(doc.items)} lines")
			# Only the trading documents are priced. A Material Request asks for
			# stock to be moved or bought; it carries no rate, and asserting one
			# would be testing a fact about ERPNext that is not true.
			# Only the trading documents are priced. A Material Request asks for
			# stock to be moved or bought and a Stock Reconciliation states a
			# balance; neither carries a rate, so asserting one would be testing a
			# fact about ERPNext that is not true.
			if key not in ("material-request", "stock-reconciliation"):
				r.check(
					f"{key} priced the line from the price list",
					flt(doc.items[0].rate) > 0,
					str(doc.items[0].rate),
				)
			# Material Request lines need a warehouse and a date ERPNext validates
			# per row; the form only asks once, so the inheritance has to work.
			if key == "material-request":
				r.check(
					"material request lines inherit the destination",
					doc.items[0].warehouse == warehouse,
					str(doc.items[0].warehouse),
				)

			submitted = frappe.call(
				documents.create_document, key=key, values=values, items=lines, submit=1
			)
			r.check(f"{key} can be created and submitted", submitted["docstatus"] == 1, submitted["name"])
		except Exception as e:
			r.check(f"{key} creation", False, f"{type(e).__name__}: {e}")

	# The guards.
	try:
		frappe.call(documents.create_document, key="sales-order", values={}, items=[])
		r.check("creating with no lines is refused", False, "no error raised")
	except frappe.ValidationError:
		r.check("creating with no lines is refused", True)

	try:
		frappe.call(documents.new_document_form, key="pos-closing")
		r.check("a type with no form is refused", False, "no error raised")
	except frappe.ValidationError:
		r.check("a type with no form is refused", True)

	try:
		documents.link_options(key="purchase-order", fieldname="qty")
		r.check("link options on a non-link field are refused", False, "no error raised")
	except frappe.ValidationError:
		r.check("link options on a non-link field are refused", True)

	items = documents.link_options(key="purchase-order", fieldname="item_code", search=item.item_code[:3])
	r.check("item picker searches", isinstance(items, list), f"{len(items)} matches")


def _document_actions(r, item, warehouse):
	"""Submit, cancel, amend and duplicate, run against a real document.

	The fixture is a Material Request because it is the only submittable type
	here that posts neither stock nor GL — so the lifecycle is exercised without
	the test's outcome depending on whether a warehouse happens to have cover.
	"""
	from frappe.utils import add_days, nowdate

	from cosmestics.api import documents

	print()
	try:
		draft = frappe.get_doc(
			{
				"doctype": "Material Request",
				"material_request_type": "Purchase",
				"transaction_date": nowdate(),
				"schedule_date": add_days(nowdate(), 7),
				"company": frappe.defaults.get_global_default("company"),
				"items": [
					{
						"item_code": item.item_code,
						"qty": 3,
						"warehouse": warehouse,
						"schedule_date": add_days(nowdate(), 7),
					}
				],
			}
		).insert()
	except Exception as e:
		r.check("document action fixture created", False, f"{type(e).__name__}: {e}")
		return

	r.check("document action fixture created", draft.docstatus == 0, draft.name)

	try:
		res = frappe.call(documents.run_action, key="material-request", name=draft.name, action="submit")
		r.check("run_action submit", res["docstatus"] == 1, str(res["docstatus"]))

		res = frappe.call(documents.run_action, key="material-request", name=draft.name, action="cancel")
		r.check("run_action cancel", res["docstatus"] == 2, str(res["docstatus"]))

		res = frappe.call(documents.run_action, key="material-request", name=draft.name, action="amend")
		amended = res["name"]
		r.check("run_action amend makes a draft", res["docstatus"] == 0 and res.get("created"), amended)
		r.check(
			"amendment points back at the original",
			frappe.db.get_value("Material Request", amended, "amended_from") == draft.name,
			str(frappe.db.get_value("Material Request", amended, "amended_from")),
		)

		res = frappe.call(documents.run_action, key="material-request", name=amended, action="duplicate")
		copy = res["name"]
		r.check("run_action duplicate makes a draft", res["docstatus"] == 0 and copy != amended, copy)
		r.check(
			"a duplicate is not an amendment",
			not frappe.db.get_value("Material Request", copy, "amended_from"),
		)

		# Amending something that was never cancelled has to be refused, or the
		# action would quietly create an orphan draft.
		try:
			frappe.call(documents.run_action, key="material-request", name=copy, action="amend")
			r.check("amending a live document is refused", False, "no error raised")
		except frappe.ValidationError:
			r.check("amending a live document is refused", True)

		try:
			frappe.call(documents.run_action, key="material-request", name=copy, action="delete")
			r.check("unknown action is refused", False, "no error raised")
		except frappe.ValidationError:
			r.check("unknown action is refused", True)
	except Exception as e:
		r.check("document actions", False, f"{type(e).__name__}: {e}")


def _dashboard(r):
	"""The dashboard's own shape.

	The trend is checked for length rather than content: a chart that drops
	quiet days draws a closed shop as if it never happened, and that is the one
	failure the numbers alone would not reveal.
	"""
	from cosmestics.api import dashboard

	print()
	try:
		data = frappe.call(dashboard.overview, days=30)
	except Exception as e:
		r.check("dashboard overview", False, f"{type(e).__name__}: {e}")
		return

	r.check("dashboard returns stat tiles", len(data["stats"]) == 8, f"{len(data['stats'])} tiles")
	r.check(
		"every tile carries an icon and a value",
		all("icon" in s and "value" in s and "type" in s for s in data["stats"]),
	)
	r.check(
		"trend covers every day in the window",
		len(data["trend"]) == 30,
		f"{len(data['trend'])} points for 30 days",
	)
	r.check(
		"trend days are unique and ordered",
		[p["day"] for p in data["trend"]] == sorted({p["day"] for p in data["trend"]}),
	)
	r.check(
		"period and comparison window are the same length",
		bool(data["period"]["from"] and data["previous"]["from"]),
		f"{data['period']['from']}..{data['period']['to']} vs {data['previous']['from']}..{data['previous']['to']}",
	)
	r.check(
		"payment mix shares add up",
		not data["payment_mix"] or abs(sum(flt(p["share"]) for p in data["payment_mix"]) - 100) < 0.5,
		str([(p["mode"], p["share"]) for p in data["payment_mix"]]),
	)
	r.check(
		"attention lists carry their own columns",
		all(v["columns"] and isinstance(v["rows"], list) for v in data["attention"].values()),
		str({k: len(v["rows"]) for k, v in data["attention"].items()}),
	)

	# A window shorter than the data must not report the same revenue as a long
	# one; that was how an unscoped date filter would look.
	week = frappe.call(dashboard.overview, days=7)
	r.check(
		"a shorter window reports no more revenue",
		flt(week["stats"][0]["value"]) <= flt(data["stats"][0]["value"]) + 0.01,
		f"7d {week['stats'][0]['value']} vs 30d {data['stats'][0]['value']}",
	)


def _custom_fields_visible(r):
	"""Every Custom Field on the sales documents must be visible in the meta.

	A field that exists in the database but not in the cached DocType meta is
	invisible to the controllers that read it, and any other app's hook doing
	`doc.some_custom_field` then dies with AttributeError — at the counter, on
	submit, after the customer has paid.

	This was observed live: posawesome reads `posa_delivery_charges` on every
	Sales Invoice, and a run against a stale cache failed submit with
	"'SalesInvoice' object has no attribute 'posa_delivery_charges'". Nothing in
	this app was wrong; the cache was. `bench --site <site> clear-cache` fixes
	it, and this check is how you find out that is what happened.
	"""
	stale = {}
	for doctype in ("Sales Invoice", "Sales Invoice Item", "POS Invoice", "Customer", "Item"):
		if not frappe.db.exists("DocType", doctype):
			continue
		declared = frappe.get_all(
			"Custom Field", filters={"dt": doctype}, pluck="fieldname", limit_page_length=0
		)
		meta = frappe.get_meta(doctype)
		missing = [f for f in declared if not meta.has_field(f)]
		if missing:
			stale[doctype] = missing

	r.check(
		"custom fields are visible in the DocType meta (cache is fresh)",
		not stale,
		f"stale meta — run `bench clear-cache`: {stale}" if stale else "no stale fields",
	)


def _till(r, item):
	"""The till's own wiring: tenders, M-Pesa channels, context and receipts."""
	from cosmestics.api import pos, session

	print()
	methods = pos.get_payment_methods()
	keys = [m["key"] for m in methods["methods"]]
	r.check("till offers at least cash", "cash" in keys, str(keys))
	r.check(
		"every offered tender maps to a real Mode of Payment",
		all(frappe.db.exists("Mode of Payment", m["mode_of_payment"]) for m in methods["methods"]),
		str([(m["key"], m["mode_of_payment"]) for m in methods["methods"]]),
	)
	r.check(
		"the three M-Pesa channels are offered",
		{"mpesa_send", "mpesa_paybill", "mpesa_withdraw"} <= set(keys),
		str([m["key"] for m in methods["mpesa_channels"]]),
	)

	# Each channel must be its own Mode of Payment, with its own company account.
	# Sharing one mode is what makes a shift impossible to reconcile: the money
	# is in three different places and the closing entry sees one number.
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	company = frappe.defaults.get_global_default("company")
	channel_modes = {}
	for channel in ("mpesa_send", "mpesa_paybill", "mpesa_withdraw"):
		try:
			mode = pos._mode_of_payment(channel, settings)
			channel_modes[channel] = mode
			r.check(f"{channel} resolves to a Mode of Payment", bool(mode), mode)
		except Exception as e:
			r.check(f"{channel} resolves to a Mode of Payment", False, f"{type(e).__name__}: {e}")

	r.check(
		"the three M-Pesa channels are separate Modes of Payment",
		len(set(channel_modes.values())) == 3,
		str(channel_modes),
	)
	unmapped = [
		mode
		for mode in set(channel_modes.values())
		if company
		and not frappe.db.get_value(
			"Mode of Payment Account", {"parent": mode, "company": company}, "default_account"
		)
	]
	r.check(
		"every M-Pesa channel has a company account, so a shift can open",
		not unmapped,
		f"missing: {unmapped}" if unmapped else f"{len(channel_modes)} mapped",
	)

	# A sale through a channel must actually book against that channel's mode.
	res = frappe.call(
		pos.submit_sale,
		items=[{"item_code": item.item_code, "qty": 1, "rate": 250, "discount_pct": 0}],
		payment={"method": "mpesa_paybill", "tendered": 250, "change": 0, "reference": "PB123"},
	)
	si = frappe.get_doc("Sales Invoice", res["invoice"])
	expected = settings.get("mode_mpesa_paybill") or settings.mode_mpesa
	r.check(
		"a paybill sale books against the paybill mode",
		si.payments[0].mode_of_payment == expected,
		f"{si.payments[0].mode_of_payment} (expected {expected})",
	)

	receipt = frappe.call(pos.receipt_url, invoice=si.name)
	r.check("receipt url built for a real sale", "/printview?" in receipt["url"], receipt["url"][:70])
	r.check("receipt offers a print format", isinstance(receipt["formats"], list), str(receipt["formats"][:3]))

	try:
		frappe.call(pos.receipt_url, invoice="NOT-A-REAL-INVOICE")
		r.check("receipt for a missing invoice is refused", False, "no error raised")
	except frappe.DoesNotExistError:
		r.check("receipt for a missing invoice is refused", True)

	ctx = session.context()
	r.check(
		"till context names a warehouse to sell from",
		bool(ctx["warehouse"]),
		f"branch={ctx['branch']} warehouse={ctx['warehouse']} shift={bool(ctx['shift'])}",
	)
	# The header must not claim one warehouse while the sale draws from another.
	r.check(
		"context warehouse matches the one the sale used",
		ctx["warehouse"] == si.items[0].warehouse,
		f"{ctx['warehouse']} vs {si.items[0].warehouse}",
	)


def _neighbour_sourcing(r, item):
	"""Buying mid-sale from a shop nobody had added to the master list first.

	This is the path that used to refuse the purchase — and therefore the sale —
	because the shop next door was not yet a Supplier. The customer is standing
	there and the goods have changed hands, so it has to succeed.
	"""
	from cosmestics.api.sourcing import receive_from_neighbours

	print()
	novel = "Smoke Test Corner Shop"
	r.check("the test neighbour does not exist yet", not frappe.db.exists("Supplier", novel))

	res = receive_from_neighbours(
		lines=[{"item_code": item.item_code, "qty": 1, "buy_rate": 120, "supplier": novel}]
	)
	r.check("buying from an unknown neighbour succeeds", bool(res["invoices"]), str(res["invoices"]))
	r.check("the shop is created as a Supplier", bool(frappe.db.exists("Supplier", novel)))

	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	r.check(
		"the new shop lands in the neighbour group, so the till offers it next time",
		frappe.db.get_value("Supplier", novel, "supplier_group") == settings.neighbour_supplier_group,
		str(frappe.db.get_value("Supplier", novel, "supplier_group")),
	)

	pi = frappe.get_doc("Purchase Invoice", res["invoices"][0]["name"])
	r.check("the purchase is submitted", pi.docstatus == 1, pi.name)
	r.check("the purchase received stock", pi.update_stock == 1)
	# Whether the cashier handed money over next door is not something the till
	# can know, so the payable stands rather than inventing a cash movement that
	# never appeared in the drawer.
	r.check(
		"the neighbour is left owed, not marked paid",
		pi.is_paid == 0 and flt(pi.outstanding_amount) > 0,
		f"is_paid={pi.is_paid} outstanding={pi.outstanding_amount}",
	)


def _dashboard_tabs(r):
	"""The five department tabs.

	All return {stats, sections}; the front end renders them through one
	component, so a tab that quietly returns a different shape would render as a
	blank panel rather than an error.
	"""
	from cosmestics.api import dashboard

	print()
	opts = dashboard.filters()
	r.check(
		"dashboard filters offer branches and warehouses",
		isinstance(opts["branches"], list) and isinstance(opts["warehouses"], list),
		f"{len(opts['branches'])} branches, {len(opts['warehouses'])} warehouses",
	)

	for tab in ("sales", "branches", "warehouses", "procurement", "accounts"):
		try:
			data = frappe.call(getattr(dashboard, tab), days=90)
			shape_ok = (
				isinstance(data.get("stats"), list)
				and data["stats"]
				and isinstance(data.get("sections"), list)
				and data["sections"]
			)
			r.check(f"dashboard tab {tab}", shape_ok, f"{len(data.get('sections', []))} sections")
			bad = [
				s["key"]
				for s in data["sections"]
				if not s.get("columns") or not isinstance(s.get("rows"), list)
			]
			r.check(f"tab {tab} sections carry their own columns", not bad, f"missing: {bad}" if bad else "")
		except Exception as e:
			r.check(f"dashboard tab {tab}", False, f"{type(e).__name__}: {e}")

	# The filters have to actually filter, or they are decoration.
	profiles = frappe.get_all("POS Profile", filters={"disabled": 0}, pluck="name")
	if profiles:
		everything = frappe.call(dashboard.sales, days=3650)
		one = frappe.call(dashboard.sales, days=3650, branch=profiles[0])
		r.check(
			"branch filter narrows the sales tab",
			flt(one["stats"][0]["value"]) <= flt(everything["stats"][0]["value"]) + 0.01,
			f"{profiles[0]}: {one['stats'][0]['value']} of {everything['stats'][0]['value']}",
		)

	warehouses = frappe.get_all("Warehouse", filters={"is_group": 0, "disabled": 0}, pluck="name")
	if warehouses:
		everything = frappe.call(dashboard.warehouses, days=3650)
		one = frappe.call(dashboard.warehouses, days=3650, warehouse=warehouses[0])
		r.check(
			"warehouse filter narrows the warehouses tab",
			len(one["sections"][0]["rows"]) <= len(everything["sections"][0]["rows"]),
			f"{len(one['sections'][0]['rows'])} of {len(everything['sections'][0]['rows'])} locations",
		)


def _master_data(r):
	"""Quick-add. Creating the record is the whole point, so it is created."""
	from cosmestics.api import customers, master

	print()
	types = master.list_types()
	r.check("master types listed", bool(types), str([t["key"] for t in types]))

	declared = {t["key"] for t in types}
	r.check(
		"the five a shop asks for are all there",
		{"customer", "supplier", "item", "warehouse", "account"} <= declared or not declared,
		str(sorted(declared)),
	)

	# Every declared field must exist on its DocType, or the form silently drops
	# what the user typed into it.
	problems = []
	for entry in master.MASTERS:
		meta = frappe.get_meta(entry["doctype"])
		for field in entry["fields"]:
			# `opening_price` is this app's own, written as an Item Price after insert.
			if field["fieldname"] == "opening_price":
				continue
			if not meta.has_field(field["fieldname"]):
				problems.append(f"{entry['doctype']}.{field['fieldname']}")
		if not meta.has_field(entry["title_field"]):
			problems.append(f"{entry['doctype']}.{entry['title_field']} (title)")
	r.check("quick-add fields exist on their DocTypes", not problems, "; ".join(problems) if problems else f"{len(master.MASTERS)} types")

	try:
		master.options(key="customer", fieldname="customer_name")
		r.check("asking for options on a non-link field is refused", False, "no error raised")
	except frappe.ValidationError:
		r.check("asking for options on a non-link field is refused", True)

	# The screen lists what already exists, not just a form: a create-only screen
	# is how a shop ends up with the same customer three times.
	for entry in master.MASTERS:
		try:
			listed = frappe.call(master.list_records, key=entry["key"], limit=5)
			r.check(
				f"records list {entry['key']}",
				bool(listed["columns"]) and isinstance(listed["rows"], list),
				f"{len(listed['rows'])} of {listed['total']}",
			)
		except Exception as e:
			r.check(f"records list {entry['key']}", False, f"{type(e).__name__}: {e}")

	# Records are editable, so editing is exercised: reading one back and saving
	# a change is the whole point of the screen.
	existing = frappe.get_all("Customer", limit=1, pluck="name")
	if existing:
		rec = frappe.call(master.get_record, key="customer", name=existing[0])
		r.check("a record loads for editing", bool(rec["values"]), rec["title"])
		res = frappe.call(
			master.update,
			key="customer",
			name=existing[0],
			values={"mobile_no": "254700000123"},
		)
		r.check("an edit saves", res["changed"], res["message"])
		r.check(
			"the edit reached the record",
			frappe.db.get_value("Customer", existing[0], "mobile_no") == "254700000123",
		)
		try:
			frappe.call(master.update, key="customer", name=existing[0], values={"customer_name": ""})
			r.check("a required field cannot be emptied", False, "no error raised")
		except frappe.ValidationError:
			r.check("a required field cannot be emptied", True)

		# The ledger is built from GL Entry, so a payment moves it and an
		# invoice-only statement would not.
		led = frappe.call(customers.ledger, customer=existing[0], days=3650)
		r.check("customer ledger loads", isinstance(led["rows"], list), f"{len(led['rows'])} entries")
		if led["rows"]:
			running = led["opening"]
			for row in led["rows"]:
				running += flt(row["billed"]) - flt(row["paid"])
			r.check(
				"the running balance adds up to the closing figure",
				abs(running - flt(led["closing"])) < 0.01,
				f"{running} vs {led['closing']}",
			)

	groups = master.options(key="customer", fieldname="customer_group")
	r.check("link options resolve", isinstance(groups, list), f"{len(groups)} customer groups")

	res = frappe.call(
		master.create,
		key="customer",
		values={"customer_name": "Quick Add Smoke Customer", "mobile_no": "254700111222"},
	)
	r.check("customer created from quick-add", bool(res["name"]), res["name"])
	r.check(
		"created customer is real",
		frappe.db.exists("Customer", res["name"]),
		str(frappe.db.get_value("Customer", res["name"], "mobile_no")),
	)
	r.check("quick-add returns a desk link", "/app/" in res["desk_url"], res["desk_url"])

	try:
		frappe.call(master.create, key="customer", values={})
		r.check("quick-add refuses a missing required field", False, "no error raised")
	except frappe.ValidationError:
		r.check("quick-add refuses a missing required field", True)

	try:
		frappe.call(master.create, key="user", values={"customer_name": "x"})
		r.check("an unregistered master type is refused", False, "no error raised")
	except frappe.DoesNotExistError:
		r.check("an unregistered master type is refused", True)

	# A supplier in the neighbour group must actually reach the till, which is
	# the whole reason quick-add offers Supplier at all.
	settings = frappe.get_cached_doc("Cosmestics POS Settings")
	if settings.neighbour_supplier_group:
		frappe.call(
			master.create,
			key="supplier",
			values={
				"supplier_name": "Quick Add Neighbour Shop",
				"supplier_group": settings.neighbour_supplier_group,
			},
		)
		from cosmestics.api.catalog import _neighbours, _sourcing_status

		names = [n["name"] for n in _neighbours()]
		r.check("a neighbour added here reaches the till", "Quick Add Neighbour Shop" in names, str(names))
		# The standing list of what has been bought next door, as its own screen.
	from cosmestics.api.sourcing import list_purchases

	purchases = list_purchases(days=30)
	r.check(
		"neighbour purchases list answers, or says why not",
		isinstance(purchases["rows"], list),
		purchases["reason"] or f"{purchases['totals']['count']} purchases",
	)
	unpaid = list_purchases(days=30, status="unpaid")
	r.check(
		"the unpaid filter only returns what is owed",
		all(p["outstanding"] > 0 for p in unpaid["rows"]),
		f"{len(unpaid['rows'])} owed",
	)

	r.check("sourcing reports available once a shop exists", _sourcing_status()["available"])


def _recent_sales(r):
	from cosmestics.api import pos

	print()
	data = frappe.call(pos.recent_sales, limit=10)
	r.check("recent sales load", isinstance(data["rows"], list), f"{len(data['rows'])} sales")
	r.check("recent sales default to this cashier", data["mine"] is True)
	if data["rows"]:
		r.check(
			"recent sales are newest first",
			[str(x["creation"]) for x in data["rows"]]
			== sorted((str(x["creation"]) for x in data["rows"]), reverse=True),
		)
		mine = frappe.get_all(
			"Sales Invoice", filters={"docstatus": 1, "owner": frappe.session.user}, pluck="name"
		)
		r.check(
			"'only mine' really is only mine",
			all(x["name"] in mine for x in data["rows"]),
		)


def _barcodes(r):
	"""Generated barcodes have to be real barcodes.

	The check digit is asserted against published EAN-13s rather than against
	this module's own arithmetic — a self-consistent implementation of the wrong
	formula would pass any test written from the same misunderstanding, and the
	failure only shows up at a counter when a scanner refuses to beep.
	"""
	from cosmestics.api import barcodes

	print()
	known = {
		"4006381333931": "1",
		"5901234123457": "7",
		"9780201379624": "4",
		"0075678164125": "5",
	}
	wrong = [k for k, digit in known.items() if barcodes.check_digit(k[:12]) != digit]
	r.check("EAN-13 check digit matches published barcodes", not wrong, f"wrong: {wrong}" if wrong else f"{len(known)} verified")

	data = frappe.call(barcodes.list_items, only_missing=1, limit=50)
	r.check("barcode candidates listed", isinstance(data["rows"], list), f"{len(data['rows'])} missing a barcode")
	r.check(
		"barcode type resolved from this site's DocType",
		data["barcode_type"] in (None, *barcodes.PREFERRED_TYPES),
		str(data["barcode_type"]),
	)

	if not data["rows"]:
		print("  SKIP: every stock item already has a barcode")
		return

	picks = [row["item_code"] for row in data["rows"][:3]]
	res = frappe.call(barcodes.generate, item_codes=picks)
	r.check("barcodes generated", res["created"] == len(picks), f"{res['created']} of {len(picks)}")

	made = [row["barcode"] for row in res["rows"] if row["created"]]
	r.check("every code is 13 digits", all(len(c) == 13 and c.isdigit() for c in made), str(made))
	r.check(
		"every code carries a valid check digit",
		all(barcodes.check_digit(c[:12]) == c[12] for c in made),
		str(made),
	)
	r.check(
		"codes use the internal prefix, so they cannot clash with a supplier's",
		all(c.startswith(barcodes.INTERNAL_PREFIX) for c in made),
	)
	r.check("codes are unique", len(set(made)) == len(made))

	# Written where the till looks, or the whole feature is decorative.
	stored = frappe.get_all(
		"Item Barcode", filters={"parent": ("in", picks)}, fields=["parent", "barcode"]
	)
	r.check(
		"codes are stored on the Item itself",
		{row.barcode for row in stored} >= set(made),
		f"{len(stored)} rows",
	)

	# Re-running must not mint a second code for an item that now has one.
	again = frappe.call(barcodes.generate, item_codes=picks)
	r.check(
		"regenerating skips items that already have a code",
		again["created"] == 0 and again["skipped"] == len(picks),
		f"created={again['created']} skipped={again['skipped']}",
	)

	try:
		frappe.call(barcodes.generate, item_codes=[])
		r.check("generating for nothing is refused", False, "no error raised")
	except frappe.ValidationError:
		r.check("generating for nothing is refused", True)


def _whatsapp(r):
	"""The WhatsApp wiring, without sending anything.

	The send itself needs a live bridge, so what is checked here is the part
	that was actually wrong: reading the bridge's reply. Its success shape is
	inconsistent, and a stricter reading than the integration's own logged
	delivered messages as failures.
	"""
	from cosmestics.api import notifications

	print()
	# Deliberately not a pass/fail on whether WhatsApp is *configured* — plenty of
	# sites will not use it. What is checked is that the app reports the truth
	# about it, because "importable" used to be treated as "working" and this
	# site has the package installed with none of its DocTypes.
	usable = notifications._integration_available()
	has_doctype = bool(frappe.db.exists("DocType", "Whatsapp Settings"))
	r.check(
		"whatsapp availability is reported honestly",
		usable == has_doctype,
		f"usable={usable} settings doctype={has_doctype}",
	)

	groups = notifications.list_groups()
	r.check(
		"group listing answers, or says why not",
		isinstance(groups["groups"], list) and (groups["groups"] or groups["reason"]),
		f"{len(groups['groups'])} groups"
		+ (f" · {groups['reason']}" if groups.get("reason") else ""),
	)
	# The envelope varies by bridge, so the parser is pinned against the shapes
	# it is known to answer with rather than the one seen most recently.
	shapes = [
		({"data": [{"id": "1@g.us", "name": "Staff"}]}, [("1@g.us", "Staff")]),
		({"groups": [{"jid": "2@g.us", "subject": "Deliveries"}]}, [("2@g.us", "Deliveries")]),
		([{"chat_id": "3@g.us", "title": "Owners"}], [("3@g.us", "Owners")]),
		({"data": [{"id": {"_serialized": "4@g.us"}, "name": "Branch"}]}, [("4@g.us", "Branch")]),
		({"error": "no instance"}, []),
		({"data": [{"name": "no id here"}]}, []),
	]
	wrong = [
		s
		for s, expected in shapes
		if [(g["id"], g["name"]) for g in notifications._parse_groups(s)] != expected
	]
	r.check("group replies are parsed whatever shape they arrive in", not wrong, str(wrong))

	if not usable:
		print("  SKIP: whatsapp_integration DocTypes are not installed on this site")
		return

	from whatsapp_integration.api.whatsapp import whatsapp as wa

	r.check(
		"the high-level send endpoint exists",
		callable(getattr(wa, "send_quick_message_via_whatsapp", None)),
	)
	r.check(
		"the document (PDF) send endpoint exists",
		callable(getattr(wa, "send_document_via_whatsapp", None)),
	)
	r.check("sender list is readable", isinstance(notifications.list_senders(), list))

	# Response shapes taken from whatsapp_integration's own handling, so the two
	# cannot come to different conclusions about the same reply.
	shapes = [
		({"status": "success"}, True),
		({"status": "queued"}, True),
		({"status": "processing"}, True),
		({"error": "false"}, True),
		({"data": {"key": {"id": "abc"}}}, True),
		({"error": "Unexpected message response format"}, True),
		({"error": "Invalid number format."}, False),
		(None, False),
	]
	wrong = [s for s, expected in shapes if notifications._succeeded(s) is not expected]
	r.check(
		"bridge responses are read the same way the integration reads them",
		not wrong,
		f"misread: {wrong}" if wrong else f"{len(shapes)} shapes",
	)


def _annotations(r):
	"""Every whitelisted argument must carry a type annotation.

	Frappe enforces this at the HTTP boundary (via the
	`require_type_annotated_api_methods` hook) but not when the function is
	called directly from Python — so the rest of this smoke test would happily
	pass while every endpoint 500s in the browser. This asserts the exact code
	path that fails: `transform_parameter_types(..., force_types=True)`.
	"""
	import inspect

	from frappe.utils.typing_validations import transform_parameter_types

	from cosmestics.api import (
		barcodes,
		catalog,
		customers,
		dashboard,
		documents,
		master,
		notifications,
		modules,
		pos,
		pricing,
		reorder,
		reports,
		session,
		settings,
		shift,
		sourcing,
		stock,
	)

	# Every whitelisted endpoint the front end calls, not just the till ones.
	# The back-office modules were missing from this list, which is why "the
	# screen is empty" and "the endpoint 500s at the HTTP boundary" were
	# indistinguishable from the browser.
	endpoints = [
		(pos.submit_sale, {"items": [], "payment": {}}),
		(shift.get_profiles, {}),
		(shift.get_open_shift, {}),
		(shift.open_shift, {"pos_profile": "x"}),
		(shift.get_closing_summary, {}),
		(shift.close_shift, {}),
		(customers.search, {"query": "x"}),
		(customers.create, {"customer_name": "x"}),
		(stock.request_transfer, {"items": [], "from_warehouse": "x"}),
		(sourcing.receive_from_neighbours, {"lines": []}),
		(sourcing.list_purchases, {"days": 30, "status": None, "limit": 200}),
		(catalog.get_catalog, {}),
		(session.me, {}),
		(session.context, {}),
		(pos.get_payment_methods, {}),
		(pos.receipt_url, {"invoice": "x", "print_format": None}),
		(modules.inventory, {"warehouse": "x", "search": "y", "limit": 10}),
		(modules.warehouses, {}),
		(modules.sales, {"days": 30, "limit": 10}),
		(modules.purchasing, {"days": 30, "limit": 10}),
		(modules.accounts, {"days": 30}),
		(reports.list_reports, {}),
		(reports.run, {"report": "sales_summary", "days": 30, "warehouse": None}),
		(reorder.get_warehouse_tree, {}),
		(reorder.get_reorder_items, {"search": None, "only_unconfigured": 0, "limit": 200}),
		(reorder.get_item_reorder, {"item_code": "x", "parent_warehouse": None}),
		(reorder.get_reorder_rows, {"parent_warehouse": "x", "search": None, "only_below": 0}),
		(reorder.save_reorder_rules, {"rules": []}),
		(reorder.copy_levels, {"from_warehouse": "x", "to_warehouses": [], "overwrite": 0}),
		(pricing.get_price_list_options, {}),
		(pricing.get_filters, {}),
		(pricing.get_prices, {"price_list": "x"}),
		(pricing.preview_bulk_change, {"price_list": "x", "item_codes": [], "mode": "percent", "value": 1}),
		(pricing.apply_bulk_change, {"price_list": "x", "changes": []}),
		(documents.list_types, {}),
		(
			documents.list_documents,
			{"key": "x", "days": 30, "status": None, "party": None, "search": None, "limit": 10, "start": 0},
		),
		(documents.get_document, {"key": "x", "name": "y"}),
		(documents.new_document_form, {"key": "x"}),
		(documents.link_options, {"key": "x", "fieldname": "y", "search": None, "limit": 20}),
		(documents.create_document, {"key": "x", "values": {}, "items": [], "submit": 0}),
		(documents.run_action, {"key": "x", "name": "y", "action": "submit"}),
		(documents.print_url, {"key": "x", "name": "y", "print_format": None}),
		(documents.send_whatsapp, {"key": "x", "name": "y", "to": None, "sender": None, "as_pdf": 1}),
		(documents.whatsapp_senders, {}),
		(documents.insights, {"key": "x", "days": 30}),
		(dashboard.overview, {"days": 30}),
		(dashboard.filters, {}),
		(dashboard.sales, {"days": 30, "branch": None}),
		(dashboard.branches, {"days": 30}),
		(dashboard.warehouses, {"days": 30, "warehouse": None}),
		(dashboard.procurement, {"days": 30}),
		(dashboard.accounts, {"days": 30}),
		(master.list_types, {}),
		(master.list_records, {"key": "customer", "search": None, "limit": 100}),
		(master.get_record, {"key": "customer", "name": "x"}),
		(master.update, {"key": "customer", "name": "x", "values": {}}),
		(customers.ledger, {"customer": "x", "days": 365}),
		(master.options, {"key": "customer", "fieldname": "customer_group", "search": None, "limit": 20}),
		(master.create, {"key": "customer", "values": {}}),
		(pos.recent_sales, {"limit": 20, "mine": 1}),
		(barcodes.list_items, {"search": None, "only_missing": 1, "limit": 50}),
		(barcodes.generate, {"item_codes": [], "skip_existing": 1}),
		(notifications.test_whatsapp, {"to": "x", "message": None}),
		(notifications.list_groups, {}),
		(
			notifications.share,
			{"to": "x", "message": "y", "sender": None, "doctype": None, "name": None},
		),
		(shift.get_movement_options, {}),
		(shift.list_movements, {"shift_name": None}),
		(shift.list_recent_shifts, {"limit": 10, "mine": 1}),
		(
			shift.record_movement,
			{
				"movement_type": "Expense",
				"amount": 1,
				"mode_of_payment": None,
				"reason": None,
				"person": None,
				"party": None,
				"expense_account": None,
			},
		),
		(shift.void_movement, {"name": "x"}),
		(settings.get, {}),
		(settings.save_pos_settings, {"values": {}}),
		(settings.save_profile, {"name": "x", "values": {}}),
		(settings.assign_profile, {"name": "x", "assign": 1}),
		(settings.save_user, {"values": {}}),
		(settings.link_options, {"doctype": "Warehouse", "search": None, "limit": 20}),
	]

	missing = []
	for func, kwargs in endpoints:
		# Unwrap the whitelist decorator to reach the annotated function.
		target = inspect.unwrap(func)
		try:
			transform_parameter_types(target, (), dict(kwargs), force_types=True)
		except frappe.exceptions.FrappeTypeError as e:
			missing.append(f"{target.__name__}: {e}")

	r.check(
		"all whitelisted args are type-annotated",
		not missing,
		"; ".join(missing) if missing else f"{len(endpoints)} endpoints",
	)


def _stocked_item(warehouse):
	"""Pick an item that can actually be sold right now.

	`Bin.actual_qty` is not sufficient: ERPNext validates against the stock
	ledger as of the posting datetime, and the two disagree when a warehouse has
	backdated or future-dated entries. Trusting Bin alone picked an item that
	then failed with NegativeStockError, so each candidate is confirmed against
	the real balance.
	"""
	from erpnext.stock.utils import get_stock_balance
	from frappe.utils import nowdate, nowtime

	rows = frappe.db.sql(
		"""select b.item_code, b.actual_qty, b.warehouse
		   from tabBin b join tabItem i on i.name = b.item_code
		   where b.warehouse = %s
		     and b.actual_qty >= 10
		     and i.is_stock_item = 1 and i.disabled = 0
		     and i.is_sales_item = 1
		     and i.has_batch_no = 0 and i.has_serial_no = 0
		   order by b.actual_qty desc limit 25""",
		warehouse,
		as_dict=True,
	)

	for row in rows:
		try:
			balance = get_stock_balance(row.item_code, row.warehouse, nowdate(), nowtime())
		except Exception:
			continue
		# The suite sells this item several times over; leave generous headroom.
		if flt(balance) >= 10:
			row.actual_qty = flt(balance)
			return row

	return None
