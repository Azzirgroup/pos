"""Structure the online shop's orders need, created on install and every migrate.

* Customer gets a shop account: username, phone, a password hash and a switch.
  Customers sign in to the shop with these — they are not Frappe users and
  never see the desk.
* Sales Order gets the online-order fields: the flag that marks it, its order
  status, how it is fulfilled, the M-Pesa receipt and a status history.
* A non-stock "Delivery Fee" item for the delivery charge line.
* A secret token for the M-Pesa callback address.

Idempotent: each piece is created only if missing, so it is safe on every
migrate and never overwrites what a shop has changed.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ONLINE_STATUSES = (
	"Draft",
	"Order Received",
	"Processing",
	"Out for Delivery",
	"Ready for Pickup",
	"Complete",
	"Cancelled",
)

DELIVERY_ITEM = "ONLINE-DELIVERY"


ONLINE_GROUP = "Online Customers"


def setup_online_orders():
	create_custom_fields(_custom_fields(), update=True)
	ensure_delivery_item()
	ensure_callback_token()
	ensure_online_customer_group()


def ensure_online_customer_group() -> str:
	"""The Customer Group every online sign-up joins, and the setting that
	names it. A shop that picks a different group keeps it."""
	settings = "Cosmestics POS Settings"
	current = frappe.db.get_single_value(settings, "shop_customer_group")
	if current and frappe.db.exists("Customer Group", current):
		return current
	if not frappe.db.exists("Customer Group", ONLINE_GROUP):
		parent = frappe.db.get_value("Customer Group", {"is_group": 1, "parent_customer_group": ("in", ("", None))}, "name") or frappe.db.get_value("Customer Group", {"is_group": 1}, "name")
		frappe.get_doc(
			{
				"doctype": "Customer Group",
				"customer_group_name": ONLINE_GROUP,
				"parent_customer_group": parent,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)
	frappe.db.set_single_value(settings, "shop_customer_group", ONLINE_GROUP)
	return ONLINE_GROUP


def _custom_fields() -> dict:
	return {
		"Customer": [
			{
				"fieldname": "cosmestics_shop_section",
				"fieldtype": "Section Break",
				"label": "Online Shop Account",
				"insert_after": "customer_primary_address",
				"collapsible": 1,
			},
			{
				"fieldname": "cosmestics_shop_username",
				"fieldtype": "Data",
				"label": "Shop Username",
				"insert_after": "cosmestics_shop_section",
				"unique": 1,
				"description": "What the customer signs in to the online shop with. Their phone number works too.",
			},
			{
				"fieldname": "cosmestics_shop_phone",
				"fieldtype": "Data",
				"options": "Phone",
				"label": "Shop Phone",
				"insert_after": "cosmestics_shop_username",
				"unique": 1,
			},
			{
				"fieldname": "cosmestics_shop_email",
				"fieldtype": "Data",
				"options": "Email",
				"label": "Shop Email",
				"insert_after": "cosmestics_shop_phone",
			},
			{
				"fieldname": "cosmestics_shop_col",
				"fieldtype": "Column Break",
				"insert_after": "cosmestics_shop_email",
			},
			{
				"fieldname": "cosmestics_shop_enabled",
				"fieldtype": "Check",
				"label": "Can Sign In to the Shop",
				"default": "1",
				"insert_after": "cosmestics_shop_col",
			},
			{
				"fieldname": "cosmestics_set_password",
				"fieldtype": "Password",
				"label": "Set Shop Password",
				"insert_after": "cosmestics_shop_enabled",
				"description": "Type a new password and save. It is stored only as a hash, and this box empties itself.",
			},
			{
				"fieldname": "cosmestics_password_hash",
				"fieldtype": "Data",
				"label": "Password Hash",
				"insert_after": "cosmestics_set_password",
				"hidden": 1,
				"read_only": 1,
				"no_copy": 1,
				"print_hide": 1,
			},
			{
				"fieldname": "cosmestics_google_sub",
				"fieldtype": "Data",
				"label": "Google Account ID",
				"insert_after": "cosmestics_password_hash",
				"read_only": 1,
				"unique": 1,
				"no_copy": 1,
				"description": "Set when the customer signs in with Google.",
			},
			{
				"fieldname": "cosmestics_shop_last_login",
				"fieldtype": "Datetime",
				"label": "Last Signed In",
				"insert_after": "cosmestics_google_sub",
				"read_only": 1,
				"no_copy": 1,
			},
		],
		"Sales Order": [
			{
				"fieldname": "cosmestics_online_order",
				"fieldtype": "Check",
				"label": "Online Order",
				"insert_after": "order_type",
				"read_only": 1,
				"no_copy": 1,
				"in_standard_filter": 1,
				"bold": 1,
				"description": "Placed by the customer on the online shop.",
			},
			{
				"fieldname": "cosmestics_order_status",
				"fieldtype": "Select",
				"label": "Online Order Status",
				"options": "\n".join(ONLINE_STATUSES),
				"insert_after": "cosmestics_online_order",
				"depends_on": "cosmestics_online_order",
				"read_only": 1,
				"no_copy": 1,
				"in_list_view": 1,
				"in_standard_filter": 1,
				"allow_on_submit": 1,
				"search_index": 1,
			},
			{
				"fieldname": "cosmestics_online_section",
				"fieldtype": "Section Break",
				"label": "Online Order",
				"insert_after": "items",
				"depends_on": "cosmestics_online_order",
				"collapsible": 0,
			},
			{
				"fieldname": "cosmestics_fulfilment",
				"fieldtype": "Select",
				"label": "Fulfilment",
				"options": "\nDelivery\nPickup",
				"insert_after": "cosmestics_online_section",
				"allow_on_submit": 1,
			},
			{
				"fieldname": "cosmestics_delivery_area",
				"fieldtype": "Link",
				"options": "Cosmestics Delivery Area",
				"label": "Delivery Area",
				"insert_after": "cosmestics_fulfilment",
				"depends_on": "eval:doc.cosmestics_fulfilment=='Delivery'",
			},
			{
				"fieldname": "cosmestics_delivery_address",
				"fieldtype": "Small Text",
				"label": "Delivery Address",
				"insert_after": "cosmestics_delivery_area",
				"depends_on": "eval:doc.cosmestics_fulfilment=='Delivery'",
				"allow_on_submit": 1,
			},
			{
				"fieldname": "cosmestics_landmark",
				"fieldtype": "Data",
				"label": "Landmark",
				"insert_after": "cosmestics_delivery_address",
				"depends_on": "eval:doc.cosmestics_fulfilment=='Delivery'",
				"allow_on_submit": 1,
			},
			{
				"fieldname": "cosmestics_online_col",
				"fieldtype": "Column Break",
				"insert_after": "cosmestics_landmark",
			},
			{
				"fieldname": "cosmestics_contact_phone",
				"fieldtype": "Data",
				"options": "Phone",
				"label": "Contact Phone",
				"insert_after": "cosmestics_online_col",
				"allow_on_submit": 1,
			},
			{
				"fieldname": "cosmestics_delivery_fee",
				"fieldtype": "Currency",
				"label": "Delivery Fee",
				"insert_after": "cosmestics_contact_phone",
				"read_only": 1,
			},
			{
				"fieldname": "cosmestics_mpesa_receipt",
				"fieldtype": "Data",
				"label": "M-Pesa Receipt",
				"insert_after": "cosmestics_delivery_fee",
				"read_only": 1,
				"no_copy": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "cosmestics_paid_at",
				"fieldtype": "Datetime",
				"label": "Paid At",
				"insert_after": "cosmestics_mpesa_receipt",
				"read_only": 1,
				"no_copy": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "cosmestics_delivery",
				"fieldtype": "Link",
				"options": "Cosmestics Delivery",
				"label": "Delivery",
				"insert_after": "cosmestics_paid_at",
				"read_only": 1,
				"no_copy": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "cosmestics_customer_note",
				"fieldtype": "Small Text",
				"label": "Customer Note",
				"insert_after": "cosmestics_delivery",
				"allow_on_submit": 1,
			},
			{
				"fieldname": "cosmestics_status_log",
				"fieldtype": "Table",
				"options": "Cosmestics Order Status Log",
				"label": "Order History",
				"insert_after": "cosmestics_customer_note",
				"read_only": 1,
				"no_copy": 1,
				"allow_on_submit": 1,
			},
		],
	}


def ensure_delivery_item():
	"""The non-stock item a delivery fee is charged as, and the setting that
	points at it. Hidden from the online catalog; it is not something to buy."""
	settings = "Cosmestics POS Settings"
	current = frappe.db.get_single_value(settings, "shop_delivery_item")
	if current and frappe.db.exists("Item", current):
		return current

	if not frappe.db.exists("Item", DELIVERY_ITEM):
		group = (
			frappe.db.get_value("Item Group", {"name": "Services", "is_group": 0})
			or frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		)
		uom = "Nos" if frappe.db.exists("UOM", "Nos") else frappe.db.get_value("UOM", {}, "name")
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": DELIVERY_ITEM,
				"item_name": "Delivery Fee",
				"item_group": group,
				"stock_uom": uom,
				"is_stock_item": 0,
				"is_sales_item": 1,
				"is_purchase_item": 0,
				"include_item_in_manufacturing": 0,
				"description": "Delivery charge on online orders.",
			}
		)
		if frappe.db.has_column("Item", "cosmestics_hide_online"):
			item.cosmestics_hide_online = 1
		item.insert(ignore_permissions=True)

	frappe.db.set_single_value(settings, "shop_delivery_item", DELIVERY_ITEM)
	return DELIVERY_ITEM


def ensure_callback_token():
	settings = "Cosmestics POS Settings"
	if not frappe.db.get_single_value(settings, "mpesa_callback_token"):
		frappe.db.set_single_value(settings, "mpesa_callback_token", frappe.generate_hash(length=32))
	if not frappe.db.get_single_value(settings, "mpesa_callback_base_url"):
		frappe.db.set_single_value(settings, "mpesa_callback_base_url", "https://classiccosmetics.frappe.cloud/")


def import_mpesa_from_env(path: str = "/home/frappe/dukaplus/apps/dukaplus/.env"):
	"""Copy the Daraja credentials DukaPlus uses into this shop's settings.

	    bench --site <site> execute cosmestics.setup.online_setup.import_mpesa_from_env

	DukaPlus keeps a Basic token (base64 of key:secret), the consumer key and
	secret, the short code, and a *precomputed* STK password — base64 of
	short code + passkey + a fixed timestamp. The passkey is recovered from
	that password and checked by rebuilding the password from it, so the shop
	can compute a fresh password and timestamp for every request as Daraja
	expects. Nothing secret is printed; the Password fields store it encrypted.
	"""
	import base64

	from dotenv import dotenv_values

	env = dotenv_values(path)
	shortcode = (env.get("SHORTCODE") or "").strip()
	stored = (env.get("PASSWORD") or "").strip()
	key = (env.get("CONSUMER_KEY") or "").strip()
	secret = (env.get("CONSUMER_SECRET") or "").strip()
	if not (shortcode and stored and key and secret):
		frappe.throw(f"{path} is missing SHORTCODE, PASSWORD, CONSUMER_KEY or CONSUMER_SECRET")

	decoded = base64.b64decode(stored).decode()
	timestamp = decoded[-14:]
	if not (decoded.startswith(shortcode) and timestamp.isdigit()):
		frappe.throw("The stored STK password is not short code + passkey + timestamp")
	passkey = decoded[len(shortcode) : -14]
	if base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode() != stored:
		frappe.throw("Could not recover the passkey from the stored password")

	s = frappe.get_doc("Cosmestics POS Settings")
	s.mpesa_environment = "Production"
	s.mpesa_shortcode = shortcode
	s.mpesa_party_b = s.mpesa_party_b or shortcode
	s.mpesa_transaction_type = s.mpesa_transaction_type or "CustomerPayBillOnline"
	s.mpesa_consumer_key = key
	s.mpesa_consumer_secret = secret
	s.mpesa_passkey = passkey
	s.mpesa_callback_base_url = s.mpesa_callback_base_url or "https://classiccosmetics.frappe.cloud/"
	s.flags.ignore_permissions = True
	s.save()
	frappe.db.commit()
	print(f"Imported M-Pesa credentials for short code {shortcode}. Callback base: {s.mpesa_callback_base_url}")
