/**
 * Colour rules shared by every table and report.
 *
 * Centralised so a negative number means the same thing on the sales list as it
 * does in a report — inconsistent colour is worse than none, because staff stop
 * trusting it.
 *
 * Colour is always secondary: the number is still readable in monochrome, and
 * status text still says what it says. Nothing is signalled by colour alone.
 *
 * The vocabulary is deliberately small:
 *
 *   red    — money owed, something negative, something late
 *   amber  — in flight, or at a threshold worth noticing
 *   green  — settled, complete, earned
 *   muted  — nothing has happened yet
 *
 * Identity columns (an item name, a warehouse, a supplier) are never coloured.
 * Colour on a name means nothing, and a page where everything is tinted is a
 * page where nothing stands out.
 */

/** Signed money: negative is bad, positive is earned. */
const MONEY_KEYS = new Set(['difference', 'margin', 'delta', 'net', 'profit'])

/** Keys where a bigger number is bad news rather than good. */
const DEBT_KEYS = new Set([
	'outstanding',
	'outstanding_amount',
	'shortfall',
	'days_overdue',
	'overdue',
	'payable',
	'owed',
])

/**
 * Keys where only a negative is worth colouring.
 *
 * Document lines are the reason this exists. A positive line amount is the
 * normal case, so painting every one of them green would make a page of
 * ordinary invoice rows look like a page of good news — and the eye stops
 * reading a colour that is always on. Negative still means what it means
 * everywhere else, so this narrows the rule rather than adding a second one.
 */
/**
 * Money you *have*, where a positive figure is genuinely good news.
 *
 * Split out of NEGATIVE_ONLY_KEYS because the reasoning there does not apply to
 * these. That rule exists because a page of ordinary invoice lines is all
 * positive, so colouring every one green makes a normal page look like a
 * celebration and the eye stops reading the colour. But an account balance, a
 * collected total or a stock valuation appears a handful of rows at a time and
 * is the whole point of the screen it is on — "what have we got" is exactly the
 * question, and green answers it at a glance.
 *
 * Line-item keys (`amount`, `rate`, `value`) stay negative-only for that
 * original reason. This is a narrower rule, not a reversal of it.
 */
const CREDIT_KEYS = new Set([
	'balance',
	'available',
	'available_qty',
	'cash_and_bank',
	'collected',
	'paid',
	'paid_amount',
	'received',
	'closing_amount',
	'opening_amount',
	'expected_amount',
	'taken',
	'revenue',
	'spend',
	'stock_value',
])

const NEGATIVE_ONLY_KEYS = new Set([
	'amount',
	'qty',
	'change_amount',
	'value_difference',
	'difference_amount',
	'allocated_amount',
	'valuation_rate',
	'price_list_rate',
	'basic_rate',
	'rate',
	'value',
])

/**
 * Percent-complete columns, where 100 means "no longer needs chasing".
 *
 * Zero is muted rather than amber: a purchase order that has received nothing
 * on the day it was raised is not a problem, and colouring it as one would put
 * a warning on every new order.
 */
const PROGRESS_KEYS = new Set([
	'per_received',
	'per_billed',
	'per_ordered',
	'per_delivered',
	'per_installed',
	'per_returned',
])

/** Dates that carry a promise, and so can be broken. */
const DUE_KEYS = new Set(['due_date'])
const SCHEDULE_KEYS = new Set(['schedule_date'])

const RED = 'text-ink-red-3 font-medium'
const AMBER = 'text-ink-amber-3'
const GREEN = 'text-ink-green-3'
const MUTED = 'text-ink-gray-5'

function isPast(value) {
	const date = new Date(value)
	if (Number.isNaN(date.getTime())) return false
	const today = new Date()
	today.setHours(0, 0, 0, 0)
	return date < today
}

function num(row, ...keys) {
	for (const key of keys) {
		if (row?.[key] !== undefined && row?.[key] !== null) return Number(row[key]) || 0
	}
	return null
}

/**
 * @param key   column key
 * @param value cell value
 * @param row   the whole row, when the table can supply it. Some rules cannot
 *              be right without it — a due date is only late if something is
 *              still owed, and "every past due date is red" would light up the
 *              entire history of a paid-up customer.
 */
