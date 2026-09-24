"""The public shop's view of the catalog.

Everything the `/shop` pages show comes from one snapshot, built here and held
in Redis for `SNAPSHOT_TTL` seconds. The pages are server-rendered — a search
engine reads the HTML it is sent and a phone on a slow connection gets a page
without waiting on a script — so every request needs the whole catalog to hand,
and rebuilding it per request would be ~2,000 items of queries each time.

**Same numbers as the till.** Prices come from the till's price list
(`Cosmestics POS Settings.selling_price_list`) through `catalog._prices`, the
same function the till reads, so a customer never sees a price the counter
would not charge. Stock is the Bin for one warehouse — see `shop_warehouse`.

**What is listed.** A sellable, enabled item with a price *and a photo whose
file is actually on this site* (`_image_ok`), not flagged
`cosmestics_hide_online`. A category appears only if something in it is listed. A variant (`variant_of`) is never a card of its own:
its template is, and the variants become the shade / size choices on the
product page. An item with no price is left out rather than shown at KES 0.

**Categories are merged on the way out, not in the data.** The shop's Item
Groups carry the history of whoever typed them — `Toners` and `TONER`,
`body  tube` and `Body Tubes` — and a customer should see one category, not
two. `_category_key` folds case, spacing and a trailing plural; the label is the
spelling most items use. Nothing is renamed in ERPNext.
"""

import hashlib
import re
import time
from urllib.parse import quote, urlencode

import frappe
from frappe.utils import add_days, cint, flt, fmt_money, get_url, nowdate

SNAPSHOT_KEY = "cosmestics:shop:snapshot"
#: How old a snapshot may be before it is refreshed. Short enough that a sale
#: at the counter shows up online within a couple of minutes.
SNAPSHOT_TTL = 120
#: How long Redis keeps a snapshot at all. Far longer than the TTL on purpose:
#: a stale snapshot is served while a fresh one is built in the background,
#: so no visitor ever waits the ~0.75s a rebuild takes.
SNAPSHOT_KEEP = 24 * 60 * 60

PAGE_SIZE = 24
#: How far back "Best sellers" looks.
BEST_SELLER_DAYS = 90

SORTS = {
	"popular": "Most popular",
	"new": "Newest",
	"price_asc": "Price: low to high",
	"price_desc": "Price: high to low",
	"name": "Name",
}

HIDE_FIELD = "cosmestics_hide_online"


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def snapshot() -> dict:
	"""The cached catalog, served stale-while-revalidate.

	A snapshot younger than `SNAPSHOT_TTL` is simply returned. An older one is
	*still* returned, and a rebuild is queued for the background worker, so the
	visitor who happens to arrive when it expires does not pay for the rebuild.
	The scheduler refreshes it every two minutes as well (`refresh_snapshot` in
	hooks), so on a running site the stale path is rare. Only a site with no
	snapshot at all — first request after a deploy or a cache flush — builds
	one inline.

	Memoised per request, so a page that asks several times reads Redis once.
	"""
	local = getattr(frappe.local, "cosmestics_shop_snapshot", None)
	if local:
		return local

	data = frappe.cache.get_value(SNAPSHOT_KEY)
	if not data:
		data = refresh_snapshot()
	elif time.time() - data.get("built_ts", 0) > SNAPSHOT_TTL:
		# A page view never commits, so this one is queued straight away.
		_queue_refresh(after_commit=False)

	frappe.local.cosmestics_shop_snapshot = data
	return data


def refresh_snapshot() -> dict:
	"""Build the catalog now and store it. The scheduler's two-minute job."""
	data = _build()
	data["built_ts"] = time.time()
	frappe.cache.set_value(SNAPSHOT_KEY, data, expires_in_sec=SNAPSHOT_KEEP)
	return data


def refresh_later(*args, **kwargs):
	"""Wired to Item and Item Price saves: rebuild in the background once the
	save commits, so the job reads the change that asked for it. A new price
	shows within seconds, and the old one is served until then."""
	_queue_refresh(after_commit=True)


def _queue_refresh(after_commit: bool):
	"""Queue one background rebuild. Deduplicated, so a burst of saves or of
	visitors on a stale snapshot queues a single job."""
	try:
		frappe.enqueue(
			"cosmestics.shop.refresh_snapshot",
			queue="short",
			job_id="cosmestics-shop-snapshot",
			deduplicate=True,
			enqueue_after_commit=after_commit,
		)
	except Exception:
		# No queue to hand it to (e.g. Redis down): drop the stale copy, and
		# the next page view rebuilds it inline instead.
		frappe.cache.delete_value(SNAPSHOT_KEY)


def clear_snapshot(*args, **kwargs):
	"""Drop the cached catalog outright; the next page view rebuilds it."""
	frappe.cache.delete_value(SNAPSHOT_KEY)
	frappe.local.cosmestics_shop_snapshot = None
	frappe.local.cosmestics_shop_settings = None


def shop_settings() -> frappe._dict:
	"""The shop's settings, read once per request — every product card asks."""
	cached = getattr(frappe.local, "cosmestics_shop_settings", None)
	if cached:
		return cached
	frappe.local.cosmestics_shop_settings = _read_settings()
	return frappe.local.cosmestics_shop_settings


def _read_settings() -> frappe._dict:
	s = frappe.get_cached_doc("Cosmestics POS Settings")
	phone = (s.get("shop_phone") or "").strip()
	return frappe._dict(
		name=frappe.defaults.get_global_default("company") or "Our Shop",
		tagline=s.get("shop_tagline") or "",
		subtitle=s.get("shop_subtitle") or "",
		whatsapp=_international(s.get("shop_whatsapp")),
		phone=("+" + _international(phone)) if phone else "",
		phone_display=phone,
		email=(s.get("shop_email") or "").strip(),
		facebook=(s.get("shop_facebook") or "").strip(),
		instagram=(s.get("shop_instagram") or "").strip(),
		brand_color=_colour(s.get("shop_brand_color")),
		address=(s.get("shop_address") or "").strip() or _company_address(),
		hours=(s.get("shop_hours") or "").strip(),
		payments=_payments(s),
		low_stock=cint(s.get("shop_low_stock")) or 3,
		price_list=s.selling_price_list
		or frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name"),
	)


