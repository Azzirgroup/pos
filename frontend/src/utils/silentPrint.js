/**
 * Print without a popup, straight to the till's printer.
 *
 * A cashier printing a receipt does not want a new browser tab, a preview and
 * a second click — they want paper. A popup also loses to blockers, which is a
 * browser setting nobody at a counter can reach.
 *
 * So the document is loaded into an off-screen iframe and printed from there.
 * An iframe is not a popup, so no blocker can refuse it, and the print dialog
 * opens against the printer the browser is already configured with — which on a
 * till is the receipt printer, usually set as the default.
 *
 * Lifted out of `Barcodes.vue`, which had already learned the two things that
 * make it work:
 *
 * * **Off-screen, not `display:none`.** A hidden frame has no layout in some
 *   browsers, and content with no layout prints blank.
 * * **Remove it after the dialog closes, not immediately.** Tearing the frame
 *   down while the dialog is open cancels the print in Safari.
 *
 * The browser still shows its own print dialog — no web page can bypass that.
 * "Automatic" here means no tab, no preview page, and no second navigation:
 * one tap, then the printer.
 */
function mountFrame(apply, onError) {
	const frame = document.createElement('iframe')
	frame.setAttribute('aria-hidden', 'true')
	frame.style.cssText =
		'position:fixed;right:0;bottom:0;width:1px;height:1px;opacity:0;border:0'

	frame.onload = () => {
		let removed = false
		const drop = () => {
			if (removed) return
			removed = true
			frame.remove()
		}

		try {
			const win = frame.contentWindow
			win.focus()
			// Torn down when the dialog actually closes, rather than one second
			// later regardless. A fixed timer is a guess about how long a person
			// spends looking at a print dialog, and removing the frame while it is
			// still open cancels the print — which is one of the ways "nothing
			// happens when I press print" comes about.
			win.addEventListener?.('afterprint', () => setTimeout(drop, 200))
			win.print()
		} catch (e) {
			onError?.(e)
			drop()
			return
		}

		// Backstop for browsers with no `afterprint`. Long, deliberately: the
		// frame is one pixel and invisible, so leaving it a while costs nothing,
		// while removing it early costs the printout.
		setTimeout(drop, 60_000)
	}
	frame.onerror = (e) => {
		onError?.(e)
		frame.remove()
	}

	apply(frame)
	document.body.appendChild(frame)
}

/** Print a URL — a Frappe printview, typically. */
export function printUrl(url, onError) {
	mountFrame((frame) => {
		frame.src = url
	}, onError)
}

/** Print a self-contained HTML string. */
export function printHtml(html, onError) {
	mountFrame((frame) => {
		frame.srcdoc = html
	}, onError)
}
