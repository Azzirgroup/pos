import frappe
from frappe import _
from frappe.utils import cint, get_system_timezone, quoted as quote

no_cache = 1


def get_context():
	if frappe.session.user == "Guest":
		# Redirect rather than throw. The permission error rendered ERPNext's own
		# 403 page with a link to the desk login — so a cashier who opened the
		# till before signing in ended up in the desk, which is the one place the
		# app exists to keep them out of. `till_login` sends them back here.
		frappe.local.flags.redirect_location = "/till-login?redirect-to=" + quote(
			frappe.request.path if frappe.request else "/pos/pos"
		)
		raise frappe.Redirect

	context = frappe._dict()
	context.boot = get_boot()
	return context


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
	"""Serves boot data to the vite dev server, which cannot render the Jinja page."""
	if not frappe.conf.developer_mode:
		frappe.throw(_("This method is only meant for developer mode"))
	return get_boot()


def build_id() -> str:
	"""Which build of the front end this page is serving.

	The hashed name of the entry chunk, which changes on every build and on no
	other occasion — so it *is* the version, with nothing extra to maintain.

	Exists because a till is a tab left open all day. A deploy under it leaves
	the cashier running yesterday's JavaScript with no sign anything is wrong:
	a fix ships, they refresh nothing, and the thing that was fixed is still
	broken in front of them. `router.js` already recovers when a *navigation*
	asks for a chunk that no longer exists, but nothing catches the case where
	the stale code simply keeps working — which is most of them.
	"""
	import glob
	import os

	base = frappe.get_app_path("cosmestics", "public", "frontend", "assets")
	entries = sorted(glob.glob(os.path.join(base, "index-*.js")))
	return os.path.basename(entries[0]) if entries else ""


@frappe.whitelist()
def get_build_id() -> str:
	"""The current build, for a tab checking whether it has fallen behind."""
	return build_id()


def get_boot():
	user = frappe.session.user
	return frappe._dict(
		{
			"frappe_version": frappe.__version__,
			"build_id": build_id(),
			"site_name": frappe.local.site,
			"csrf_token": frappe.sessions.get_csrf_token(),
			"read_only_mode": frappe.flags.read_only,
			"setup_complete": cint(frappe.get_system_settings("setup_complete")),
			"user": {
				"name": user,
				"full_name": frappe.utils.get_fullname(user),
				"user_image": frappe.db.get_value("User", user, "user_image"),
			},
			"timezone": {
				"system": get_system_timezone(),
				"user": frappe.db.get_value("User", user, "time_zone") or get_system_timezone(),
			},
		}
	)