def _company_address() -> str:
	"""The company's own address from ERPNext, one line, as the footer fallback."""
	company = frappe.defaults.get_global_default("company")
	if not company:
		return ""
	rows = frappe.db.sql(
		"""
		select a.address_line1, a.address_line2, a.city
		from `tabAddress` a
		join `tabDynamic Link` d on d.parent = a.name and d.parenttype = 'Address'
		where d.link_doctype = 'Company' and d.link_name = %s and a.disabled = 0
		order by a.is_your_company_address desc, a.is_primary_address desc
		limit 1
		""",
		company,
		as_dict=True,
	)
	if not rows:
		return ""
	return ", ".join(p for p in (rows[0].address_line1, rows[0].address_line2, rows[0].city) if p)


def _payments(s) -> list:
	"""How customers can pay, from the tenders the till is set up for — so the
	footer never promises a payment method the counter cannot take."""
	out = []
	if any(s.get(f) for f in ("mode_mpesa", "mode_mpesa_send", "mode_mpesa_paybill")):
		out.append(("mpesa", "M-Pesa"))
	if s.get("mode_cash"):
		out.append(("cash", "Cash"))
	if s.get("mode_card"):
		out.append(("card", "Card"))
	return out


def _international(number) -> str:
	"""`0715 718 776` → `254715718776`, the form wa.me and tel: links need."""
	digits = re.sub(r"\D", "", number or "")
	return "254" + digits[1:] if digits.startswith("0") else digits


def _colour(value) -> str:
	"""A #hex colour or nothing. It goes into a <style> block, so anything
	that is not strictly a hex colour is dropped rather than escaped."""
	value = (value or "").strip()
	return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else ""


def shop_warehouse() -> str | None:
	"""Where the stock badge counts from.

	The shop's own setting first. Failing that, the warehouse of the one
	enabled POS Profile — the counter online orders will be packed at — and
	then the till's fallback. Deliberately not `pos.selling_warehouse`: that
	starts from the signed-in user's open shift, and a shopper has neither.

	None means "count every warehouse", which is right for a one-store shop
	that never configured any of this.
	"""
	s = frappe.get_cached_doc("Cosmestics POS Settings")
	if s.get("shop_warehouse"):
		return s.shop_warehouse

	profiles = frappe.get_all("POS Profile", filters={"disabled": 0}, pluck="warehouse", limit=2)
	if len(profiles) == 1 and profiles[0]:
		return profiles[0]

	return s.default_source_warehouse or None


def _build() -> dict:
	from cosmestics.api.catalog import _prices

	settings = shop_settings()
	warehouse = shop_warehouse()

	fields = [
		"name",
		"item_name",
		"item_group",
		"image",
		"has_variants",
		"variant_of",
		"stock_uom",
		"creation",
	]
	has_hide = frappe.db.has_column("Item", HIDE_FIELD)
	if has_hide:
		fields.append(HIDE_FIELD)

	items = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1},
		fields=fields,
		limit_page_length=0,
	)
	if has_hide:
		items = [i for i in items if not i.get(HIDE_FIELD)]

	codes = [i.name for i in items]
	prices = _prices(codes, settings.price_list) if codes else {}
	stock = _stock(codes, warehouse)
	sold = _sold(codes)
	attrs = _variant_attributes(codes)
	currency = (
		frappe.db.get_value("Price List", settings.price_list, "currency") if settings.price_list else None
	) or frappe.defaults.get_global_default("currency")

	products = {}
	for it in items:
		price = flt(prices.get((it.name, it.stock_uom)) or prices.get((it.name, None)))
		products[it.name] = {
			"code": it.name,
			"name": display_name(it.item_name or it.name),
			"group": it.item_group or "",
			"image": (it.image or "").strip(),
			"price": price,
			"qty": flt(stock.get(it.name)),
			"sold": flt(sold.get(it.name)),
			"template": it.variant_of or None,
			"has_variants": bool(it.has_variants),
			"attrs": attrs.get(it.name, []),
			"created": str(it.creation),
		}

	# Variants roll up into their template: it is the card, they are its choices.
	families = {}
	for p in products.values():
		if p["template"] and p["template"] in products and p["price"] > 0:
			families.setdefault(p["template"], []).append(p["code"])

	for code, members in families.items():
		t = products[code]
		kids = [products[m] for m in members]
		t["price"] = min(k["price"] for k in kids)
		t["price_max"] = max(k["price"] for k in kids)
		t["qty"] = sum(max(k["qty"], 0) for k in kids)
		t["sold"] += sum(k["sold"] for k in kids)
		if not t["image"]:
			t["image"] = next((k["image"] for k in kids if k["image"]), "")
		t["variants"] = sorted(members, key=lambda m: [a[1] for a in products[m]["attrs"]])

	# What gets a card. A template without a priced variant cannot be bought.
	listed = []
	for p in products.values():
		if p["template"]:
			continue
		if p["has_variants"] and p["code"] not in families:
			continue
		if not p["has_variants"] and p["price"] <= 0:
			continue
		# A shop window of "No image" placeholders reads as a broken site, so
		# an item is only shown once its photo really exists.
		if not _image_ok(p["image"]):
			continue
		listed.append(p["code"])

	# Variants of a listed template stay reachable even though they have no card.
	live = set(listed)
	for code in listed:
		live.update(products[code].get("variants", []))
	products = {c: p for c, p in products.items() if c in live}

	categories = _categories(products, listed)
	_assign_slugs(products)

	return {
		"products": products,
		"listed": listed,
		"categories": categories,
		"slugs": {p["slug"]: c for c, p in products.items()} | {p["hslug"]: c for c, p in products.items()},
		"currency": currency,
		"warehouse": warehouse,
		"low_stock": settings.low_stock,
		"built": frappe.utils.now(),
	}


