import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getMe } from '@/data/api'

/**
 * Who is signed in, and what they are allowed to open.
 *
 * A store rather than a per-component `getMe()` because three unrelated things
 * now ask the same question — the rail decides whether to draw Dashboard, the
 * router decides whether to let you navigate there, and Purchasing decides
 * whether you get a "Post purchase" button or a "Confirm" one. Three copies
 * loaded at three moments is three chances to disagree, and the disagreement
 * looks like a permission bug.
 *
 * `can` is computed on the **server** — see `cosmestics.permissions.abilities`.
 * Nothing here matches role names itself, so the rule about who counts as a
 * superuser lives in one place and the two ends cannot drift.
 *
 * None of this is a security boundary. Every gated endpoint checks again; this
 * only decides which buttons are worth drawing.
 */
export const useSessionStore = defineStore('session', () => {
	const me = ref(null)
	const loaded = ref(false)
	/** The in-flight load, so N callers on first paint make one request. */
	let inflight = null

	const can = computed(() => me.value?.can || {})

	/**
	 * Closed until proven open.
	 *
	 * While the session is still loading these read false, which means the rail
	 * draws without Dashboard for a moment on a slow connection rather than
	 * drawing it and snatching it away. A control that appears and vanishes is
	 * worse than one that arrives late.
	 */
	const canViewAnalytics = computed(() => !!can.value.analytics)
	const isPurchaseManager = computed(() => !!can.value.purchase_manager)
	const isStoreKeeper = computed(() => !!can.value.store_keeper)

	async function load() {
		if (loaded.value) return me.value
		if (inflight) return inflight
		inflight = getMe()
			.then((data) => {
				me.value = data
				loaded.value = true
				return data
			})
			.catch((e) => {
				// A session lookup that fails must not take the app with it. The
				// gated screens stay shut, which is the safe way to be wrong, and
				// everything operational carries on.
				console.warn('[pos] session lookup failed', e)
				loaded.value = true
				return null
			})
			.finally(() => {
				inflight = null
			})
		return inflight
	}

	return { me, loaded, can, canViewAnalytics, isPurchaseManager, isStoreKeeper, load }
})
