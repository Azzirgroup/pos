import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { round2 } from '@/utils/format'

/**
 * Kenyan retail quotes shelf prices VAT-inclusive, so the cart total must equal
 * the sum of the price tags exactly. Tax is therefore extracted from the total
 * rather than added to it — getting this backwards makes every receipt wrong.
 */
const VAT_RATE = 0.16
const TAX_INCLUSIVE = true

let lineSeq = 0

export const useCartStore = defineStore('cart', () => {
	const lines = ref([])
	const customer = ref(null)
	/** Whole-sale discount, in shillings, on top of any per-line discount. */
	const discount = ref(0)
	/** Line id most recently touched — drives the flash/scroll-into-view affordance. */
	const lastTouched = ref(null)

	/**
	 * The quotation this cart was loaded from, if any.
	 *
	 * Without it, editing a loaded quote and saving raised a *second* quotation:
	 * the customer ended up holding two documents with different numbers and
	 * different totals, and the shop had to work out which one it was honouring.
	 * Held here rather than in the view because it belongs to the cart's
	 * contents — clearing the cart has to forget it, and only the store knows
	 * every way a cart gets cleared.
	 */
	const sourceQuotation = ref(null)

	/**
	 * The held ticket this cart was resumed from, for the same reason. Resuming
	 * H002, adding a line and holding again used to file it as H004 — the same
	 * parked sale, now under a number the customer was never told.
	 */
	const sourceTicket = ref(null)
	const held = ref([])
	/**
	 * Ticket numbering, counted rather than derived from `held.length`.
	 *
	 * Length went backwards whenever a ticket was resumed or dropped, so the next
	 * hold reused a live ticket's number — and `resume` takes the first match, so
	 * the wrong cart could come back. It matters more now that the hold button
	 * undoes itself: holding, undoing and holding again is one tap each.
	 */
	let ticketSeq = 0

	/**
	 * `sourced` marks a line bought from a neighbouring shop for this sale:
	 * { supplier, buyRate }. Such a line is kept separate from an identical
	 * in-stock line — they have different costs, and merging them would hide
	 * the margin and produce a wrong Purchase Receipt.
	 */
	function add(item, qty = 1, { sourced = null, uom = null, negativeStockOk = false } = {}) {
		// The unit being sold, and what one of it costs. `uoms[0]` is always the
		// stock unit at factor 1, so an item nobody has configured a second unit
		// for behaves exactly as before.
		const units = item.uoms?.length ? item.uoms : [{ uom: item.uom || 'Nos', factor: 1, rate: item.price }]
		const unit = units.find((u) => u.uom === uom) || units[0]

		if (!sourced) {
			// Merged only when it is the *same unit*. A dozen and a single are
			// different lines with different rates — adding them together would
			// silently reprice one of them.
			const existing = lines.value.find(
				(l) => l.item_code === item.item_code && l.uom === unit.uom && !l.sourced,
			)
			if (existing) {
				existing.qty = round2(existing.qty + qty)
				// Sticky once granted: a line already sold past the shelf count has
				// already had that conversation, and re-asking on every `+` tap is
				// the bug this flag exists to fix.
				if (negativeStockOk) existing.negativeStockOk = true
				lastTouched.value = existing.id
				return existing
			}
		}
		const line = {
			id: ++lineSeq,
			item_code: item.item_code,
			item_name: item.item_name,
			brand: item.brand,
			hue: item.hue,
			uom: unit.uom,
			/** How many stock units one of `uom` is. A dozen is 12. */
			conversionFactor: unit.factor || 1,
			/** Every unit this item may be sold in, so the line can be switched. */
			units,
			// In stock units, which is what the shelf holds. The cart compares
			// against `stockQty`, not `qty` — one dozen is twelve off the shelf.
			stock: item.stock,
			rate: unit.rate,
			listRate: unit.rate,
			qty,
			discountPct: 0,
			sourced,
			// Once a cashier has agreed to sell this line past the shelf count, the
			// question is answered — every `+` after that should just increment,
			// not ask again for the same line.
			negativeStockOk,
		}
		lines.value.push(line)
		lastTouched.value = line.id
		return line
	}

	/**
	 * Switch a line to another unit — pieces to a dozen, say.
	 *
	 * The rate moves with it, because a rate is always "per one of these". The
	 * quantity does not: somebody changing the unit means "two dozen", not
	 * "two twelfths of what I typed".
	 */
	function setUom(id, uom) {
		const line = lines.value.find((l) => l.id === id)
		if (!line) return
		const unit = (line.units || []).find((u) => u.uom === uom)
		if (!unit) return
		line.uom = unit.uom
		line.conversionFactor = unit.factor || 1
		line.rate = unit.rate
		line.listRate = unit.rate
	}

	function setQty(id, qty) {
		const line = lines.value.find((l) => l.id === id)
		if (!line) return
		if (qty <= 0) return remove(id)
		line.qty = round2(qty)
		lastTouched.value = id
	}

	function inc(id, step = 1) {
		const line = lines.value.find((l) => l.id === id)
		if (line) setQty(id, line.qty + step)
	}

	function dec(id, step = 1) {
		const line = lines.value.find((l) => l.id === id)
		if (line) setQty(id, line.qty - step)
	}

	function setRate(id, rate) {
		const line = lines.value.find((l) => l.id === id)
		if (line) line.rate = Math.max(0, Number(rate) || 0)
	}

	function setLineDiscount(id, pct) {
		const line = lines.value.find((l) => l.id === id)
		if (line) line.discountPct = Math.min(100, Math.max(0, Number(pct) || 0))
	}

	function remove(id) {
		lines.value = lines.value.filter((l) => l.id !== id)
		if (lastTouched.value === id) lastTouched.value = null
	}

	function clear() {
		lines.value = []
		customer.value = null
		discount.value = 0
		lastTouched.value = null
		// An emptied cart is no longer that quote or that ticket.
		sourceQuotation.value = null
		sourceTicket.value = null
	}

	function lineTotal(line) {
		return round2(line.qty * line.rate * (1 - line.discountPct / 100))
	}

	const count = computed(() => lines.value.reduce((n, l) => n + l.qty, 0))
	const isEmpty = computed(() => lines.value.length === 0)

	const grossTotal = computed(() =>
		round2(lines.value.reduce((sum, l) => sum + lineTotal(l), 0)),
	)

	// Clamped to the subtotal: a discount worth more than the sale is a typo,
	// not a valid negative-total invoice.
	const discountAmount = computed(() => round2(Math.min(discount.value, grossTotal.value)))

	/** What the customer actually pays. */
	const total = computed(() => round2(grossTotal.value - discountAmount.value))

	/** Set the whole-sale discount, in shillings. Clamped to non-negative. */
	function setDiscount(amount) {
		discount.value = round2(Math.max(0, Number(amount) || 0))
	}

	const taxAmount = computed(() =>
		TAX_INCLUSIVE
			? round2(total.value - total.value / (1 + VAT_RATE))
			: round2(total.value * VAT_RATE),
	)

	const netTotal = computed(() => round2(total.value - taxAmount.value))

	/** Lines bought from a neighbour — drive the Purchase Receipt on checkout. */
	const sourcedLines = computed(() => lines.value.filter((l) => l.sourced))

	/** What we owe neighbours for this sale, and what we make on top. */
	const sourcedCost = computed(() =>
		round2(sourcedLines.value.reduce((s, l) => s + l.qty * l.sourced.buyRate, 0)),
	)

	const sourcedMargin = computed(() =>
		round2(sourcedLines.value.reduce((s, l) => s + lineTotal(l), 0) - sourcedCost.value),
	)

	/** Park the current sale so the next customer can be served immediately. */
	function hold() {
		if (isEmpty.value) return null
		// Back under its own number when this cart came off the held list, so a
		// parked sale keeps the reference the customer was given.
		const reusing = sourceTicket.value
		const ticket = {
			id: reusing || `H${String((ticketSeq += 1)).padStart(3, '0')}`,
			at: Date.now(),
			customer: customer.value,
			lines: JSON.parse(JSON.stringify(lines.value)),
			discount: discount.value,
			total: total.value,
			count: count.value,
			// A cart parked mid-edit is still that quote when it comes back.
			sourceQuotation: sourceQuotation.value,
		}
		// Put it back where it was rather than at the end: a list that reorders
		// itself every time somebody looks at a ticket is a list nobody can scan.
		const at = reusing ? held.value.findIndex((t) => t.id === reusing) : -1
		if (at >= 0) held.value.splice(at, 1, ticket)
		else held.value.push(ticket)
		clear()
		return ticket
	}

	function resume(ticketId) {
		const idx = held.value.findIndex((t) => t.id === ticketId)
		if (idx === -1) return
		const [ticket] = held.value.splice(idx, 1)
		lines.value = ticket.lines
		customer.value = ticket.customer
		discount.value = ticket.discount || 0
		lastTouched.value = null
		// Remembered so re-holding files it under the same number.
		sourceTicket.value = ticket.id
		sourceQuotation.value = ticket.sourceQuotation || null
	}

	/**
	 * Fold several parked sales into one ticket.
	 *
	 * A customer who was served twice — a bag put aside, then more added later —
	 * ends up with two tickets and one bill to pay. Merging them is the same
	 * request as merging two quotes, one screen earlier.
	 *
	 * Lines are combined by item *and* rate, matching `quotations.merge`: two
	 * tickets holding the same item at the same price become one line, and the
	 * same item at two prices stays two, because somebody was told both.
	 *
	 * The earliest ticket's number survives — it is the one the customer was
	 * given first, and the one they are most likely to quote back.
	 */
	function mergeHeld(ticketIds) {
		const ids = new Set(ticketIds || [])
		const chosen = held.value.filter((t) => ids.has(t.id))
		if (chosen.length < 2) return null

		const merged = []
		for (const ticket of chosen) {
			for (const line of ticket.lines) {
				const same = merged.find(
					(l) => l.item_code === line.item_code && l.rate === line.rate && l.uom === line.uom,
				)
				if (same) same.qty = round2(same.qty + line.qty)
				else merged.push(JSON.parse(JSON.stringify(line)))
			}
		}

		const keep = chosen[0]
		const ticket = {
			...keep,
			lines: merged,
			at: Date.now(),
			// A customer named on any of them is the customer for all of them; the
			// first name found wins rather than being dropped.
			customer: chosen.find((t) => t.customer)?.customer || null,
			discount: chosen.reduce((sum, t) => sum + (t.discount || 0), 0),
			count: merged.reduce((n, l) => n + l.qty, 0),
			total: round2(merged.reduce((sum, l) => sum + lineTotal(l), 0)),
			sourceQuotation: chosen.find((t) => t.sourceQuotation)?.sourceQuotation || null,
		}

		const at = held.value.findIndex((t) => t.id === keep.id)
		held.value = held.value.filter((t) => !ids.has(t.id))
		held.value.splice(Math.max(at, 0), 0, ticket)
		return ticket
	}

	function dropHeld(ticketId) {
		held.value = held.value.filter((t) => t.id !== ticketId)
	}

	return {
		lines,
		customer,
		discount,
		lastTouched,
		sourceQuotation,
		sourceTicket,
		held,
		vatRate: VAT_RATE,
		taxInclusive: TAX_INCLUSIVE,
		add,
		setUom,
		setQty,
		inc,
		dec,
		setRate,
		setLineDiscount,
		setDiscount,
		remove,
		clear,
		lineTotal,
		hold,
		resume,
		mergeHeld,
		dropHeld,
		count,
		isEmpty,
		grossTotal,
		discountAmount,
		total,
		taxAmount,
		netTotal,
		sourcedLines,
		sourcedCost,
		sourcedMargin,
	}
})
