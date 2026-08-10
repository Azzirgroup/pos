/**
 * Matching what a cashier typed against what is on the shelf.
 *
 * A counter is not a search box. The person typing is looking at a bottle, has
 * a customer waiting, and is going from memory and a half-read label — so the
 * query is routinely a partial name in the wrong order with a letter missing:
 * `vaslin cocoa 400` for "Vaseline Cocoa Radiant 400ml". A substring match
 * finds none of that, and the item that is definitely in stock looks like it is
 * not.
 *
 * Three ideas, in order of cost:
 *
 * 1. **Normalise.** Case, punctuation and runs of whitespace are noise. `400ml`
 *    and `400 ML` and `400-ml` are the same thing to everyone except a string
 *    comparison.
 * 2. **Tokens, unordered.** Every word of the query has to appear somewhere in
 *    the item, but not in the order it was typed and not adjacently. This alone
 *    fixes most real misses.
 * 3. **Bounded edit distance**, and only where the cheaper tiers found little.
 *    Fuzzy matching over a whole catalog on every keystroke is exactly the kind
 *    of thing that makes a till feel slow, so it is a fallback, not the plan.
 */

/** Lowercase, strip punctuation, collapse whitespace. */
export function normalise(text) {
	return String(text || '')
		.toLowerCase()
		// Keep digits and letters; everything else becomes a break. `400ml` stays
		// one token, `400-ml` becomes two — both then match the same item.
		.replace(/[^a-z0-9]+/g, ' ')
		.trim()
}

export function tokenise(text) {
	const n = normalise(text)
	return n ? n.split(' ') : []
}

/**
 * Levenshtein distance, abandoned as soon as it cannot come in under `max`.
 *
 * The early exit is the whole point: comparing a 6-letter query token against a
 * 40-character product name is work that can be refused after two rows, and
 * refusing it is what keeps this usable per keystroke.
 */
export function withinDistance(a, b, max) {
	if (a === b) return true
	if (Math.abs(a.length - b.length) > max) return false

	const rows = a.length + 1
	let prev = new Array(rows)
	let curr = new Array(rows)
	for (let i = 0; i < rows; i++) prev[i] = i

	for (let j = 1; j <= b.length; j++) {
		curr[0] = j
		let best = curr[0]
		for (let i = 1; i < rows; i++) {
			const cost = a[i - 1] === b[j - 1] ? 0 : 1
			curr[i] = Math.min(prev[i] + 1, curr[i - 1] + 1, prev[i - 1] + cost)
			if (curr[i] < best) best = curr[i]
		}
		// Nothing in this row is close enough, and rows only ever grow.
		if (best > max) return false
		const swap = prev
		prev = curr
		curr = swap
	}

	return prev[a.length] <= max
}

/**
 * How much slack a token of this length gets.
 *
 * Scaled, because one wrong letter in `oil` is a different word while one wrong
 * letter in `vaseline` is a typo. A flat threshold either refuses real typos in
 * long names or turns every short token into a wildcard.
 */
export function slackFor(token) {
	// Anything with a digit in it is a size, a strength or a code, and one
	// character is the whole difference between them: `400ml` and `200ml` are a
	// substitution apart and are two different products on the same shelf.
	// Correcting a "typo" there hands the cashier the wrong bottle, so numeric
	// tokens have to match exactly — the same argument as short words below,
	// with more at stake.
	if (/\d/.test(token)) return 0
	if (token.length <= 3) return 0
	if (token.length <= 5) return 1
	return 2
}

/** Does `token` match any word of `words`, allowing for a typo? */
export function fuzzyHit(token, words) {
	const slack = slackFor(token)
	if (!slack) return false
	for (const w of words) {
		// A prefix that is already exact is handled by the cheaper tiers; here we
		// only care whether the shapes are close.
		if (withinDistance(token, w, slack)) return true
		// `vaslin` against `vaseline400ml` — compare against the same length so a
		// long word is not penalised for being long.
		if (w.length > token.length && withinDistance(token, w.slice(0, token.length), slack)) {
			return true
		}
	}
	return false
}
