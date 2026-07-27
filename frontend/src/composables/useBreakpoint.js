import { ref, onMounted, onUnmounted } from 'vue'

/**
 * Layout is CSS-driven wherever possible. This exists only for the cases where
 * the *behaviour* differs, not just the styling — a docked cart panel and a
 * bottom sheet are different components, not one component with different
 * padding.
 *
 * The cart docks at 1024px rather than 768px: on a portrait tablet a 340px
 * panel leaves too little room and the item grid collapses to two stretched
 * columns. Below that the cart is a sheet and the grid keeps the full width.
 */
export function useBreakpoint() {
	const isCompact = ref(false) // < 1024px — cart is a sheet + bottom bar
	const isDesktop = ref(false) // >= 1280px — vertical category rail

	const mqCompact = window.matchMedia('(max-width: 1023px)')
	const mqDesktop = window.matchMedia('(min-width: 1280px)')

	function sync() {
		isCompact.value = mqCompact.matches
		isDesktop.value = mqDesktop.matches
	}

	onMounted(() => {
		sync()
		mqCompact.addEventListener('change', sync)
		mqDesktop.addEventListener('change', sync)
	})

	onUnmounted(() => {
		mqCompact.removeEventListener('change', sync)
		mqDesktop.removeEventListener('change', sync)
	})

	sync()

	return { isCompact, isDesktop }
}
