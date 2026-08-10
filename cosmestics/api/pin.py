"""Signing in at the till with a four-digit PIN.

## Why this is not just a short password

A PIN has ten thousand possible values. Typed at a counter, in front of
customers, on a device the whole shop shares. Nothing about the secret itself is
strong, so the strength has to come from everywhere else:

* **Opt-in per person.** A user cannot be signed into by PIN unless somebody
  deliberately ticked the box on their account. No PIN, no box, no entry.
* **Hashed, not stored.** The digits are hashed with the same pbkdf2 context
  Frappe uses for real passwords, and the plaintext is dropped before the
  document is written. A site backup does not contain anybody's PIN.
* **Locked after a handful of tries.** Five wrong attempts and that person's PIN
  is refused for fifteen minutes, however many browsers or tabs are used. Ten
  thousand guesses at five per fifteen minutes is three weeks of continuous
  attempts to cover half the keyspace, and a shop notices a locked till long
  before that.
* **Rate limited per address** as well, so a script cannot work through the
  staff list in parallel.

The lockout is the actual control here. Everything else is hygiene.

## What it is not

It is not a way onto the desk. It signs a cashier into the till and nothing
else — the same session Frappe would have issued, so every permission check
downstream is unchanged. A shop that wants a cashier kept out of the desk does
that with roles, exactly as before.
"""

import hashlib
import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils.password import passlibctx

#: Wrong tries before a person's PIN stops being accepted.
MAX_ATTEMPTS = 5

#: How long the refusal lasts, in seconds.
LOCKOUT_SECONDS = 15 * 60

PIN_PATTERN = re.compile(r"^\d{4}$")


def _key_for(user: str) -> str:
	"""A stable, opaque handle for a user, safe to hand to a signed-out browser.

	The PIN screen has to list who can use it, and listing login names would
	publish every staff email to anyone who opens the page — a ready-made list
	of accounts to attack, on a site that may well be on the open internet.

	Derived from the site's own encryption key so the mapping cannot be
	reproduced elsewhere, and truncated because it is a lookup handle rather
	than a secret in its own right.
	"""
	secret = frappe.local.conf.get("encryption_key") or frappe.local.site
	return hashlib.sha256(f"{secret}:{user}".encode()).hexdigest()[:24]


def _pin_enabled_users() -> list:
	return frappe.get_all(
		"User",
		filters={
			"enabled": 1,
			"user_type": "System User",
			"cosmestics_pin_login": 1,
			"name": ("not in", ["Guest"]),
		},
		fields=["name", "full_name"],
		order_by="full_name asc",
		limit_page_length=0,
		ignore_permissions=True,
	)


def _initials(name: str) -> str:
	parts = [p for p in (name or "").replace(".", " ").split() if p]
	return "".join(p[0] for p in parts[:2]).upper() or "?"


def pin_people() -> list:
	"""Who can sign in by PIN, ready to render as a row of faces.

	Names only, never login ids — see `_key_for`. Anybody standing at the counter
	can already see who works there, so the names themselves give nothing away;
	the addresses would.

	Plain function as well as an endpoint, because the sign-in page renders this
	server-side: fetching it after paint means the page appears with an empty
	card and fills in a moment later, which on a slow counter tablet reads as a
	broken screen rather than a loading one.
	"""
	return [
		{
			"key": _key_for(u.name),
			"label": u.full_name or u.name,
			"initials": _initials(u.full_name or u.name),
		}
		for u in _pin_enabled_users()
		if frappe.db.get_value("User", u.name, "cosmestics_pin_hash")
	]


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="pin_users", limit=30, seconds=60, ip_based=True)
def pin_users() -> list:
	"""The same list, for anything that needs it after the page has loaded."""
	return pin_people()


def _lock_key(user: str) -> str:
	return f"cosmestics:pin-fail:{user}"


def _attempts(user: str) -> int:
	return frappe.cache().get_value(_lock_key(user)) or 0


