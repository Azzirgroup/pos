"""WhatsApp notifications for the POS.

Uses the site's existing `whatsapp_integration` app, which runs on a WhatsApp
Web bridge (waclient) rather than Meta's Cloud API. That distinction matters:
the official Cloud API cannot post to groups at all, whereas the bridge accepts
a group JID as `chat_id` and routes to it verbatim.

Everything here is best-effort. A failed notification must never roll back or
block the stock document that triggered it — the shop still needs the request.
"""

import frappe
from frappe.utils import flt, get_url_to_form


def _settings():
	return frappe.get_cached_doc("Cosmestics POS Settings")


def send_to_staff_group(message: str) -> bool:
	"""Post a plain-text message to the configured staff group.

	Returns True if handed off to the bridge, False if skipped or failed.
	"""
	try:
		settings = _settings()
	except Exception:
		return False

	if not settings.notify_material_request or not settings.whatsapp_group_jid:
		return False

	try:
		from whatsapp_integration.service.rest import send_whatsapp_message
	except ImportError:
		frappe.log_error(
			"whatsapp_integration app is not installed; POS notification skipped",
			"Cosmestics POS",
		)
		return False

	try:
		send_whatsapp_message(
			to_number=None,
			message=message,
			chat_id=settings.whatsapp_group_jid,
			sender=settings.whatsapp_sender or None,
		)
		return True
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Cosmestics POS: WhatsApp send failed")
		return False


def format_material_request(doc) -> str:
	"""Human-readable summary. Staff read this on a phone, so it leads with what
	is needed and where, not with document metadata."""
	lines = [
		"*Stock request*",
		f"{doc.name} · {doc.material_request_type}",
		"",
	]

	for item in doc.items:
		qty = flt(item.qty)
		qty_str = f"{qty:g}"
		row = f"• {qty_str} × {item.item_name or item.item_code}"
		if item.warehouse:
			row += f" → {item.warehouse}"
		lines.append(row)

	if getattr(doc, "set_from_warehouse", None):
		lines.append("")
		lines.append(f"From: {doc.set_from_warehouse}")

	lines.append("")
	lines.append(f"Raised by {frappe.utils.get_fullname(doc.owner)}")
	lines.append(get_url_to_form(doc.doctype, doc.name))

	return "\n".join(lines)


def on_material_request_submit(doc, method=None):
	"""Hooked on Material Request `on_submit`.

	Enqueued rather than inline: an HTTP call to the WhatsApp bridge can take
	seconds, and nobody at a till should wait on it.
	"""
	try:
		settings = _settings()
		if not settings.notify_material_request:
			return
	except Exception:
		return

	frappe.enqueue(
		"cosmestics.api.notifications._enqueued_material_request_notice",
		queue="short",
		enqueue_after_commit=True,
		docname=doc.name,
	)


def _enqueued_material_request_notice(docname: str):
	doc = frappe.get_doc("Material Request", docname)
	send_to_staff_group(format_material_request(doc))
