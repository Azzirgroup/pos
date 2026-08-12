"""The transactional documents, through one generic set of endpoints.

Eleven document types share one list, one detail payload and one set of row
actions. A module per doctype would be eleven near-identical files, and the
first bug fixed in ten of them would leave the eleventh quietly wrong — so the
differences live in `DOCUMENTS` as data and the behaviour is written once.

Labels and render types are read from the DocType itself rather than restated
here: a field relabelled in the desk shows the new label on this screen without
an edit. What the registry *does* carry is the editorial choice — which columns
a shop manager wants to see, and in what order — because `in_list_view` on a
core ERPNext doctype is tuned for the desk, not for this screen.

Everything is permission-checked by Frappe in the normal way: documents are
loaded with `frappe.get_doc` and actions run through the real `submit`/`cancel`
lifecycle. This module never passes `ignore_permissions`. A caller reaches a
doctype only by its registry key, so an arbitrary doctype name cannot travel
from the browser into `get_doc`.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_url, nowdate, quoted

from cosmestics.api.search import like_or_filters, search_rows

DEFAULT_DAYS = 30
MAX_LIMIT = 500

# Fields worth a totals block, in the order a reader wants them. Only those the
# doctype actually has, and only when non-zero, are returned.
TOTAL_FIELDS = (
	"total_qty",
	"total_quantity",
	"net_total",
	"total_taxes_and_charges",
	"grand_total",
	"rounded_total",
	"paid_amount",
	"received_amount",
	"total_allocated_amount",
	"outstanding_amount",
	"change_amount",
	"total_incoming_value",
	"total_outgoing_value",
	"value_difference",
	"difference_amount",
)

# Types that are deliberately not raised by hand, and where they come from
# instead. Stated rather than left blank: a screen with no New button and no
# reason looks broken, when in fact making one here would be the wrong move.
NOT_CREATABLE = {
	"quotation": "Given at the till, where a price is what a customer was actually told. Load one back into the cart from there to turn it into a sale.",
	"pos-invoice": "ERPNext's offline till document. This app posts Sales Invoices, so raise one of those.",
	"pos-opening": "Created by opening a shift at the till.",
	"pos-closing": "Created by closing a shift at the till, so it reconciles against what was counted.",
	"payment-entry": "Raised against an invoice, so the money lands on the right one. Open the invoice and record the payment there.",
	"landed-cost-voucher": "Spreads freight and duty across receipts that already exist, so start from the Purchase Receipt.",
}


def _lines(rate: bool = True, warehouse: str | None = "Warehouse", extra: list | None = None) -> list:
	"""The line spec most documents share: an item, a quantity, and usually a
	price and a place. Written once so ten forms cannot drift apart."""
	out = [
		{"fieldname": "item_code", "label": "Item", "type": "item", "required": True},
		{"fieldname": "qty", "label": "Qty", "type": "number", "required": True, "default": 1},
	]
	if rate:
		out.append({"fieldname": "rate", "label": "Rate", "type": "currency"})
	if warehouse:
		# Defaulted, because the answer is the same on nearly every line of
		# nearly every document a one-shop site raises — and a field that has to
		# be retyped per row is the field that gets left blank.
		out.append(
			{
				"fieldname": "warehouse",
				"label": warehouse,
				"type": "link",
				"options": "Warehouse",
				"default": "stock_warehouse",
			}
		)
	return out + (extra or [])


def _dated(*fields) -> list:
	return [
		{"fieldname": f, "label": label, "type": "date", "default": default, "required": required}
		for f, label, default, required in fields
	]


DOCUMENTS = [
	{
		"key": "sales-invoice",
		"doctype": "Sales Invoice",
		"group": "Sales",
		"icon": "receipt",
		"date_field": "posting_date",
		"party_field": "customer",
		"party_doctype": "Customer",
		"amount_field": "grand_total",
		"outstanding_field": "outstanding_amount",
		"due_field": "due_date",
		"columns": ["name", "posting_date", "customer", "status", "grand_total", "outstanding_amount"],
		"detail": ["due_date", "is_pos", "pos_profile", "company", "remarks"],
		"tables": [
			("items", ["item_code", "item_name", "qty", "uom", "rate", "amount"]),
			("payments", ["mode_of_payment", "amount"]),
			("taxes", ["description", "rate", "tax_amount"]),
		],
		"reports": ["sales_summary", "top_items", "profit_margin", "payment_modes", "receivables"],
		"create": {
			"fields": [
				{"fieldname": "customer", "label": "Customer", "type": "link", "options": "Customer", "required": True},
				*_dated(
					("posting_date", "Date", "today", True),
					("due_date", "Due", "week", False),
				),
			],
			"items": _lines(),
			"hint": "For invoices raised off the till. Sales rung up at the counter post themselves.",
		},
	},
	{
		# Raised at the till by `cosmestics.api.quotations.create`, or from the
		# desk. Not creatable from this generic form — the till's own flow is
		# where a quote is actually given, and it prices lines from what the
		# cashier told the customer rather than re-deriving them here.
		"key": "quotation",
		"doctype": "Quotation",
		"group": "Sales",
		"icon": "file",
		"date_field": "transaction_date",
		"party_field": "party_name",
		"amount_field": "grand_total",
		"columns": ["name", "transaction_date", "party_name", "status", "valid_till", "grand_total"],
		"detail": ["quotation_to", "valid_till", "order_type", "company", "terms"],
		"tables": [
			("items", ["item_code", "item_name", "qty", "uom", "rate", "amount"]),
			("taxes", ["description", "rate", "tax_amount"]),
		],
		"reports": [],
	},
	{
		# ERPNext's own POS Invoice, used by sites running the offline till. This
		# app posts Sales Invoices with `is_pos` set, so on a Cosmestics-only site
		# this list is legitimately empty — the Channel column on Sales Invoice is
		# where till sales show up.
		"key": "pos-invoice",
		"doctype": "POS Invoice",
		"group": "Sales",
		"icon": "cart",
		"date_field": "posting_date",
		"party_field": "customer",
		"party_doctype": "Customer",
		"amount_field": "grand_total",
		"outstanding_field": "outstanding_amount",
		"columns": ["name", "posting_date", "customer", "status", "grand_total", "outstanding_amount"],
		"detail": ["pos_profile", "company"],
		"tables": [
			("items", ["item_code", "item_name", "qty", "uom", "rate", "amount"]),
			("payments", ["mode_of_payment", "amount"]),
		],
		"reports": ["sales_summary", "payment_modes", "cashier_sales"],
	},
	{
		"key": "sales-order",
		"doctype": "Sales Order",
		"group": "Sales",
		"icon": "clipboard",
		"date_field": "transaction_date",
		"party_field": "customer",
		"party_doctype": "Customer",
		"amount_field": "grand_total",
		"columns": ["name", "transaction_date", "customer", "status", "per_delivered", "per_billed", "grand_total"],
		"detail": ["delivery_date", "company"],
		"tables": [
			("items", ["item_code", "item_name", "delivery_date", "qty", "delivered_qty", "uom", "rate", "amount", "warehouse"]),
		],
		"reports": ["sales_summary", "top_items", "receivables"],
		"create": {
			"fields": [
				{"fieldname": "customer", "label": "Customer", "type": "link", "options": "Customer", "required": True},
				{"fieldname": "transaction_date", "label": "Date", "type": "date", "default": "today", "required": True},
				{"fieldname": "delivery_date", "label": "Deliver by", "type": "date", "default": "week", "required": True},
			],
			"items": [
				{"fieldname": "item_code", "label": "Item", "type": "item", "required": True},
				{"fieldname": "qty", "label": "Qty", "type": "number", "required": True, "default": 1},
				{"fieldname": "rate", "label": "Rate", "type": "currency"},
				{
					"fieldname": "warehouse",
					"label": "From",
					"type": "link",
					"options": "Warehouse",
					"default": "stock_warehouse",
				},
			],
		},
	},
	{
		"key": "payment-entry",
		"doctype": "Payment Entry",
		"group": "Sales",
		"icon": "money",
		"date_field": "posting_date",
		"party_field": "party",
		"amount_field": "paid_amount",
		"columns": ["name", "posting_date", "payment_type", "party", "mode_of_payment", "paid_amount", "status"],
		"detail": ["party_type", "party_name", "reference_no", "reference_date", "company"],
		"tables": [
			(
				"references",
				["reference_doctype", "reference_name", "due_date", "total_amount", "outstanding_amount", "allocated_amount"],
			),
			("deductions", ["account", "amount"]),
		],
		"reports": ["receivables", "payables"],
	},
	{
		"key": "purchase-invoice",
		"doctype": "Purchase Invoice",
		"group": "Purchasing",
		"icon": "receipt",
		"date_field": "posting_date",
		"party_field": "supplier",
		"party_doctype": "Supplier",
		"amount_field": "grand_total",
		"outstanding_field": "outstanding_amount",
		"due_field": "due_date",
		"columns": ["name", "posting_date", "supplier", "status", "grand_total", "outstanding_amount"],
		"detail": ["due_date", "bill_no", "bill_date", "company"],
		"tables": [
			("items", ["item_code", "item_name", "qty", "uom", "rate", "amount"]),
			("taxes", ["description", "rate", "tax_amount"]),
		],
		"reports": ["payables"],
		"create": {
			"fields": [
				# Not required: a line can name its own supplier instead (see
				# the `items` spec below) — required only when nothing else
				# will supply one, which `create_document` checks itself once
				# every line is known.
				{"fieldname": "supplier", "label": "Default supplier", "type": "link", "options": "Supplier"},
				*_dated(
					("posting_date", "Date", "today", True),
					("due_date", "Due", "week", False),
				),
				# Asked once at the top rather than on every line, the way the
				# receipt form asks it. Naming a warehouse here also turns the
				# invoice into a stock receipt — see `_apply_stock_receipt`.
				{
					"fieldname": "set_warehouse",
					"label": "Into",
					"type": "link",
					"options": "Warehouse",
					"default": "stock_warehouse",
				},
			],
			# A Purchase Invoice is one supplier's document — this per-line
			# override exists so a bulk entry spanning several suppliers can
			# still be filled in as one list, and `create_document` splits it
			# into one invoice per supplier actually used rather than
			# pretending a single invoice could hold all of them.
			"items": _lines(
				warehouse=None,
				extra=[{"fieldname": "supplier", "label": "Supplier", "type": "link", "options": "Supplier"}],
			),
			"line_from_header": {"warehouse": "set_warehouse"},
		},
	},
	{
		"key": "purchase-order",
		"doctype": "Purchase Order",
		"group": "Purchasing",
		"icon": "truck",
		"date_field": "transaction_date",
		"party_field": "supplier",
		"party_doctype": "Supplier",
		"amount_field": "grand_total",
		"columns": ["name", "transaction_date", "supplier", "status", "per_received", "per_billed", "grand_total"],
		"detail": ["schedule_date", "company"],
		"tables": [
			("items", ["item_code", "item_name", "schedule_date", "qty", "received_qty", "uom", "rate", "amount"]),
		],
		"reports": ["payables", "below_reorder"],
		"create": {
			"fields": [
				{"fieldname": "supplier", "label": "Supplier", "type": "link", "options": "Supplier", "required": True},
				{"fieldname": "transaction_date", "label": "Date", "type": "date", "default": "today", "required": True},
				{"fieldname": "schedule_date", "label": "Needed by", "type": "date", "default": "week", "required": True},
			],
			"items": [
				{"fieldname": "item_code", "label": "Item", "type": "item", "required": True},
				{"fieldname": "qty", "label": "Qty", "type": "number", "required": True, "default": 1},
				{"fieldname": "rate", "label": "Rate", "type": "currency"},
				{
					"fieldname": "warehouse",
					"label": "Into",
					"type": "link",
					"options": "Warehouse",
					"default": "stock_warehouse",
				},
			],
		},
	},
	{
		"key": "purchase-receipt",
		"doctype": "Purchase Receipt",
		"group": "Purchasing",
		"icon": "package",
		"date_field": "posting_date",
		"party_field": "supplier",
		"party_doctype": "Supplier",
		"amount_field": "grand_total",
		"columns": ["name", "posting_date", "supplier", "status", "per_billed", "grand_total"],
		"detail": ["set_warehouse", "company"],
		"tables": [
			("items", ["item_code", "item_name", "qty", "received_qty", "rejected_qty", "uom", "rate", "amount", "warehouse"]),
		],
		"reports": ["stock_movement", "payables"],
		"create": {
			"fields": [
				# Not required — see the matching note on Purchase Invoice.
				{"fieldname": "supplier", "label": "Default supplier", "type": "link", "options": "Supplier"},
				*_dated(("posting_date", "Date", "today", True)),
				{
					"fieldname": "set_warehouse",
					"label": "Into",
					"type": "link",
					"options": "Warehouse",
					"required": True,
					"default": "stock_warehouse",
				},
			],
			"items": _lines(
				warehouse=None,
				extra=[{"fieldname": "supplier", "label": "Supplier", "type": "link", "options": "Supplier"}],
			),
			"line_from_header": {"warehouse": "set_warehouse"},
			"hint": "Receiving goods without a purchase order. Bill it afterwards with a Purchase Invoice. Different lines can name different suppliers — one receipt is raised per supplier used.",
		},
	},
	{
		"key": "landed-cost-voucher",
		"doctype": "Landed Cost Voucher",
		"group": "Purchasing",
		"icon": "truck",
		"date_field": "posting_date",
		"amount_field": "total_taxes_and_charges",
		"columns": ["name", "posting_date", "distribute_charges_based_on", "total_taxes_and_charges"],
		"detail": ["company"],
		"tables": [
			("purchase_receipts", ["receipt_document_type", "receipt_document", "supplier", "grand_total"]),
			("items", ["item_code", "receipt_document", "qty", "rate", "amount", "applicable_charges"]),
			("taxes", ["expense_account", "description", "amount"]),
		],
		"reports": ["stock_balance", "payables"],
	},
	{
		"key": "material-request",
		"doctype": "Material Request",
		"group": "Purchasing",
		"icon": "clipboard",
		"date_field": "transaction_date",
		"columns": ["name", "transaction_date", "material_request_type", "status", "per_ordered", "per_received"],
		"detail": ["schedule_date", "set_warehouse", "company"],
		"tables": [
			("items", ["item_code", "item_name", "schedule_date", "qty", "ordered_qty", "uom", "warehouse"]),
		],
		"reports": ["below_reorder", "stock_balance"],
		"create": {
			"fields": [
				{
					"fieldname": "material_request_type",
					"label": "Type",
					"type": "select",
					"options": ["Purchase", "Material Transfer", "Material Issue", "Manufacture"],
					"default": "Purchase",
					"required": True,
				},
				{"fieldname": "transaction_date", "label": "Date", "type": "date", "default": "today", "required": True},
				{"fieldname": "schedule_date", "label": "Needed by", "type": "date", "default": "week", "required": True},
				{
					"fieldname": "set_warehouse",
					"label": "Goes to",
					"type": "link",
					"options": "Warehouse",
					"required": True,
					"default": "stock_warehouse",
				},
			],
			"items": [
				{"fieldname": "item_code", "label": "Item", "type": "item", "required": True},
				{"fieldname": "qty", "label": "Qty", "type": "number", "required": True, "default": 1},
			],
			# Every line needs a warehouse and a date of its own; ERPNext validates
			# them per row, and asking for them twice on a form this small is noise.
			"line_from_header": {"warehouse": "set_warehouse", "schedule_date": "schedule_date"},
		},
	},
	{
		"key": "stock-entry",
		"doctype": "Stock Entry",
		"group": "Stock",
		"icon": "boxes",
		"date_field": "posting_date",
		"amount_field": "total_amount",
		"columns": ["name", "posting_date", "stock_entry_type", "from_warehouse", "to_warehouse", "total_amount"],
		"detail": ["purpose", "company", "remarks"],
		"tables": [
			("items", ["item_code", "item_name", "s_warehouse", "t_warehouse", "qty", "uom", "basic_rate", "amount"]),
		],
		"reports": ["stock_movement", "stock_balance"],
		"create": {
			"fields": [
				{
					"fieldname": "stock_entry_type",
					"label": "Type",
					"type": "select",
					"options": ["Material Receipt", "Material Issue", "Material Transfer"],
					"default": "Material Transfer",
					"required": True,
				},
				*_dated(("posting_date", "Date", "today", True)),
				{"fieldname": "from_warehouse", "label": "From", "type": "link", "options": "Warehouse"},
				{"fieldname": "to_warehouse", "label": "To", "type": "link", "options": "Warehouse"},
			],
			# ERPNext copies the header warehouses onto each line itself, and which
			# of the two applies depends on the type — a receipt has no source, an
			# issue has no target. Leaving the one that does not apply blank is the
			# correct answer, so the form asks for both and lets the type decide.
			"items": _lines(rate=False, warehouse=None, extra=[
				{"fieldname": "basic_rate", "label": "Rate", "type": "currency"},
			]),
			"hint": "Moving stock between branches, or writing it in and out. Leave From blank for a receipt, To blank for an issue.",
		},
	},
	{
		"key": "stock-reconciliation",
		"doctype": "Stock Reconciliation",
		"group": "Stock",
		"icon": "scale",
		"date_field": "posting_date",
		"amount_field": "difference_amount",
		"columns": ["name", "posting_date", "purpose", "set_warehouse", "difference_amount"],
		"detail": ["expense_account", "company"],
		"tables": [
			(
				"items",
				["item_code", "item_name", "warehouse", "current_qty", "qty", "current_valuation_rate", "valuation_rate", "amount"],
			),
		],
		"reports": ["stock_balance", "stock_movement"],
		"create": {
			"fields": [
				{
					"fieldname": "purpose",
					"label": "Purpose",
					"type": "select",
					"options": ["Stock Reconciliation", "Opening Stock"],
					"default": "Stock Reconciliation",
					"required": True,
				},
				*_dated(("posting_date", "Date", "today", True)),
				{
					"fieldname": "set_warehouse",
					"label": "Warehouse",
					"type": "link",
					"options": "Warehouse",
					"required": True,
					"default": "stock_warehouse",
				},
			],
			"items": _lines(rate=False, warehouse=None, extra=[
				{"fieldname": "valuation_rate", "label": "Cost each", "type": "currency"},
			]),
			"line_from_header": {"warehouse": "set_warehouse"},
			"hint": "A stock count. The quantity you enter becomes the balance — it is not added to it.",
		},
	},
	{
		"key": "delivery-note",
		"doctype": "Delivery Note",
		"group": "Stock",
		"icon": "package",
		"date_field": "posting_date",
		"party_field": "customer",
		"party_doctype": "Customer",
		"amount_field": "grand_total",
		"columns": ["name", "posting_date", "customer", "status", "per_billed", "grand_total"],
		"detail": ["set_warehouse", "company"],
		"tables": [
			("items", ["item_code", "item_name", "qty", "uom", "rate", "amount", "warehouse"]),
		],
		"reports": ["stock_movement", "top_items"],
		"create": {
			"fields": [
				{"fieldname": "customer", "label": "Customer", "type": "link", "options": "Customer", "required": True},
				*_dated(("posting_date", "Date", "today", True)),
				{
					"fieldname": "set_warehouse",
					"label": "Out of",
					"type": "link",
					"options": "Warehouse",
					"required": True,
					"default": "stock_warehouse",
				},
			],
			"items": _lines(warehouse=None),
			"line_from_header": {"warehouse": "set_warehouse"},
		},
	},
	{
		# Several sales bundled onto one delivery run. Not creatable from the
		# generic form below — its "lines" are invoices, not items with a
		# quantity, which is the one shape this whole registry otherwise
		# assumes. Raised instead from its own sheet; see `api/deliveries.py`.
		"key": "delivery-trip",
		"doctype": "Cosmestics Delivery Trip",
		"group": "Sales",
		"icon": "truck",
		"date_field": "departure_time",
		"columns": ["name", "departure_time", "driver_name", "vehicle", "status", "total_amount"],
		"detail": ["driver_phone", "company"],
		"tables": [
			("invoices", ["sales_invoice", "customer", "amount", "delivered"]),
		],
		"reports": [],
	},
	{
		"key": "pos-opening",
		"doctype": "POS Opening Entry",
		"group": "Till",
		"icon": "unlock",
		"date_field": "period_start_date",
		"columns": ["name", "period_start_date", "user", "pos_profile", "status"],
		"detail": ["posting_date", "company"],
		"tables": [("balance_details", ["mode_of_payment", "opening_amount"])],
		"reports": ["shift_history", "cashier_sales"],
	},
	{
		"key": "pos-closing",
		"doctype": "POS Closing Entry",
		"group": "Till",
		"icon": "lock",
		"date_field": "posting_date",
		"amount_field": "grand_total",
		"columns": ["name", "posting_date", "user", "pos_profile", "grand_total", "status"],
		"detail": ["period_start_date", "period_end_date", "total_quantity", "net_total", "company"],
		"tables": [
			(
				"payment_reconciliation",
				["mode_of_payment", "opening_amount", "expected_amount", "closing_amount", "difference"],
			),
			("sales_invoices", ["sales_invoice", "posting_date", "customer", "grand_total"]),
		],
		"reports": ["shift_history", "cashier_sales", "payment_modes"],
	},
]


# --------------------------------------------------------------------------
# Registry helpers
# --------------------------------------------------------------------------


def _entry(key: str) -> dict:
	"""Resolve a registry key, or refuse.

	This is the security boundary of the module: only these eleven doctypes are
	reachable, so no caller-supplied string ever becomes a doctype name.
	"""
	for d in DOCUMENTS:
		if d["key"] == key:
			return d
	frappe.throw(_("Unknown document type: {0}").format(key), frappe.DoesNotExistError)


_CURRENCY_TYPES = {"Currency"}
_NUMBER_TYPES = {"Int", "Float", "Percent"}


def _render_type(fieldtype: str) -> str:
	if fieldtype in _CURRENCY_TYPES:
		return "currency"
	if fieldtype in _NUMBER_TYPES:
		return "number"
	return "text"


def _column(doctype: str, fieldname: str) -> dict | None:
	"""Column spec taken from the DocType, so labels never drift from the desk."""
	if fieldname == "name":
		return {"label": _("No."), "key": "name", "type": "text"}

	df = frappe.get_meta(doctype).get_field(fieldname)
	if not df:
		return None
	return {"label": _(df.label or fieldname), "key": fieldname, "type": _render_type(df.fieldtype)}


def _columns(doctype: str, fieldnames: list) -> list:
	return [c for c in (_column(doctype, f) for f in fieldnames) if c]


def _company():
	"""The company documents raised here belong to.

	Four sources, most specific first, because they disagree on real sites and
	each one goes missing for its own reason. The global default in particular
	is a `tabDefaultValue` row that is deleted along with the company it names —
	so removing an old company silently leaves every new document with no
	company at all, and ERPNext throws "Please specify Company" from three
	frames inside `get_item_details`, which says nothing about what to fix.

	The last resort is the only company on the site. A single-company shop that
	has never set a default is unambiguous, and refusing it would be pedantry.
	"""
	return (
		frappe.defaults.get_user_default("Company")
		or frappe.defaults.get_global_default("company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
		or _only_company()
	)


def _only_company():
	companies = frappe.get_all("Company", pluck="name", limit_page_length=2)
	return companies[0] if len(companies) == 1 else None


def _window(days: int):
	"""`days <= 0` means all time — a manager chasing one old invoice needs that."""
	days = cint(days)
	if days <= 0:
		return None, None
	return add_days(nowdate(), -days), nowdate()


def _has(doctype: str, fieldname: str | None) -> bool:
	return bool(fieldname) and frappe.get_meta(doctype).has_field(fieldname)


DOCSTATUS_LABEL = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


def _statuses(doctype: str) -> list:
	"""Status vocabulary for the filter.

	Stock Entry and Stock Reconciliation have no status field at all, so their
	only real states are the docstatus ones — showing an empty dropdown there
	would imply a filter that cannot filter.
	"""
	df = frappe.get_meta(doctype).get_field("status")
	if df and df.options:
		return [s for s in df.options.split("\n") if s]
	return list(DOCSTATUS_LABEL.values())


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


@frappe.whitelist()
def list_types() -> list:
	"""The registry, minus anything this user may not read.

	Filtered by permission rather than shown-and-then-failing: a cashier who
	cannot open Purchase Invoices should not be given the tab.
	"""
	out = []
	for d in DOCUMENTS:
		if not frappe.db.exists("DocType", d["doctype"]):
			continue
		if not frappe.has_permission(d["doctype"], "read"):
			continue
		out.append(
			{
				"key": d["key"],
				"doctype": d["doctype"],
				"label": _(d["doctype"]),
				"group": d["group"],
				"icon": d["icon"],
				# `.get`, not `d["reports"]`: one entry missing this key used to take
				# the whole list down for every document type at once — the
				# frontend's `.catch(() => [])` around this call turns any exception
				# here into a silently empty registry, so every "New" button and
				# permission message on the whole screen disappears with no error
				# anywhere a person would see it. A missing key from here on is a
				# document type with no reports, not a broken screen.
				"reports": d.get("reports") or [],
				"has_party": bool(d.get("party_field")),
				"party_label": _(d["party_field"]).title() if d.get("party_field") else None,
				# Only offered when the type declares a form *and* this user may
				# create it: a "New" button that throws on save is worse than none.
				"creatable": bool(d.get("create")) and frappe.has_permission(d["doctype"], "create"),
				# Why there is no button, when there is none. A missing control with
				# no explanation reads as something broken; these are documents that
				# genuinely come from somewhere else.
				"create_hint": _(NOT_CREATABLE[d["key"]])
				if d["key"] in NOT_CREATABLE
				else (_(d["create"]["hint"]) if d.get("create", {}).get("hint") else None),
				"cannot_create": d["key"] in NOT_CREATABLE,
				# Distinct from `cannot_create`: this type *can* be raised from here in
				# principle — it has a form — but this user's role cannot submit one.
				# Without this, the screen fell back to `create_hint`'s creation tip
				# (meant to sit beside the button, not explain its absence) or, for a
				# type with no hint at all, to plain silence — a missing button with
				# no reason looks like a bug rather than a permission a manager needs
				# to grant.
				"no_permission": bool(d.get("create"))
				and d["key"] not in NOT_CREATABLE
				and not frappe.has_permission(d["doctype"], "create"),
			}
		)
	return out


@frappe.whitelist()
def list_documents(
	key: str,
	days: int = DEFAULT_DAYS,
	status: str | None = None,
	party: str | None = None,
	search: str | None = None,
	limit: int = 100,
	start: int = 0,
) -> dict:
	"""One page of documents, with the columns the front end should render.

	The columns travel with the rows so the table stays a single component: it
	never needs to know which doctype it is showing.
	"""
	entry = _entry(key)
	doctype = entry["doctype"]
	limit = min(max(cint(limit) or 100, 1), MAX_LIMIT)

	filters = {}
	start_date, end_date = _window(days)
	if start_date:
		filters[entry["date_field"]] = ("between", [start_date, end_date])

	company = _company()
	if company and _has(doctype, "company"):
		filters["company"] = company

	if status:
		if _has(doctype, "status"):
			filters["status"] = status
		else:
			# No status field: the filter can still mean something via docstatus.
			by_label = {v: k for k, v in DOCSTATUS_LABEL.items()}
			if status in by_label:
				filters["docstatus"] = by_label[status]

	if party and entry.get("party_field"):
		filters[entry["party_field"]] = ("like", f"%{party}%")

	search_fields = ["name"]
	if entry.get("party_field"):
		search_fields.append(entry["party_field"])

	fields = ["name", "docstatus", "owner", "modified", entry["date_field"]]
	if _has(doctype, "status"):
		fields.append("status")
	for f in entry["columns"]:
		if f == "name" or _has(doctype, f):
			fields.append(f)

	def _fetch(or_filters, page_length):
		return frappe.get_all(
			doctype,
			filters=filters,
			or_filters=or_filters,
			fields=list(dict.fromkeys(fields)),
			order_by=f"{entry['date_field']} desc, creation desc",
			limit_page_length=page_length,
			limit_start=cint(start),
		)

	rows = search_rows(_fetch, search, search_fields, limit)

	# The count has to be counted the same way the rows were found, or "showing
	# 100 of 412" describes a different list from the one on screen.
	or_filters = like_or_filters(search, search_fields)

	# Documents with no status field still need a word in the Status column, or
	# the reader cannot tell a draft from a posted one at a glance.
	if not _has(doctype, "status"):
		for r in rows:
			r["status"] = DOCSTATUS_LABEL.get(cint(r.docstatus), "")

	# Counted through the same filters — including the search — so "showing 100
	# of 412" is a statement about the list on screen and not about the doctype.
	# `frappe.db.count` cannot take or_filters, hence the aggregate here; the
	# column comes back named after the function, so it is read positionally.
	count_row = frappe.get_all(
		doctype,
		filters=filters,
		or_filters=or_filters or None,
		fields=[{"COUNT": "name"}],
	)
	total = cint(next(iter(count_row[0].values()))) if count_row else 0

	columns = _columns(doctype, entry["columns"])
	if not _has(doctype, "status") and not any(c["key"] == "status" for c in columns):
		columns.append({"label": _("Status"), "key": "status", "type": "text"})

	amount_field = entry.get("amount_field")
	outstanding_field = entry.get("outstanding_field")
	perms = _permissions(doctype)

	# Rows whose available steps depend on a field rather than only on docstatus
	# carry their own list. Only computed for the doctypes that actually have a
	# conditional step, so the common case still costs nothing — see
	# `actions_by_docstatus` below, which stays the answer for everything else.
	if any(step.get("when") for step in _next_steps(doctype)):
		for r in rows:
			r["_actions"] = _actions_for(doctype, cint(r.docstatus), perms, row=r)


	return {
		"key": key,
		"doctype": doctype,
		"columns": columns,
		"rows": rows,
		"total": total,
		"statuses": _statuses(doctype),
		"period": {"from": start_date, "to": end_date, "days": cint(days)},
		"permissions": perms,
		"submittable": bool(frappe.get_meta(doctype).is_submittable),
		# Which row actions are live, keyed by docstatus. Sent as a lookup rather
		# than per row (the answer only varies by docstatus) and rather than
		# re-derived in the browser, so the list menu and the detail modal cannot
		# come to different conclusions about what a user may do.
		"actions_by_docstatus": {str(d): _actions_for(doctype, d, perms) for d in (0, 1, 2)},
		"totals": {
			"count": len(rows),
			"amount": sum(flt(r.get(amount_field)) for r in rows) if amount_field else 0,
			"outstanding": sum(flt(r.get(outstanding_field)) for r in rows) if outstanding_field else 0,
		},
	}


def _permissions(doctype: str) -> dict:
	return {
		"submit": frappe.has_permission(doctype, "submit"),
		"cancel": frappe.has_permission(doctype, "cancel"),
		"create": frappe.has_permission(doctype, "create"),
		"print": frappe.has_permission(doctype, "print"),
	}


#: What each document naturally becomes next.
#:
#: A shop does not raise a Payment Entry out of nowhere — it pays *an invoice*,
#: receives *an order*, bills *a delivery*. Until now every one of those meant
#: leaving for the desk, finding the source document again and using its own
#: "Create" menu. This is that menu, for the handful of steps this shop actually
#: takes.
#:
#: Each entry names ERPNext's own mapper. That matters: the mapper decides which
#: lines are still outstanding, what rate and warehouse to carry over, and what
#: to write back to the source. Assembling the target here by hand would be a
#: second, worse copy of rules ERPNext already enforces — and it is exactly the
#: copy that drifts when they upgrade.
#:
#: Everything lands as a **draft**. The source document is history; the new one
#: is a decision somebody is about to make, and it deserves a look before it
#: posts. The one exception a shop might want — auto-submitting a payment — is
#: deliberately not offered, because a payment posted by a mis-tap is the single
#: hardest thing on this list to unpick.
NEXT_DOCUMENTS = {
	"Sales Invoice": [
		{
			"action": "payment",
			"label": "Record payment",
			"target": "Payment Entry",
			"mapper": "payment",
		},
	],
	"Purchase Invoice": [
		{
			"action": "payment",
			"label": "Pay this bill",
			"target": "Payment Entry",
			"mapper": "payment",
		},
	],
	"Delivery Note": [
		{
			"action": "invoice",
			"label": "Bill this delivery",
			"target": "Sales Invoice",
			"mapper": "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
		},
	],
	"Purchase Receipt": [
		{
			"action": "invoice",
			"label": "Enter the bill",
			"target": "Purchase Invoice",
			"mapper": "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",
		},
	],
	"Sales Order": [
		{
			"action": "deliver",
			"label": "Deliver these goods",
			"target": "Delivery Note",
			"mapper": "erpnext.selling.doctype.sales_order.sales_order.make_delivery_note",
		},
		{
			"action": "invoice",
			"label": "Invoice this order",
			"target": "Sales Invoice",
			"mapper": "erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice",
		},
	],
	"Purchase Order": [
		{
			"action": "receive",
			"label": "Receive these goods",
			"target": "Purchase Receipt",
			"mapper": "erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt",
		},
		{
			"action": "invoice",
			"label": "Enter the bill",
			"target": "Purchase Invoice",
			"mapper": "erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice",
		},
	],
	"Material Request": [
		{
			"action": "stock_entry",
			"label": "Move the stock",
			"target": "Stock Entry",
			"mapper": "erpnext.stock.doctype.material_request.material_request.make_stock_entry",
			# Only a request to *move* stock becomes a stock movement. Declared
			# here so the action is never offered on a purchase request rather
			# than offered and then refused — a button that exists and always
			# fails is worse than no button, because it reads as a broken app.
			"when": {
				"field": "material_request_type",
				"in": ("Material Transfer", "Material Issue", "Manufacture"),
			},
		},
		# Purchase Order is deliberately absent. ERPNext's mapper leaves the
		# supplier blank — a Material Request says what is needed, not who from —
		# and the document is mandatory on it, so the action could only ever fail
		# or guess. Choosing the supplier is a question, and this menu answers
		# with documents rather than asking questions.
	],
}


def _next_steps(doctype: str) -> list:
	return NEXT_DOCUMENTS.get(doctype) or []


def _step_applies(step, row) -> bool:
	"""Whether a next-step is live for this particular document.

	Without a row — the list's per-docstatus lookup — a conditional step is
	assumed to apply, and `_assert_worth_doing` catches it on the way through.
	With one, it is filtered out before it is ever drawn.
	"""
	rule = step.get("when")
	if not rule or row is None:
		return True
	return (row.get(rule["field"]) if hasattr(row, "get") else getattr(row, rule["field"], None)) in rule["in"]


def _actions_for(doctype: str, docstatus: int, perms: dict, row=None) -> list:
	"""Which row actions are live for a document in this state.

	Computed once per response rather than per row: the answer depends only on
	docstatus, and a permission check per row across 500 rows is a lot of work
	for an answer that repeats.
	"""
	submittable = frappe.get_meta(doctype).is_submittable
	actions = ["print", "whatsapp"]

	# What this document becomes next — a payment against an invoice, a bill
	# against a receipt. Only once submitted: a draft is not yet a commitment to
	# anything, so there is nothing to carry forward from it.
	if docstatus == 1 and perms["create"]:
		actions.extend(
			step["action"] for step in _next_steps(doctype) if _step_applies(step, row)
		)
	if perms["create"]:
		actions.append("duplicate")
	if submittable:
		if docstatus == 0 and perms["submit"]:
			actions.append("submit")
		if docstatus == 1 and perms["cancel"]:
			actions.append("cancel")
		if docstatus == 2 and perms["create"]:
			actions.append("amend")
	return actions


@frappe.whitelist()
def get_document(key: str, name: str) -> dict:
	"""Everything the detail modal shows: header, lines, totals and actions."""
	entry = _entry(key)
	doctype = entry["doctype"]
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")

	meta = frappe.get_meta(doctype)
	header = []
	for f in list(dict.fromkeys(entry["columns"] + entry.get("detail", []))):
		if f == "name":
			continue
		col = _column(doctype, f)
		if not col:
			continue
		value = doc.get(f)
		if value in (None, ""):
			continue
		header.append({**col, "value": value})

	tables = []
	for fieldname, fields in entry.get("tables", []):
		df = meta.get_field(fieldname)
		if not df:
			continue
		child_rows = doc.get(fieldname) or []
		if not child_rows:
			continue
		columns = _columns(df.options, [f for f in fields if frappe.get_meta(df.options).has_field(f)])
		tables.append(
			{
				"fieldname": fieldname,
				"label": _(df.label or fieldname),
				"columns": columns,
				"rows": [{c["key"]: row.get(c["key"]) for c in columns} for row in child_rows],
			}
		)

	totals = []
	for f in TOTAL_FIELDS:
		if not meta.has_field(f):
			continue
		value = flt(doc.get(f))
		if not value:
			continue
		totals.append({**_column(doctype, f), "value": value})

	status = doc.get("status") if meta.has_field("status") else DOCSTATUS_LABEL.get(cint(doc.docstatus), "")
	perms = _permissions(doctype)

	return {
		"key": key,
		"doctype": doctype,
		"name": doc.name,
		"title": f"{_(doctype)} · {doc.name}",
		"docstatus": cint(doc.docstatus),
		"status": status,
		"party": doc.get(entry["party_field"]) if entry.get("party_field") else None,
		"date": doc.get(entry["date_field"]),
		"header": header,
		"tables": tables,
		"totals": totals,
		"actions": _actions_for(doctype, cint(doc.docstatus), perms, row=doc),
		"print_formats": _print_formats(doctype),
		"whatsapp_to": _party_mobile(entry, doc),
	}


def _print_formats(doctype: str) -> list:
	return frappe.get_all(
		"Print Format",
		filters={"doc_type": doctype, "disabled": 0},
		pluck="name",
		order_by="name asc",
	)


def _party_mobile(entry: dict, doc) -> str | None:
	"""Best phone number to send this document to."""
	party_doctype = entry.get("party_doctype")
	party_field = entry.get("party_field")
	if not party_doctype or not party_field or not doc.get(party_field):
		return None

	for field in ("mobile_no", "phone", "contact_mobile"):
		if frappe.get_meta(party_doctype).has_field(field):
			value = frappe.db.get_value(party_doctype, doc.get(party_field), field)
			if value:
				return value
	return doc.get("contact_mobile") or None


# --------------------------------------------------------------------------
# Creating
#
# The same registry drives creation. A document type becomes creatable by
# gaining a `create` block describing its header and its lines — there is no
# per-doctype endpoint, and no form logic in the browser that could disagree
# with what the server will accept.
# --------------------------------------------------------------------------


def _create_spec(entry: dict) -> dict:
	spec = entry.get("create")
	if not spec:
		frappe.throw(_("{0} cannot be created from here yet").format(_(entry["doctype"])))
	return spec


def _default_value(default):
	"""Dates a shop actually wants, and the warehouse it actually uses.

	`stock_warehouse` resolves at request time rather than being written into the
	registry, because the answer is per-site and can change — a registry entry
	naming one would be wrong on the second shop that installs this.
	"""
	if default == "today":
		return nowdate()
	if default == "week":
		return add_days(nowdate(), 7)
	if default == "stock_warehouse":
		return _default_stock_warehouse()
	return default


def _default_stock_warehouse() -> str | None:
	"""Where stock goes unless somebody says otherwise.

	The till's own warehouse first — on a one-shop site that is the only place
	stock ever lives, and typing it into every receipt is a keystroke for a fact
	nobody is choosing. Falls back to the company's default, then to the only
	non-group warehouse if there happens to be exactly one; several with no
	default configured is a genuine question, so it stays blank and asks.
	"""
	from cosmestics.api.pos import selling_warehouse

	warehouse = selling_warehouse()
	if warehouse:
		return warehouse

	company = _company()
	if company:
		default = frappe.db.get_value("Company", company, "default_warehouse_for_sales_return")
		if default:
			return default

	candidates = frappe.get_all(
		"Warehouse",
		filters={"is_group": 0, "disabled": 0, **({"company": company} if company else {})},
		pluck="name",
		limit_page_length=2,
	)
	return candidates[0] if len(candidates) == 1 else None


@frappe.whitelist()
def new_document_form(key: str) -> dict:
	"""The form for one creatable document type, with its defaults filled in."""
	entry = _entry(key)
	spec = _create_spec(entry)
	doctype = entry["doctype"]

	if not frappe.has_permission(doctype, "create"):
		frappe.throw(_("You may not create {0}").format(_(doctype)), frappe.PermissionError)

	def prepare(field):
		out = {**field}
		if "default" in out:
			out["default"] = _default_value(out["default"])
		return out

	return {
		"key": key,
		"doctype": doctype,
		"label": _(doctype),
		"fields": [prepare(f) for f in spec["fields"]],
		"items": [prepare(f) for f in spec["items"]],
		"hint": _(spec["hint"]) if spec.get("hint") else None,
		"can_submit": frappe.has_permission(doctype, "submit")
		and bool(frappe.get_meta(doctype).is_submittable),
	}


@frappe.whitelist()
def link_options(key: str, fieldname: str, search: str | None = None, limit: int = 20) -> list:
	"""Values for one link field on one create form.

	Scoped to the field being filled, exactly as `master.options` is: a generic
	"search any doctype" endpoint would be a way to read any table in the system
	through a whitelisted method.
	"""
	entry = _entry(key)
	spec = _create_spec(entry)

	field = next(
		(f for f in [*spec["fields"], *spec["items"]] if f["fieldname"] == fieldname), None
	)
	if not field or field["type"] not in ("link", "item"):
		frappe.throw(_("{0} is not a link field on this form").format(fieldname))

	target = "Item" if field["type"] == "item" else field["options"]
	filters = {}
	meta = frappe.get_meta(target)
	if meta.has_field("disabled"):
		filters["disabled"] = 0
	if meta.has_field("is_group"):
		filters["is_group"] = 0
	if target == "Item":
		filters["is_stock_item"] = 1

	company = _company()
	if meta.has_field("company") and company:
		filters["company"] = company

	limit = min(max(cint(limit) or 20, 1), 50)

	if target == "Item":
		# Searched on both code and name: staff know a product by one or the other,
		# rarely by whichever the record happens to be named after.
		or_filters = (
			{"item_code": ("like", f"%{search}%"), "item_name": ("like", f"%{search}%")}
			if search
			else None
		)
		rows = frappe.get_all(
			"Item",
			filters=filters,
			or_filters=or_filters,
			fields=["name", "item_name", "stock_uom"],
			order_by="item_name asc",
			limit_page_length=limit,
		)
		return [
			{"label": f"{r.item_name} · {r.name}", "value": r.name, "uom": r.stock_uom} for r in rows
		]

	if search:
		filters["name"] = ("like", f"%{search}%")

	return [
		{"label": r, "value": r}
		for r in frappe.get_all(
			target, filters=filters, pluck="name", order_by="name asc", limit_page_length=limit
		)
	]


# A Purchase Invoice or Purchase Receipt is one supplier's document by
# ERPNext's own model — it cannot hold lines from two. These are the only
# two specs that give a line its own `supplier` override for exactly that
# reason; see the note on each in `DOCUMENTS`.
_MULTI_SUPPLIER_DOCTYPES = {"Purchase Invoice", "Purchase Receipt"}


@frappe.whitelist(methods=["POST"])
def create_document(key: str, values: dict | str, items: list | str, submit: int = 0) -> dict:
	"""Create one document with its lines — or several, split by supplier.

	Built through `frappe.new_doc(...).insert()` with permissions intact, so
	ERPNext's own validation, pricing and mandatory-field rules apply exactly as
	they do in the desk. Only fieldnames the form declared are copied across, so
	a value the browser was never offered cannot be smuggled onto the document.

	Saved as a draft unless `submit` is set: a purchase order raised in a hurry
	is usually worth a second look before it goes to the supplier.

	When the lines carry their own `supplier` (Purchase Invoice / Purchase
	Receipt only) and name more than one between them, one document is raised
	per supplier rather than raising a single one that quietly kept only the
	last supplier it saw.
	"""
	if isinstance(values, str):
		values = frappe.parse_json(values)
	if isinstance(items, str):
		items = frappe.parse_json(items)
	values = values or {}
	items = items or []

	entry = _entry(key)
	spec = _create_spec(entry)
	doctype = entry["doctype"]

	missing = [
		f["label"]
		for f in spec["fields"]
		# The header's own `supplier` is a default now, not a requirement — a
		# line naming its own is just as good, checked below once every line
		# is known.
		if f.get("required") and f["fieldname"] != "supplier" and not values.get(f["fieldname"])
	]
	if missing:
		frappe.throw(_("Fill in: {0}").format(", ".join(missing)))

	lines = [row for row in items if row.get("item_code") and flt(row.get("qty")) > 0]
	if not lines:
		frappe.throw(_("Add at least one line with a quantity above zero"))

	line_fields = {f["fieldname"] for f in spec["items"]}

	# groups: [(supplier_or_None, [line, ...])]. A single group whose supplier
	# is None is the ordinary path every other document type takes — nothing
	# here changes for them.
	groups = [(None, lines)]
	if doctype in _MULTI_SUPPLIER_DOCTYPES and "supplier" in line_fields:
		by_supplier = {}
		for row in lines:
			supplier = row.get("supplier") or values.get("supplier")
			if not supplier:
				frappe.throw(
					_("{0} has no supplier, and no default supplier is set").format(
						row.get("item_name") or row.get("item_code")
					)
				)
			by_supplier.setdefault(supplier, []).append(row)
		# More than one supplier in use: split. Exactly one keeps the single-
		# document path — a bulk entry that happens to use only one supplier
		# should not be treated any differently from the ordinary case.
		if len(by_supplier) > 1:
			groups = list(by_supplier.items())

	created = [
		_insert_one(doctype, spec, values, line_fields, group_lines, supplier, submit)
		for supplier, group_lines in groups
	]

	first = created[0]
	if len(created) == 1:
		message = (
			_("{0} created and submitted") if cint(submit) else _("{0} created")
		).format(first["name"])
	else:
		names = ", ".join(d["name"] for d in created)
		message = (
			_("{0} documents raised across {1} suppliers: {2}")
			if cint(submit)
			else _("{0} draft documents raised across {1} suppliers: {2}")
		).format(len(created), len(created), names)

	return {
		"key": key,
		"doctype": doctype,
		"name": first["name"],
		"docstatus": first["docstatus"],
		# So a caller chaining a second document off this one (a landed cost
		# voucher off a bulk receipt, say) has a total to default a charge to
		# without a second round trip just to read it back. Only meaningful
		# for the single-document case; a multi-supplier split reads `created`.
		"grand_total": first["grand_total"] if len(created) == 1 else None,
		"created": created,
		"message": message,
	}


def _apply_stock_receipt(doc, values):
	"""A warehouse on a Purchase Invoice only counts if it also receives.

	ERPNext ignores `set_warehouse` on a Purchase Invoice unless `update_stock`
	is on — the field is even hidden behind it on the desk form. Asking a shop
	for a warehouse and then quietly not moving any stock into it is the worst
	of both: the invoice looks right and the shelf never changes.

	So naming one here means what it appears to mean. This matches how the app
	already buys from a neighbour (`sourcing._make_purchase_invoice` sets the
	same flag): one document that both bills and receives, because that is what
	happens when goods and a bill arrive together.

	Not applied when the invoice bills an existing Purchase Receipt — the stock
	arrived with the receipt, and ERPNext refuses `update_stock` on those rows.
	"""
	if doc.doctype != "Purchase Invoice" or not values.get("set_warehouse"):
		return
	if any(row.get("pr_detail") for row in doc.get("items", [])):
		return
	doc.update_stock = 1


def _insert_one(doctype, spec, values, line_fields, lines, supplier_override, submit):
	"""One document, one supplier. `supplier_override` is set only mid-split;
	the ordinary single-document path leaves the header's own value alone."""
	doc = frappe.new_doc(doctype)
	company = _company()
	if _has(doctype, "company"):
		if not company:
			# Said here, naming the setting. Left to ERPNext this surfaces as
			# "Please specify Company" raised inside item-detail lookup, which
			# reads like a broken form rather than a missing default.
			frappe.throw(
				_(
					"No default company is set, so this {0} has nothing to belong to. "
					"Set one in Global Defaults, or on your own user as a default."
				).format(_(doctype))
			)
		doc.company = company

	allowed = {f["fieldname"] for f in spec["fields"]}
	for fieldname, value in values.items():
		if fieldname in allowed and value not in (None, ""):
			doc.set(fieldname, value)

	if supplier_override:
		doc.supplier = supplier_override

	inherited = spec.get("line_from_header") or {}

	for row in lines:
		# `supplier` is this module's own grouping key, not a real field on
		# Purchase Invoice Item / Purchase Receipt Item — it does the
		# splitting above and has no business on the child row itself.
		line = {
			f: row[f] for f in line_fields if f != "supplier" and row.get(f) not in (None, "")
		}
		# Fields ERPNext validates per row but a small form should only ask once.
		for line_field, header_field in inherited.items():
			if values.get(header_field):
				line.setdefault(line_field, values[header_field])
		doc.append("items", line)

	# After the rows exist: the guard inside reads them.
	_apply_stock_receipt(doc, values)

	# Pulls prices, UOMs and the rest of what the desk would fill in for you.
	if hasattr(doc, "set_missing_values"):
		doc.set_missing_values()

	doc.insert()
	if cint(submit):
		doc.submit()

	return {
		"name": doc.name,
		"supplier": doc.get("supplier"),
		"docstatus": cint(doc.docstatus),
		"grand_total": flt(doc.get("grand_total")) if _has(doctype, "grand_total") else None,
	}


