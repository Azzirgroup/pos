"""/shop/orders/<name> — tracking one order. Rendered by the shop app (frontend/shop/pages/OrderPage.vue).

The server only provides the page shell; the customer's data is fetched by
the app with their shop session. Never indexed.
"""

import frappe

from cosmestics import shop

no_cache = 1
sitemap = 0


def get_context(context):
	shop.base_context(context, title="Track your order", noindex=True)
	context.tab = "account"
	context.order_name = (frappe.form_dict.order or "")[:140]
	return context
