/**
 * EAN-13 rendered as actual bars.
 *
 * The label sheet used to print the digits and nothing else, which is why the
 * codes would not scan: a scanner reads the bar pattern, not the number under
 * it. The number is printed too, but only so a human can key it in when the
 * label is damaged — it is the caption, not the barcode.
 *
 * Drawn as inline SVG rather than with a barcode font, because a font has to be
 * installed on whatever machine opens the print window and silently falls back
 * to text when it is not — which is exactly the failure being fixed.
 */

// Left-hand odd (L), left-hand even (G) and right-hand (R) module patterns.
const L = [
	'0001101', '0011001', '0010011', '0111101', '0100011',
	'0110001', '0101111', '0111011', '0110111', '0001011',
]
const G = [
	'0100111', '0110011', '0011011', '0100001', '0011101',
	'0111001', '0000101', '0010001', '0001001', '0010111',
]
const R = [
	'1110010', '1100110', '1101100', '1000010', '1011100',
	'1001110', '1010000', '1000100', '1001000', '1110100',
]

/**
 * The first digit is not drawn as bars at all — it is encoded in the *parity*
 * of the next six. That is why EAN-13 fits 13 digits into 12 digits' worth of
 * bars, and why a renderer that ignores it produces a code that scans as the
 * wrong number rather than failing outright.
 */
const PARITY = [
	'LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG',
	'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL',
]

/** Check digit for the leading 12 digits; mirrors `api/barcodes.py`. */
export function checkDigit(body) {
	const total = [...body].reduce((sum, d, i) => sum + Number(d) * (i % 2 ? 3 : 1), 0)
	return String((10 - (total % 10)) % 10)
}

export function isValidEan13(code) {
	const value = String(code || '')
	return /^\d{13}$/.test(value) && checkDigit(value.slice(0, 12)) === value[12]
}

/**
 * Could this string be a barcode at all?
 *
 * Deliberately permissive about the alphabet — Code 128 and Code 39 carry
 * letters, and shops label their own shelf stock with all sorts — but strict
 * about the characters that never appear in a scan. Whitespace and control
 * characters mean the read was interrupted rather than short.
 */
export function looksLikeBarcode(code) {
	const value = String(code || '')
	return /^[A-Za-z0-9\-._$/+%]{6,48}$/.test(value)
}

/**
 * Verify the check digit, for the symbologies that carry one.
 *
 * EAN-13, EAN-8, UPC-A and UPC-E all end in a modulo-10 check digit computed
 * over the digits before it, so a misread almost always fails it. That is the
 * difference between "this scanned wrong, do it again" and sending somebody to
 * look for a product that was never on the shelf.
 *
 * Anything that is not a fixed-length all-numeric code returns true: Code 128
 * has no check digit a reader exposes, and refusing those would reject every
 * legitimate shelf label a shop prints for itself.
 */
export function checksumOk(code) {
	const value = String(code || '')
	if (!/^\d+$/.test(value)) return true
	// UPC-E uses a different expansion before the check digit is computed, so it
	// is left alone rather than checked with the wrong formula.
	if (![8, 12, 13].includes(value.length)) return true

	// UPC-A is EAN-13 with a leading zero, and EAN-8 uses the same alternating
	// weights — so one calculation covers all three once the weighting is taken
	// from the right-hand end rather than the left.
	const digits = [...value].map(Number)
	const check = digits.pop()
	const total = digits
		.reverse()
		.reduce((sum, d, i) => sum + d * (i % 2 === 0 ? 3 : 1), 0)
	return (10 - (total % 10)) % 10 === check
}

/** The 95-module bit string: guard, six left, centre, six right, guard. */
function modules(code) {
	const digits = [...code].map(Number)
	const parity = PARITY[digits[0]]

	let bits = '101'
	for (let i = 1; i <= 6; i++) {
		bits += (parity[i - 1] === 'L' ? L : G)[digits[i]]
	}
	bits += '01010'
	for (let i = 7; i <= 12; i++) {
		bits += R[digits[i]]
	}
	return bits + '101'
}

/**
 * Standalone SVG for one code, sized in millimetres so it prints at a physical
 * size a scanner can resolve rather than at whatever the screen felt like.
 *
 * Returns null for anything that is not a valid EAN-13 — better a label with no
 * barcode than one carrying bars that scan as a different product.
 */
export function ean13Svg(code, { moduleWidth = 0.33, height = 18 } = {}) {
	const value = String(code || '')
	if (!isValidEan13(value)) return null

	const bits = modules(value)
	// Guards run past the baseline; the human-readable digits sit in that band.
	const guards = new Set()
	for (const start of [0, 46, 92]) {
		for (let i = start; i < start + 3; i++) guards.add(i)
	}
	for (let i = 45; i < 50; i++) guards.add(i)

	const quiet = 11 * moduleWidth // mandatory quiet zone, in modules
	const width = bits.length * moduleWidth + quiet * 2
	const textY = height + 3.2
	const totalHeight = textY + 1

	let bars = ''
	for (let i = 0; i < bits.length; i++) {
		if (bits[i] !== '1') continue
		const x = (quiet + i * moduleWidth).toFixed(3)
		const h = guards.has(i) ? height + 2 : height
		bars += `<rect x="${x}" y="0" width="${moduleWidth}" height="${h}"/>`
	}

	// Digit groups sit where the standard puts them: one outside the left quiet
	// zone, then six under each half.
	const label = (text, x, anchor = 'middle') =>
		`<text x="${x.toFixed(2)}" y="${textY.toFixed(2)}" font-family="monospace" font-size="3.2" text-anchor="${anchor}">${text}</text>`

	const leftHalfMid = quiet + 3 * moduleWidth + 21 * moduleWidth
	const rightHalfMid = quiet + 50 * moduleWidth + 21 * moduleWidth

	return (
		`<svg xmlns="http://www.w3.org/2000/svg" width="${width.toFixed(2)}mm" height="${totalHeight.toFixed(2)}mm" ` +
		`viewBox="0 0 ${width.toFixed(2)} ${totalHeight.toFixed(2)}" shape-rendering="crispEdges">` +
		`<rect width="100%" height="100%" fill="#fff"/><g fill="#000">${bars}</g>` +
		label(value[0], quiet - moduleWidth, 'end') +
		label(value.slice(1, 7), leftHalfMid) +
		label(value.slice(7), rightHalfMid) +
		`</svg>`
	)
}
