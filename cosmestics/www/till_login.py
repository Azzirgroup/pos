"""The till's own sign-in page.

Separate from the SPA rather than a route inside it, and deliberately so: every
screen in `/pos` is behind `pos.py`'s permission check, which throws for Guest.
A login route living in there could never be reached by the person who most
needs it. This page is the one thing in the app a signed-out user may open.

It is also separate from ERPNext's `/login`, which is a desk sign-in: it offers
password resets, signup, social logins and an email field, and it lands on the
desk. None of that belongs on a shop counter, and the worst of it — landing a
cashier in the desk — is what made the till feel like a bolt-on.

Authentication itself is *not* reimplemented here. The form posts to Frappe's
own `/api/method/login`, so rate limiting, password policy and session handling
stay exactly where they are. This page is a face, not a mechanism.
"""

import frappe

no_cache = 1


def get_context(context):
	# Already signed in: there is nothing to ask. Sending them to the till is
	# what they wanted from the link they clicked.
	if frappe.session.user != "Guest":
		frappe.local.flags.redirect_location = _redirect_target()
		raise frappe.Redirect

	from cosmestics.api.pin import pin_people

	context.no_header = 1
	context.no_breadcrumbs = 1
	context.redirect_to = _redirect_target()
	context.shop_name = _shop_name()

	# Rendered into the page rather than fetched after it. A counter tablet on a
	# slow connection would otherwise paint an empty card and fill it in a beat
	# later, which reads as broken rather than loading.
	context.people = pin_people()
	# PIN is the front door where the shop has set one up. It is the faster of
	# the two by a wide margin, and the one a cashier uses every morning; typing
	# a password is the exception, so it is the link rather than the form.
	context.default_mode = "pin" if context.people else "password"

	return context


def _redirect_target() -> str:
	"""Where to land after signing in.

	Read from the query string so "switch user" comes back to the screen the
	cashier was on, but validated rather than trusted: an open redirect on a
	login page is how a convincing phishing link gets built. Only paths inside
	this app are honoured — anything else, including a full URL to somewhere
	else, falls back to the till.
	"""
	target = frappe.form_dict.get("redirect-to") or frappe.form_dict.get("redirect_to") or ""

	# Must be a site-relative path under /pos. `//evil.com` is a protocol-
	# relative URL that a naive "starts with /" check would let through.
	if target.startswith("/pos") and not target.startswith("//"):
		return target

	return "/pos/pos"


def _shop_name() -> str:
	"""Whose counter this is. A cashier signing in at one of several branches
	should see which one before they type anything."""
	company = frappe.defaults.get_global_default("company")
	return company or "Cosmetics POS"
