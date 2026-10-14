"""Every WhatsApp message this app tries to send, and what became of it.

Sending is best-effort by design: a notification must never fail a sale, so
`notifications.send_text` swallows the error and returns False. That is right
for the sale and wrong for the shop — when the bridge is down for a morning,
or a subscription lapses, the messages are simply gone. There was no record of
what should have gone out, which is the question somebody asks afterwards.

So each attempt is written here first and marked afterwards. The row holds
enough to send it again — the number, the body, any attachment — because an
Error Log line holds the number and the reason and not the message.

Deliberately not submittable: this is a log, not a transaction. Rows are
written by the sender and only ever re-read by `api/outbox.py`.
"""

import frappe
from frappe.model.document import Document


class CosmesticsOutboundMessage(Document):
	pass