def _record_failure(user: str) -> int:
	count = _attempts(user) + 1
	# The window restarts on every failure, deliberately: an attacker pacing
	# themselves to just under the limit should not be able to keep going for
	# ever, and a cashier who mistypes twice an hour apart is never affected.
	frappe.cache().set_value(_lock_key(user), count, expires_in_sec=LOCKOUT_SECONDS)
	return count


def _clear_failures(user: str):
	frappe.cache().delete_value(_lock_key(user))


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="pin_login", limit=20, seconds=60, ip_based=True)
def pin_login(key: str, pin: str) -> dict:
	"""Sign in as the holder of `key`, if the PIN matches.

	Failures are deliberately vague — "That PIN was not recognised" whether the
	handle is unknown, the account has no PIN, or the digits are wrong. A message
	that distinguishes them is a way to confirm which handles are real.

	The lockout message is the one exception. It is not a hint about a secret; it
	is the reason the till is refusing somebody who is standing there, and
	leaving them to guess is how a shop concludes the feature is broken.
	"""
	pin = (pin or "").strip()

	# Resolved by scanning the small set of PIN-enabled accounts rather than by
	# reversing the handle, which is a hash and cannot be reversed.
	user = next((u.name for u in _pin_enabled_users() if _key_for(u.name) == key), None)

	if not user or not PIN_PATTERN.match(pin):
		frappe.local.response["http_status_code"] = 401
		return {"ok": False, "message": _("That PIN was not recognised")}

	if _attempts(user) >= MAX_ATTEMPTS:
		frappe.local.response["http_status_code"] = 429
		return {
			"ok": False,
			"locked": True,
			"message": _("Too many wrong tries. Sign in with a password, or wait 15 minutes."),
		}

	stored = frappe.db.get_value("User", user, "cosmestics_pin_hash")
	if not stored or not passlibctx.verify(pin, stored):
		remaining = MAX_ATTEMPTS - _record_failure(user)
		frappe.local.response["http_status_code"] = 401
		if remaining <= 0:
			return {
				"ok": False,
				"locked": True,
				"message": _("Too many wrong tries. Sign in with a password, or wait 15 minutes."),
			}
		return {"ok": False, "message": _("That PIN was not recognised")}

	_clear_failures(user)

	# Frappe's own session, issued the way any other login issues one, so nothing
	# downstream has to know this was a PIN. `login_as` runs `post_login` itself —
	# calling it again fires the login hooks and the audit trail twice.
	login_manager = getattr(frappe.local, "login_manager", None)
	if not login_manager:
		# No request to attach a session to. Only reachable from a script or the
		# console, where "signed in" means nothing — better to say so than to
		# report a success that issued no cookie.
		frappe.throw(_("PIN sign-in is only available over HTTP"))

	login_manager.login_as(user)

	return {"ok": True, "user": user, "full_name": frappe.utils.get_fullname(user)}


def hash_user_pin(doc, method=None):
	"""Turn a typed PIN into a hash, and forget the digits.

	Hooked on User validate, so it runs whoever set the PIN and through whatever
	route — the desk form, an import, a script. Clearing `cosmestics_pin` before
	the document is written is what keeps the plaintext out of the database
	entirely: a `Password` field would otherwise be kept, encrypted but
	recoverable, and a PIN nobody can recover is a strictly better thing to own.
	"""
	pin = (doc.get("cosmestics_pin") or "").strip()

	if not pin:
		return

	if not PIN_PATTERN.match(pin):
		frappe.throw(_("A till PIN must be exactly four digits."))

	# Cheap refusals for the PINs that are not a secret at all. A shop that has
	# just been told PIN sign-in exists reaches for 1234 first.
	if pin in {"1234", "0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999"}:
		frappe.throw(_("Pick a less obvious PIN — {0} is one of the first anybody tries.").format(pin))

	doc.cosmestics_pin_hash = passlibctx.hash(pin)
	# Never stored. The field exists to be typed into, not to hold anything.
	doc.cosmestics_pin = ""
