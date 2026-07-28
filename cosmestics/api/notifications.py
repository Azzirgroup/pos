"""WhatsApp notifications for the POS.

Sends through the site's `whatsapp_integration` app, which talks to a waclient
bridge rather than Meta's Cloud API. That distinction matters: the Cloud API
cannot post to groups at all, whereas the bridge accepts a group JID and routes
to it verbatim — so a JID is passed in the same argument as a phone number.

Everything goes through that app's **high-level API**
(`whatsapp_integration.api.whatsapp.whatsapp`) rather than the low-level
`service.rest` transport. The high-level layer normalises phone numbers, picks
the right sender account for the logged-in user, and — most importantly — knows
how to read the bridge's inconsistent success responses. Calling the transport
directly meant reimplementing that interpretation here, and getting it subtly
wrong: a send the bridge had accepted was reported as a failure whenever it
answered with anything other than a plain `status: success`.

`service.rest` is kept only as a fallback for installs that predate the
high-level module.

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

# The bridge answers with any of these when it has accepted a message. Taken
# from `whatsapp_integration`'s own reading of its responses rather than guessed
# at again here — two different opinions about what "sent" means is how a
# delivered message gets logged as a failure.
ACCEPTED_STATUSES = ("success", "sent", "queued", "processing", "ok", "true")


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


def _quiet(fn, *args, **kwargs):
	"""Run a whatsapp_integration call without its `msgprint` reaching the UI.

	Those calls announce their own success in a dialog, which is right for the
	desk and wrong here — this app reports the outcome in its own toast, and two
	notifications for one action reads as a bug.
	"""
	previous = frappe.flags.mute_messages
	frappe.flags.mute_messages = True
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.flags.mute_messages = previous


def _send_once(to: str, message: str, sender: str | None):
	"""One attempt, through the highest-level API this install has."""
	try:
		from whatsapp_integration.api.whatsapp.whatsapp import send_quick_message_via_whatsapp

		return _quiet(
			send_quick_message_via_whatsapp,
			phone_number=to,
			message=message,
			sender=sender,
		)
	except ImportError:
		# Older whatsapp_integration: only the transport exists.
		from whatsapp_integration.service.rest import send_whatsapp_message

		return _quiet(send_whatsapp_message, to_number=to, message=message, sender=sender)


def send_text(to: str, message: str, sender: str | None = None) -> bool:
	"""Send one message. `to` is a phone number or a group JID.

	Returns True on success and never raises — callers are stock and sales
	documents that must not fail because a notification did.
	"""
	if not to or not message:
		return False

	if not _integration_available():
		frappe.log_error(
			"whatsapp_integration is not installed; POS notification skipped",
			"Cosmestics POS",
		)
		return False

	warm_up()

	last_error = None
	for attempt in range(SEND_ATTEMPTS):
		try:
			result = _send_once(to, message, sender)
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


def send_document(doctype: str, name: str, to: str, message: str | None = None, sender: str | None = None) -> bool:
	"""Send a document as a PDF attachment.

	Uses `send_document_via_whatsapp`, which renders the document through
	ERPNext's own print format. That matters: a customer who is sent an invoice
	should receive the invoice, not a paraphrase of it, and the PDF matches what
	the shop would have printed.

	Note the integration publishes the PDF as a **public** File so the bridge can
	fetch it — the URL is unguessable but not access-controlled.
	"""
	if not to:
		return False

	try:
		from whatsapp_integration.api.whatsapp.whatsapp import send_document_via_whatsapp
	except ImportError:
		# No document endpoint on this install: a text summary is better than
		# nothing, and the caller has already composed one.
		return send_text(to, message or f"{doctype} {name}", sender)

	warm_up()
	try:
		result = _quiet(
			send_document_via_whatsapp,
			doctype=doctype,
			docname=name,
			phone_number=to,
			message=message,
			sender=sender,
		)
		return _succeeded(result)
	except Exception as e:
		frappe.log_error(f"WhatsApp document send of {doctype} {name} to {to} failed: {e}", "Cosmestics POS")
		return False


def list_senders() -> list:
	"""Sender accounts this user may send from. Empty when unconfigured."""
	try:
		from whatsapp_integration.api.whatsapp.whatsapp import get_whatsapp_senders
	except ImportError:
		return []

	try:
		return get_whatsapp_senders() or []
	except Exception:
		return []


def _integration_available() -> bool:
	try:
		import whatsapp_integration  # noqa: F401

		return True
	except ImportError:
		return False


def _succeeded(result) -> bool:
	"""Did the bridge accept the message?

	The response shape is inconsistent, so this mirrors the integration's own
	reading of it: an explicit accepted status, or no error at all, both count.
	The "unexpected message response format" case is included deliberately — the
	bridge returns it on messages it has in fact delivered.
	"""
	if result is None:
		return False
	if isinstance(result, bool):
		return result
	if not isinstance(result, dict):
		return True

	status = str(result.get("status", "")).lower()
	if status in ACCEPTED_STATUSES:
		return True

	error = result.get("error")
	if not error or str(error).lower() == "false":
		return True

	blurb = str(result.get("message") or error or "").lower()
	if "unexpected message response" in blurb:
		return True

	# Some responses carry only a message id, nested under the bridge's own
	# envelope.
	data = result.get("data")
	if isinstance(data, dict) and data.get("key", {}).get("id"):
		return True

	return bool(result.get("id") or result.get("message_id"))


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
	installed = _integration_available()
	sent = send_text(
		to,
		message or "Cosmestics POS test message — if you can read this, sending works.",
	)
	return {
		"integration_installed": installed,
		"bridge_reachable": warmed,
		"senders": [s.get("value") for s in list_senders()],
		"sent": sent,
		"hint": None
		if sent
		else (
			"whatsapp_integration is not installed on this site"
			if not installed
			else "Bridge did not respond at all — check waclient is running"
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
