"""What went out on WhatsApp, what did not, and sending it again.

A shop whose WhatsApp subscription lapses for a morning loses every statement,
receipt and notice that was due in it, and nothing says so afterwards: the
senders are best-effort by design, because a notification must never fail a
sale. `Cosmestics Outbound Message` is the record that makes the question
answerable, and this is what reads it back.

The bridge cannot be asked. The integration only ever calls `/api/send` and
`/api/set_webhook` — there is no endpoint that answers "what did you deliver on
Tuesday", so the only honest record is the one kept here.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, nowdate

#: Kinds whose message is only true on the day it was made.
#:
#: Sending Tuesday's shift summary on Friday is not a late notice, it is a
#: wrong one — the figures describe a drawer that has been counted twice since.
#: The same goes for a void or a payment correction: by the time anyone reads
#: it, the thing it is warning about is history. They stay in the list and can
#: still be sent one at a time, deliberately, but "send everything" skips them.
PERISHABLE = {"Shift summary", "Sale voided", "Quotation ended", "Payment changed"}

#: How long a perishable notice is still worth sending, in days.
PERISHABLE_DAYS = 1


def _spec(row) -> dict:
	stale = False
	if row.kind in PERISHABLE:
		stale = getdate(row.creation) < getdate(add_days(nowdate(), -PERISHABLE_DAYS))
	return {
		"name": row.name,
		"status": row.status,
		"kind": row.kind,
		"subject": row.subject,
		"to": row.to_number,
		"is_group": bool(row.is_group),
		"body": (row.body or "")[:400],
		"has_file": bool(row.media_url),
		"attempts": cint(row.attempts),
		"error": row.last_error,
		"at": str(row.creation),
		"sent_at": str(row.sent_at) if row.sent_at else None,
		# Still sendable, but not as part of "send all" — see `PERISHABLE`.
		"stale": stale,
	}


@frappe.whitelist()
def list_messages(
	from_date: str | None = None,
	to_date: str | None = None,
	status: str | None = None,
	limit: int = 200,
) -> dict:
	"""One day's outbound messages, newest first.

	Defaults to today, because the question is nearly always asked about the
	morning that just went wrong.
	"""
	if not frappe.has_permission("Cosmestics Outbound Message", "read"):
		frappe.throw(_("You may not see the message log"), frappe.PermissionError)

	start = getdate(from_date or nowdate())
	end = getdate(to_date or from_date or nowdate())
	if start > end:
		start, end = end, start

	filters = {"creation": ["between", [f"{start} 00:00:00", f"{end} 23:59:59"]]}
	if status in ("Queued", "Sent", "Failed"):
		filters["status"] = status

	rows = frappe.get_all(
		"Cosmestics Outbound Message",
		filters=filters,
		fields=[
			"name", "status", "kind", "subject", "to_number", "is_group", "body",
			"media_url", "attempts", "last_error", "creation", "sent_at",
		],
		order_by="creation desc",
		limit_page_length=min(max(cint(limit) or 200, 1), 500),
	)
	out = [_spec(r) for r in rows]

	counts = {"Sent": 0, "Failed": 0, "Queued": 0}
	for r in out:
		counts[r["status"]] = counts.get(r["status"], 0) + 1

	return {
		"from_date": str(start),
		"to_date": str(end),
		"rows": out,
		"counts": counts,
		# What "Send the failed ones again" would actually do, so the button can
		# say it rather than the shop finding out.
		"resendable": len([r for r in out if r["status"] != "Sent" and not r["stale"]]),
	}


@frappe.whitelist(methods=["POST"])
def resend(names: list | str) -> dict:
	"""Try these messages again, oldest first.

	Oldest first so a customer who was owed three messages gets them in the
	order they happened. Each one updates the row it came from rather than
	writing a new one — otherwise a bad morning doubles the log every time
	somebody presses the button.
	"""
	from cosmestics.api.notifications import send_file, send_text

	if isinstance(names, str):
		names = frappe.parse_json(names)
	names = [n for n in (names or []) if n]
	if not names:
		frappe.throw(_("Nothing chosen to send"))

	if not frappe.has_permission("Cosmestics Outbound Message", "write"):
		frappe.throw(_("You may not send these again"), frappe.PermissionError)

	rows = frappe.get_all(
		"Cosmestics Outbound Message",
		filters={"name": ["in", names]},
		fields=["name", "to_number", "body", "media_url", "filename", "sender", "status"],
		order_by="creation asc",
	)

	sent, failed = [], []
	for row in rows:
		if row.status == "Sent":
			# Asked for by name, already gone. Skipped rather than refused: a
			# selection that happens to include one is a normal thing to do, and
			# sending it twice is the one outcome nobody wants.
			continue
		frappe.local.cosmestics_outbox_replaying = True
		try:
			if row.media_url:
				ok = send_file(row.to_number, row.body or "", row.media_url, row.filename or "file.pdf")
			else:
				ok = send_text(row.to_number, row.body or "", row.sender)
		except Exception as e:
			ok = False
			frappe.log_error(f"Resend of {row.name} failed: {e}", "Cosmetics POS")
		finally:
			frappe.local.cosmestics_outbox_replaying = False

		frappe.db.set_value(
			"Cosmestics Outbound Message",
			row.name,
			{
				"status": "Sent" if ok else "Failed",
				"attempts": cint(frappe.db.get_value("Cosmestics Outbound Message", row.name, "attempts")) + 1,
				"sent_at": frappe.utils.now() if ok else None,
				"last_error": None if ok else _("still not going through"),
			},
			update_modified=False,
		)
		(sent if ok else failed).append(row.name)

	message = _("{0} sent").format(len(sent))
	if failed:
		message += _(", {0} still failing").format(len(failed))

	return {"sent": sent, "failed": failed, "message": message}


@frappe.whitelist(methods=["POST"])
def resend_day(date: str | None = None) -> dict:
	"""Everything that did not go out on one day.

	Perishable notices are left out — see `PERISHABLE`. They are still in the
	list and can be sent one at a time if the shop wants them.
	"""
	listing = list_messages(from_date=date, to_date=date)
	names = [r["name"] for r in listing["rows"] if r["status"] != "Sent" and not r["stale"]]
	if not names:
		return {"sent": [], "failed": [], "message": _("Nothing left to send for {0}").format(listing["from_date"])}
	return resend(names)
