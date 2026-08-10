import { defineStore } from 'pinia'
import { ref, computed, shallowRef } from 'vue'
import { ITEMS, CATEGORIES, WAREHOUSES, NEIGHBOURS } from '@/data/seed'
import { decorate } from '@/data/derive'
import { getCatalog } from '@/data/api'
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

	async function load() {
		if (loaded.value) return
		loading.value = true
		error.value = null
		try {
			const data = await getCatalog()
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
				isDemo.value = false
			}
			loaded.value = true
		} catch (e) {
			console.error('[pos] catalog load failed', e)
			error.value = e?.message || 'Could not load catalog'
			useDemo()
			loaded.value = true
		} finally {
			loading.value = false
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
		load,
		refresh,
		search,
		findByBarcode,
		byCode,
	}
})
