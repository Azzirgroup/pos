import { onMounted, onUnmounted } from 'vue'

/**
 * Counter keyboard shortcuts. A fast cashier never leaves the keyboard, so the
 * whole sale must be reachable without the mouse.
 *
 * Bindings are function keys rather than letters because letters would collide
 * with the always-on scanner capture and with typing in the search box.
 */
export function useShortcuts(map) {
	function isTypingTarget(el) {
		if (!el) return false
		const tag = el.tagName
		return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable
	}

	function handler(e) {
		const key = e.key

		// Escape must always work, including out of an input.
		if (key === 'Escape' && map.escape) {
			map.escape(e)
			return
		}

		if (isTypingTarget(e.target) && !key.startsWith('F')) return

		const fn = map[key]
		if (fn) {
			e.preventDefault()
			fn(e)
		}
	}

	onMounted(() => document.addEventListener('keydown', handler))
	onUnmounted(() => document.removeEventListener('keydown', handler))
}
