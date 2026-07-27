"""Post-deploy smoke test.

Posts two real sales through `submit_sale`, asserts the invoice, payment mode
and change accounting are right, then rolls back so nothing persists.

    bench --site <site> execute cosmestics.setup.smoke.run

Safe to run against a live site: the transaction is always rolled back, even
on failure.
"""

import frappe
from frappe.utils import flt


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

	wh = _default_warehouse()
	wh_type = frappe.db.get_value("Warehouse", wh, "warehouse_type") if wh else None
	r.check(
		"default warehouse is sellable (not Transit)",
		bool(wh) and wh_type != "Transit",
		f"{wh} (type={wh_type})",
	)

	item = _stocked_item()
	if not item:
		print("SKIP: no stocked, non-batched item to sell")
		return

	settings = frappe.get_single("Cosmestics POS Settings")
	settings.default_source_warehouse = item.warehouse
	settings.save(ignore_permissions=True)
	frappe.clear_cache(doctype="Cosmestics POS Settings")
	print(f"  selling {item.item_code} (qty {item.actual_qty}) from {item.warehouse}\n")

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

	_shift_and_credit(r, item)


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

	shift = open_shift(
		pos_profile=profile,
		balances=[{"mode_of_payment": "Cash", "opening_amount": 5000}],
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

	# --- Close, with a deliberate 100 short in the drawer ---
	closed = close_shift(counted=[{"mode_of_payment": "Cash", "closing_amount": 5300}])
	r.check("shift closed", bool(closed["name"]), closed["name"])
	r.check("shortfall detected (-100)", flt(closed["difference"]) == -100,
	        str(closed["difference"]))
	r.check("opening entry marked Closed",
	        frappe.db.get_value("POS Opening Entry", shift["name"], "status") == "Closed",
	        str(frappe.db.get_value("POS Opening Entry", shift["name"], "status")))


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

	from cosmestics.api import customers, pos, shift, sourcing, stock

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


def _stocked_item():
	rows = frappe.db.sql(
		"""select b.item_code, b.actual_qty, b.warehouse
		   from tabBin b join tabItem i on i.name = b.item_code
		   where b.actual_qty >= 3
		     and i.is_stock_item = 1 and i.disabled = 0
		     and i.is_sales_item = 1
		     and i.has_batch_no = 0 and i.has_serial_no = 0
		   order by b.actual_qty desc limit 1""",
		as_dict=True,
	)
	return rows[0] if rows else None