@frappe.whitelist()
def expense_accounts(search: str | None = None, limit: int = 20) -> list:
	"""Accounts a landed cost charge can book to.

	Its own lookup rather than routed through `link_options`, which only
	serves fields a `create` spec actually declares — no registered document
	asks for an account this way, a landed cost charge is the first.
	"""
	filters = {"is_group": 0, "disabled": 0}
	company = _company()
	if company:
		filters["company"] = company
	if search:
		filters["name"] = ("like", f"%{search}%")

	return [
		{"label": r, "value": r}
		for r in frappe.get_all(
			"Account", filters=filters, pluck="name", order_by="name asc", limit_page_length=cint(limit)
		)
	]


@frappe.whitelist(methods=["POST"])
def create_landed_cost_voucher(
	receipt_key: str,
	receipt_name: str,
	charges: list | str,
	vendor_invoices: list | str | None = None,
	distribute_based_on: str = "Qty",
) -> dict:
	"""Allocate additional cost — freight, customs — across a receipt or
	invoice's items, the same way ERPNext's own Landed Cost Voucher does.

	`charges` is [{description, amount, expense_account}] — what the voucher
	actually distributes across the items; the whole reason it exists.
	`vendor_invoices` is [{name, amount}], optional: real Purchase Invoices
	from whoever billed the charge (a freight or customs company), kept as a
	reference total rather than part of the allocation itself — that is what
	ERPNext's own `total_vendor_invoices_cost` does with them, and reworking
	that split would drift from what the standard voucher reports.

	`items` is deliberately left unset: ERPNext's own `validate()` pulls them
	from `purchase_receipts` via `get_items_from_purchase_receipts` when the
	table is empty, and reimplementing that by hand would drift from what the
	standard report expects.
	"""
	if isinstance(charges, str):
		charges = frappe.parse_json(charges)
	if isinstance(vendor_invoices, str):
		vendor_invoices = frappe.parse_json(vendor_invoices)

	if not charges:
		frappe.throw(_("Add at least one charge to allocate"))

	entry = _entry(receipt_key)
	doctype = entry["doctype"]
	if doctype not in ("Purchase Receipt", "Purchase Invoice"):
		frappe.throw(_("Landed cost can only be added to a Purchase Receipt or Purchase Invoice"))

	receipt = frappe.get_doc(doctype, receipt_name)
	if receipt.docstatus != 1:
		frappe.throw(_("{0} must be submitted before landed cost can be added").format(receipt.name))

	lcv = frappe.new_doc("Landed Cost Voucher")
	lcv.company = receipt.company
	lcv.posting_date = nowdate()
	lcv.distribute_charges_based_on = distribute_based_on or "Qty"
	lcv.append(
		"purchase_receipts",
		{
			"receipt_document_type": doctype,
			"receipt_document": receipt.name,
			"supplier": receipt.get("supplier"),
			"posting_date": receipt.posting_date,
			"grand_total": receipt.grand_total,
		},
	)

	for c in charges:
		amount = flt(c.get("amount"))
		if amount <= 0:
			continue
		lcv.append(
			"taxes",
			{
				"description": c.get("description") or _("Landed cost"),
				"amount": amount,
				"expense_account": c.get("expense_account"),
			},
		)

	if not lcv.taxes:
		frappe.throw(_("Add at least one charge with an amount above zero"))

	for v in vendor_invoices or []:
		if not v.get("name"):
			continue
		lcv.append("vendor_invoices", {"vendor_invoice": v["name"], "amount": flt(v.get("amount"))})

	lcv.insert()
	lcv.submit()

	return {
		"name": lcv.name,
		"total_taxes_and_charges": flt(lcv.total_taxes_and_charges),
		"message": _("{0} created — landed cost applied to {1}").format(lcv.name, receipt.name),
	}


