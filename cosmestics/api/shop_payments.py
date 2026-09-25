"""M-Pesa (Daraja STK push) for online orders.

The same Safaricom Daraja integration DukaPlus uses — Lipa na M-Pesa Online,
`/mpesa/stkpush/v1/processrequest` — with the credentials kept in Cosmestics
POS Settings (Password fields, encrypted). Differences from DukaPlus, on
purpose:

* **The STK password is computed per request** — base64(short code + passkey +
  timestamp) with the current timestamp — rather than one precomputed value
  with a frozen timestamp.
* **No request is held open while waiting.** DukaPlus polls for up to 85s
  inside the web request, tying up a worker per payment. Here `pay` returns
  as soon as Safaricom accepts the prompt; the shop page asks
  `payment_status` every few seconds.
* **Two ways to learn the result.** Safaricom's callback is the normal path.
  If it has not arrived after 15s, `payment_status` asks Daraja directly
  (`/stkpushquery/v1/query`), so an order still confirms if the callback is
  lost — and on a development machine the callback cannot reach at all.
* **The callback is authenticated.** Its URL carries a per-site secret token,
  and it must match a request this site actually made, for the amount asked.

Once paid, `finalize` submits the Sales Order (Order Received) and books a
Payment Entry against it — idempotently, under a lock, because the callback
and a status query can arrive together.
"""

import base64
import json
import re

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime, nowdate

from cosmestics import online_orders as oo
from cosmestics.api.shop_account import (
	current_customer,
	normalise_phone,
	require_shop_request,
	valid_phone,
)
from cosmestics.api.shop_orders import _cart_name, _own_order, cart_payload

HOSTS = {"Production": "https://api.safaricom.co.ke", "Sandbox": "https://sandbox.safaricom.co.ke"}
QUERY_AFTER_SECONDS = 15
QUERY_EVERY_SECONDS = 8
GIVE_UP_SECONDS = 180

#: Daraja result codes a customer can act on.
RESULT_MESSAGES = {
	"1": "Your M-Pesa balance is not enough for this payment.",
	"1032": "You cancelled the payment on your phone.",
	"1037": "Your phone did not respond in time. Check it is on and try again.",
	"2001": "The M-Pesa PIN entered was wrong.",
	"1025": "M-Pesa could not send the prompt. Try again.",
	"9999": "M-Pesa could not send the prompt. Try again.",
}


# ---------------------------------------------------------------------------
# Daraja client
# ---------------------------------------------------------------------------