def _image_ok(url: str) -> bool:
	"""Whether `url` is a photo a visitor can actually load.

	An uploaded file is checked on disk: this site's data came from another
	server, and `Item.image` can name a file that never came with it. Private
	files are refused — they need a signed-in session. An absolute URL is
	trusted; there is no cheap way to check it here.
	"""
	import os
	from urllib.parse import unquote

	url = (url or "").split("?")[0]
	if url.startswith(("http://", "https://")):
		return True
	if not url.startswith("/files/"):
		return False
	name = unquote(url[len("/files/") :])
	return bool(name) and "/" not in name and os.path.isfile(frappe.get_site_path("public", "files", name))


def _stock(codes, warehouse) -> dict:
	if not codes:
		return {}
	filters = {"item_code": ("in", codes)}
	if warehouse:
		filters["warehouse"] = warehouse
	out = {}
	for r in frappe.get_all(
		"Bin", filters=filters, fields=["item_code", "actual_qty"], limit_page_length=0
	):
		out[r.item_code] = out.get(r.item_code, 0) + flt(r.actual_qty)
	return out


def _sold(codes) -> dict:
	"""Units sold over the last `BEST_SELLER_DAYS`, which is what "popular"
	means — the shop's own till, not a guess."""
	if not codes:
		return {}
	rows = frappe.db.sql(
		"""
		select sii.item_code, sum(sii.stock_qty) as qty
		from `tabSales Invoice Item` sii
		join `tabSales Invoice` si on si.name = sii.parent
		where si.docstatus = 1 and si.is_return = 0 and si.posting_date >= %s
		group by sii.item_code
		""",
		add_days(nowdate(), -BEST_SELLER_DAYS),
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}


def _variant_attributes(codes) -> dict:
	"""{item: [(attribute, value), …]} in the template's attribute order."""
	if not codes:
		return {}
	rows = frappe.get_all(
		"Item Variant Attribute",
		filters={"parenttype": "Item", "parent": ("in", codes), "attribute_value": ("is", "set")},
		fields=["parent", "attribute", "attribute_value"],
		order_by="idx asc",
		limit_page_length=0,
	)
	out = {}
	for r in rows:
		out.setdefault(r.parent, []).append((r.attribute, r.attribute_value))
	return out


def _category_key(group: str) -> str:
	key = re.sub(r"[^a-z0-9]", "", (group or "").lower())
	return key[:-1] if len(key) > 3 and key.endswith("s") else key


def _categories(products, listed) -> list:
	"""Merged categories, busiest first: [{key, slug, label, count, groups}]."""
	merged = {}
	for code in listed:
		p = products[code]
		key = _category_key(p["group"])
		if not key:
			continue
		p["cat"] = key
		c = merged.setdefault(key, {"key": key, "count": 0, "spellings": {}})
		c["count"] += 1
		c["spellings"][p["group"]] = c["spellings"].get(p["group"], 0) + 1

	# Variants belong to their template's category.
	for p in products.values():
		if p["template"] and p["template"] in products:
			p["cat"] = products[p["template"]].get("cat")

	out = []
	for c in merged.values():
		spelling = max(c["spellings"].items(), key=lambda kv: (kv[1], kv[0]))[0]
		label = display_name(spelling)
		out.append(
			{
				"key": c["key"],
				"label": label,
				"slug": slugify(label) or c["key"],
				"count": c["count"],
				"groups": sorted(c["spellings"]),
			}
		)
	out.sort(key=lambda c: (-c["count"], c["label"]))
	return out


# ---------------------------------------------------------------------------
# Names and URLs
# ---------------------------------------------------------------------------

_UNIT = re.compile(r"^\d+(\.\d+)?(ml|l|ltr|g|gm|gms|kg|mg|oz|pcs|s)$", re.I)
_SMALL = {"and", "of", "with", "for", "the", "in", "on", "a", "to", "or"}


def display_name(raw: str) -> str:
	"""An item name fit for a shop window.

	Names typed at a counter are all capitals (`1L BODY SERUM`) or all lower
	case (`bio oil`) about as often as they are written properly. Only those two
	cases are touched — a name somebody took the trouble to case by hand is
	theirs — and sizes are left readable (`80ml`, not `80Ml`).
	"""
	name = re.sub(r"\s+", " ", (raw or "").strip())
	letters = [ch for ch in name if ch.isalpha()]
	if not letters:
		return name
	if not (all(ch.isupper() for ch in letters) or all(ch.islower() for ch in letters)):
		return name

	words = []
	for i, word in enumerate(name.split(" ")):
		if _UNIT.match(word):
			words.append(word.lower())
		elif any(ch.isdigit() for ch in word):
			words.append(word)
		elif i and word.lower() in _SMALL:
			words.append(word.lower())
		else:
			words.append(_capitalise(word))
	return " ".join(words)


def _capitalise(word: str) -> str:
	"""`(ALOE` → `(Aloe`: the first letter up, the rest down, punctuation kept."""
	lowered = word.lower()
	for i, ch in enumerate(lowered):
		if ch.isalpha():
			return lowered[:i] + ch.upper() + lowered[i + 1 :]
	return lowered


def slugify(text: str) -> str:
	text = (text or "").lower().replace("&", " and ")
	return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:80].strip("-")


def _code_hash(code: str) -> str:
	return hashlib.md5(code.encode()).hexdigest()[:6]


