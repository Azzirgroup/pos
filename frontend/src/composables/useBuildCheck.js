import { ref } from 'vue'
import { frappeRequest } from 'frappe-ui'

/**
 * Notice when the tab is running an older build than the server.
 *
 * A till is a tab left open all day. Deploy under it and the cashier keeps
 * running yesterday's JavaScript with nothing on screen to say so — a fix
 * ships, they refresh nothing, and the thing that was just fixed is still
 * broken in front of them. That has now cost real time twice.
 *
 * `router.js` already recovers from the *loud* version of this: a navigation
 * that asks for a chunk the server has since replaced fails, and the tab
 * reloads itself. It cannot catch the quiet version, which is far more common —
 * stale code that loads fine and simply behaves like the old build.
 *
 * ## Why a banner and not a reload
 *
 * Reloading on its own would be the tidy answer and the wrong one: a cart with
 * eleven items in it lives in memory, and throwing that away because a deploy
 * happened is a worse failure than the one being fixed. So the tab says so and
 * lets the person choose the moment.
 *
 * Checked on focus rather than on a timer. A shop's tab is out of focus most of
 * the day, and the moment somebody comes back to it is exactly when they are
 * about to use it — a poll would ask a question nobody was waiting for the
 * answer to, all day long.
 */
const CHECK_METHOD = 'cosmestics.www.pos.get_build_id'

/** How long to leave between checks, however often focus fires. */
const MIN_GAP_MS = 60_000

export const buildStale = ref(false)

let booted = null
let lastCheck = 0
let started = false

async function check() {
	if (buildStale.value) return
	const now = Date.now()
	if (now - lastCheck < MIN_GAP_MS) return
	lastCheck = now

	try {
		const current = await frappeRequest({
			url: `/api/method/${CHECK_METHOD}`,
			method: 'POST',
		})
		// An empty answer means the server could not work out its own build —
		// never a reason to tell somebody their tab is stale.
		if (current && booted && current !== booted) buildStale.value = true
	} catch {
		// Offline, or the session lapsed. Neither is a version problem, and a till
		// on a bad connection must not start claiming it needs reloading.
	}
}

export function useBuildCheck() {
	if (started) return { buildStale }
	started = true

	booted = window.build_id || null
	// Nothing to compare against — an older page, or a dev server.
	if (!booted) return { buildStale }

	window.addEventListener('focus', check)
	document.addEventListener('visibilitychange', () => {
		if (!document.hidden) check()
	})

	return { buildStale }
}
