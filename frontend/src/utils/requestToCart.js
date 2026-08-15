/**
 * Turning a material request into a cart.
 *
 * Shared by the till's own Requests sheet and the Documents detail view,
 * because the two offer the same button and it has to behave identically —
 * a shop that gets a confirmation on one screen and a silent replacement on
 * the other will not trust either.
 */

/** The item lines of a document, in the shape `documents.get_document` sends. */
export function requestedLines(doc) {
	const table = doc?.tables?.find((t) => t.fieldname === 'items')
	return (table?.rows || [])
		.map((row) => ({ item_code: row.item_code, qty: Number(row.qty) || 0 }))
		.filter((l) => l.item_code && l.qty > 0)
}

/**
 * Put those lines in the cart, replacing whatever is there.
 *
 * Replacing rather than adding: this is "sell this request", not "sell this
 * request as well as whatever was on screen". The caller confirms first when
 * the cart is not empty — a basket at a counter may belong to somebody
 * standing there.
 *
 * Lines go in with the shelf-count prompt suppressed. The entire point of a
 * request is that the shop does not have these yet, so the usual "you are
 * short" sheet would fire on every single line and have to be dismissed one
 * at a time.
 *
 * Returns what happened, so the caller can report it: an item that has since
 * been disabled or deleted is not in the catalogue any more, and quietly
 * dropping it would leave somebody selling a short basket without knowing.
 */
export function loadRequestIntoCart(doc, { cart, catalog }) {
	const wanted = requestedLines(doc)
	if (!wanted.length) return { loaded: 0, missing: [], empty: true }

	cart.clear()

	const missing = []
	for (const line of wanted) {
		const item = catalog.byCode.get(line.item_code)
		if (item) cart.add(item, line.qty, { negativeStockOk: true })
		else missing.push(line.item_code)
	}

	return { loaded: wanted.length - missing.length, missing, empty: false }
}

/** One sentence describing the result, for a toast. */
export function loadSummary(result, name) {
	if (result.empty) return { message: 'There are no lines on this request', tone: 'bad' }
	if (result.missing.length) {
		return {
			message: `Loaded ${result.loaded} of ${result.loaded + result.missing.length} lines — ${result.missing.join(', ')} not in the catalogue`,
			tone: 'bad',
		}
	}
	return { message: `Loaded ${result.loaded} lines from ${name}`, tone: 'good' }
}