# --------------------------------------------------------------------------
# Acting
# --------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def run_action(key: str, name: str, action: str) -> dict:
	"""Submit, cancel, amend or duplicate — through the real document lifecycle.

	Deliberately thin: ERPNext's own `submit`/`cancel` do the validation, the
	GL and stock postings and the permission checks. Anything reimplemented
	here would be a second, worse copy of that.

	There is no explicit commit. Frappe commits a successful whitelisted POST on
	the way out, and committing here as well would put these actions beyond the
	reach of a smoke test that rolls back — which is how they get tested.
	"""
	entry = _entry(key)
	doctype = entry["doctype"]
	doc = frappe.get_doc(doctype, name)

	if action == "submit":
		doc.submit()
		return {"name": doc.name, "docstatus": doc.docstatus, "message": _("{0} submitted").format(doc.name)}

	if action == "cancel":
		doc.cancel()
		return {"name": doc.name, "docstatus": doc.docstatus, "message": _("{0} cancelled").format(doc.name)}

	step = next((s for s in _next_steps(doctype) if s["action"] == action), None)
	if step:
		return _make_next(doc, step)

	if action in ("amend", "duplicate"):
		if action == "amend" and cint(doc.docstatus) != 2:
			frappe.throw(_("Only a cancelled document can be amended"))

		new = frappe.copy_doc(doc)
		if action == "amend":
			new.amended_from = doc.name
		new.docstatus = 0
		new.insert()
		return {
			"name": new.name,
			"docstatus": new.docstatus,
			"created": True,
			"message": _("{0} created as a draft").format(new.name),
		}

	frappe.throw(_("Unknown action: {0}").format(action))


