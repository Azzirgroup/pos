import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getTillContext, getOpenShift, getMe } from '@/data/api'
import { useCartStore } from './cart'

/**
 * Which till, shop and warehouse this session is selling from.
 *
 * A store rather than local state in the header, because the two components
 * that care are not related: the header *shows* the shift, and the till screen
 * *changes* it. Loading it once in the header meant opening a shift left the
 * chip reading "No shift" until the page was reloaded — the one moment it most
 * needs to be right.
 */
export const useTillStore = defineStore('till', () => {
	const context = ref(null)
	const loaded = ref(false)
	/**
	 * The open shift, shared rather than copied.
	 *
	 * The till screen used to hold its own copy, loaded once on mount. That was
	 * fine while the till was the only place a shift could be opened — but a
	 * shift can now be opened and closed from the Shifts page too, and a second
	 * copy loaded at a different moment is a copy that disagrees. The symptom is
	 * a till insisting there is no open shift while the header chip names one.
	 *
	 * Same reasoning as `context` above, which is here for exactly this bug.
	 */
	const shift = ref(null)

	/**
	 * Never throws and never clears what it already had: this drives a status
	 * chip, and a failed refresh should leave the last known truth on screen
	 * rather than blanking it.
	 */
	async function refresh() {
		try {
			context.value = await getTillContext()
			loaded.value = true
			// Now that we know who is signed in and which counter this is, point
			// the saved cart at them — see `cart.adoptSession`. Until this runs a
			// reload restores from an anonymous key, which is what makes the cart
			// survive a refresh before this call has even returned.
			try {
				const me = await getMe()
				useCartStore().adoptSession(me?.name || me?.user, context.value?.branch)
			} catch (e) {
				console.warn('[till] could not scope the saved cart', e)
			}
		} catch (e) {
			console.warn('[till] context refresh failed', e)
		}
		// The shift moves with the context: the two are read together on every
		// screen that cares, and refreshing one without the other is how they
		// come to disagree.
		refreshShift()
		return context.value
	}

	/**
	 * Re-read the open shift.
	 *
	 * Deliberately clears on a *successful* empty answer — "no shift is open" is
	 * a real answer that has to be able to replace an earlier one, or closing a
	 * shift would leave the till still believing it has one. Only a thrown error
	 * leaves the previous value alone.
	 */
	async function refreshShift() {
		try {
			shift.value = await getOpenShift()
		} catch (e) {
			console.warn('[till] shift refresh failed', e)
		}
		return shift.value
	}

	return { context, loaded, shift, refresh, refreshShift }
})