class Daraja:
	def __init__(self):
		s = frappe.get_doc("Cosmestics POS Settings")
		self.host = HOSTS.get(s.get("mpesa_environment") or "Production", HOSTS["Production"])
		self.shortcode = (s.get("mpesa_shortcode") or "").strip()
		self.party_b = (s.get("mpesa_party_b") or "").strip() or self.shortcode
		self.transaction_type = s.get("mpesa_transaction_type") or "CustomerPayBillOnline"
		self.account_reference = (s.get("mpesa_account_reference") or "").strip()
		self.key = s.get_password("mpesa_consumer_key", raise_exception=False)
		self.secret = s.get_password("mpesa_consumer_secret", raise_exception=False)
		self.passkey = s.get_password("mpesa_passkey", raise_exception=False)
		base = (s.get("mpesa_callback_base_url") or "").strip()
		token = s.get("mpesa_callback_token") or ""
		self.callback_url = (
			f"{base.rstrip('/')}/api/method/cosmestics.api.shop_payments.mpesa_callback?token={token}"
			if base
			else ""
		)

	def ready(self) -> bool:
		return all((self.shortcode, self.party_b, self.key, self.secret, self.passkey, self.callback_url))

	def _token(self) -> str:
		cache_key = f"cosmestics:mpesa:token:{self.host}:{self.key[:6]}"
		token = frappe.cache.get_value(cache_key)
		if token:
			return token
		basic = base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
		r = requests.get(
			f"{self.host}/oauth/v1/generate",
			params={"grant_type": "client_credentials"},
			headers={"Authorization": f"Basic {basic}"},
			timeout=20,
		)
		r.raise_for_status()
		data = r.json()
		token = data["access_token"]
		frappe.cache.set_value(cache_key, token, expires_in_sec=max(60, cint(data.get("expires_in")) - 120))
		return token

	def _password(self) -> tuple[str, str]:
		timestamp = now_datetime().strftime("%Y%m%d%H%M%S")
		raw = f"{self.shortcode}{self.passkey}{timestamp}"
		return base64.b64encode(raw.encode()).decode(), timestamp

	def _post(self, path: str, payload: dict) -> dict:
		r = requests.post(
			f"{self.host}{path}",
			json=payload,
			headers={"Authorization": f"Bearer {self._token()}"},
			timeout=30,
		)
		try:
			return r.json()
		except ValueError:
			return {"errorMessage": r.text[:300], "status_code": r.status_code}

	def stk_push(self, phone: str, amount: int, reference: str, description: str) -> dict:
		password, timestamp = self._password()
		return self._post(
			"/mpesa/stkpush/v1/processrequest",
			{
				"BusinessShortCode": self.shortcode,
				"Password": password,
				"Timestamp": timestamp,
				"TransactionType": self.transaction_type,
				"Amount": amount,
				"PartyA": phone,
				"PartyB": self.party_b,
				"PhoneNumber": phone,
				"CallBackURL": self.callback_url,
				"AccountReference": (self.account_reference or reference)[:12],
				"TransactionDesc": description[:13],
			},
		)

	def query(self, checkout_request_id: str) -> dict:
		password, timestamp = self._password()
		return self._post(
			"/mpesa/stkpushquery/v1/query",
			{
				"BusinessShortCode": self.shortcode,
				"Password": password,
				"Timestamp": timestamp,
				"CheckoutRequestID": checkout_request_id,
			},
		)


def _reference(order_name: str) -> str:
	"""The order number, compacted to Daraja's 12-character limit:
	`SAL-ORD-2026-00012` → `ORD202600012`."""
	compact = re.sub(r"[^A-Za-z0-9]", "", order_name)
	return compact[-12:]


