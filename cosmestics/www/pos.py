import frappe
from frappe import _
from frappe.utils import cint, get_system_timezone

no_cache = 1


def get_context():
	if frappe.session.user == "Guest":
		frappe.throw(_("You need to be logged in to use the POS"), frappe.PermissionError)

	context = frappe._dict()
	context.boot = get_boot()
	return context


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
	"""Serves boot data to the vite dev server, which cannot render the Jinja page."""
	if not frappe.conf.developer_mode:
		frappe.throw(_("This method is only meant for developer mode"))
	return get_boot()


def get_boot():
	user = frappe.session.user
	return frappe._dict(
		{
			"frappe_version": frappe.__version__,
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
