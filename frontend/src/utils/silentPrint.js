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
/**
 * Width the hidden frame is laid out at, in CSS pixels.
 *
 * A4 at 96dpi. It matters more than it looks: the browser prints the frame's
 * document using the layout it already has, and a frame one pixel wide laid a
 * customer statement out **201px wide** — so the sheet came off the printer as
 * a narrow squeezed column with the money columns crowded together, which is
 * exactly what "a bit misaligned on prints" turned out to be. The frame is
 * still invisible; it is parked off-screen instead of being made tiny.
 */
const PAPER_WIDTH = 794
const PAPER_HEIGHT = 1123

function mountFrame(apply, onError, width = PAPER_WIDTH) {
	const frame = document.createElement('iframe')
	frame.setAttribute('aria-hidden', 'true')
	// Off the left edge rather than at 1×1: content with no room has no correct
	// layout, and what has no correct layout prints wrong. See `PAPER_WIDTH`.
	frame.style.cssText =
		`position:fixed;left:-10000px;top:0;width:${width}px;height:${PAPER_HEIGHT}px;opacity:0;border:0;pointer-events:none`

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

/**
 * A receipt roll, not a sheet of paper.
 *
 * Receipt formats size themselves in millimetres, so laying one out on a page
 * three times its width leaves the printed slip correct but the frame's own
 * layout nothing like it. Passed deliberately rather than left to the default
 * so the two kinds of printout are each laid out as what they are.
 */
const RECEIPT_WIDTH = 302 // 80mm at 96dpi

/** Print a URL — a Frappe printview, typically. */
export function printUrl(url, onError, { width } = {}) {
	mountFrame(
		(frame) => {
			frame.src = url
		},
		onError,
		width,
	)
}

/** Print a self-contained HTML string. */
export function printHtml(html, onError, { width } = {}) {
	mountFrame(
		(frame) => {
			frame.srcdoc = html
		},
		onError,
		width,
	)
}

export { PAPER_WIDTH, RECEIPT_WIDTH }