# ---------------------------------------------------------------------------
# Customer endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
def pay(phone: str | None = None) -> dict:
	"""Send the M-Pesa prompt for the customer's cart to `phone`."""
	require_shop_request()
	customer = current_customer(required=True)
	name = _cart_name(customer)
	if not name:
		frappe.throw(_("Your cart is empty"))
	so = frappe.get_doc("Sales Order", name)

	payload = cart_payload(so)
	if not payload["lines"]:
		frappe.throw(_("Your cart is empty"))
	if not so.get("cosmestics_fulfilment") or not so.get("cosmestics_contact_phone"):
		frappe.throw(_("Choose delivery or pickup first"))
	short = [line for line in payload["lines"] if line["short"]]
	if short:
		frappe.throw(
			_("Only {0} of {1} are available now. Update your cart to continue.").format(
				short[0]["available"], short[0]["name"]
			)
		)

	phone = normalise_phone(phone or so.cosmestics_contact_phone)
	if not valid_phone(phone):
		frappe.throw(_("Enter the M-Pesa number to pay from, like 0712 345 678"))

	daraja = Daraja()
	if not daraja.ready():
		frappe.throw(_("Online payment is not set up yet. Please contact the shop to order."))

	amount = int(-(-flt(so.grand_total) // 1))  # M-Pesa takes whole shillings; round up
	if amount < 1:
		frappe.throw(_("Nothing to pay for"))

	req = frappe.get_doc(
		{
			"doctype": "Cosmestics Mpesa Request",
			"sales_order": so.name,
			"customer": customer,
			"phone": phone,
			"amount": amount,
			"status": "Pending",
		}
	).insert(ignore_permissions=True)

	try:
		resp = daraja.stk_push(phone, amount, _reference(so.name), "Online order")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "M-Pesa STK push failed")
		resp = {"errorMessage": "Could not reach M-Pesa"}

	if str(resp.get("ResponseCode")) != "0":
		req.status = "Failed"
		req.result_desc = resp.get("errorMessage") or resp.get("ResponseDescription") or json.dumps(resp)[:500]
		req.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.throw(_("M-Pesa could not send the prompt: {0}").format(req.result_desc))

	req.merchant_request_id = resp.get("MerchantRequestID")
	req.checkout_request_id = resp.get("CheckoutRequestID")
	req.result_desc = resp.get("CustomerMessage") or resp.get("ResponseDescription")
	req.save(ignore_permissions=True)

	# Keep the cart's hold on its stock while the customer pays.
	frappe.db.set_value("Sales Order", so.name, "modified", now_datetime(), update_modified=False)
	return {"request": req.name, "amount": amount, "phone": phone, "message": req.result_desc}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def payment_status(request: str) -> dict:
	"""Where a payment has got to. Asks Daraja directly if the callback is late."""
	customer = current_customer(required=True)
	req = frappe.get_doc("Cosmestics Mpesa Request", request)
	if req.customer != customer:
		raise frappe.DoesNotExistError(_("Payment not found"))

	if req.status == "Pending" and req.checkout_request_id:
		age = (now_datetime() - get_datetime(req.creation)).total_seconds()
		since_query = (now_datetime() - get_datetime(req.last_query)).total_seconds() if req.last_query else 1e9
		if age >= QUERY_AFTER_SECONDS and since_query >= QUERY_EVERY_SECONDS:
			_query(req)
			req.reload()
		if req.status == "Pending" and age >= GIVE_UP_SECONDS:
			req.db_set({"status": "Timed Out", "result_desc": "No answer from M-Pesa"})

	return {
		"status": req.status,
		"order": req.sales_order,
		"receipt": req.mpesa_receipt,
		"message": _(RESULT_MESSAGES.get(str(req.result_code or ""), "")) or req.result_desc,
	}


def _query(req):
	req.db_set("last_query", now_datetime(), update_modified=False)
	try:
		resp = Daraja().query(req.checkout_request_id)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "M-Pesa status query failed")
		return
	code = resp.get("ResultCode")
	if code is None:
		# "The transaction is being processed" comes back as an error body.
		return
	code = str(code)
	if code == "0":
		_mark_paid(req.name, amount=req.amount, receipt=None, raw=resp)
	else:
		_mark_failed(req.name, code, resp.get("ResultDesc"), raw=resp)


# ---------------------------------------------------------------------------
# Safaricom's callback
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
def mpesa_callback(token: str | None = None):
	"""Daraja's result for an STK push. Always answers "accepted" — Safaricom
	retries anything else — and records what it could not use."""
	expected = frappe.db.get_single_value("Cosmestics POS Settings", "mpesa_callback_token")
	if not expected or token != expected:
		frappe.local.response["http_status_code"] = 403
		return {"ResultCode": 1, "ResultDesc": "Rejected"}

	try:
		body = frappe.request.get_json(force=True) or {}
		cb = body["Body"]["stkCallback"]
	except Exception:
		frappe.log_error(frappe.request.get_data(as_text=True)[:2000], "M-Pesa callback: unreadable body")
		return {"ResultCode": 0, "ResultDesc": "Accepted"}

	name = frappe.db.get_value("Cosmestics Mpesa Request", {"checkout_request_id": cb.get("CheckoutRequestID")}, "name")
	if not name:
		frappe.log_error(json.dumps(body)[:2000], "M-Pesa callback: unknown request")
		return {"ResultCode": 0, "ResultDesc": "Accepted"}

	code = str(cb.get("ResultCode"))
	if code == "0":
		meta = {i.get("Name"): i.get("Value") for i in (cb.get("CallbackMetadata") or {}).get("Item", [])}
		_mark_paid(name, amount=flt(meta.get("Amount")), receipt=meta.get("MpesaReceiptNumber"), raw=body, phone=meta.get("PhoneNumber"))
	else:
		_mark_failed(name, code, cb.get("ResultDesc"), raw=body)
	return {"ResultCode": 0, "ResultDesc": "Accepted"}


