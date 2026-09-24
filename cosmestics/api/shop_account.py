"""Customer accounts for the online shop, kept on the Customer record.

A shopper is a **Customer**, not a Frappe User: they sign in with the shop
username (or phone) and password stored on their Customer, and never get a
desk account, a role, or anything that could reach ERPNext. Their session is
this module's own — an opaque token in an HttpOnly cookie, mapped to the
Customer in Redis — and every shop endpoint resolves the customer from it
with `current_customer()`.

Security notes, because this is a login system:

* **Passwords are hashed** with Frappe's own pbkdf2 context, on every save
  path (`hash_customer_password` runs on Customer `validate`), so staff can
  set one from the desk and the plaintext is never written.
* **Cookie** is HttpOnly (scripts cannot read it), Secure on HTTPS and
  SameSite=Lax. State-changing calls must also carry an `X-Shop: 1` header,
  which a form on another site cannot send — the CSRF guard for a session
  Frappe itself does not know about.
* **Failures are vague** ("Wrong username or password") and rate limited per
  IP and per account, so the login cannot be used to find which phone
  numbers have accounts or to guess passwords.
"""

import hashlib
import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, now_datetime
from frappe.utils.password import passlibctx

COOKIE = "cc_shop"
SESSION_DAYS = 30
MIN_PASSWORD = 6
MAX_FAILS = 8
LOCK_SECONDS = 15 * 60


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def _session_key(token: str) -> str:
	return "cosmestics:shop:sess:" + hashlib.sha256(token.encode()).hexdigest()


def current_customer(required: bool = False) -> str | None:
	"""The Customer signed in on this request, or None.

	With `required`, a missing session raises a 401 the shop app turns into
	its sign-in dialog."""
	cached = getattr(frappe.local, "cosmestics_shop_customer", "unset")
	if cached != "unset":
		customer = cached
	else:
		customer = None
		token = frappe.request.cookies.get(COOKIE) if frappe.request else None
		if token:
			name = frappe.cache.get_value(_session_key(token))
			if name and frappe.db.get_value("Customer", name, ["disabled", "cosmestics_shop_enabled"]) == (0, 1):
				customer = name
		frappe.local.cosmestics_shop_customer = customer

	if required and not customer:
		frappe.local.response["http_status_code"] = 401
		raise frappe.AuthenticationError(_("Please sign in to continue"))
	return customer


def require_shop_request():
	"""Refuse a state-changing call that did not come from the shop's own
	pages. A cross-site form can send cookies but not custom headers."""
	if frappe.get_request_header("X-Shop") != "1":
		frappe.throw(_("Please use the shop to do this"), frappe.PermissionError)


def _start_session(customer: str):
	token = frappe.generate_hash(length=48)
	frappe.cache.set_value(_session_key(token), customer, expires_in_sec=SESSION_DAYS * 86400)
	frappe.local.cookie_manager.set_cookie(
		COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="Lax"
	)
	frappe.local.cosmestics_shop_customer = customer
	frappe.db.set_value("Customer", customer, "cosmestics_shop_last_login", now_datetime(), update_modified=False)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def hash_customer_password(doc, method=None):
	"""Customer `validate`: tidy the sign-in fields, and turn a typed password
	into a hash and drop it."""
	if doc.get("cosmestics_shop_username"):
		doc.cosmestics_shop_username = doc.cosmestics_shop_username.strip().lower()
	if doc.get("cosmestics_shop_phone"):
		doc.cosmestics_shop_phone = normalise_phone(doc.cosmestics_shop_phone)
		if not valid_phone(doc.cosmestics_shop_phone):
			frappe.throw(_("Shop Phone should be a Kenyan mobile number, like 0712 345 678"))

	typed = doc.get("cosmestics_set_password")
	if not typed or set(str(typed)) == {"*"}:
		# The desk sends asterisks back for a Password field it did not change.
		doc.cosmestics_set_password = None
		return
	_check_password_strength(typed)
	doc.cosmestics_password_hash = passlibctx.hash(typed)
	doc.cosmestics_set_password = None


def _check_password_strength(password: str):
	if len(password) < MIN_PASSWORD:
		frappe.throw(_("Use at least {0} characters for the password").format(MIN_PASSWORD))
	if password.isdigit() and len(set(password)) <= 2:
		frappe.throw(_("Pick a less obvious password"))


def normalise_phone(raw: str) -> str:
	"""`0712 345 678`, `+254712345678` and `712345678` all become
	`254712345678`, the form M-Pesa and the account lookup both use."""
	digits = re.sub(r"\D", "", raw or "")
	if digits.startswith("0") and len(digits) == 10:
		digits = "254" + digits[1:]
	elif len(digits) == 9 and digits[0] in "17":
		digits = "254" + digits
	return digits


def valid_phone(phone: str) -> bool:
	return bool(re.fullmatch(r"254[17]\d{8}", phone or ""))