def _assign_slugs(products):
	"""A readable slug where the name is unique, and a hashed one always.

	`perley-gleam-cream` is what gets linked. When two items share a name —
	this shop has several — both get the hashed form, `bio-oil-3fa2c1`, which
	is built from the item code and so never changes. The hashed slug of every
	item resolves forever, which is what lets `product.py` redirect an old link
	after a rename.
	"""
	seen = {}
	for p in products.values():
		p["hslug"] = f"{slugify(p['name']) or 'item'}-{_code_hash(p['code'])}"
		seen.setdefault(slugify(p["name"]), []).append(p)
	for base, group in seen.items():
		for p in group:
			p["slug"] = base if base and len(group) == 1 else p["hslug"]


def resolve_slug(slug: str) -> tuple[str | None, bool]:
	"""(item code, is the canonical slug). A hashed slug for an item whose
	readable one is canonical still resolves, and the caller redirects."""
	snap = snapshot()
	code = snap["slugs"].get(slug)
	if code:
		return code, snap["products"][code]["slug"] == slug

	# A renamed item: the hash suffix still identifies it.
	m = re.search(r"-([0-9a-f]{6})$", slug or "")
	if m:
		for c, p in snap["products"].items():
			if p["hslug"].endswith(m.group(0)):
				return c, False
	return None, False


def product_url(p) -> str:
	return f"/shop/p/{p['slug']}"


def category_url(c) -> str:
	return f"/shop/c/{c['slug']}"


def listing_url(path, *, q=None, sort="popular", stock=0, page=1, min=None, max=None, view="grid") -> str:
	"""A listing URL carrying only what differs from the defaults, so the
	plain category link and page one of it are the same URL."""
	params = {}
	if q:
		params["q"] = q
	if sort and sort != "popular":
		params["sort"] = sort
	if cint(stock):
		params["stock"] = 1
	if min:
		params["min"] = cint(min)
	if max:
		params["max"] = cint(max)
	if view == "list":
		params["view"] = "list"
	if cint(page) > 1:
		params["page"] = cint(page)
	return path + (f"?{urlencode(params)}" if params else "")


def absolute(path: str) -> str:
	if not path:
		return ""
	if path.startswith(("http://", "https://")):
		return path
	return get_url(quote(path, safe="/?=&%:"))


# ---------------------------------------------------------------------------
# What the templates read
# ---------------------------------------------------------------------------


def card(p) -> dict:
	"""Everything a product card needs, and nothing it does not."""
	snap = snapshot()
	status = stock_status(p["qty"])
	price = money(p["price"])
	if p.get("price_max") and p["price_max"] > p["price"]:
		price = f"From {price}"
	return {
		"code": p["code"],
		"name": p["name"],
		"url": product_url(p),
		"image": p["image"],
		"price": price,
		"status": status,
		"category": _category_label(p.get("cat")),
		"initials": _initials(p["name"]),
		"tint": int(_code_hash(p.get("cat") or p["code"]), 16) % 6,
		"currency": snap["currency"],
		"order_url": whatsapp_link(p, absolute(product_url(p))) if not p.get("variants") else "",
		"has_choices": bool(p.get("variants")),
	}


def stock_status(qty) -> dict:
	low = snapshot()["low_stock"]
	if qty <= 0:
		return {"key": "out", "label": "Out of stock"}
	if qty <= low:
		return {"key": "low", "label": "Only a few left"}
	return {"key": "in", "label": "In stock"}


def money(amount) -> str:
	"""`KES 1,250`. The currency code rather than Frappe's symbol for it —
	KES renders as `Sh`, which is not how a Kenyan price tag reads."""
	currency = snapshot()["currency"] or ""
	return f"{currency} {fmt_money(amount, precision=0)}".strip()


def categories() -> list:
	return snapshot()["categories"]


def category_by_slug(slug: str) -> dict | None:
	return next((c for c in categories() if c["slug"] == slug), None)


def _category_label(key) -> str:
	return next((c["label"] for c in categories() if c["key"] == key), "")


def _initials(name: str) -> str:
	words = [w for w in re.split(r"[^A-Za-z]+", name) if w]
	return "".join(w[0] for w in words[:2]).upper() or "•"


def sort_products(codes, sort="popular") -> list:
	"""Out of stock always sinks — a customer browsing wants what they can buy
	— and the default order also floats items with a photo above ones without."""
	products = snapshot()["products"]
	ps = [products[c] for c in codes]
	avail = lambda p: 0 if p["qty"] > 0 else 1  # noqa: E731

	if sort == "price_asc":
		key = lambda p: (avail(p), p["price"], p["name"].lower())  # noqa: E731
	elif sort == "price_desc":
		key = lambda p: (avail(p), -p["price"], p["name"].lower())  # noqa: E731
	elif sort == "new":
		ps.sort(key=lambda p: p["created"], reverse=True)
		key = lambda p: avail(p)  # noqa: E731
	elif sort == "name":
		key = lambda p: (avail(p), p["name"].lower())  # noqa: E731
	else:
		key = lambda p: (avail(p), -p["sold"], 0 if p["image"] else 1, p["name"].lower())  # noqa: E731
	ps.sort(key=key)
	return ps


def in_category(key: str) -> list:
	snap = snapshot()
	return [c for c in snap["listed"] if snap["products"][c].get("cat") == key]


