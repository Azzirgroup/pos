"""Tolerant searching for every list in the app.

The till already searches this way — see `frontend/src/utils/search.js`, which
this deliberately mirrors so a name typed at the counter and the same name typed
on the invoices screen find the same thing. The rules were written for a cashier
holding a bottle; they apply just as well to somebody half-remembering a
supplier.

Every back-office list used to send its box straight into one
`LIKE %whatever%`. That fails three ways a person actually types:

* **Word order.** `cocoa vaseline` finds nothing, `vaseline cocoa` finds it.
* **Punctuation.** `SAL-QTN-2026-00004` against a stored `SAL-QTN-2026-00004`
  is fine; `sal qtn 2026 4` is not, and both are the same request.
* **A missing letter.** `vaslin` finds nothing at all.

## Why it is two passes

Fuzzy matching cannot use an index — it has to look at candidate rows. Doing
that on every keystroke against a table with fifty thousand customers is exactly
the kind of thing that makes an app feel broken.

So: the indexed `LIKE` runs first and, when it finds a reasonable number of
rows, that is the answer. Only when it comes back thin does the caller widen to
a capped scan and rank in Python. A search that already works stays as fast as
it was; a search that used to fail now finds something.
"""

import re

#: Below this many hits, it is worth paying for a fuzzy pass.
FUZZY_FLOOR = 5

#: Never scan more than this in the widened pass, whatever the table holds.
FUZZY_SCAN_CAP = 2000

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_HAS_DIGIT = re.compile(r"\d")


def normalise(text) -> str:
	"""Lowercase, punctuation to spaces, whitespace collapsed."""
	return _NON_ALNUM.sub(" ", str(text or "").lower()).strip()


def tokenise(text) -> list:
	n = normalise(text)
	return n.split(" ") if n else []


def slack_for(token: str) -> int:
	"""How many edits a token of this length is allowed.

	Anything containing a digit gets none: `400ml` and `200ml` are one
	substitution apart and are two different products on the same shelf, and
	`SAL-QTN-…-00004` and `…-00005` are two different documents. Correcting a
	"typo" there hands somebody the wrong thing.
	"""
	if _HAS_DIGIT.search(token):
		return 0
	if len(token) <= 3:
		return 0
	if len(token) <= 5:
		return 1
	return 2


def within_distance(a: str, b: str, max_edits: int) -> bool:
	"""Damerau-Levenshtein, abandoned once it cannot come in under `max_edits`.

	Transpositions count as **one** edit, not two. That is the difference between
	finding `cocao lotion` and not: swapping two letters is the single most
	common way a person mistypes a word they know, and plain Levenshtein charges
	it as a delete plus an insert — which puts every transposed five-letter word
	outside the one-edit budget its length allows.
	"""
	if a == b:
		return True
	if abs(len(a) - len(b)) > max_edits:
		return False

	# Three rows, because a transposition looks back two.
	prev2 = None
	prev = list(range(len(a) + 1))
	for j in range(1, len(b) + 1):
		curr = [j] + [0] * len(a)
		best = curr[0]
		for i in range(1, len(a) + 1):
			cost = 0 if a[i - 1] == b[j - 1] else 1
			val = min(prev[i] + 1, curr[i - 1] + 1, prev[i - 1] + cost)
			if (
				prev2 is not None
				and i > 1
				and a[i - 1] == b[j - 2]
				and a[i - 2] == b[j - 1]
			):
				val = min(val, prev2[i - 2] + 1)
			curr[i] = val
			if val < best:
				best = val
		if best > max_edits:
			return False
		prev2, prev = prev, curr

	return prev[len(a)] <= max_edits


def fuzzy_hit(token: str, words: list) -> bool:
	slack = slack_for(token)
	if not slack:
		return False
	for w in words:
		if within_distance(token, w, slack):
			return True
		# Compare like for like, so a long word is not penalised for its length.
		if len(w) > len(token) and within_distance(token, w[: len(token)], slack):
			return True
	return False


def like_or_filters(search: str, fields: list) -> dict | None:
	"""The indexed fast path: `%search%` against each field, ORed.

	Unchanged behaviour from before, kept as the first pass because it is the
	one that uses an index.
	"""
	term = (search or "").strip()
	if not term:
		return None
	return {f: ("like", f"%{term}%") for f in fields}


def score_row(row, query_tokens: list, raw: str, fields: list) -> int:
	"""Tier for one row, or -1 for no match. Lower is better.

	The tiers mirror the till's, minus the barcode ones that only apply there.
	"""
	values = [str(row.get(f) or "") for f in fields]
	joined_raw = " ".join(values).lower()
	joined = normalise(" ".join(values))
	words = joined.split(" ") if joined else []

	if not raw:
		return 0
	if any(v.lower() == raw for v in values):
		return 0
	if any(v.lower().startswith(raw) for v in values):
		return 1
	if raw in joined_raw:
		return 2
	# Word order is not information: "cocoa vaseline" is one request.
	if query_tokens and all(t in joined for t in query_tokens):
		return 3
	if query_tokens and all(t in joined or fuzzy_hit(t, words) for t in query_tokens):
		return 4
	return -1


def rank(rows: list, search: str, fields: list) -> list:
	"""Filter and order `rows` by how well they match. Non-matches drop out."""
	raw = (search or "").strip().lower()
	if not raw:
		return rows

	tokens = tokenise(raw)
	scored = []
	for r in rows:
		s = score_row(r, tokens, raw, fields)
		if s >= 0:
			scored.append((s, r))

	scored.sort(key=lambda p: p[0])
	return [r for _, r in scored]


def search_rows(
	fetch,
	search: str,
	fields: list,
	limit: int = 100,
	rank_fields: list | None = None,
	key: str = "name",
) -> list:
	"""Run a list query tolerantly.

	`fetch(or_filters, page_length)` does the actual query — the caller owns its
	doctype, base filters, field list and ordering, all of which differ per
	screen. This owns only the matching.

	`fields` are **database columns**, used to build the indexed `LIKE`.
	`rank_fields` are the **keys on the returned rows**, used for the Python
	pass. They are usually the same, and differ wherever a query aliases a
	column — `name as item_code` being the common one here. Getting that wrong
	silently ranks every row against empty strings, so it is a parameter rather
	than an assumption.
	"""
	term = (search or "").strip()
	if not term:
		return fetch(None, limit)

	rank_on = rank_fields or fields

	rows = fetch(like_or_filters(term, fields), limit)
	if len(rows) >= FUZZY_FLOOR:
		return rows

	# Thin. Widen and rank — this is the pass that catches a typo, and the only
	# one that costs anything.
	wide = fetch(None, min(FUZZY_SCAN_CAP, max(limit * 20, 500)))
	ranked = rank(wide, term, rank_on)

	# The fast path's hits are already correct and already ordered; anything the
	# wide pass adds goes after them rather than reordering what was working.
	seen = {r.get(key) for r in rows}
	return rows + [r for r in ranked if r.get(key) not in seen][: max(0, limit - len(rows))]
