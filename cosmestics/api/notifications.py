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

	# A group is a different send, whoever is asking. Routed here rather than at
	# each call site because every path that shares something — the documents
	# hub, the row-action share sheet, the staff-group notice — ends up in this
	# function, and fixing only the one that was reported would leave the others
	# failing in exactly the same way.
	if is_group(to):
		return _send_to_group(to, message)

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

	# The integration's document send takes a `phone_number`, so it cannot reach
	# a group at all. The summary still goes — a group getting the text and no
	# PDF is a smaller failure than a group getting nothing, which is what
	# happened before.
	if is_group(to):
		return _send_to_group(to, message or f"{doctype} {name}")

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


#: waclient's own send endpoint. Posted to directly for group messages — see
#: `_send_to_group` for why the integration cannot do it.
SEND_URL = f"{WACLIENT_HOST}/api/send"

#: A WhatsApp group id always ends this way. A phone number never does, which is
#: what makes the distinction safe to draw from the value itself.
GROUP_SUFFIX = "@g.us"


def is_group(to: str) -> bool:
	return bool(to) and str(to).strip().endswith(GROUP_SUFFIX)


def _send_to_group(jid: str, message: str) -> bool:
	"""Post to a WhatsApp group, going around the integration's transport.

	**Why this exists.** `whatsapp_integration.service.rest.send_whatsapp_message`
	builds its payload as `{"number": to_number, ...}`. waclient treats `number`
	as a phone number and expects a group to arrive as **`chat_id`** instead, so
	a group JID sent that way is not delivered — the reply comes back with no
	`data`, and the integration logs `Unexpected message format: None` and
	returns an error.

	That is precisely the failure a shop sees as "material requests are not
	reaching the group": the request is raised, the job runs, the bridge answers,
	and nothing arrives. Nothing in the chain is missing — one field is wrong,
	in an app this one does not own.

	So group sends are posted here, with `chat_id`. Phone numbers still go
	through the integration, which handles normalisation and sender selection
	properly and is the better path for the case it actually supports.
	"""
	creds = _credentials()
	if not creds:
		frappe.log_error(
			"WhatsApp credentials are not configured; group message skipped",
			"Cosmetics POS",
		)
		return False

	payload = {
		# The field that makes this a group send rather than a phone number.
		"chat_id": jid,
		"type": "text",
		"message": message,
		"instance_id": creds.get("instance_id"),
		"access_token": creds.get("access_token"),
	}

	last_error = None
	for attempt in range(SEND_ATTEMPTS):
		try:
			response = requests.post(SEND_URL, json=payload, timeout=30)
			response.raise_for_status()
			body = response.json()
			if _succeeded(body):
				return True
			last_error = body
		except Exception as e:
			last_error = e

		if attempt < len(BACKOFF_SECONDS):
			time.sleep(BACKOFF_SECONDS[attempt])
			warm_up()

	frappe.log_error(
		f"WhatsApp group send to {jid} failed after {SEND_ATTEMPTS} attempts: {last_error}",
		"Cosmetics POS",
	)
	return False


def _send_media_to_group(jid: str, message: str, media_url: str, filename: str) -> bool:
	"""A file to a group, with `chat_id` — same reason as `_send_to_group`."""
	creds = _credentials()
	if not creds:
		return False

	payload = {
		"chat_id": jid,
		"type": "media",
		"message": message,
		"media_url": media_url,
		"filename": filename,
		"instance_id": creds.get("instance_id"),
		"access_token": creds.get("access_token"),
	}
	try:
		response = requests.post(SEND_URL, json=payload, timeout=45)
		response.raise_for_status()
		return _succeeded(response.json())
	except Exception as e:
		frappe.log_error(f"WhatsApp group file send to {jid} failed: {e}", "Cosmetics POS")
		return False


def send_file(to: str, message: str, media_url: str, filename: str) -> bool:
	"""Send an attachment, to a group or a number.

	Groups go direct; numbers keep using the integration, which normalises the
	phone number and picks the sender account.
	"""
	if not to or not media_url:
		return False

	if is_group(to):
		return _send_media_to_group(to, message, media_url, filename)

	try:
		from whatsapp_integration.service.rest import send_whatsapp_media
	except ImportError:
		return send_text(to, message)

	try:
		return _succeeded(
			_quiet(
				send_whatsapp_media,
				to_number=to,
				message=message,
				media_url=media_url,
				file_name=filename,
				country_name=None,
				sender=None,
			)
		)
	except Exception as e:
		frappe.log_error(f"WhatsApp file send to {to} failed: {e}", "Cosmetics POS")
		return False


