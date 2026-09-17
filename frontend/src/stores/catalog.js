import { defineStore } from 'pinia'
import { ref, computed, shallowRef } from 'vue'
import { ITEMS, CATEGORIES, WAREHOUSES, NEIGHBOURS } from '@/data/seed'
import { decorate } from '@/data/derive'
import { getCatalog, getStockLevels } from '@/data/api'
import { tokenise, fuzzyHit } from '@/utils/search'

/**
 * The catalog is read-mostly and can be thousands of rows, so it lives in a
 * shallowRef — Vue never needs to deep-proxy every item, and search stays a
 * plain array scan. This is the single biggest reason the grid feels instant.
 *
 * Loaded once from the server and searched locally. A per-keystroke server
 * search is the single biggest cause of a sluggish till.
 */
export const useCatalogStore = defineStore('catalog', () => {
	const items = shallowRef([])
	const categories = ref([])
	const warehouses = ref([])
	const neighbours = ref([])
	const loading = ref(false)
	const loaded = ref(false)
	/** True when showing fake items — nothing here can actually be sold. */
	const isDemo = ref(false)
	const error = ref(null)

	function useDemo() {
		items.value = ITEMS
		categories.value = CATEGORIES
		warehouses.value = WAREHOUSES
		neighbours.value = NEIGHBOURS
		isDemo.value = true
	}

	/** The warehouse the counts are for, and when they were read. */
	const warehouse = ref(null)
	/** The stores every card lists: [{name, label, is_here}], this till's first. */
	const stores = ref([])
	let stockAt = null
	/**
	 * Which load is current. Two sales in quick succession each trigger a reload,
	 * and the first request — started before the second sale posted — can land
	 * *after* the second one. Without this it overwrote the newer counts with
	 * older ones, and the card went back to showing stock already sold.
	 */
	let loadSeq = 0

	async function load() {
		if (loaded.value) return
		const seq = ++loadSeq
		loading.value = true
		error.value = null
		try {
			const data = await getCatalog()
			if (seq !== loadSeq) return
			if (data?.empty || !data?.items?.length) {
				// A site with no sellable items yet: show the demo so the till is
				// explorable, but flag it — these SKUs do not exist in ERPNext and
				// selling one fails with DoesNotExistError.
				useDemo()
			} else {
				items.value = data.items.map(decorate)
				categories.value = data.categories || []
				warehouses.value = data.warehouses || []
				neighbours.value = data.neighbours || []
				warehouse.value = data.warehouse || null
				stores.value = data.stores || []
				stockAt = data.stock_at || null
				isDemo.value = false
			}
			loaded.value = true
		} catch (e) {
			if (seq !== loadSeq) return
			console.error('[pos] catalog load failed', e)
			error.value = e?.message || 'Could not load catalog'
			// A failed *reload* keeps the real catalogue it already has. Swapping a
			// working till to demo items because one refresh dropped on the wifi
			// would put SKUs on screen that cannot be sold.
			if (isDemo.value || !items.value.length) useDemo()
			loaded.value = true
		} finally {
			if (seq === loadSeq) loading.value = false
		}
	}

	/** Replace the counts that differ, as new objects so the cards re-render. */
	/**
	 * Merge fresh figures into the cards. Every argument is {item_code: value}
	 * for the items that changed; anything absent is left as it was.
	 */
	function applyStock(levels, elsewhere = null, byStore = null, pendingIn = null) {
		if (isDemo.value) return
		const maps = { stock: levels, elsewhere, byStore, pendingIn }
		if (!Object.values(maps).some(Boolean)) return
		let changed = false
		const next = items.value.map((it) => {
			let copy = null
			for (const [field, map] of Object.entries(maps)) {
				if (!map || !(it.item_code in map)) continue
				const raw = map[it.item_code]
				const value = field === 'byStore' ? raw || {} : Number(raw) || 0
				const same =
					field === 'byStore'
						? JSON.stringify(value) === JSON.stringify(it.byStore || {})
						: value === it[field]
				if (same) continue
				copy ||= { ...it }
				copy[field] = value
			}
			if (!copy) return it
			changed = true
			return copy
		})
		if (changed) items.value = next
	}

	/**
	 * Take a sale off the shelf on screen the moment it is charged.
	 *
	 * The invoice posts in the background while the next customer is served, so
	 * waiting for the server left the card reading the old count through the
	 * whole of the next sale. `deltas` is {item_code: stock units}.
	 */
	function adjustStock(deltas) {
		const levels = {}
		const shelves = {}
		for (const [code, delta] of Object.entries(deltas || {})) {
			const it = byCode.value.get(code)
			if (!it) continue
			levels[code] = (Number(it.stock) || 0) + Number(delta || 0)
			if (warehouse.value) shelves[code] = { ...(it.byStore || {}), [warehouse.value]: levels[code] }
		}
		applyStock(levels, null, shelves)
	}

	/** Mark an item as asked for, before the next sync says so. */
	function markRequested(code, qty) {
		const it = byCode.value.get(code)
		if (it) applyStock(null, null, null, { [code]: (Number(it.pendingIn) || 0) + Number(qty || 0) })
	}

	let syncing = false
	/**
	 * Pick up stock moved by anyone — another till, the back office, a receipt.
	 *
	 * Only this till's own sales used to reach the cards. Asks for the bins
	 * changed since the last read, which is usually nothing, so it is cheap
	 * enough to run every few seconds.
	 */
	async function syncStock() {
		if (syncing || loading.value || !loaded.value || isDemo.value) return
		syncing = true
		const seq = loadSeq
		try {
			const res = await getStockLevels(stockAt)
			// A full reload started meanwhile and is the better answer.
			if (seq !== loadSeq) return
			if (res?.warehouse !== warehouse.value) {
				// A different counter's shelf now (a shift opened on another till):
				// every count on screen is for the wrong place.
				await refresh()
				return
			}
			applyStock(res?.stock, res?.elsewhere, res?.by_store, res?.pending_in)
			stockAt = res?.at || stockAt
		} catch (e) {
			// Quiet: the next tick tries again, and a toast every few seconds on a
			// flaky connection helps nobody.
			console.warn('[pos] stock sync failed', e)
		} finally {
			syncing = false
		}
	}

	/** Keep counts current while the till is on screen. Returns a stop function. */
	function startStockSync(everyMs = 15000) {
		const tick = () => {
			if (document.visibilityState === 'visible' && navigator.onLine !== false) syncStock()
		}
		const timer = setInterval(tick, everyMs)
		// Coming back to the tab is exactly when counts are most likely stale.
		document.addEventListener('visibilitychange', tick)
		window.addEventListener('focus', tick)
		return () => {
			clearInterval(timer)
			document.removeEventListener('visibilitychange', tick)
			window.removeEventListener('focus', tick)
		}
	}

	/** Re-read stock and prices after a sale without rebuilding the whole store. */
	async function refresh() {
		loaded.value = false
		await load()
	}

	const byCode = computed(() => {
		const m = new Map()
		for (const it of items.value) m.set(it.item_code, it)
		return m
	})

	/** Barcode → item. Built once; a scan is then a single Map lookup. */
	const byBarcode = computed(() => {
		const m = new Map()
		for (const it of items.value) {
			for (const b of it.barcodes || []) m.set(b, it)
		}
		return m
	})

	function findByBarcode(code) {
		return byBarcode.value.get(String(code).trim()) || null
	}

	/**
	 * Ranked local search, tolerant of how a cashier actually types.
	 *
	 * Ranking matters: typing "red" should surface "Gel Polish — Classic Red"
	 * above anything that merely contains the letters. Tiers, cheapest first:
	 *
	 *   0  exact item code            — a code typed in full means that item
	 *   1  barcode, exact or prefix   — reading digits off a carton
	 *   2  name starts with the query
	 *   3  brand starts with the query
	 *   4  raw substring              — the old behaviour, kept
	 *   5  all tokens present, any order  — "cocoa 400 vaseline"
	 *   6  all tokens within a typo       — "vaslin cocoa 400"
	 *
	 * Tier 6 is the expensive one and is skipped entirely unless the cheaper
	 * tiers came back thin. A cashier who typed something that already matches
	 * plenty does not need spelling correction, and running it anyway is how a
	 * search box starts lagging behind the keyboard.
	 */
	function search(query, category) {
		const raw = query.trim().toLowerCase()
		const pool = items.value

		if (!raw) {
			return category ? pool.filter((i) => i.category === category) : pool
		}

		const tokens = tokenise(raw)
		const normQuery = tokens.join(' ')
		const hits = []
		// Only the items nothing cheaper matched, so the fuzzy pass walks a
		// shrinking list rather than the whole catalog.
		const misses = []

		for (const it of pool) {
			if (category && it.category !== category) continue

			let score = -1
			// `brand` is optional on real ERPNext items — the demo seed always had
			// one, so an unguarded .toLowerCase() only blows up on live data.
			if (it.item_code.toLowerCase() === raw) score = 0
			// Prefix, not equality: a cashier reading a code off a carton types
			// the first few digits, and an exact-match-only rule made barcode
			// search look broken for everything except a full 13-digit paste.
			else if (it.barcodes?.some((b) => b === raw || b.startsWith(raw))) score = 1
			else if (it.item_name.toLowerCase().startsWith(raw)) score = 2
			else if (it.brand?.toLowerCase().startsWith(raw)) score = 3
			else if (it._search.includes(raw)) score = 4
			// Word order is not information here. "cocoa vaseline" and "vaseline
			// cocoa" are one request, and only one of them used to find anything.
			else if (tokens.length > 1 && tokens.every((t) => it._norm.includes(t))) score = 5
			else if (tokens.length === 1 && it._norm.includes(normQuery)) score = 5

			if (score >= 0) hits.push({ it, score })
			else misses.push(it)
		}

		// Enough already, and all of it better than anything a typo could find.
		const FUZZY_FLOOR = 5
		if (hits.length < FUZZY_FLOOR) {
			for (const it of misses) {
				if (tokens.every((t) => it._norm.includes(t) || fuzzyHit(t, it._words))) {
					hits.push({ it, score: 6 })
				}
			}
		}

		hits.sort((a, b) => a.score - b.score || a.it.item_name.localeCompare(b.it.item_name))
		return hits.map((h) => h.it)
	}

	return {
		items,
		categories,
		warehouses,
		neighbours,
		loading,
		loaded,
		isDemo,
		error,
		warehouse,
		stores,
		markRequested,
		load,
		refresh,
		adjustStock,
		syncStock,
		startStockSync,
		search,
		findByBarcode,
		byCode,
	}
})
