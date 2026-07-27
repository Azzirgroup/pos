import { onMounted, onUnmounted } from 'vue'

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
 */
const MAX_KEY_GAP_MS = 40 // slower than this between keys = a human typing
const MIN_LENGTH = 4 // shorter than this = not a barcode

export function useScanner(onScan) {
	let buffer = ''
	let lastKeyAt = 0

	function handler(e) {
		// Let the cashier type normally in real inputs unless it arrives at
		// scanner speed — then it's a scan aimed at a focused field.
		const now = performance.now()
		const gap = now - lastKeyAt
		lastKeyAt = now

		if (e.key === 'Enter') {
			if (buffer.length >= MIN_LENGTH) {
				const code = buffer
				buffer = ''
				e.preventDefault()
				onScan(code)
				return
			}
			buffer = ''
			return
		}

		// Only printable single characters form part of a barcode.
		if (e.key.length !== 1) return

		if (gap > MAX_KEY_GAP_MS) buffer = ''
		buffer += e.key
	}

	onMounted(() => document.addEventListener('keydown', handler, true))
	onUnmounted(() => document.removeEventListener('keydown', handler, true))
}
