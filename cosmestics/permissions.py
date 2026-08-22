"""Who may do what, named once.

Three roles this app creates for itself, rather than borrowing ERPNext's.
"Purchase Manager" and "Stock User" already mean something in the desk and
carry a great deal else with them; these mean exactly one thing each and are
safe to hand to a shop assistant.

* **Purchase Manager** raises the purchase and may correct it while it is still
  a draft. Nothing they do posts stock or a payable.
* **Store Keeper** counts what actually arrived, adjusts the quantities to
  match, and confirms — which is the act that submits the invoice. The split is
  the point: the person who orders is not the person who says it turned up.
* **Analytics** sees the dashboard and the reports. Every other screen is
  operational and everybody needs it; these two are the shop's numbers.

`System Manager` holds all three implicitly. A site's administrator locking
themselves out of the dashboard by forgetting to assign a role is a support
call, not a security posture.
"""

import frappe
from frappe import _

PURCHASE_MANAGER = "Cosmestics Purchase Manager"
STORE_KEEPER = "Cosmestics Store Keeper"
ANALYTICS = "Cosmestics Analytics"

#: Created by the installer, in this order, on every migrate.
APP_ROLES = (PURCHASE_MANAGER, STORE_KEEPER, ANALYTICS)

#: Holds everything, so a fresh site is never locked out of its own numbers.
SUPERUSER = "System Manager"


def has_role(role: str, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = frappe.get_roles(user)
	return role in roles or SUPERUSER in roles


def is_purchase_manager(user: str | None = None) -> bool:
	return has_role(PURCHASE_MANAGER, user)


def is_store_keeper(user: str | None = None) -> bool:
	return has_role(STORE_KEEPER, user)


def can_view_analytics(user: str | None = None) -> bool:
	return has_role(ANALYTICS, user)


def require(role: str, message: str | None = None):
	"""Refuse in the shop's words rather than Frappe's.

	`frappe.only_for` throws "Not permitted", which tells whoever is standing at
	the counter nothing about what to do next. Every caller here knows what the
	person was trying to do, so it says that.
	"""
	if has_role(role):
		return
	frappe.throw(message or _("You do not have permission to do that"), frappe.PermissionError)


def abilities(user: str | None = None) -> dict:
	"""What this session may do, in the shape the frontend gates on.

	Sent with the session rather than derived in the browser from a role list:
	the rule about who counts as a superuser lives here, once, and the two ends
	cannot drift. The server still checks on every write — this only decides
	which buttons are worth drawing.
	"""
	return {
		"purchase_manager": is_purchase_manager(user),
		"store_keeper": is_store_keeper(user),
		"analytics": can_view_analytics(user),
	}
