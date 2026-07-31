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
from frappe import _
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
			"Cosmetics POS",
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
		"Cosmetics POS",
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
		frappe.log_error(f"WhatsApp document send of {doctype} {name} to {to} failed: {e}", "Cosmetics POS")
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
	"""Is the integration actually usable, not merely importable?

	The Python package being on the path is not enough: on a site where the app
	is listed but its DocTypes were never migrated, `Whatsapp Settings` does not
	exist, so every send dies resolving credentials. Checking only the import
	reported that site as healthy — which is how "WhatsApp is set up" and
	"WhatsApp cannot possibly work" came to look identical.
	"""
	try:
		import whatsapp_integration  # noqa: F401
	except ImportError:
		return False

	return bool(frappe.db.exists("DocType", "Whatsapp Settings"))


def _credentials() -> dict | None:
	"""Instance id and access token, however this install stores them.

	Never raises. The integration's own resolver throws when the single is
	missing or its controller cannot be imported, and this is called from status
	and picker endpoints where "not configured" is an answer, not an error.
	"""
	try:
		from whatsapp_integration.service.rest import get_whatsapp_settings

		creds = get_whatsapp_settings()
		if creds.get("access_token") and creds.get("instance_id"):
			return creds
	except Exception:
		pass

	if not frappe.db.exists("DocType", "Whatsapp Settings"):
		return None

	settings = frappe.db.get_singles_dict("Whatsapp Settings") or {}
	if settings.get("access_token") and settings.get("instance_id"):
		return {"access_token": settings["access_token"], "instance_id": settings["instance_id"]}
	return None


@frappe.whitelist()
def list_groups() -> dict:
	"""WhatsApp groups this instance belongs to.

	`GET /api/get_groups` on the bridge, documented alongside `/api/send`. It
	exists so nobody has to paste a raw group JID — `120363012345678901@g.us` is
	not something a shop manager can find, let alone verify they typed correctly,
	and a wrong one fails silently by delivering nowhere.

	Read-only and best-effort: a bridge that is asleep or unconfigured returns an
	empty list with a reason rather than throwing.
	"""
	creds = _credentials()
	if not creds:
		return {
			"groups": [],
			"reason": _(
				"WhatsApp is not configured on this site. Install the whatsapp_integration "
				"DocTypes and set an instance id and access token in Whatsapp Settings."
			),
		}

	warm_up()
	try:
		resp = requests.get(
			f"{WACLIENT_HOST}/api/get_groups",
			params={"instance_id": creds["instance_id"], "access_token": creds["access_token"]},
			timeout=20,
		)
		payload = resp.json()
	except (requests.RequestException, ValueError) as e:
		frappe.log_error(f"Could not list WhatsApp groups: {e}", "Cosmetics POS")
		return {"groups": [], "reason": _("The WhatsApp bridge did not answer.")}

	return {"groups": _parse_groups(payload), "reason": None}


def _parse_groups(payload) -> list:
	"""Normalise the bridge's reply into [{id, name}].

	The envelope varies — the same bridge answers `data`, `groups` or a bare list
	depending on the call — so the shape is discovered rather than assumed, the
	way `_succeeded` treats send responses.
	"""
	rows = payload
	if isinstance(payload, dict):
		for key in ("data", "groups", "result", "message"):
			if isinstance(payload.get(key), list):
				rows = payload[key]
				break
		else:
			rows = []

	if not isinstance(rows, list):
		return []

	groups = []
	for row in rows:
		if not isinstance(row, dict):
			continue
		jid = row.get("id") or row.get("jid") or row.get("chat_id") or row.get("group_id")
		if isinstance(jid, dict):
			jid = jid.get("_serialized") or jid.get("user")
		if not jid:
			continue
		groups.append(
			{
				"id": str(jid),
				"name": row.get("name") or row.get("subject") or row.get("title") or str(jid),
			}
		)
	return groups


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
	groups = list_groups()
	sent = send_text(
		to,
		message or "Cosmetics POS test message — if you can read this, sending works.",
	)
	return {
		"integration_installed": installed,
		"bridge_reachable": warmed,
		"senders": [s.get("value") for s in list_senders()],
		"groups": groups["groups"],
		"sent": sent,
		"hint": None
		if sent
		else (
			groups.get("reason")
			or "whatsapp_integration is not usable on this site — its DocTypes are missing"
			if not installed
			else "Bridge did not respond at all — check waclient is running"
			if not warmed
			else "Bridge is awake but rejected the send; check access token, instance id and the number/JID"
		),
	}


@frappe.whitelist(methods=["POST"])
def share(
	to: str,
	message: str,
	sender: str | None = None,
	doctype: str | None = None,
	name: str | None = None,
) -> dict:
	"""Share something from a list view on WhatsApp.

	Two shapes, deliberately one endpoint. Given a `doctype` and `name` the real
	PDF goes out with the text as its caption, so sharing an invoice from any
	screen sends the invoice rather than a description of it. Given neither — a
	reorder line, a stock figure, a row from a report — the text is the message,
	because there is no document to render.

	Composing the text is the caller's job. The rows on screen are already
	formatted, labelled and filtered by the user, and rebuilding that server-side
	would produce a message that does not match what they were looking at.

	`to` is a phone number or a group JID; both go through the same send.
	"""
	if not to:
		frappe.throw(_("Say where to send it"))
	if not message or not message.strip():
		frappe.throw(_("There is nothing to send"))

	sender = sender or _settings().whatsapp_sender or None

	if doctype and name:
		# Read permission is checked on the real document: this endpoint must not
		# become a way to render a PDF of anything on the site by naming it.
		if not frappe.has_permission(doctype, "read", doc=name):
			frappe.throw(_("You do not have permission to share {0} {1}").format(doctype, name))
		sent = send_document(doctype, name, to, message, sender)
	else:
		sent = send_text(to, message, sender)

	return {
		"sent": bool(sent),
		"to": to,
		"message": _("Sent to {0}").format(to)
		if sent
		else _("Could not send to {0} — check the WhatsApp settings").format(to),
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

	try:
		frappe.enqueue(
			"cosmestics.api.notifications._enqueued_material_request_notice",
			queue="short",
			enqueue_after_commit=True,
			docname=doc.name,
		)
	except Exception as e:
		# Enqueuing itself can fail — Redis down is the common one — and that
		# exception propagates out of `on_submit` and rolls back the Material
		# Request. A shop then cannot request stock because a notification queue
		# is unavailable, which inverts this module's whole premise: the request
		# matters, the message about it does not.
		frappe.log_error(
			f"Could not queue the WhatsApp notice for {doc.name}: {e}", "Cosmetics POS"
		)


def _enqueued_material_request_notice(docname: str):
	doc = frappe.get_doc("Material Request", docname)
	send_to_staff_group(format_material_request(doc))
