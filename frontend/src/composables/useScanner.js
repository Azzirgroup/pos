import { onMounted, onUnmounted } from 'vue'
import { looksLikeBarcode, checksumOk } from '@/utils/barcode'

/**
 * HID keyboard-wedge scanner capture.
 *
 * Nearly every retail barcode scanner presents as a keyboard: it "types" the
 * barcode then sends Enter. No drivers, no permissions, no native shell needed.
 * We distinguish a scan from a human by inter-keystroke timing — a scanner
 * emits characters far faster than fingers can.
 *
 * Deliberately listens on the document rather than a focused input, so a scan
 * registers no matter what the cashier last tapped.
 *
 * ## Why the timing rule is an average
 *
 * It used to reset the buffer the moment any single gap exceeded 40ms, which is
 * where the misreads came from. A scanner emits evenly, but the *browser* does
 * not deliver evenly: one Vue re-render, one garbage collection or one slow
 * frame between two keystrokes stretches a single gap past the threshold, and
 * the buffer was thrown away mid-code. The scan then arrived truncated —
 * "No item with barcode 6291" for a label reading 6291041500213 — which looks
 * exactly like a scanner that "sometimes doesn't work".
 *
 * The average gap across the whole sequence is what actually separates a
 * machine from a person, and it survives a blip. A new sequence is started only
 * on a gap long enough that it cannot be one hiccup.
 */
const AVG_GAP_MS = 55 // mean gap across the code; above this, a human typed it
const NEW_SEQUENCE_MS = 500 // a gap this long is a new scan, not a stutter
const MIN_LENGTH = 6 // shorter than this is not a product barcode

export function useScanner(onScan, { onMisread = null } = {}) {
	let buffer = ''
	let startedAt = 0
	let lastKeyAt = 0

	function reset() {
		buffer = ''
		startedAt = 0
	}

	function handler(e) {
		const now = performance.now()
		const gap = now - lastKeyAt
		lastKeyAt = now

		if (e.key === 'Enter') {
			const code = buffer
			const elapsed = now - startedAt
			reset()

			if (code.length < MIN_LENGTH) return

			// One character cannot have an average gap; anything this long did not
			// come from a person in the time available either way.
			const avgGap = code.length > 1 ? elapsed / (code.length - 1) : 0
			if (avgGap > AVG_GAP_MS) return

			// Enter belongs to the scan, not to whatever form is focused — without
			// this a scan into the search field also submits it.
			e.preventDefault()
			e.stopPropagation()

			if (!looksLikeBarcode(code)) {
				onMisread?.(code, 'shape')
				return
			}

			// A failed check digit means the read is wrong, not that the product is
			// unknown. Reporting it as a misread tells the cashier to scan again
			// rather than sending them hunting for an item that does not exist.
			if (!checksumOk(code)) {
				onMisread?.(code, 'checksum')
				return
			}

			onScan(code)
			return
		}

		// Only printable single characters form part of a barcode. Modifier keys
		// reach here first on a scanner that sends uppercase, and must not count
		// as content or as a break in the sequence.
		if (e.key.length !== 1) return

		if (gap > NEW_SEQUENCE_MS || !buffer) {
			buffer = ''
			startedAt = now
		}
		buffer += e.key
	}

	onMounted(() => document.addEventListener('keydown', handler, true))
	onUnmounted(() => document.removeEventListener('keydown', handler, true))
}
