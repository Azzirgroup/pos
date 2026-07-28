"""WhatsApp notifications for the POS.

Sends through the site's `whatsapp_integration` app, which talks to a waclient
bridge rather than Meta's Cloud API. That distinction matters: the Cloud API
cannot post to groups at all, whereas the bridge accepts a group JID and routes
to it verbatim — so a JID is passed in the same argument as a phone number.

The bridge idles aggressively, and the first request after a quiet spell tends
to time out while it wakes. Every send therefore pings the host first and
retries with backoff, treating an early failure as "still waking" rather than
"broken".

Everything here is best-effort. A failed notification must never roll back or
block the stock document that triggered it — the shop still needs the request.
"""

import time

import frappe
import requests
from frappe.utils import flt, get_url_to_form

# The bridge's own host. Pinging it is what wakes the process; the send that
# follows then lands on a warm one.
WACLIENT_HOST = "https://waclient.com"
PING_TIMEOUT = 8
SEND_ATTEMPTS = 3
# First retry is quick (the ping usually woke it); the next backs off.
BACKOFF_SECONDS = (1, 4)


def _settings():
	return frappe.get_cached_doc("Cosmestics POS Settings")


def warm_up() -> bool:
	"""Nudge the bridge so the real send does not pay the cold-start cost.

	Deliberately tolerant: any HTTP response at all means a process is running,
	including a 4xx, because this ping carries no credentials. Only a connection
	failure or timeout counts as still-asleep.
	"""
	try:
		requests.get(WACLIENT_HOST, timeout=PING_TIMEOUT)
		return True
	except requests.RequestException:
		return False


def send_text(to: str, message: str, sender: str | None = None) -> bool:
	"""Send one message. `to` is a phone number or a group JID.

	Returns True on success and never raises — callers are stock and sales
	documents that must not fail because a notification did.
	"""
	if not to or not message:
		return False

	try:
		from whatsapp_integration.service.rest import send_whatsapp_message
	except ImportError:
		frappe.log_error(
			"whatsapp_integration is not installed; POS notification skipped",
			"Cosmestics POS",
		)
		return False

	warm_up()

	last_error = None
	for attempt in range(SEND_ATTEMPTS):
		try:
			# Signature is (to_number, message, country_name, sender). A group JID
			# goes in to_number; there is no separate chat_id argument.
			result = send_whatsapp_message(to_number=to, message=message, sender=sender)
			if _succeeded(result):
				return True
			last_error = result
		except Exception as e:
			last_error = e

		if attempt < len(BACKOFF_SECONDS):
			# A sleeping bridge often accepts the second attempt, so retrying is
			# worth more here than failing fast.
			time.sleep(BACKOFF_SECONDS[attempt])
			warm_up()

	frappe.log_error(
		f"WhatsApp send to {to} failed after {SEND_ATTEMPTS} attempts: {last_error}",
		"Cosmestics POS",
	)
	return False


def _succeeded(result) -> bool:
	"""The bridge is inconsistent about its success shape, so check several."""
	if result is None:
		return False
	if isinstance(result, bool):
		return result
	if isinstance(result, dict):
		if result.get("error"):
			return False
		status = str(result.get("status", "")).lower()
		if status in ("success", "ok", "sent", "true"):
			return True
		# Some responses carry only a message id.
		return bool(result.get("id") or result.get("message_id"))
	return True


def send_to_staff_group(message: str) -> bool:
	"""Post to the configured staff group."""
	try:
		settings = _settings()
	except Exception:
		return False

	if not settings.notify_material_request or not settings.whatsapp_group_jid:
		return False

	return send_text(
		settings.whatsapp_group_jid, message, settings.whatsapp_sender or None
	)


@frappe.whitelist(methods=["POST"])
def test_whatsapp(to: str, message: str | None = None):
	"""Send a test message, reporting each stage separately.

	Split out because "it never arrived" has three very different causes — the
	bridge asleep, the credentials wrong, or the number malformed — and the shop
	needs to know which one it is looking at.
	"""
	warmed = warm_up()
	sent = send_text(
		to,
		message or "Cosmestics POS test message — if you can read this, sending works.",
	)
	return {
		"bridge_reachable": warmed,
		"sent": sent,
		"hint": None
		if sent
		else (
			"Bridge did not respond at all — check waclient is running"
			if not warmed
			else "Bridge is awake but rejected the send; check access token, instance id and the number/JID"
		),
	}


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
		row = f"• {qty:g} × {item.item_name or item.item_code}"
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

	Enqueued rather than inline: waking the bridge and sending can take several
	seconds, and nobody at a till should wait on that.
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
