import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { round2 } from '@/utils/format'
import {
	clearPending,
	clearStored,
	loadCart,
	loadPending,
	savePending,
	saveCart,
	storageKey,
} from './cartStorage'

/**
 * Kenyan retail quotes shelf prices VAT-inclusive, so the cart total must equal
 * the sum of the price tags exactly. Tax is therefore extracted from the total
 * rather than added to it — getting this backwards makes every receipt wrong.
 */
const VAT_RATE = 0.16
const TAX_INCLUSIVE = true

let lineSeq = 0

/**
 * Keep line ids counting from where a restored cart left off.
 *
 * `lineSeq` is a module variable, so a reload resets it to zero while the
 * restored lines still carry ids 1, 2, 3. The next item added was then handed an
 * id that already belonged to something else — and every lookup is
 * `find((l) => l.id === id)`, which takes the first match. So the grid's `+`,
 * the quantity box and the bin all reached the *older* line: tapping `+` on one
 * product silently raised the quantity of another, and the product actually
 * being tapped never moved. It looked like the button was dead.
 *
 * Seeded from the highest id anywhere in the payload, held tickets included —
 * a parked ticket's lines come back into the cart on resume and collide just
 * the same.
 */
function seedLineSeq(payload) {
	const ids = [
		...(payload?.lines || []).map((l) => l.id),
		...(payload?.held || []).flatMap((t) => (t.lines || []).map((l) => l.id)),
	].filter((n) => Number.isFinite(n))
	lineSeq = Math.max(lineSeq, 0, ...ids)
}

