"""End-to-end check of online orders, rolled back when it finishes.

    bench --site <site> execute cosmestics.setup.online_check.run

Signs up a customer, fills a cart, checks the stock hold another customer
sees, checks out for delivery, simulates the M-Pesa callback (the real API
is not called), then walks the order through the staff workflow — billing,
the rider's delivery, and completion when the rider marks it delivered.
Commits are disabled for the run, so nothing persists.
"""

import json
from unittest.mock import patch

import frappe
from frappe.auth import CookieManager
from frappe.utils import flt, random_string

from cosmestics import online_orders as oo
from cosmestics.setup.smoke import _Report


def run():
	r = _Report()
	real_commit = frappe.db.commit
	try:
		with patch.object(frappe.db, "commit", lambda *a, **k: None):
			_run(r)
	finally:
		frappe.db.rollback()
		frappe.db.commit = real_commit
		frappe.set_user("Administrator")
	return r.summary()


def _as_shopper(token: str | None = None):
	"""Make the next calls look like they come from the shop in a browser."""
	from frappe.utils import set_request

	headers = {"X-Shop": "1"}
	if token:
		headers["Cookie"] = f"cc_shop={token}"
	set_request(method="POST", path="/api/method/x", headers=headers)
	frappe.local.cookie_manager = CookieManager()
	frappe.local.request_ip = "127.0.0.1"
	frappe.local.cosmestics_shop_customer = "unset"
	frappe.local.response = frappe._dict()
	frappe.set_user("Guest")


def _signup(name, phone):
	from cosmestics.api import shop_account

	_as_shopper()
	out = shop_account.signup(full_name=name, phone=phone, password="Secret-pass1")
	token = frappe.local.cookie_manager.cookies["cc_shop"]["value"]
	return out["customer"]["id"], token


def _stocked_item():
	from cosmestics import shop

	snap = shop.snapshot()
	for code in snap["listed"]:
		p = snap["products"][code]
		if p.get("has_variants") or p["price"] <= 0:
			continue
		if oo.available([code]).get(code, 0) >= 3:
			return code, p
	return None, None