def _fail_key(identifier: str) -> str:
	return "cosmestics:shop:login-fail:" + hashlib.sha256(identifier.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _find_customer(identifier: str) -> str | None:
	identifier = (identifier or "").strip()
	if not identifier:
		return None
	by_name = frappe.db.get_value("Customer", {"cosmestics_shop_username": identifier.lower()}, "name")
	if by_name:
		return by_name
	phone = normalise_phone(identifier)
	if valid_phone(phone):
		return frappe.db.get_value("Customer", {"cosmestics_shop_phone": phone}, "name")
	return None


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="shop_login", limit=20, seconds=60, ip_based=True)
def login(identifier: str, password: str) -> dict:
	require_shop_request()
	identifier = (identifier or "").strip()
	fails = frappe.cache.get_value(_fail_key(identifier.lower())) or 0
	if fails >= MAX_FAILS:
		frappe.local.response["http_status_code"] = 429
		return {"ok": False, "message": _("Too many tries. Wait 15 minutes, or reset your password with the shop.")}

	customer = _find_customer(identifier)
	row = (
		frappe.db.get_value(
			"Customer",
			customer,
			["cosmestics_password_hash", "cosmestics_shop_enabled", "disabled"],
			as_dict=True,
		)
		if customer
		else None
	)
	ok = bool(
		row
		and row.cosmestics_password_hash
		and cint(row.cosmestics_shop_enabled)
		and not cint(row.disabled)
		and passlibctx.verify(password or "", row.cosmestics_password_hash)
	)
	if not ok:
		frappe.cache.set_value(_fail_key(identifier.lower()), fails + 1, expires_in_sec=LOCK_SECONDS)
		frappe.local.response["http_status_code"] = 401
		return {"ok": False, "message": _("Wrong username, phone or password")}

	frappe.cache.delete_value(_fail_key(identifier.lower()))
	_start_session(customer)
	return {"ok": True, "customer": profile(customer)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="shop_signup", limit=10, seconds=3600, ip_based=True)