def _mark_failed(name: str, code: str, desc: str | None, raw=None):
	req = frappe.get_doc("Cosmestics Mpesa Request", name, for_update=True)
	if req.status != "Pending":
		return
	req.status = "Cancelled" if code in ("1032",) else "Failed"
	req.result_code = code
	req.result_desc = desc
	if raw:
		req.callback = json.dumps(raw, indent=1)[:10000]
	req.save(ignore_permissions=True)
	frappe.db.commit()


def _mark_paid(name: str, amount: float, receipt: str | None, raw=None, phone=None):
	"""Record the payment, commit it, then complete the order. The payment is
	saved first on its own, so a problem finishing the order can never lose
	the fact that the customer paid."""
	req = frappe.get_doc("Cosmestics Mpesa Request", name, for_update=True)
	if req.status == "Paid":
		if receipt and not req.mpesa_receipt:
			# The status query confirmed it first; the callback brings the receipt.
			req.db_set("mpesa_receipt", receipt)
			frappe.db.set_value("Sales Order", req.sales_order, "cosmestics_mpesa_receipt", receipt, update_modified=False)
		return
	req.status = "Paid"
	req.result_code = "0"
	req.paid_amount = flt(amount) or req.amount
	req.mpesa_receipt = receipt
	req.paid_on = now_datetime()
	if raw:
		req.callback = json.dumps(raw, indent=1)[:10000]
	req.save(ignore_permissions=True)
	frappe.db.commit()

	try:
		finalize(req.name)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), f"Online order {req.sales_order}: paid but not finalised")


def finalize(request_name: str):
	"""Paid → the order is placed: Sales Order submitted and marked Order
	Received, and a Payment Entry booked against it. Safe to call twice."""
	req = frappe.get_doc("Cosmestics Mpesa Request", request_name)
	so = frappe.get_doc("Sales Order", req.sales_order, for_update=True)
	if so.docstatus == 1 and so.cosmestics_order_status != oo.DRAFT:
		return so.name

	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		so.cosmestics_paid_at = req.paid_on or now_datetime()
		so.cosmestics_mpesa_receipt = req.mpesa_receipt
		oo.set_status(
			so,
			oo.RECEIVED,
			note=_("Paid KES {0} by M-Pesa{1}").format(
				frappe.utils.fmt_money(req.paid_amount, precision=0),
				f" ({req.mpesa_receipt})" if req.mpesa_receipt else "",
			),
			by="M-Pesa",
		)
		so.flags.ignore_permissions = True
		if so.docstatus == 0:
			so.submit()
		else:
			so.save()
		_book_payment(so, req)
	finally:
		frappe.set_user(user)
	return so.name


def _book_payment(so, req):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	if frappe.db.exists(
		"Payment Entry Reference",
		{"reference_doctype": "Sales Order", "reference_name": so.name, "docstatus": 1},
	):
		return
	s = oo.settings()
	mode = s.get("shop_mode_of_payment") or s.get("mode_mpesa_paybill") or s.get("mode_mpesa")
	amount = min(flt(req.paid_amount), flt(so.grand_total))
	pe = get_payment_entry("Sales Order", so.name, party_amount=amount)
	if mode:
		pe.mode_of_payment = mode
		account = frappe.db.get_value(
			"Mode of Payment Account", {"parent": mode, "company": so.company}, "default_account"
		)
		if account:
			pe.paid_to = account
	pe.paid_amount = amount
	pe.received_amount = amount
	for ref in pe.references:
		ref.allocated_amount = amount
	pe.reference_no = req.mpesa_receipt or req.checkout_request_id or req.name
	pe.reference_date = nowdate()
	pe.remarks = _("M-Pesa payment for online order {0}").format(so.name)
	pe.flags.ignore_permissions = True
	pe.insert()
	pe.submit()
