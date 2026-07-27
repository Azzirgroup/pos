import { defineStore } from 'pinia'
import { ref, computed, shallowRef } from 'vue'
import { ITEMS, CATEGORIES, WAREHOUSES, NEIGHBOURS } from '@/data/seed'

/**
 * The catalog is read-mostly and can be thousands of rows, so it lives in a
 * shallowRef — Vue never needs to deep-proxy every item, and search stays a
 * plain array scan. This is the single biggest reason the grid feels instant.
 *
 * Swap `load()` for the real API call when the backend lands; nothing else in
 * the UI needs to change.
 */
export const useCatalogStore = defineStore('catalog', () => {
	const items = shallowRef([])
	const categories = ref([])
	const warehouses = ref([])
	const neighbours = ref([])
	const loading = ref(false)
	const loaded = ref(false)

	async function load() {
		if (loaded.value) return
		loading.value = true
		try {
			// TODO(backend): frappeRequest('cosmestics.api.pos.get_catalog')
			items.value = ITEMS
			categories.value = CATEGORIES
			warehouses.value = WAREHOUSES
			neighbours.value = NEIGHBOURS
			loaded.value = true
		} finally {
			loading.value = false
		}
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
	 * Ranked local search. Ranking matters: typing "red" should surface
	 * "Gel Polish — Classic Red" above anything that merely contains the
	 * letters. Single pass, no regex, no allocation per item.
	 */
	function search(query, category) {
		const q = query.trim().toLowerCase()
		const pool = items.value

		if (!q) {
			return category ? pool.filter((i) => i.category === category) : pool
		}

		const hits = []
		for (const it of pool) {
			if (category && it.category !== category) continue

			let score = -1
			if (it.item_code.toLowerCase() === q) score = 0
			else if (it.barcodes?.includes(q)) score = 1
			else if (it.item_name.toLowerCase().startsWith(q)) score = 2
			else if (it.brand.toLowerCase().startsWith(q)) score = 3
			else if (it._search.includes(q)) score = 4

			if (score >= 0) hits.push({ it, score })
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
		load,
		search,
		findByBarcode,
		byCode,
	}
})
