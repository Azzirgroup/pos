/**
 * Fields the UI needs that the server has no reason to compute.
 *
 * Shared by the live catalog and the demo seed so both produce byte-identical
 * item shapes — otherwise the demo drifts from reality and hides bugs.
 */

/**
 * Deterministic hue per item. Avoids shipping product photos: swatches render
 * instantly with zero network requests, which matters far more at the till than
 * photography does.
 *
 * FNV-1a rather than a simple rolling hash: item codes are sequential
 * (MKP-001, MKP-002 …) and a weak hash maps them to near-identical hues, which
 * defeats the entire point — the cashier must be able to tell two shades apart
 * at a glance. FNV avalanches, so adjacent codes land far apart on the wheel.
 */
export function hueFor(code) {
	let h = 2166136261
	for (let i = 0; i < String(code).length; i++) {
		h ^= String(code).charCodeAt(i)
		h = Math.imul(h, 16777619)
	}
	return Math.abs(h) % 360
}

/**
 * Cosmetics SKUs are dominated by shade variants of one product. The part after
 * the em dash is the only thing that distinguishes them, so it is split out and
 * surfaced on the card instead of the (identical) product name.
 */
export function splitVariant(name) {
	const n = name || ''
	const idx = n.indexOf('—')
	if (idx === -1) return { base: n, variant: null }
	return { base: n.slice(0, idx).trim(), variant: n.slice(idx + 1).trim() }
}

/** Turn a raw catalog row into what the grid and search expect. */
export function decorate(row) {
	const { base, variant } = splitVariant(row.item_name)
	const barcodes = row.barcodes || []
	return {
		item_code: row.item_code,
		item_name: row.item_name,
		base_name: base,
		variant,
		brand: row.brand || null,
		category: row.category,
		price: Number(row.price) || 0,
		stock: Number(row.stock) || 0,
		barcodes,
		uom: row.uom || 'Nos',
		batched: Boolean(row.batched),
		hue: hueFor(row.item_code),
		// Pre-lowered haystack: built once at load, not per keystroke.
		_search:
			`${row.item_code} ${row.item_name} ${row.brand || ''} ${row.category || ''} ${barcodes.join(' ')}`.toLowerCase(),
	}
}
