/**
 * Opening a print view without the browser eating it.
 *
 * Every print path in this app did the obvious thing:
 *
 *     const { url } = await getPrintUrl(...)
 *     window.open(url, '_blank')
 *
 * and every one of them is blocked. A browser only allows a popup while it can
 * still see the user gesture that asked for it, and awaiting a round trip ends
 * that window — so the tab never opens, nothing is thrown, and the cashier
 * presses print again. On a till, where the fix is a browser setting nobody at
 * the counter can reach, that reads as "printing is broken".
 *
 * So the tab is opened *first*, synchronously, while the click is still live,
 * and pointed at the URL once it arrives.
 *
 * `noopener` cannot be passed as a window feature here: it makes `window.open`
 * return null by design, and the handle is the whole point. `opener` is cleared
 * on the new window instead, which is the same protection.
 */
export async function openPrintWindow(getUrl, { onError } = {}) {
	// about:blank now, real URL in a moment. Opened inside the gesture.
	const win = window.open('', '_blank')
	if (win) {
		try {
			win.opener = null
		} catch {
			// Cross-origin restrictions on some browsers; the tab is still ours.
		}
		// Something to look at while the server renders the format.
		try {
			win.document.write('<title>Preparing…</title><p style="font:14px sans-serif">Preparing…</p>')
			win.document.close()
		} catch {
			// Not fatal — an empty tab for a moment is fine.
		}
	}

	try {
		const url = await getUrl()
		if (!url) throw new Error('No print URL returned')

		if (win) win.location.href = url
		// Popup blocked despite the gesture (some kiosk configurations block all
		// of them). Navigating the current tab is worse than a new one but far
		// better than nothing happening at all.
		else window.location.href = url

		return true
	} catch (e) {
		try {
			win?.close()
		} catch {
			/* already gone */
		}
		if (onError) onError(e)
		else console.error('[pos] print failed', e)
		return false
	}
}
