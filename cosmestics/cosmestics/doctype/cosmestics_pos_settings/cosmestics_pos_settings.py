import frappe
from frappe import _
from frappe.model.document import Document


class CosmesticsPOSSettings(Document):
	def validate(self):
		self.validate_group_jid()

	def validate_group_jid(self):
		"""A group JID is not a phone number — catching this here saves a long
		debugging session when messages silently go nowhere."""
		if not self.notify_material_request or not self.whatsapp_group_jid:
			return

		jid = self.whatsapp_group_jid.strip()
		if not jid.endswith("@g.us"):
			frappe.throw(
				_(
					"Staff Group JID must be a WhatsApp group ID ending in <b>@g.us</b>, "
					"not a phone number. You can read it from the group in the WhatsApp bridge."
				)
			)
		self.whatsapp_group_jid = jid
