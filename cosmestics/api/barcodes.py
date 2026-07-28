"""Barcodes for items that arrived without one.

A cosmetics shop buys a lot of stock that has no scannable code on it — loose
units, repacks, anything imported in a mixed carton. Those items are the slowest
to sell at the counter, because the cashier has to find them by name while
somebody waits.

This generates a real EAN-13 for each one: a genuine barcode with a valid check
digit, not a serial number in a barcode-shaped field. A cheap label printer will
print it, any scanner will read it, and the till already resolves scans through
`Item Barcode`, so a generated code works the moment it is written — nothing
else in the app needs to know these were made rather than received.

The leading digit is **2**, which GS1 reserves for a shop's own internal use.
That is the whole reason a made-up code is safe: numbers in that range are
guaranteed never to be issued to a real product, so nothing here can ever
collide with a manufacturer's barcode.
"""

import frappe
from frappe import _
from frappe.utils import cint

# GS1 reserves prefix 2 for in-store items. Never issued to a real product, so a
# code minted here cannot collide with one printed on a supplier's carton.
INTERNAL_PREFIX = "2"
EAN_13_LENGTH = 13
# 13 digits, minus the prefix, minus the check digit.
SERIAL_DIGITS = EAN_13_LENGTH - len(INTERNAL_PREFIX) - 1

# In the order we would rather use. The field is a Select whose options differ
# between ERPNext versions, so the type is chosen from what this site actually
# offers rather than hard-coded to a value that may not validate.
PREFERRED_TYPES = ("EAN", "EAN-13", "GTIN", "UPC-A", "UPC")


def check_digit(body: str) -> str:
	"""EAN-13 check digit for the leading 12 digits.

	Positions alternate weight 1 and 3 from the left; the check digit is
	whatever takes the weighted sum to the next multiple of ten. This is the
	part that makes the number a barcode rather than a string of digits — a
	scanner rejects a code whose check digit does not agree.
	"""
	total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
	return str((10 - total % 10) % 10)


def _barcode_type() -> str | None:
	field = frappe.get_meta("Item Barcode").get_field("barcode_type")
	options = [o for o in (field.options or "").split("\n") if o] if field else []
	for preferred in PREFERRED_TYPES:
		if preferred in options:
			return preferred
	return None


def _next_serial() -> int:
	"""One past the highest internal code already issued.

	Read from the barcodes themselves rather than from a counter document: a
	counter can drift out of step with reality after a restore or an import, and
	then quietly mints duplicates.
	"""
	row = frappe.db.sql(
		"""select max(cast(substring(barcode, %(skip)s, %(digits)s) as unsigned))
		   from `tabItem Barcode`
		   where barcode like %(prefix)s and length(barcode) = %(length)s
		     and barcode regexp '^[0-9]+$'""",
		{
			"skip": len(INTERNAL_PREFIX) + 1,
			"digits": SERIAL_DIGITS,
			"prefix": f"{INTERNAL_PREFIX}%",
			"length": EAN_13_LENGTH,
		},
	)
	return cint(row[0][0] if row and row[0] else 0) + 1


def _mint(serial: int) -> tuple[str, int]:
	"""Next unused code at or after `serial`, and the serial that follows it."""
	while True:
		body = f"{INTERNAL_PREFIX}{serial:0{SERIAL_DIGITS}d}"
		code = body + check_digit(body)
		if not frappe.db.exists("Item Barcode", {"barcode": code}):
			return code, serial + 1
		serial += 1


# --------------------------------------------------------------------------


@frappe.whitelist()
def list_items(search: str | None = None, only_missing: int = 1, limit: int = 200) -> dict:
	"""Stock items and the barcodes they already carry.

	Defaults to the ones with none, because that is the working list — but the
	filter can be turned off so someone can check what an item already has
	before printing another label for it.
	"""
	filters = {"disabled": 0, "is_stock_item": 1}
	if search:
		filters["item_name"] = ("like", f"%{search}%")

	items = frappe.get_all(
		"Item",
		filters=filters,
		fields=["name as item_code", "item_name", "item_group", "brand", "stock_uom"],
		order_by="item_name asc",
		limit_page_length=min(max(cint(limit) or 200, 1), 500),
	)
	if not items:
		return {"rows": [], "missing": 0, "barcode_type": _barcode_type()}

	codes = [i.item_code for i in items]
	existing = {}
	for b in frappe.get_all(
		"Item Barcode",
		filters={"parent": ("in", codes)},
		fields=["parent", "barcode", "barcode_type"],
		limit_page_length=0,
	):
		existing.setdefault(b.parent, []).append(b.barcode)

	rows = []
	for it in items:
		found = existing.get(it.item_code, [])
		if cint(only_missing) and found:
			continue
		rows.append(
			{
				"item_code": it.item_code,
				"item_name": it.item_name,
				"item_group": it.item_group,
				"brand": it.brand,
				"uom": it.stock_uom,
				"barcodes": found,
				"barcode": found[0] if found else None,
				"barcode_count": len(found),
			}
		)

	return {
		"rows": rows,
		"missing": sum(1 for r in rows if not r["barcode_count"]),
		"barcode_type": _barcode_type(),
	}


@frappe.whitelist(methods=["POST"])
def generate(item_codes: list | str, skip_existing: int = 1) -> dict:
	"""Mint an EAN-13 for each item and write it as an `Item Barcode` row.

	Written to the Item's own child table, not to a table of this app's own, so
	the desk, the scanner and every ERPNext report see the barcode the same way.

	Items that already have one are skipped by default — printing a second label
	for a product that already scans is how a shop ends up with two codes for one
	thing and no idea which is on the shelf.
	"""
	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)
	if not item_codes:
		frappe.throw(_("Select at least one item"))

	barcode_type = _barcode_type()
	serial = _next_serial()

	created, skipped, results = 0, 0, []
	for code in item_codes:
		if not frappe.db.exists("Item", code):
			frappe.throw(_("{0} does not exist").format(code))

		item = frappe.get_doc("Item", code)
		item.check_permission("write")

		if item.barcodes and cint(skip_existing):
			skipped += 1
			results.append(
				{
					"item_code": code,
					"item_name": item.item_name,
					"barcode": item.barcodes[0].barcode,
					"created": False,
				}
			)
			continue

		barcode, serial = _mint(serial)
		row = {"barcode": barcode}
		if barcode_type:
			row["barcode_type"] = barcode_type
		item.append("barcodes", row)
		item.save()

		created += 1
		results.append(
			{"item_code": code, "item_name": item.item_name, "barcode": barcode, "created": True}
		)

	return {
		"created": created,
		"skipped": skipped,
		"barcode_type": barcode_type,
		"rows": results,
	}
