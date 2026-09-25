"""/shop/account — My orders and account details. Rendered by the shop app (frontend/shop/pages/AccountPage.vue).

The server only provides the page shell; the customer's data is fetched by
the app with their shop session. Never indexed.
"""

import frappe

from cosmestics import shop

no_cache = 1
sitemap = 0


def get_context(context):
	shop.base_context(context, title="My account", noindex=True)
	context.tab = "account"
	return context
