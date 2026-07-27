/**
 * Demo catalog derivations.
 *
 * The raw data lives in `cosmestics/data/catalog.json` — one file shared with
 * the Python installer, so the demo the cashier sees and the demo seeded into
 * a site can never drift apart. This module only derives the extra fields the
 * UI needs; it invents no data of its own.
 *
 * Shape matches what `cosmestics.api.pos.get_catalog` will return, so swapping
 * the source is a one-line change in stores/catalog.js.
 */
import catalog from '@data/catalog.json'

export const CATEGORIES = catalog.categories

/** Own branches — targets for a Material Transfer request. */
export const WAREHOUSES = catalog.warehouses

/**
 * Neighbouring shops we buy from when we are out of stock and the customer is
 * waiting. Modelled as Suppliers, not warehouses — the goods are genuinely
 * bought and resold, so they need a purchase document and a cost price.
 */
export const NEIGHBOURS = catalog.neighbours

/**
 * Deterministic hue per item. Avoids shipping product photos: swatches render
 * instantly with zero network requests, which matters far more at the till than
 * photography does. Real image_url slots in later without layout change.
 *
 * FNV-1a rather than a simple rolling hash: item codes are sequential
 * (MKP-001, MKP-002 …) and a weak hash maps them to near-identical hues, which
 * defeats the entire point — the cashier must be able to tell two shades apart
 * at a glance. FNV avalanches, so adjacent codes land far apart on the wheel.
 */
function hueFor(code) {
	let h = 2166136261
	for (let i = 0; i < code.length; i++) {
		h ^= code.charCodeAt(i)
		h = Math.imul(h, 16777619)
	}
	return Math.abs(h) % 360
}

/**
 * Cosmetics SKUs are dominated by shade variants of one product. The part after
 * the em dash is the only thing that distinguishes them, so it is split out and
 * surfaced on the card instead of the (identical) product name.
 */
function splitVariant(name) {
	const idx = name.indexOf('—')
	if (idx === -1) return { base: name, variant: null }
	return {
		base: name.slice(0, idx).trim(),
		variant: name.slice(idx + 1).trim(),
	}
}

export const ITEMS = catalog.items.map((row) => {
	const { base, variant } = splitVariant(row.item_name)
	return {
		item_code: row.item_code,
		item_name: row.item_name,
		base_name: base,
		variant,
		brand: row.brand,
		category: row.category,
		price: row.price,
		stock: row.stock,
		barcodes: [row.barcode],
		uom: 'Nos',
		hue: hueFor(row.item_code),
		// Pre-lowered haystack: built once at load, not per keystroke.
		_search:
			`${row.item_code} ${row.item_name} ${row.brand} ${row.category} ${row.barcode}`.toLowerCase(),
	}
})