def _make_next(doc, step) -> dict:
	"""Turn one document into the next, through ERPNext's own mapper.

	Left as a **draft** every time. A transfer moves real stock off a real shelf
	and a payment moves real money, and unlike a till sale nobody is standing at
	a counter waiting — so the person who receives the goods, or hands over the
	cash, submits it having checked. Auto-submitting would post what the source
	document *said*, which is not always what happened.
	"""
	if doc.docstatus != 1:
		frappe.throw(_("{0} has not been submitted yet").format(doc.name))

	_assert_worth_doing(doc, step)

	target = (
		_payment_entry_for(doc)
		if step["mapper"] == "payment"
		else frappe.get_attr(step["mapper"])(doc.name)
	)

	# A mapper can hand back a document with nothing on it — every line already
	# billed, every unit already received. Caught here so the shop is told why
	# rather than left with an empty draft to work out for itself.
	if not target.get("items") and target.doctype != "Payment Entry":
		frappe.throw(
			_("There is nothing left on {0} to carry into a {1}").format(
				doc.name, _(step["target"])
			)
		)

	target.insert(ignore_permissions=False)

	return {
		"name": target.name,
		"doctype": target.doctype,
		"docstatus": target.docstatus,
		"created": True,
		"message": _("{0} created as a draft — check it, then submit").format(target.name),
	}