def paginate(items, page, url_for) -> dict:
	"""One page of `items`. `url_for(n)` builds the link to page n."""
	pages = max(1, -(-len(items) // PAGE_SIZE))
	page = min(max(cint(page) or 1, 1), pages)
	start = (page - 1) * PAGE_SIZE
	return frappe._dict(
		items=items[start : start + PAGE_SIZE],
		page=page,
		pages=pages,
		total=len(items),
		first=start + 1 if items else 0,
		last=min(start + PAGE_SIZE, len(items)),
		prev_url=url_for(page - 1) if page > 1 else "",
		next_url=url_for(page + 1) if page < pages else "",
		first_url=url_for(1),
		last_url=url_for(pages),
		numbers=[
			{"n": n, "url": url_for(n), "current": n == page} if n else None
			for n in _page_window(page, pages)
		],
	)


def _page_window(page, pages) -> list:
	"""[1, None, 6, 7, 8, None, 85] — the numbers either side of the current
	page and both ends, `None` for a gap. A category of 85 pages cannot list
	every number the way a shop of forty products can."""
	keep = {1, pages, page - 1, page, page + 1}
	out, last = [], 0
	for n in sorted(k for k in keep if 1 <= k <= pages):
		if n - last > 1:
			out.append(None)
		out.append(n)
		last = n
	return out


def search(q: str) -> list:
	"""Every listed product matching all the words typed, best match first.

	In memory over the snapshot: the catalog is a few thousand rows, and a
	query per word per request against `tabItem` would be slower and harder to
	rank. A barcode matches too, so a code read off a bottle finds it.
	"""
	tokens = [t for t in re.split(r"[^a-z0-9]+", (q or "").lower()) if t]
	if not tokens:
		return []

	snap = snapshot()
	products = snap["products"]
	labels = {c["key"]: c["label"] for c in snap["categories"]}
	barcodes = _barcodes_by_item()

	scored = []
	for code in snap["listed"]:
		p = products[code]
		family = [p] + [products[v] for v in p.get("variants", []) if v in products]
		hay = " ".join(
			[f.get("name", "") for f in family]
			+ [a[1] for f in family for a in f["attrs"]]
			+ [labels.get(p.get("cat"), ""), code]
			+ [b for f in family for b in barcodes.get(f["code"], [])]
		).lower()
		if not all(t in hay for t in tokens):
			continue
		name = p["name"].lower()
		score = 0
		if name.startswith(tokens[0]):
			score += 3
		score += sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}", name))
		score += 1 if p["qty"] > 0 else 0
		scored.append((-score, -p["sold"], name, code))

	scored.sort()
	return [s[3] for s in scored]


def _barcodes_by_item() -> dict:
	def load():
		out = {}
		for r in frappe.get_all(
			"Item Barcode", filters={"parenttype": "Item"}, fields=["parent", "barcode"], limit_page_length=0
		):
			out.setdefault(r.parent, []).append(r.barcode)
		return out

	key = "cosmestics:shop:barcodes"
	out = frappe.cache.get_value(key)
	if out is None:
		out = load()
		frappe.cache.set_value(key, out, expires_in_sec=SNAPSHOT_TTL)
	return out


def best_sellers(limit=12) -> list:
	snap = snapshot()
	ps = [snap["products"][c] for c in snap["listed"]]
	ps = [p for p in ps if p["qty"] > 0 and p["sold"] > 0]
	ps.sort(key=lambda p: (0 if p["image"] else 1, -p["sold"]))
	return ps[:limit]


def new_arrivals(limit=12) -> list:
	"""Newest in-stock items, the ones with a photo first."""
	snap = snapshot()
	ps = [snap["products"][c] for c in snap["listed"]]
	ps = [p for p in ps if p["qty"] > 0]
	ps.sort(key=lambda p: p["created"], reverse=True)
	ps.sort(key=lambda p: 0 if p["image"] else 1)
	return ps[:limit]


def category_image(key: str) -> str:
	"""A category's picture: the photo of its best seller."""
	codes = in_category(key)
	return next((p["image"] for p in sort_products(codes) if p["image"]), "")


def hero_products(limit=6) -> list:
	"""The products scattered across the front page's hero.

	Best sellers in stock, one per category so the hero is not six pots of the
	same cream, and only photos shot on a plain white background: the hero
	blends that white into its own colour so each product stands on it like a
	cut-out, and a photo of a bottle on a kitchen table would show as a
	rectangle instead. Falls back to any photo if too few are white.
	"""
	pool = best_sellers(limit=60) + new_arrivals(limit=60)
	out, seen = [], set()
	for strict in (True, False):
		for p in pool:
			if len(out) == limit:
				return out
			if p["code"] in {o["code"] for o in out} or p.get("cat") in seen or not p["image"]:
				continue
			if strict and not white_backdrop(p["image"]):
				continue
			seen.add(p.get("cat"))
			out.append(p)
		if len(out) >= 4:
			break
	return out


#: Redis hash of photo path|mtime → shot on white. Renamed when the test changes.
WHITE_KEY = "cosmestics:shop:whitebg:v2"


def white_backdrop(url: str) -> bool:
	"""Whether a product photo was shot on (near) white — its border pixels.

	Answered once per file and version: the result is kept in Redis keyed by
	path and modified time, so a replaced photo is looked at again.
	"""
	import os
	from urllib.parse import unquote

	path = unquote((url or "").split("?")[0])
	if not path.startswith("/files/"):
		return False
	full = frappe.get_site_path("public", "files", path[len("/files/") :])
	try:
		key = f"{path}|{int(os.path.getmtime(full))}"
	except OSError:
		return False

	known = frappe.cache.hget(WHITE_KEY, key)
	if known is not None:
		return bool(known)

	answer = False
	try:
		from PIL import Image

		with Image.open(full) as im:
			im = im.convert("RGB")
			im.thumbnail((64, 64))
			w, h = im.size
			px = im.load()
			edge = [px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)]
			edge += [px[0, y] for y in range(h)] + [px[w - 1, y] for y in range(h)]
			# Near-pure white only: a light grey studio backdrop multiplies into
			# a visible grey box on the hero, so it does not count.
			white = sum(1 for r, g, b in edge if min(r, g, b) >= 246)
			answer = white >= 0.9 * len(edge)
	except Exception:
		answer = False

	frappe.cache.hset(WHITE_KEY, key, 1 if answer else 0)
	return answer


