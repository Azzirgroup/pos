"""Turn product photos on for shops installed before they were the default.

The till has drawn item photos for a while, behind `show_item_images`, which
shipped **off**. That was the wrong default: staff recognise packaging faster
than a product name, and a setting nobody knows exists is a feature nobody has.
The DocType default is now 1, which only changes what a *fresh* install gets —
an existing site keeps the 0 written into its Singles table on the day it was
installed, and would go on showing a grid of names for ever.

## Why this is a patch and not a line in `setup_prerequisites`

`after_migrate` runs on every migrate. Enabling this there would mean a shop
that deliberately turned photos off — the shop with no photos loaded, for whom
the setting genuinely earns its keep — gets them switched back on at the next
deploy, repeatedly, with nothing on screen explaining why. A patch runs once
and then never again, so their choice sticks.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Cosmestics POS Settings"):
		return

	settings = frappe.get_single("Cosmestics POS Settings")
	if not settings.meta.has_field("show_item_images"):
		return
	if settings.show_item_images:
		return

	settings.show_item_images = 1
	settings.save(ignore_permissions=True)