def _assert_worth_doing(doc, step):
	"""Refuse the steps that would produce a document with no purpose.

	Said before the mapper runs, naming the reason. The alternative is an empty
	draft, or a payment for nothing, and both look like the app misbehaving.
	"""
	if step["mapper"] == "payment" and flt(doc.get("outstanding_amount")) <= 0:
		frappe.throw(_("{0} is already settled — there is nothing to pay").format(doc.name))

	if doc.doctype == "Material Request":
		if flt(doc.get("per_ordered")) >= 100:
			frappe.throw(_("{0} has already been fulfilled").format(doc.name))

		# Only a request to *move* stock becomes a stock movement. A purchase
		# request becomes an order and then a receipt — ERPNext's mapper still
		# tries, and fails deep inside with "Could not find Stock Entry Type:
		# Purchase", which reads as a broken app rather than the wrong action.
		movable = ("Material Transfer", "Material Issue", "Manufacture")
		if step["action"] == "stock_entry" and doc.material_request_type not in movable:
			frappe.throw(
				_(
					"{0} is a {1} request, which is filled by ordering and receiving "
					"rather than by moving stock between warehouses."
				).format(doc.name, _(doc.material_request_type))
			)


def _payment_entry_for(doc):
	"""A payment against this invoice, for whatever is still outstanding.

	`get_payment_entry` is ERPNext's own builder: it picks the party account, the
	reference row, the exchange rate and the allocation. Every one of those is a
	rule this app would otherwise be guessing at, and getting the party account
	wrong is how a payment lands against the wrong ledger.
	"""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from frappe.utils import nowdate

	entry = get_payment_entry(doc.doctype, doc.name)

	# ERPNext refuses a bank-mode payment with no reference: "Reference No and
	# Reference Date is mandatory for Bank transaction". Prefilled with the
	# invoice number and today, which is both true and a sensible default — the
	# real cheque or M-Pesa code is typed in before submitting.
	if not entry.get("reference_no"):
		entry.reference_no = doc.name
	if not entry.get("reference_date"):
		entry.reference_date = nowdate()

	return entry