def related(p, limit=8) -> list:
	base = products_family_root(p)
	codes = [c for c in in_category(base.get("cat")) if c != base["code"]]
	return [x for x in sort_products(codes) if x["qty"] > 0][:limit]


def products_family_root(p) -> dict:
	products = snapshot()["products"]
	return products.get(p["template"]) if p.get("template") in products else p


def choices(p) -> list:
	"""The shade / size pickers for a product in a variant family.

	[{attribute, options: [{value, url, selected, available}]}]. Each option
	links to the variant that keeps every *other* choice as it is and changes
	this one — so picking a size keeps the shade — falling back to any variant
	with that value when that exact combination does not exist. Plain links:
	they work without JavaScript and each variant is its own crawlable page.
	"""
	products = snapshot()["products"]
	root = products_family_root(p)
	members = [products[v] for v in root.get("variants", []) if v in products]
	if not members:
		return []

	current = dict(p["attrs"]) if p is not root else {}
	order = []
	for m in members:
		for attr, _v in m["attrs"]:
			if attr not in order:
				order.append(attr)

	out = []
	for attr in order:
		values = []
		for m in members:
			v = dict(m["attrs"]).get(attr)
			if v and v not in values:
				values.append(v)
		options = []
		for v in values:
			want = {**current, attr: v}
			exact = [m for m in members if dict(m["attrs"]) == want]
			# In stock first, then whichever shares the most of the current choices.
			loose = sorted(
				(m for m in members if dict(m["attrs"]).get(attr) == v),
				key=lambda m: (
					0 if m["qty"] > 0 else 1,
					-sum(dict(m["attrs"]).get(a) == current.get(a) for a in current),
				),
			)
			target = (exact or loose)[0]
			options.append(
				{
					"value": v,
					"url": product_url(target),
					"selected": current.get(attr) == v,
					"available": any(m["qty"] > 0 for m in members if dict(m["attrs"]).get(attr) == v),
				}
			)
		out.append({"attribute": attr, "options": options})
	return out


def description(code: str) -> str:
	"""The item's description, cleaned for a public page.

	Staff write it in the desk's editor; it is still shown through
	`clean_html`, because a pasted supplier blurb can carry markup that has no
	place on the storefront.
	"""
	from frappe.utils.html_utils import clean_html

	raw = frappe.db.get_value("Item", code, "description") or ""
	text = frappe.utils.strip_html(raw).strip()
	# ERPNext fills an empty description with the item name — that is not a
	# description, it is the title said twice.
	if not text or text.lower() == (frappe.db.get_value("Item", code, "item_name") or "").strip().lower():
		return ""
	return clean_html(raw)


def whatsapp_link(p, url: str) -> str:
	text = f"Hello, I'd like to order: {p['name']} ({money(p['price'])})\n{url}"
	return chat_link(text)


def chat_link(text="Hi, I'd like to know more about your products") -> str:
	number = shop_settings().whatsapp
	return f"https://wa.me/{number}?{urlencode({'text': text})}" if number else ""


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

#: The shop has sixty-odd flat Item Groups. The sidebar and the phone's
#: category browser group them under a handful of headings, matched on the
#: category name in this order — the first keyword that appears wins, so
#: "Face Cream" is Face before "cream" can make it Body, and "shaving spray"
#: is Body before "spray" can make it Fragrance. Anything unmatched is "More".
DEPARTMENTS = (
	("Face & Makeup", ("face", "lip", "eye", "mascara", "foundation", "toner", "mask", "lipstick")),
	("Hair", ("hair", "shampoo", "conditioner", "henna", "relaxer", "wig")),
	("Body & Bath", ("shav", "wax")),
	("Fragrance", ("perfume", "mist", "spray", "splash", "roll on", "cologne", "deodorant")),
	("Wellness", ("gumm", "tablet", "capsule", "vitamin", "collagen", "powder", "tea", "coffee")),
	(
		"Body & Bath",
		(
			"body", "shower", "soap", "lotion", "cream", "oil", "scrub", "vaseline",
			"gel", "wash", "sunscreen", "hand", "aloe", "rose water", "tooth",
		),
	),
)
DEPARTMENT_ORDER = ("Body & Bath", "Face & Makeup", "Hair", "Fragrance", "Wellness", "More")


def departments() -> list:
	"""[{name, slug, categories: [...]}] in `DEPARTMENT_ORDER`, empty ones left out."""
	groups = {name: [] for name in DEPARTMENT_ORDER}
	for c in categories():
		label = c["label"].lower()
		dept = next(
			(name for name, words in DEPARTMENTS if any(w in label for w in words)),
			"More",
		)
		groups[dept].append(c)
	return [
		{"name": name, "slug": slugify(name), "categories": groups[name]}
		for name in DEPARTMENT_ORDER
		if groups[name]
	]


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