def _run(r):
	from cosmestics.api import online_orders as staff
	from cosmestics.api import shop_account, shop_orders, shop_payments

	tag = random_string(4)
	phone_a = "0799" + str(abs(hash(tag)) % 1000000).zfill(6)
	phone_b = "0798" + str(abs(hash(tag + "b")) % 1000000).zfill(6)

	# --- accounts --------------------------------------------------------
	customer, token = _signup(f"Test Shopper {tag}", phone_a)
	r.check("signup creates a Customer", frappe.db.exists("Customer", customer))
	group = frappe.db.get_single_value("Cosmestics POS Settings", "shop_customer_group")
	r.check("the customer joins the online group", frappe.db.get_value("Customer", customer, "customer_group") == group, group)
	stored = frappe.db.get_value("Customer", customer, "cosmestics_password_hash")
	r.check("password is stored hashed", stored and "Secret-pass1" not in stored)

	_as_shopper(token)
	r.check("session cookie resolves the customer", shop_account.current_customer() == customer)

	_as_shopper()
	try:
		shop_account.signup(full_name="Mismatch", phone="0797" + phone_a[-6:], password="abcdef12", confirm_password="abcdef13")
		r.check("mismatched confirm password is refused", False)
	except frappe.ValidationError:
		r.check("mismatched confirm password is refused", True)

	# Google: the token check is Google's library; here it is stubbed to what a
	# verified token for this shop decodes to.
	claims = {"sub": "g-" + tag, "email": f"g{tag}@example.com".lower(), "email_verified": True, "name": f"Google Shopper {tag}"}
	with patch.object(shop_account, "google_client_id", lambda: "test-client"), patch(
		"google.oauth2.id_token.verify_oauth2_token", lambda *a, **k: claims
	):
		_as_shopper()
		g1 = shop_account.google_login(credential="token")
		_as_shopper()
		g2 = shop_account.google_login(credential="token")
	group = frappe.db.get_single_value("Cosmestics POS Settings", "shop_customer_group")
	r.check("Google sign-up creates a Customer in the online group", g1["ok"] and frappe.db.get_value("Customer", g1["customer"]["id"], "customer_group") == group)
	r.check("signing in with Google again finds the same customer", g2["customer"]["id"] == g1["customer"]["id"])
	r.check("a Google customer is asked for a phone", g1["customer"]["needs_phone"])
	with patch.object(shop_account, "google_client_id", lambda: "test-client"), patch(
		"google.oauth2.id_token.verify_oauth2_token", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
	):
		_as_shopper()
		bad_g = shop_account.google_login(credential="forged")
	r.check("a token Google cannot verify is refused", not bad_g["ok"])

	_as_shopper()
	bad = shop_account.login(identifier=phone_a, password="wrong-password")
	r.check("wrong password is refused vaguely", not bad["ok"] and "Wrong" in bad["message"])
	good = shop_account.login(identifier=phone_a, password="Secret-pass1")
	r.check("sign in by phone works", good["ok"])

	# --- cart and holds --------------------------------------------------
	code, product = _stocked_item()
	r.check("found a stocked product", code, code)
	if not code:
		return
	before = oo.available([code])[code]

	_as_shopper(token)
	cart = shop_orders.set_line(item_code=code, qty=2)
	r.check("adding makes a Draft online Sales Order", cart["order"] and cart["count"] == 2)
	so = frappe.get_doc("Sales Order", cart["order"])
	r.check("the order is flagged online", so.cosmestics_online_order == 1 and so.cosmestics_order_status == "Draft")
	r.check("the draft is logged", len(so.cosmestics_status_log) == 1)

	other, token_b = _signup(f"Other Shopper {tag}", phone_b)
	r.check("another shopper sees the held stock gone", oo.available([code])[code] == before - 2, (before, oo.available([code])[code]))
	_as_shopper(token)
	r.check("the holder still sees their own stock", shop_orders.availability(item_codes=json.dumps([code]))[code] == before)

	try:
		_as_shopper(token)
		shop_orders.set_line(item_code=code, qty=before + 5)
		r.check("more than available is refused", False)
	except frappe.ValidationError as e:
		r.check("more than available is refused", "available" in str(e) or "out of stock" in str(e), str(e)[:80])

	# --- checkout --------------------------------------------------------
	frappe.db.delete("Cosmestics Delivery Area")
	frappe.db.set_single_value("Cosmestics POS Settings", "shop_delivery_fee", 1)
	frappe.clear_document_cache("Cosmestics POS Settings", "Cosmestics POS Settings")
	_as_shopper(token)
	cart = shop_orders.set_fulfilment(fulfilment="Delivery", address="Kimathi Street, 3rd floor", phone=phone_a)
	r.check("with no areas, delivery charges the flat fee", cart["delivery_fee"] == 1, cart["delivery_fee"])

	area = frappe.get_doc({"doctype": "Cosmestics Delivery Area", "area_name": f"Test Area {tag}", "fee": 150, "enabled": 1}).insert(ignore_permissions=True)
	_as_shopper(token)
	cart = shop_orders.set_fulfilment(fulfilment="Delivery", area=area.name, address="Kimathi Street, 3rd floor", phone=phone_a)
	r.check("delivery fee is added", cart["delivery_fee"] == 150 and flt(cart["total"]) == flt(cart["subtotal"]) + 150, cart["total"])
	_as_shopper(token)
	cart = shop_orders.set_fulfilment(fulfilment="Pickup", phone=phone_a)
	r.check("pickup removes the fee", cart["delivery_fee"] == 0)
	_as_shopper(token)
	cart = shop_orders.set_fulfilment(fulfilment="Delivery", area=area.name, address="Kimathi Street, 3rd floor", phone=phone_a)

	# --- payment (simulated callback) -----------------------------------
	_as_shopper(token)
	with patch.object(shop_payments.Daraja, "ready", lambda self: True), patch.object(
		shop_payments.Daraja,
		"stk_push",
		lambda self, *a, **k: {"ResponseCode": "0", "MerchantRequestID": "M-" + tag, "CheckoutRequestID": "ws_CO_" + tag, "CustomerMessage": "Success"},
	):
		sent = shop_payments.pay(phone=phone_a)
	r.check("pay sends the prompt", sent["request"] and sent["amount"] == int(-(-flt(cart["total"]) // 1)))

	frappe.set_user("Guest")
	frappe.local.form_dict = frappe._dict(token=frappe.db.get_single_value("Cosmestics POS Settings", "mpesa_callback_token"))
	body = {
		"Body": {
			"stkCallback": {
				"MerchantRequestID": "M-" + tag,
				"CheckoutRequestID": "ws_CO_" + tag,
				"ResultCode": 0,
				"ResultDesc": "The service request is processed successfully.",
				"CallbackMetadata": {
					"Item": [
						{"Name": "Amount", "Value": sent["amount"]},
						{"Name": "MpesaReceiptNumber", "Value": "TST" + tag.upper()},
						{"Name": "PhoneNumber", "Value": 254700000000},
					]
				},
			}
		}
	}
	from frappe.utils import set_request

	set_request(method="POST", path="/api/method/cb", data=json.dumps(body), headers={"Content-Type": "application/json"})
	rejected = shop_payments.mpesa_callback(token="wrong")
	r.check("a callback with the wrong token is rejected", rejected["ResultCode"] == 1)
	set_request(method="POST", path="/api/method/cb", data=json.dumps(body), headers={"Content-Type": "application/json"})
	ack = shop_payments.mpesa_callback(token=frappe.db.get_single_value("Cosmestics POS Settings", "mpesa_callback_token"))
	r.check("the callback is acknowledged", ack["ResultCode"] == 0)

	so = frappe.get_doc("Sales Order", cart["order"])
	r.check("paid order is submitted", so.docstatus == 1, so.docstatus)
	r.check("status is Order Received", so.cosmestics_order_status == "Order Received", so.cosmestics_order_status)
	r.check("receipt is on the order", so.cosmestics_mpesa_receipt == "TST" + tag.upper())
	pe = frappe.db.get_value("Payment Entry Reference", {"reference_name": so.name, "docstatus": 1}, "parent")
	r.check("a Payment Entry is booked against it", pe, pe)

	set_request(method="POST", path="/api/method/cb", data=json.dumps(body), headers={"Content-Type": "application/json"})
	shop_payments.mpesa_callback(token=frappe.db.get_single_value("Cosmestics POS Settings", "mpesa_callback_token"))
	count = frappe.db.count("Payment Entry Reference", {"reference_name": so.name, "docstatus": 1})
	r.check("a repeated callback books nothing twice", count == 1, count)

	_as_shopper(token)
	mine = shop_orders.my_orders()
	r.check("the customer sees their order", any(o["name"] == so.name for o in mine))
	detail = shop_orders.order(name=so.name)
	states = {t["status"]: t["state"] for t in detail["timeline"]}
	r.check("tracking shows Order Received as current", states.get("Order Received") == "current", states)
	r.check("tracking times the Draft stage", detail["timeline"][0]["seconds"] is not None)

	_as_shopper(token_b)
	try:
		shop_orders.order(name=so.name)
		r.check("another customer cannot see the order", False)
	except frappe.DoesNotExistError:
		r.check("another customer cannot see the order", True)

	# --- staff workflow --------------------------------------------------
	frappe.set_user("Administrator")
	frappe.local.response = frappe._dict()
	queue = staff.list_orders()
	r.check("the order is in the staff queue", any(o["name"] == so.name for o in queue["orders"]))
	staff.advance(name=so.name, to="Processing")
	out = staff.advance(name=so.name, to="Out for Delivery", rider_name=f"Rider {tag}")
	so.reload()
	r.check("out for delivery bills the order", out["invoice"] and frappe.db.get_value("Sales Invoice", out["invoice"], "docstatus") == 1)
	r.check("the advance is used on the invoice", flt(frappe.db.get_value("Sales Invoice", out["invoice"], "outstanding_amount")) <= 1)
	r.check("a delivery is on the rider's worklist", so.cosmestics_delivery and frappe.db.get_value("Cosmestics Delivery", so.cosmestics_delivery, "status") == "Dispatched")

	from cosmestics.api.deliveries import set_delivery_status

	set_delivery_status(so.cosmestics_delivery, "Delivered")
	so.reload()
	r.check("the rider's Delivered completes the order", so.cosmestics_order_status == "Complete", so.cosmestics_order_status)
	r.check("every step is in the history", [row.status for row in so.cosmestics_status_log] == ["Draft", "Order Received", "Processing", "Out for Delivery", "Complete"], [row.status for row in so.cosmestics_status_log])

	try:
		staff.advance(name=so.name, to="Processing")
		r.check("a finished order cannot go back", False)
	except frappe.ValidationError:
		r.check("a finished order cannot go back", True)