def signup(
	full_name: str,
	phone: str,
	password: str,
	confirm_password: str | None = None,
	email: str | None = None,
	username: str | None = None,
) -> dict:
	"""Create a Customer with a shop account and sign them in."""
	require_shop_request()
	if confirm_password is not None and confirm_password != password:
		frappe.throw(_("The two passwords do not match"))
	full_name = re.sub(r"\s+", " ", (full_name or "").strip())
	phone = normalise_phone(phone)
	username = (username or "").strip().lower() or None
	email = (email or "").strip() or None

	if len(full_name) < 2:
		frappe.throw(_("Enter your name"))
	if not valid_phone(phone):
		frappe.throw(_("Enter a Kenyan mobile number, like 0712 345 678"))
	if username and not re.fullmatch(r"[a-z0-9._-]{3,30}", username):
		frappe.throw(_("A username is 3-30 letters, numbers, dots, dashes or underscores"))
	if email and not frappe.utils.validate_email_address(email):
		frappe.throw(_("That email address does not look right"))
	_check_password_strength(password or "")

	if frappe.db.exists("Customer", {"cosmestics_shop_phone": phone}):
		frappe.throw(_("That phone number already has an account. Sign in instead."))
	if username and frappe.db.exists("Customer", {"cosmestics_shop_username": username}):
		frappe.throw(_("That username is taken"))

	selling = frappe.get_cached_doc("Selling Settings")
	doc = frappe.new_doc("Customer")
	doc.customer_name = full_name
	doc.customer_type = "Individual"
	# Every online sign-up joins the shop's online group (Cosmestics POS
	# Settings → Online Customer Group), so they can be told apart, priced or
	# reported on as a group.
	from cosmestics.setup.online_setup import ensure_online_customer_group

	doc.customer_group = ensure_online_customer_group()
	doc.territory = selling.territory or frappe.db.get_value("Territory", {"is_group": 0}, "name")
	doc.cosmestics_shop_username = username or phone
	doc.cosmestics_shop_phone = phone
	doc.cosmestics_shop_email = email
	doc.cosmestics_shop_enabled = 1
	doc.cosmestics_set_password = password
	doc.flags.ignore_permissions = True
	doc.insert()

	_start_session(doc.name)
	return {"ok": True, "customer": profile(doc.name)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def logout() -> dict:
	require_shop_request()
	token = frappe.request.cookies.get(COOKIE) if frappe.request else None
	if token:
		frappe.cache.delete_value(_session_key(token))
	frappe.local.cookie_manager.delete_cookie(COOKIE)
	frappe.local.cosmestics_shop_customer = None
	return {"ok": True}


def profile(customer: str) -> dict:
	row = frappe.db.get_value(
		"Customer",
		customer,
		[
			"name",
			"customer_name",
			"cosmestics_shop_username",
			"cosmestics_shop_phone",
			"cosmestics_shop_email",
			"cosmestics_google_sub",
		],
		as_dict=True,
	)
	return {
		"google": bool(row.cosmestics_google_sub),
		"has_password": bool(frappe.db.get_value("Customer", customer, "cosmestics_password_hash")),
		"needs_phone": not row.cosmestics_shop_phone,
		"id": row.name,
		"name": row.customer_name,
		"username": row.cosmestics_shop_username,
		"phone": row.cosmestics_shop_phone,
		"email": row.cosmestics_shop_email,
		"first_name": (row.customer_name or "").split(" ")[0],
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def me() -> dict:
	customer = current_customer()
	return {"customer": profile(customer) if customer else None}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def update_profile(full_name: str | None = None, email: str | None = None, phone: str | None = None) -> dict:
	require_shop_request()
	customer = current_customer(required=True)
	doc = frappe.get_doc("Customer", customer)
	if phone and not doc.cosmestics_shop_phone:
		# A customer who signed up with Google adds their number once; after
		# that it is changed only by the shop, since it is also a sign-in.
		phone = normalise_phone(phone)
		if not valid_phone(phone):
			frappe.throw(_("Enter a Kenyan mobile number, like 0712 345 678"))
		if frappe.db.exists("Customer", {"cosmestics_shop_phone": phone, "name": ("!=", customer)}):
			frappe.throw(_("That phone number already belongs to another account"))
		doc.cosmestics_shop_phone = phone
	if full_name and len(full_name.strip()) >= 2:
		doc.customer_name = re.sub(r"\s+", " ", full_name.strip())
	if email is not None:
		email = email.strip() or None
		if email and not frappe.utils.validate_email_address(email):
			frappe.throw(_("That email address does not look right"))
		doc.cosmestics_shop_email = email
	doc.flags.ignore_permissions = True
	doc.save()
	return {"customer": profile(customer)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="shop_password", limit=10, seconds=3600, ip_based=True)
def change_password(current: str, new: str) -> dict:
	require_shop_request()
	customer = current_customer(required=True)
	stored = frappe.db.get_value("Customer", customer, "cosmestics_password_hash")
	if not stored or not passlibctx.verify(current or "", stored):
		frappe.throw(_("Your current password is not right"))
	doc = frappe.get_doc("Customer", customer)
	doc.cosmestics_set_password = new
	doc.flags.ignore_permissions = True
	doc.save()
	return {"ok": True}


# ---------------------------------------------------------------------------
# Sign in with Google
# ---------------------------------------------------------------------------


def google_client_id() -> str:
	"""The OAuth client ID the Google button uses: the shop's own setting, or
	Frappe's Google Social Login Key if that is where it was configured."""
	own = (frappe.db.get_single_value("Cosmestics POS Settings", "shop_google_client_id") or "").strip()
	if own:
		return own
	if frappe.db.exists("Social Login Key", "google"):
		return (frappe.db.get_value("Social Login Key", "google", "client_id") or "").strip()
	return ""


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="shop_google", limit=30, seconds=60, ip_based=True)
def google_login(credential: str) -> dict:
	"""Sign in (or sign up) with the ID token Google's button hands the page.

	The token is verified here — signature, issuer, expiry and that it was
	issued for *this* shop's client ID — so a token minted for another site
	is refused. An existing Customer is matched by their Google account, then
	by a verified email that matches their shop email; otherwise a new
	Customer is created in the online group. Google does not share a phone
	number, so a new account adds one at checkout.
	"""
	require_shop_request()
	client_id = google_client_id()
	if not client_id:
		frappe.throw(_("Sign in with Google is not set up for this shop"))

	from google.auth.transport import requests as google_requests
	from google.oauth2 import id_token

	try:
		info = id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)
	except Exception:
		frappe.local.response["http_status_code"] = 401
		return {"ok": False, "message": _("Google sign-in did not go through. Please try again.")}

	sub = info.get("sub")
	email = (info.get("email") or "").strip().lower()
	verified = bool(info.get("email_verified"))
	if not sub:
		frappe.throw(_("Google did not say who you are"))

	customer = frappe.db.get_value("Customer", {"cosmestics_google_sub": sub}, "name")
	if not customer and email and verified:
		customer = frappe.db.get_value("Customer", {"cosmestics_shop_email": email, "cosmestics_google_sub": ("is", "not set")}, "name")
		if customer:
			frappe.db.set_value("Customer", customer, "cosmestics_google_sub", sub)

	if customer:
		row = frappe.db.get_value("Customer", customer, ["disabled", "cosmestics_shop_enabled"], as_dict=True)
		if cint(row.disabled) or not cint(row.cosmestics_shop_enabled):
			frappe.local.response["http_status_code"] = 403
			return {"ok": False, "message": _("This account cannot sign in. Please contact the shop.")}
	else:
		from cosmestics.setup.online_setup import ensure_online_customer_group

		selling = frappe.get_cached_doc("Selling Settings")
		name = re.sub(r"\s+", " ", (info.get("name") or email.split("@")[0] or "Customer").strip())
		doc = frappe.new_doc("Customer")
		doc.customer_name = name
		doc.customer_type = "Individual"
		doc.customer_group = ensure_online_customer_group()
		doc.territory = selling.territory or frappe.db.get_value("Territory", {"is_group": 0}, "name")
		doc.cosmestics_shop_username = email or None
		doc.cosmestics_shop_email = email or None
		doc.cosmestics_google_sub = sub
		doc.cosmestics_shop_enabled = 1
		doc.flags.ignore_permissions = True
		doc.insert()
		customer = doc.name

	_start_session(customer)
	return {"ok": True, "customer": profile(customer)}