#: Lucide outlines (stroke) and brand marks (fill), inlined so the shop needs
#: no icon font or script. Rendered through `icon()`.
_STROKE = {
	"search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
	"phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
	"mail": '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
	"shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
	"headset": '<path d="M3 11h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5Zm0 0a9 9 0 1 1 18 0m0 0v5a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3Z"/><path d="M21 16v2a4 4 0 0 1-4 4h-5"/>',
	"truck": '<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>',
	"percent": '<path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/><path d="m15 9-6 6"/><path d="M9 9h.01"/><path d="M15 15h.01"/>',
	"left": '<path d="m15 18-6-6 6-6"/>',
	"right": '<path d="m9 18 6-6-6-6"/>',
	"first": '<path d="m11 17-5-5 5-5"/><path d="m18 17-5-5 5-5"/>',
	"last": '<path d="m6 17 5-5-5-5"/><path d="m13 17 5-5-5-5"/>',
	"home": '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
	"grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
	"store": '<path d="m2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7"/><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4"/><path d="M2 7h20"/><path d="M22 7v3a2 2 0 0 1-2 2a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 16 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 12 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 8 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 4 12a2 2 0 0 1-2-2V7"/>',
	"list": '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M8 6h13"/>',
	"sliders": '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
	"more": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
	"sparkle": '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
	"instagram": '<rect width="20" height="20" x="2" y="2" rx="5" ry="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/><line x1="17.5" x2="17.51" y1="6.5" y2="6.5"/>',
	"close": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
	"pin": '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>',
	"clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
	"up": '<path d="m18 15-6-6-6 6"/>',
	"mpesa": '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/>',
	"cash": '<rect width="20" height="12" x="2" y="6" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/>',
	"card": '<rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/>',
	"user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
	"bag": '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
	"check": '<path d="M20 6 9 17l-5-5"/>',
	"lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
	"package": '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7"/><path d="m7.5 4.27 9 5.15"/>',
	"logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
}
_FILL = {
	"whatsapp": '<path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2Zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8s-.4-.1-.6.1-.7.8-.8 1-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.3-.4.2-.4.7-1.4.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.1 5.1 0 0 0 1.1 2.7 11.7 11.7 0 0 0 4.5 4c1.7.7 2.3.8 3.2.6a2.7 2.7 0 0 0 1.8-1.2 2.2 2.2 0 0 0 .1-1.3c0-.1-.2-.2-.5-.3Z"/>',
	"facebook": '<path d="M24 12.07C24 5.41 18.63 0 12 0S0 5.4 0 12.07C0 18.1 4.39 23.1 10.13 24v-8.44H7.08v-3.49h3.04V9.41c0-3.02 1.8-4.7 4.54-4.7 1.31 0 2.68.24 2.68.24v2.97h-1.5c-1.5 0-1.96.93-1.96 1.89v2.26h3.32l-.53 3.5h-2.8V24C19.62 23.1 24 18.1 24 12.07"/>',
	"x": '<path d="M18.9 1.15h3.68l-8.04 9.19L24 22.85h-7.4l-5.8-7.58-6.64 7.58H.47l8.6-9.83L0 1.15h7.59l5.24 6.93zm-1.29 19.5h2.04L6.48 3.24H4.3z"/>',
	"linkedin": '<path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z"/>',
}


def icon(name: str, cls: str = "i") -> str:
	"""A reference into the page's sprite (`icon_sprite`), not the drawing
	itself — the home page shows the same few icons a hundred times."""
	from markupsafe import Markup

	if name not in _FILL and name not in _STROKE:
		raise KeyError(name)
	return Markup(f'<svg class="{cls}" aria-hidden="true"><use href="#i-{name}"/></svg>')


def icon_sprite() -> str:
	"""Every icon once, as <symbol>s, emitted at the top of <body>."""
	from markupsafe import Markup

	stroke = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
	parts = [f'<symbol id="i-{n}" viewBox="0 0 24 24"><g {stroke}>{d}</g></symbol>' for n, d in _STROKE.items()]
	parts += [f'<symbol id="i-{n}" viewBox="0 0 24 24"><g fill="currentColor">{d}</g></symbol>' for n, d in _FILL.items()]
	return Markup('<svg xmlns="http://www.w3.org/2000/svg" style="display:none">' + "".join(parts) + "</svg>")


def share_links(url: str, title: str) -> list:
	"""The product page's share row, in PLM's order."""
	from urllib.parse import quote_plus as q

	return [
		{"label": "Share on X", "icon": "x", "cls": "share-x",
			"href": f"https://twitter.com/intent/tweet?url={q(url)}&text={q(title)}"},
		{"label": "Share on Facebook", "icon": "facebook", "cls": "share-fb",
			"href": f"https://www.facebook.com/sharer/sharer.php?u={q(url)}"},
		{"label": "Share on LinkedIn", "icon": "linkedin", "cls": "share-in",
			"href": f"https://www.linkedin.com/sharing/share-offsite/?url={q(url)}"},
		{"label": "Share on WhatsApp", "icon": "whatsapp", "cls": "share-wa",
			"href": f"https://wa.me/?text={q(title + ' ' + url)}"},
	]


# ---------------------------------------------------------------------------
# Listings (catalog, category, search)
# ---------------------------------------------------------------------------


#: Quick price bands for the filter panel, in the shop's currency. Chosen for
#: this catalog, where almost everything sits between KES 50 and 3,000.
PRICE_BANDS = ((None, 200), (200, 500), (500, 1000), (1000, 2000), (2000, None))


