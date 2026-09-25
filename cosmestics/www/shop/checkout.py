"""/shop/checkout — checkout: delivery or pickup, then M-Pesa. Rendered by the shop app (frontend/shop/pages/CheckoutPage.vue).

The server only provides the page shell; the customer's data is fetched by
the app with their shop session. Never indexed.
"""

import frappe

from cosmestics import shop

no_cache = 1
sitemap = 0


def get_context(context):
	shop.base_context(context, title="Checkout", noindex=True)
	context.tab = ""
	return context