export const useCartStore = defineStore('cart', () => {
	/**
	 * Restored before anything else, so a reload comes back to the same cart.
	 *
	 * The key is anonymous at this point — the session has not loaded yet — and
	 * `adoptSession` re-keys it the moment it does. See `cartStorage`.
	 */
	let key = storageKey(null, null)
	const restored = loadCart(key)
	seedLineSeq(restored)

	const lines = ref(restored?.lines || [])
	const customer = ref(restored?.customer ?? null)
	/** Whole-sale discount, in shillings, on top of any per-line discount. */
	const discount = ref(restored?.discount || 0)
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
	const sourceQuotation = ref(restored?.sourceQuotation ?? null)

	/**
	 * The held ticket this cart was resumed from, for the same reason. Resuming
	 * H002, adding a line and holding again used to file it as H004 — the same
	 * parked sale, now under a number the customer was never told.
	 */
	const sourceTicket = ref(restored?.sourceTicket ?? null)
	const held = ref(restored?.held || [])
	/**
	 * Ticket numbering, counted rather than derived from `held.length`.
	 *
	 * Length went backwards whenever a ticket was resumed or dropped, so the next
	 * hold reused a live ticket's number — and `resume` takes the first match, so
	 * the wrong cart could come back. It matters more now that the hold button
	 * undoes itself: holding, undoing and holding again is one tap each.
	 */
	let ticketSeq = restored?.ticketSeq || 0

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
				// Re-numbered, not copied across: two tickets number their lines
				// independently, so both can hold a line 3. Merged as-is, the
				// combined ticket carries two lines with one id and every lookup
				// finds the wrong one — the same fault `seedLineSeq` fixes on
				// reload, reached by a different route.
				else merged.push({ ...JSON.parse(JSON.stringify(line)), id: ++lineSeq })
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

	/**
	 * A basket that has been paid for but not yet posted.
	 *
	 * Called immediately before the invoice goes to the server, and cleared by
	 * `submitSettled` once it has answered either way. In between, this is the
	 * only durable copy of the basket — the cart on screen has already been
	 * emptied for the next customer. See `cartStorage.savePending`.
	 */
	/**
	 * The ticket an interrupted sale came back as, for the view to announce.
	 *
	 * A ref rather than a return value because recovery cannot be pinned to one
	 * moment: the cart is stored anonymously until the session loads, so the
	 * stash may only become visible when `adoptSession` re-keys — which happens
	 * on its own schedule, sometimes before the till has mounted and sometimes
	 * after. Whoever finds it sets this; the view watches and says so.
	 */
	const recovered = ref(null)

	function submitStarted(snapshot) {
		savePending(key, snapshot)
	}

	function submitSettled() {
		clearPending(key)
	}

	/**
	 * Put back a basket whose sale did not post.
	 *
	 * The wifi drops between "Complete sale" and the invoice, and the cart has
	 * already been cleared: the customer is standing there with goods that no
	 * longer exist anywhere. Re-scanning a full basket from memory is exactly
	 * what the persistence work was meant to stop, and it happens at the worst
	 * possible moment.
	 *
	 * Where it goes depends on what the cashier has done since. Usually nothing —
	 * the failure lands within a second or two — so it goes straight back into
	 * the cart, and they can retry as if the tap had not happened. But if they
	 * have already started ringing the next customer, dropping the old lines on
	 * top would silently merge two people's shopping into one bill. In that case
	 * it is parked as a held ticket, which is the till's existing answer to "keep
	 * this basket for later" and costs one tap to bring back.
	 *
	 * Returns where it went, so the caller can say so.
	 */
	function restoreFailedSale(snapshot) {
		const recovered = (snapshot?.lines || []).map((l) => ({ ...l }))
		if (!recovered.length) return null

		if (isEmpty.value) {
			lines.value = recovered
			customer.value = snapshot.customer ?? null
			discount.value = snapshot.discount || 0
			sourceQuotation.value = snapshot.sourceQuotation ?? null
			sourceTicket.value = snapshot.sourceTicket ?? null
			return { where: 'cart' }
		}

		const ticket = {
			id: `H${String((ticketSeq += 1)).padStart(3, '0')}`,
			at: Date.now(),
			customer: snapshot.customer ?? null,
			lines: recovered,
			discount: snapshot.discount || 0,
			total: round2(recovered.reduce((s, l) => s + lineTotal(l), 0) - (snapshot.discount || 0)),
			count: recovered.reduce((n, l) => n + l.qty, 0),
			sourceQuotation: snapshot.sourceQuotation ?? null,
		}
		held.value.push(ticket)
		return { where: 'held', ticket }
	}

	/**
	 * A basket left mid-post by a reload, a crash or a tab the tablet reclaimed.
	 *
	 * Deliberately *not* dropped back into the cart. Unlike a failed submit,
	 * nobody knows whether this one reached the server: the tab died with the
	 * request in the air, and it may well have posted. Re-ringing it
	 * automatically would risk charging the customer twice, which is a worse
	 * failure than the one being recovered.
	 *
	 * So it comes back as a held ticket — the basket is safe, and settling it
	 * takes a deliberate act by someone who can check Recent sales first.
	 */
	function recoverPending() {
		const pending = loadPending(key)
		if (!pending) return null
		clearPending(key)
		const restored = restoreFailedSale(pending)
		if (!restored) return null
		// Always a ticket, never the live cart: see above.
		const found =
			restored.where === 'cart'
				? (() => {
						const ticket = hold()
						return ticket ? { where: 'held', ticket } : null
					})()
				: restored
		if (!found) return null
		recovered.value = { ...found, unverified: true }
		return recovered.value
	}

	/**
	 * Write the whole cart on every change.
	 *
	 * Deep, because a quantity typed on an existing line is the commonest edit
	 * and a shallow watch would miss it. Cheap enough: this is a handful of rows
	 * serialised on human-speed interaction, not a hot loop.
	 */
	watch(
		[lines, customer, discount, held, sourceQuotation, sourceTicket],
		() => {
			saveCart(key, {
				lines: lines.value,
				customer: customer.value,
				discount: discount.value,
				held: held.value,
				sourceQuotation: sourceQuotation.value,
				sourceTicket: sourceTicket.value,
				ticketSeq,
			})
		},
		{ deep: true },
	)

	/**
	 * Point storage at this cashier and this till, once the session says who
	 * they are.
	 *
	 * Until this runs the cart is stored anonymously, which is what makes a
	 * reload work before the boot call returns. When the real key arrives, an
	 * anonymous cart is carried over to it — that is this same person, one
	 * moment later — but a cart already stored under the real key wins, because
	 * it is the one they actually left behind.
	 *
	 * Signing in as somebody else therefore lands on *their* cart, not the
	 * previous cashier's. See `cartStorage` for why that matters on a shared
	 * machine.
	 */
	function adoptSession(user, till) {
		const next = storageKey(user, till)
		if (next === key) return

		// A sale left in the air before we knew who was ringing it up still has to
		// be recoverable afterwards, so the stash moves with the key.
		const pending = loadPending(key)
		if (pending && !loadPending(next)) savePending(next, pending)
		clearPending(key)

		const existing = loadCart(next)
		if (existing) {
			seedLineSeq(existing)
			lines.value = existing.lines || []
			customer.value = existing.customer ?? null
			discount.value = existing.discount || 0
			held.value = existing.held || []
			sourceQuotation.value = existing.sourceQuotation ?? null
			sourceTicket.value = existing.sourceTicket ?? null
			ticketSeq = existing.ticketSeq || 0
			clearStored(key)
		} else if (lines.value.length || held.value.length) {
			// Carry the anonymous cart across, then stop using the old key.
			clearStored(key)
		}
		key = next
		// The stash under the real key only becomes reachable now, and the till
		// may already have mounted and looked for it. See `recovered`.
		recoverPending()
		saveCart(key, {
			lines: lines.value,
			customer: customer.value,
			discount: discount.value,
			held: held.value,
			sourceQuotation: sourceQuotation.value,
			sourceTicket: sourceTicket.value,
			ticketSeq,
		})
	}

	return {
		adoptSession,
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
		submitStarted,
		submitSettled,
		restoreFailedSale,
		recoverPending,
		recovered,
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