export function cellTone(key, value, row = null) {
	if (value === null || value === undefined || value === '') return ''

	if (DUE_KEYS.has(key)) return dueTone(value, row)
	if (SCHEDULE_KEYS.has(key)) return scheduleTone(value, row)

	const n = Number(value)
	// Only status-ish columns get colour from their text. Matching words
	// anywhere would tint a customer called "Paid Ltd" green.
	if (Number.isNaN(n)) return STATUS_KEYS.has(key) ? statusTone(String(value)) : ''

	if (DEBT_KEYS.has(key)) return n > 0 ? RED : 'text-ink-gray-8'

	if (PROGRESS_KEYS.has(key)) {
		if (n >= 100) return GREEN
		if (n > 0) return AMBER
		return MUTED
	}

	// Money in hand: green when there is some, red when it has gone negative,
	// muted at zero — an empty account is a fact rather than a problem.
	if (CREDIT_KEYS.has(key)) {
		if (n < 0) return RED
		if (n > 0) return GREEN
		return MUTED
	}

	if (NEGATIVE_ONLY_KEYS.has(key)) return n < 0 ? RED : ''

	if (MONEY_KEYS.has(key) || key === 'margin_pct') {
		if (n < 0) return RED
		if (n > 0) return GREEN
		return 'text-ink-gray-6'
	}

	if (STOCK_KEYS.has(key)) return stockTone(n)

	return ''
}

/**
 * Every column that states a stock balance, so a count reads the same on the
 * inventory screen, the stock report and a warehouse dashboard. Previously only
 * two of them were coloured and the rest were plain, which made the colour look
 * arbitrary rather than meaningful.
 */
const STOCK_KEYS = new Set([
	'actual_qty',
	'projected_qty',
	'total_stock',
	'stock_qty',
	'reserved_qty',
	'received',
	'issued',
	'on_hand',
	'current_qty',
])

/**
 * Negative is impossible and therefore wrong; zero means nothing is on the
 * shelf. Anything positive is the ordinary case and stays uncoloured — a shop
 * with stock is not news, and colouring it would drown the two states that are.
 */
function stockTone(n) {
	if (n < 0) return RED
	if (n === 0) return AMBER
	return ''
}

function dueTone(value, row) {
	// Without the row there is no way to know whether it was ever settled, and
	// guessing wrong means colouring paid invoices as late.
	const owed = num(row, 'outstanding_amount', 'outstanding')
	if (owed === null || owed <= 0) return ''
	return isPast(value) ? RED : ''
}

function scheduleTone(value, row) {
	if (!isPast(value)) return ''
	const wanted = num(row, 'qty')
	const done = num(row, 'received_qty', 'ordered_qty', 'delivered_qty')
	if (wanted !== null && done !== null && done >= wanted) return ''
	return AMBER
}

/**
 * Badge theme for a status word.
 *
 * Matched on tokens rather than whole strings: ERPNext's status vocabulary is
 * long and compound ("Partly Paid and Discounted", "To Receive and Bill"), and
 * an exact-match list left most of them grey. Word boundaries keep it honest —
 * "Unpaid" must not match "Paid", and "Material Issue" must not match "Issued".
 *
 * Order matters, and the red and amber rules are checked first, because the
 * compound statuses contain the settled words too.
 */
const STATUS_RULES = [
	[/\b(overdue|cancelled|failed|stopped|return|returned|credit note|debit note)\b/, 'red'],
	[/\b(draft|queued|pending|unpaid|on hold|partly|partially|to bill|to receive|to deliver)\b/, 'orange'],
	[/\b(paid|completed|closed|received|submitted|ordered|delivered|issued|transferred|consolidated|open)\b/, 'green'],
]

export function statusTheme(value) {
	const v = String(value || '')
		.toLowerCase()
		.trim()
	if (!v) return 'gray'
	for (const [pattern, theme] of STATUS_RULES) {
		if (pattern.test(v)) return theme
	}
	return 'gray'
}

function statusTone(value) {
	return { green: GREEN, red: RED, orange: AMBER }[statusTheme(value)] || ''
}

/**
 * Columns rendered as a status badge rather than plain text.
 *
 * Two kinds live here: real states (`status`) and document kinds
 * (`stock_entry_type`, `payment_type`). Kinds come out grey, which is right —
 * a grey badge reads as a category, and a category is not a state.
 */
export const STATUS_KEYS = new Set([
	'status',
	'doctype',
	'type',
	'material_request_type',
	'stock_entry_type',
	'payment_type',
	'purpose',
	'reference_doctype',
])

/**
 * Row-level tone. Cell colour says which number is wrong; this says the whole
 * row wants attention, and is used sparingly for exactly that reason.
 *
 * `below` and `below_cost` are the existing flags from the reorder and pricing
 * screens; `_tone` lets an endpoint say so directly without inventing another
 * boolean per screen.
 */
export function rowTone(row) {
	if (!row) return null
	if (row._tone) return row._tone
	if (row.below || row.below_cost) return 'bad'
	return null
}
