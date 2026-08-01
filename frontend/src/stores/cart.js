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
	const cartDiscountPct = ref(0)
	/** Line id most recently touched — drives the flash/scroll-into-view affordance. */
	const lastTouched = ref(null)
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
	function add(item, qty = 1, { sourced = null } = {}) {
		if (!sourced) {
			const existing = lines.value.find((l) => l.item_code === item.item_code && !l.sourced)
			if (existing) {
				existing.qty = round2(existing.qty + qty)
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
			uom: item.uom || 'Nos',
			stock: item.stock,
			rate: item.price,
			listRate: item.price,
			qty,
			discountPct: 0,
			sourced,
		}
		lines.value.push(line)
		lastTouched.value = line.id
		return line
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
		cartDiscountPct.value = 0
		lastTouched.value = null
	}

	function lineTotal(line) {
		return round2(line.qty * line.rate * (1 - line.discountPct / 100))
	}

	const count = computed(() => lines.value.reduce((n, l) => n + l.qty, 0))
	const isEmpty = computed(() => lines.value.length === 0)

	const grossTotal = computed(() =>
		round2(lines.value.reduce((sum, l) => sum + lineTotal(l), 0)),
	)

	const discountAmount = computed(() =>
		round2((grossTotal.value * cartDiscountPct.value) / 100),
	)

	/** What the customer actually pays. */
	const total = computed(() => round2(grossTotal.value - discountAmount.value))

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
		const ticket = {
			id: `H${String((ticketSeq += 1)).padStart(3, '0')}`,
			at: Date.now(),
			customer: customer.value,
			lines: JSON.parse(JSON.stringify(lines.value)),
			total: total.value,
			count: count.value,
		}
		held.value.push(ticket)
		clear()
		return ticket
	}

	function resume(ticketId) {
		const idx = held.value.findIndex((t) => t.id === ticketId)
		if (idx === -1) return
		const [ticket] = held.value.splice(idx, 1)
		lines.value = ticket.lines
		customer.value = ticket.customer
		lastTouched.value = null
	}

	function dropHeld(ticketId) {
		held.value = held.value.filter((t) => t.id !== ticketId)
	}

	return {
		lines,
		customer,
		cartDiscountPct,
		lastTouched,
		held,
		vatRate: VAT_RATE,
		taxInclusive: TAX_INCLUSIVE,
		add,
		setQty,
		inc,
		dec,
		setRate,
		setLineDiscount,
		remove,
		clear,
		lineTotal,
		hold,
		resume,
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