@frappe.whitelist()
def print_url(key: str, name: str, print_format: str | None = None) -> dict:
	"""A printable view, opened in a new tab rather than rendered in the app.

	Print formats are letterheads, page sizes and Jinja — re-implementing any of
	that in the front end would produce a document that does not match what the
	desk prints, which is the one thing a printed invoice must do.
	"""
	entry = _entry(key)
	doctype = entry["doctype"]
	if not frappe.has_permission(doctype, "print"):
		frappe.throw(_("Not permitted to print {0}").format(_(doctype)), frappe.PermissionError)
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} {1} not found").format(_(doctype), name), frappe.DoesNotExistError)

	params = [
		f"doctype={quoted(doctype)}",
		f"name={quoted(name)}",
		"no_letterhead=0",
		"trigger_print=1",
	]
	if print_format:
		params.append(f"format={quoted(print_format)}")

	return {"url": get_url("/printview?" + "&".join(params))}


@frappe.whitelist(methods=["POST"])
def send_whatsapp(key: str, name: str, to: str | None = None, sender: str | None = None, as_pdf: int = 1) -> dict:
	"""Send a document to a phone or a group JID.

	Defaults to the PDF, rendered through the document's own print format, with
	the text summary as the caption — a customer sent an invoice should receive
	the invoice, not a paraphrase of it. `as_pdf=0` falls back to the summary
	alone, which is what a staff group usually wants.

	Best-effort, like every other send in this app: a failed message is reported
	back but never rolls anything back.
	"""
	from cosmestics.api import notifications

	entry = _entry(key)
	doc = frappe.get_doc(entry["doctype"], name)
	doc.check_permission("read")

	number = to or _party_mobile(entry, doc)
	if not number:
		frappe.throw(_("No phone number on this document. Enter one to send."))

	# A send with no PDF is the staff-group shape; one with the document attached
	# is what goes to a customer. See `format_document`.
	summary = format_document(entry, doc, internal=not cint(as_pdf))
	if cint(as_pdf):
		sent = notifications.send_document(doc.doctype, doc.name, number, message=summary, sender=sender)
	else:
		sent = notifications.send_text(number, summary, sender)

	return {
		"sent": sent,
		"to": number,
		"message": _("Sent to {0}").format(number) if sent else _("WhatsApp did not accept the message"),
	}


