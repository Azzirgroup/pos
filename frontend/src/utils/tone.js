/**
 * Colour rules shared by every table and report.
 *
 * Centralised so a negative number means the same thing on the sales list as it
 * does in a report — inconsistent colour is worse than none, because staff stop
 * trusting it.
 *
 * Colour is always secondary: the number is still readable in monochrome, and
 * status text still says what it says. Nothing is signalled by colour alone.
 */

const MONEY_KEYS = new Set([
	'outstanding',
	'outstanding_amount',
	'difference',
	'margin',
	'delta',
	'shortfall',
	'net',
])

/** Keys where a bigger number is bad news rather than good. */
const DEBT_KEYS = new Set(['outstanding', 'outstanding_amount', 'shortfall'])

export function cellTone(key, value) {
	if (value === null || value === undefined || value === '') return ''

	const n = Number(value)
	if (Number.isNaN(n)) return statusTone(String(value))

	if (DEBT_KEYS.has(key)) {
		return n > 0 ? 'text-ink-red-3 font-medium' : 'text-ink-gray-8'
	}

	if (MONEY_KEYS.has(key) || key === 'margin_pct') {
		if (n < 0) return 'text-ink-red-3 font-medium'
		if (n > 0) return 'text-ink-green-3'
		return 'text-ink-gray-6'
	}

	// Stock counts: zero and negative are the states worth noticing.
	if (key === 'actual_qty' || key === 'projected_qty') {
		if (n < 0) return 'text-ink-red-3 font-medium'
		if (n === 0) return 'text-ink-amber-3'
	}

	return ''
}

/** Badge theme for a status word, matching ERPNext's own vocabulary. */
export function statusTheme(value) {
	const v = String(value || '').toLowerCase()
	if (['paid', 'completed', 'received', 'closed', 'submitted', 'ordered'].includes(v)) return 'green'
	if (['overdue', 'cancelled', 'failed', 'stopped'].includes(v)) return 'red'
	if (['unpaid', 'pending', 'draft', 'queued', 'partly paid'].includes(v)) return 'orange'
	return 'gray'
}

function statusTone(value) {
	const theme = statusTheme(value)
	return { green: 'text-ink-green-3', red: 'text-ink-red-3', orange: 'text-ink-amber-3' }[theme] || ''
}

/** Columns rendered as a status badge rather than plain text. */
export const STATUS_KEYS = new Set(['status', 'material_request_type', 'type', 'doctype'])
