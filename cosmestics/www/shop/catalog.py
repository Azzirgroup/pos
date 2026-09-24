"""/shop/catalog — every listed product, with PLM's filter panel."""

import frappe

from cosmestics import shop

no_cache = 1
sitemap = 0


def get_context(context):
	snap = shop.snapshot()
	settings = shop.shop_settings()
	shop.base_context(context, title="All Products", description=(
		f"Browse all {len(snap['listed']):,} products at {settings.name}: skin, body and hair care, "
		"fragrance and wellness. Live prices and stock."
	))
	page = shop.listing_context(context, codes=snap["listed"], path="/shop/catalog", title="All Products")
	# One canonical per page of the default view; sorted or filtered views point back at it.
	context.canonical = shop.absolute(shop.listing_url("/shop/catalog", page=page.page))
	listing = context.listing
	context.noindex = bool(listing.stock or listing.min or listing.max or listing.sort != "popular" or listing.view == "list")
	context.tab = "shop"
	return context