@frappe.whitelist()
def whatsapp_senders() -> list:
	"""Sender accounts configured for this user, for the send dialog."""
	from cosmestics.api import notifications

	return notifications.list_senders()


def format_document(entry: dict, doc, internal: bool = False) -> str:
	"""Readable on a phone: what it is, who it is for, what it comes to.

	`internal` is the difference between the shop's own group and a customer.
	A staff post wants the link — somebody is going to open the document. A
	customer gets neither the link nor anything about how the shop is run: the
	URL exposes the site and its login, and it is noise to the person reading.
	"""
	from frappe.utils import fmt_money, get_url_to_form

	lines = [f"*{_(doc.doctype)}*", doc.name]

	if entry.get("party_field") and doc.get(entry["party_field"]):
		lines.append(str(doc.get(entry["party_field"])))
	if doc.get(entry["date_field"]):
		lines.append(str(doc.get(entry["date_field"])))

	lines.append("")
	for fieldname, _fields in entry.get("tables", [])[:1]:
		for row in (doc.get(fieldname) or [])[:10]:
			label = row.get("item_name") or row.get("item_code") or row.get("mode_of_payment")
			if not label:
				continue
			qty = row.get("qty")
			lines.append(f"• {flt(qty):g} × {label}" if qty else f"• {label}")

	currency = doc.get("currency") or None
	if entry.get("amount_field") and doc.get(entry["amount_field"]) is not None:
		lines.append("")
		lines.append(f"Total: {fmt_money(flt(doc.get(entry['amount_field'])), currency=currency)}")
	if entry.get("outstanding_field") and flt(doc.get(entry["outstanding_field"])):
		lines.append(f"Outstanding: {fmt_money(flt(doc.get(entry['outstanding_field'])), currency=currency)}")

	if internal:
		lines.append("")
		lines.append(get_url_to_form(doc.doctype, doc.name))
	return "\n".join(lines)