def publish_csv(filename: str, columns: list, rows: list) -> str | None:
	"""Write rows to a CSV the bridge can fetch, and return its URL.

	**Public, like the integration's own PDF attachments.** waclient pulls the
	file over plain HTTP, so a private File would come back as a login page.
	The URL is unguessable but not access-controlled — the same trade the
	document send already makes, restated here because it is easy to miss when
	the payload is a list of customer balances rather than one invoice.

	A CSV rather than a prettier format because the thing anybody does with a
	shared list is open it in a spreadsheet, and every phone can.
	"""
	if not rows:
		return None

	import csv
	import io

	buffer = io.StringIO()
	writer = csv.writer(buffer)
	writer.writerow([c.get("label", c.get("key")) for c in columns])
	for row in rows:
		writer.writerow([row.get(c["key"], "") for c in columns])

	doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename if filename.endswith(".csv") else f"{filename}.csv",
			"content": buffer.getvalue(),
			"is_private": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	# Committed so the bridge can fetch it: it reads the file over HTTP in
	# another request, which cannot see an uncommitted transaction.
	frappe.db.commit()

	return f"{frappe.utils.get_url()}{doc.file_url}"


@frappe.whitelist()
def status() -> dict:
	"""Can this site actually deliver a WhatsApp message right now?

	Used by the till so it can say whether anybody will be told, rather than
	claiming a message was sent because one was queued. Every field is a
	separate reason it might not work, because they need different fixes.
	"""
	settings = _settings()
	group = settings.whatsapp_group_jid
	installed = _integration_available()
	creds = _credentials() if installed else None

	if not settings.notify_material_request:
		reason = "WhatsApp notices are switched off in settings."
	elif not group:
		reason = "No staff group is chosen in settings."
	elif not installed:
		reason = (
			"whatsapp_integration is not installed on this site — its DocTypes are "
			"missing, so there is nowhere for the credentials to live."
		)
	elif not creds:
		reason = "WhatsApp is installed but has no instance id or access token."
	else:
		reason = None

	return {
		"usable": reason is None,
		"reason": reason,
		"group": group,
		"is_group": is_group(group),
		"installed": installed,
	}


@frappe.whitelist(methods=["POST"])
def send_material_request(name: str) -> dict:
	"""Post one material request to the staff group, now.

	The submit hook already queues this, but a queued job that failed leaves
	nothing a shop can retry — the request is submitted and cannot be submitted
	again. This is the retry, and the way to test the group is reachable without
	raising a fake request to do it.
	"""
	doc = frappe.get_doc("Material Request", name)
	if not frappe.has_permission("Material Request", "read", doc=doc.name):
		frappe.throw(_("You do not have permission to send {0}").format(name))

	state = status()
	if not state["usable"]:
		return {"sent": False, "message": state["reason"], **state}

	sent = send_to_staff_group(format_material_request(doc))
	return {
		"sent": bool(sent),
		"message": _("{0} posted to the staff group").format(name)
		if sent
		else _("WhatsApp accepted nothing — check the Error Log for the reply"),
		**state,
	}


def send_to_staff_group(message: str) -> bool:
	"""Post to the configured staff group."""
	try:
		settings = _settings()
	except Exception:
		return False

	if not settings.notify_material_request or not settings.whatsapp_group_jid:
		return False

	target = settings.whatsapp_group_jid

	# A group and a phone number are two different sends. The integration only
	# knows how to do the second — it puts whatever it is given in the `number`
	# field, which waclient will not route to a group.
	if is_group(target):
		return _send_to_group(target, message)

	return send_text(target, message, settings.whatsapp_sender or None)


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
	csv_columns: list | str | None = None,
	csv_rows: list | str | None = None,
	filename: str | None = None,
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

	if isinstance(csv_columns, str):
		csv_columns = frappe.parse_json(csv_columns)
	if isinstance(csv_rows, str):
		csv_rows = frappe.parse_json(csv_rows)

	attached = None
	if doctype and name:
		# Read permission is checked on the real document: this endpoint must not
		# become a way to render a PDF of anything on the site by naming it.
		if not frappe.has_permission(doctype, "read", doc=name):
			frappe.throw(_("You do not have permission to share {0} {1}").format(doctype, name))
		sent = send_document(doctype, name, to, message, sender)
	elif csv_rows and csv_columns:
		# A list goes as a file as well as text. The message is readable on the
		# phone; the CSV is what somebody actually works from.
		attached = publish_csv(filename or "list", csv_columns, csv_rows)
		sent = (
			send_file(to, message, attached, (filename or "list") + ".csv")
			if attached
			else send_text(to, message, sender)
		)
	else:
		sent = send_text(to, message, sender)

	return {
		"sent": bool(sent),
		"to": to,
		"attached": attached,
		"message": _("Sent to {0}").format(to)
		if sent
		else _("Could not send to {0} — check the WhatsApp settings").format(to),
	}