def listing_context(context, *, codes, path, title, q=None, relevance=False, category=None):
	"""Everything the shared catalog layout reads: filters from the query
	string, the sorted and filtered products, one page of them, and the links
	to every other page. `relevance` keeps `codes` in the order given (search)
	for the default sort instead of popularity. `category` is the category
	being shown, if any.

	Every link the filter panel draws keeps the other filters: picking a
	category keeps the price range, picking a price band keeps "in stock".
	The counts beside each option are what that option would show given the
	*other* filters, so a band reading "0" is never offered.
	"""
	fd = frappe.form_dict
	sort = fd.sort if fd.sort in SORTS else "popular"
	stock = 1 if fd.stock else 0
	view = "list" if fd.view == "list" else "grid"
	lo, hi = cint(fd.min) or None, cint(fd.max) or None
	if lo and hi and lo > hi:
		lo, hi = hi, lo

	products = snapshot()["products"]
	if relevance and sort == "popular":
		ps = sorted((products[c] for c in codes), key=lambda p: 0 if p["qty"] > 0 else 1)
	else:
		ps = sort_products(codes, sort)
	everything = ps
	bounds = (min((p["price"] for p in ps), default=0), max((p["price"] for p in ps), default=0))

	def in_price(p, a=None, b=None):
		return (not a or p["price"] >= a) and (not b or p["price"] <= b)

	priced = [p for p in ps if in_price(p, lo, hi)]
	stocked = [p for p in ps if p["qty"] > 0]
	ps = [p for p in priced if p["qty"] > 0] if stock else priced

	def url(path_=None, **over):
		args = {"q": q, "sort": sort, "stock": stock, "min": lo, "max": hi, "view": view, "page": 1}
		args.update(over)
		return listing_url(path_ or path, **args)

	page = paginate(ps, fd.page, lambda n: url(page=n))

	# Price bands, counted against the stock filter but not the price one.
	pool = stocked if stock else everything
	bands = []
	for a, b in PRICE_BANDS:
		n = sum(1 for p in pool if in_price(p, a, b - 1 if b else None))
		if not n:
			continue
		label = f"Under {b:,}" if not a else (f"{a:,}+" if not b else f"{a:,} - {b:,}")
		hi_ = b - 1 if b else None
		bands.append({
			"label": label,
			"count": n,
			"active": (lo or None) == a and (hi or None) == hi_,
			"url": url(min=a, max=hi_),
		})

	# Categories, grouped by department, each link keeping the other filters.
	# Search stays search: from a results page they open the plain category.
	keep = {} if q else {"sort": sort, "stock": stock, "min": lo, "max": hi, "view": view}
	active_key = category["key"] if category else None
	depts = []
	for d in departments():
		cats = [
			{
				"label": c["label"],
				"count": c["count"],
				"active": c["key"] == active_key,
				"url": listing_url(category_url(c), **keep),
			}
			for c in d["categories"]
		]
		depts.append({
			"name": d["name"],
			"cats": cats,
			"count": sum(c["count"] for c in cats),
			"open": any(c["active"] for c in cats),
		})
	if depts and not any(d["open"] for d in depts):
		depts[0]["open"] = True

	# What is narrowing the list, each with a link that drops just that.
	chips = []
	if category:
		chips.append({"label": category["label"], "url": url("/shop/catalog")})
	if lo or hi:
		money_label = (
			f"{money(lo)} - {money(hi)}" if lo and hi else (f"From {money(lo)}" if lo else f"Up to {money(hi)}")
		)
		chips.append({"label": money_label, "url": url(min=None, max=None)})
	if stock:
		chips.append({"label": "In stock", "url": url(stock=0)})

	context.listing = frappe._dict(
		title=title,
		path=path,
		query=q,
		sort=sort,
		stock=stock,
		view=view,
		min=lo or "",
		max=hi or "",
		bounds=(cint(bounds[0]), cint(bounds[1])),
		filtered=bool(stock or lo or hi or category),
		grid_url=url(view="grid"),
		list_url=url(view="list"),
		clear_url=listing_url("/shop/search" if q else "/shop/catalog", q=q),
		all_url=listing_url("/shop/catalog", **keep),
		stock_url=url(stock=0 if stock else 1),
		stock_count=sum(1 for p in priced if p["qty"] > 0),
		priced_count=len(priced),
		bands=bands,
		depts=depts,
		chips=chips,
		total_all=len(everything),
		in_stock_all=len(stocked),
	)
	context.cards = [card(p) for p in page["items"]]
	context.page = page
	context.sorts = (
		{"popular": "Best match", **{k: v for k, v in SORTS.items() if k != "popular"}} if relevance else SORTS
	)
	context.rel_prev = absolute(page.prev_url) if page.prev_url else ""
	context.rel_next = absolute(page.next_url) if page.next_url else ""
	return page


@frappe.whitelist(allow_guest=True, methods=["GET"])
def suggest(q: str = "") -> list[dict]:
	"""The header search's dropdown: the first six matches as the visitor
	types. Served from the same snapshot as the pages, so it is as cheap as a
	cache read."""
	products = snapshot()["products"]
	out = []
	for code in search((q or "")[:100])[:6]:
		p = products[code]
		out.append({"name": p["name"], "url": product_url(p), "image": p["image"], "price": card(p)["price"]})
	return out


def _asset_version(name: str) -> str:
	"""`?v=<mtime>` for a built shop asset, or "" if it has not been built."""
	import os

	path = frappe.get_app_path("cosmestics", "public", "shop", name)
	return str(int(os.path.getmtime(path))) if os.path.exists(path) else ""


def base_context(context, *, title, description="", canonical="", noindex=False):
	"""The fields `templates/shop/base.html` reads, set in one place so no page
	forgets its canonical URL or its title."""
	settings = shop_settings()
	context.no_cache = 1
	context.shop = settings
	context.page_title = f"{title} · {settings.name}" if title != settings.name else title
	context.meta_description = (description or "")[:160]
	context.canonical = absolute(canonical) if canonical else ""
	context.noindex = noindex
	# As many as a wide screen can show; narrower screens scroll the bar.
	context.nav_categories = categories()[:16]
	context.footer_categories = categories()[:8]
	context.all_categories_pills = categories()
	context.footer_departments = departments()
	context.total_listed = len(snapshot()["listed"])
	context.year = nowdate()[:4]
	context.icon = icon
	context.icon_sprite = icon_sprite()
	context.shop_js = _asset_version("shop.js")
	from cosmestics.api.shop_account import google_client_id

	context.google_client_id = google_client_id()
	# A staff member signed in to the desk in the same browser makes Frappe
	# want its CSRF token on the shop's POSTs; shoppers themselves are Guest.
	context.csrf_token = (
		frappe.sessions.get_csrf_token()
		if frappe.session.user != "Guest" and getattr(frappe.local, "session_obj", None)
		else ""
	)
	context.chat_url = chat_link()
	context.shop_currency = snapshot()["currency"]
	context.filter_categories = categories()
	return context