# --------------------------------------------------------------------------
# Insights
# --------------------------------------------------------------------------


@frappe.whitelist()
def insights(key: str, days: int = DEFAULT_DAYS) -> dict:
	"""The stat tiles and ageing for one document type.

	Counted in SQL rather than over a fetched page: these answer "how much is
	outstanding", which is a question about every document, not the hundred
	currently on screen.
	"""
	entry = _entry(key)
	doctype = entry["doctype"]
	table = f"`tab{doctype}`"
	date_field = entry["date_field"]

	conditions = ["1 = 1"]
	values = {}
	start_date, end_date = _window(days)
	if start_date:
		# `date_field` comes from the registry above, never from the caller.
		conditions.append(f"`{date_field}` between %(start)s and %(end)s")
		values.update({"start": start_date, "end": end_date})
	if _has(doctype, "company") and _company():
		conditions.append("company = %(company)s")
		values["company"] = _company()

	where = " and ".join(conditions)

	amount_field = entry.get("amount_field")
	amount_sql = f"sum(ifnull(`{amount_field}`, 0))" if _has(doctype, amount_field) else "0"

	summary = frappe.db.sql(
		f"""select count(name) as documents,
		           sum(case when docstatus = 0 then 1 else 0 end) as drafts,
		           sum(case when docstatus = 1 then 1 else 0 end) as submitted,
		           sum(case when docstatus = 2 then 1 else 0 end) as cancelled,
		           {amount_sql} as value
		    from {table} where {where}""",
		values,
		as_dict=True,
	)[0]

	stats = [
		{"key": "documents", "label": _("Documents"), "value": cint(summary.documents), "type": "number", "icon": "file"},
		{
			"key": "value",
			"label": _("Value"),
			"value": flt(summary.value),
			"type": "currency",
			"icon": "money",
		},
		{
			"key": "drafts",
			"label": _("Drafts"),
			"value": cint(summary.drafts),
			"type": "number",
			"icon": "pencil",
			"tone": "warn" if cint(summary.drafts) else "default",
		},
		{
			"key": "cancelled",
			"label": _("Cancelled"),
			"value": cint(summary.cancelled),
			"type": "number",
			"icon": "ban",
			"tone": "bad" if cint(summary.cancelled) else "default",
		},
	]

	ageing = {"columns": [], "rows": []}
	outstanding_field = entry.get("outstanding_field")
	if _has(doctype, outstanding_field):
		age_field = entry.get("due_field") if _has(doctype, entry.get("due_field")) else date_field
		# Deliberately not scoped to the period: what is owed is a fact about
		# today, not about the last thirty days. The company scope still applies.
		company_cond = "and company = %(company)s" if "company" in values else ""
		buckets = frappe.db.sql(
			f"""select case
			             when datediff(%(today)s, `{age_field}`) <= 0  then '0 · not yet due'
			             when datediff(%(today)s, `{age_field}`) <= 30 then '1 · 1-30 days'
			             when datediff(%(today)s, `{age_field}`) <= 60 then '2 · 31-60 days'
			             when datediff(%(today)s, `{age_field}`) <= 90 then '3 · 61-90 days'
			             else '4 · over 90 days' end as bucket,
			           count(name) as documents,
			           sum(`{outstanding_field}`) as outstanding
			    from {table}
			    where docstatus = 1 and ifnull(`{outstanding_field}`, 0) > 0 {company_cond}
			    group by bucket order by bucket""",
			{**values, "today": nowdate()},
			as_dict=True,
		)
		for b in buckets:
			b["bucket"] = b["bucket"].split(" · ", 1)[1]

		ageing = {
			"columns": [
				{"label": _("Age"), "key": "bucket", "type": "text"},
				{"label": _("Documents"), "key": "documents", "type": "number"},
				{"label": _("Outstanding"), "key": "outstanding", "type": "currency"},
			],
			"rows": buckets,
		}
		total_outstanding = sum(flt(b["outstanding"]) for b in buckets)
		overdue = sum(flt(b["outstanding"]) for b in buckets if b["bucket"] != "not yet due")
		stats.insert(
			2,
			{
				"key": "outstanding",
				"label": _("Outstanding"),
				"value": total_outstanding,
				"type": "currency",
				"icon": "hourglass",
				"tone": "warn" if total_outstanding else "good",
			},
		)
		stats.insert(
			3,
			{
				"key": "overdue",
				"label": _("Overdue"),
				"value": overdue,
				"type": "currency",
				"icon": "alert",
				"tone": "bad" if overdue else "good",
			},
		)

	by_status = []
	if _has(doctype, "status"):
		by_status = frappe.db.sql(
			f"""select status, count(name) as documents, {amount_sql} as value
			    from {table} where {where}
			    group by status order by documents desc""",
			values,
			as_dict=True,
		)
	else:
		rows = frappe.db.sql(
			f"""select docstatus, count(name) as documents, {amount_sql} as value
			    from {table} where {where} group by docstatus order by docstatus""",
			values,
			as_dict=True,
		)
		by_status = [
			{"status": DOCSTATUS_LABEL.get(cint(r.docstatus), ""), "documents": r.documents, "value": r.value}
			for r in rows
		]

	return {
		"key": key,
		"doctype": doctype,
		"stats": stats,
		"ageing": ageing,
		"by_status": {
			"columns": [
				{"label": _("Status"), "key": "status", "type": "text"},
				{"label": _("Documents"), "key": "documents", "type": "number"},
				{"label": _("Value"), "key": "value", "type": "currency"},
			],
			"rows": by_status,
		},
		"period": {"from": start_date, "to": end_date, "days": cint(days)},
	}