def app_url(path: str) -> str:
	"""A link into this app, not into the desk.

	`get_url_to_form` points at `/app/material-request/…`, which opens ERPNext's
	desk — a screen most shop staff cannot use and some cannot even reach. The
	people this message goes to live in the POS, so the link should land there.
	"""
	return f"{frappe.utils.get_url()}/pos{path}"


def _table(headers: list, rows: list) -> str:
	"""A fixed-width table, wrapped in a WhatsApp code block.

	WhatsApp renders text between triple backticks in a monospace font, which is
	the only way to get columns that line up on a phone — proportional text
	turns any amount of padding into a ragged mess. Widths are measured from the
	content so a long item name does not push the numbers out of alignment.

	Long names are truncated rather than wrapped: a wrapped cell breaks the
	column for every row beneath it, and the request already carries a link to
	the full document.
	"""
	widths = [len(h) for h in headers]
	for row in rows:
		for i, cell in enumerate(row):
			widths[i] = max(widths[i], len(str(cell)))

	def line(cells):
		# Last column is not padded — trailing spaces just widen the block.
		out = []
		for i, cell in enumerate(cells):
			text = str(cell)
			out.append(text if i == len(cells) - 1 else text.ljust(widths[i]))
		return "  ".join(out).rstrip()

	body = [line(headers), line(["-" * w for w in widths])]
	body += [line(r) for r in rows]
	return "```\n" + "\n".join(body) + "\n```"


def format_material_request(doc) -> str:
	"""What is needed, as a table.

	Leads with the goods rather than with document metadata: the person reading
	this on a phone is being asked to fetch something, and the reference number
	only matters once they have decided to.
	"""
	rows = []
	for item in doc.items:
		name = item.item_name or item.item_code
		rows.append(
			[
				f"{flt(item.qty):g}",
				name if len(name) <= 24 else name[:23] + "…",
				item.warehouse or "—",
			]
		)

	lines = [
		"*Stock request*",
		f"{doc.name} · {doc.material_request_type}",
		"",
		_table(["Qty", "Item", "To"], rows),
	]

	if getattr(doc, "set_from_warehouse", None):
		lines.append(f"From: {doc.set_from_warehouse}")

	lines.append(f"Needed by: {doc.schedule_date or 'as soon as possible'}")
	lines.append(f"Raised by {frappe.utils.get_fullname(doc.owner)}")
	lines.append("")
	lines.append(app_url("/documents/material-request"))

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
	message = format_material_request(doc)

	settings = _settings()
	target = settings.whatsapp_group_jid
	if not target:
		return

	# The table in the message is for reading; the CSV is for working from —
	# whoever is buying wants it in a spreadsheet, not retyped off a phone.
	columns = [
		{"key": "item_code", "label": "Item code"},
		{"key": "item_name", "label": "Item"},
		{"key": "qty", "label": "Qty"},
		{"key": "uom", "label": "UOM"},
		{"key": "warehouse", "label": "To"},
	]
	rows = [
		{
			"item_code": i.item_code,
			"item_name": i.item_name,
			"qty": flt(i.qty),
			"uom": i.uom,
			"warehouse": i.warehouse,
		}
		for i in doc.items
	]

	url = publish_csv(docname, columns, rows)
	if url and send_file(target, message, url, f"{docname}.csv"):
		return

	# The list still has to reach the group even if the attachment did not.
	send_to_staff_group(message)
