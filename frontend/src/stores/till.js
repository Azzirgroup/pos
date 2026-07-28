import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getTillContext } from '@/data/api'

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
	 * Never throws and never clears what it already had: this drives a status
	 * chip, and a failed refresh should leave the last known truth on screen
	 * rather than blanking it.
	 */
	async function refresh() {
		try {
			context.value = await getTillContext()
			loaded.value = true
		} catch (e) {
			console.warn('[till] context refresh failed', e)
		}
		return context.value
	}

	return { context, loaded, refresh }
})
