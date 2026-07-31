import { ref } from 'vue'
import { fmtMoney } from '@/utils/format'
import LucideSend from '~icons/lucide/send'
import LucideCopy from '~icons/lucide/copy'

/**
 * Row actions for any list.
 *
 * Written once because there is nothing list-specific about "share this row" —
 * a customer with a balance, a stock line below reorder and an overdue invoice
 * are all a set of labelled values somebody wants to send to somebody else. The
 * documents hub had this and nothing else did, which meant the only way to pass
 * on a number was to read it down the phone.
 *
 * The message is composed from the columns the list is already rendering, so
 * what gets sent is what was on screen — same labels, same formatting, same
 * filters. Rebuilding it from the row's raw fields would quietly produce a
 * different set of numbers.
 */

/** Format one value the way its column renders it. */
function formatValue(row, col) {
	const v = row[col.key]
	if (v === null || v === undefined || v === '') return '—'
	if (col.type === 'currency') return fmtMoney(v)
	if (col.type === 'number') return Number(v).toLocaleString()
	return String(v)
}

/**
 * One row as a WhatsApp message.
 *
 * Labelled lines rather than a table: the reader is on a phone, and columns
 * that wrap are harder to read than a short list. Empty values are dropped —
 * a screenful of "—" says nothing worth sending.
 */
export function rowToMessage(row, columns, { title } = {}) {
	const lines = []
	if (title) lines.push(`*${title}*`)

	for (const col of columns) {
		if (!col.label || col.key === '_actions') continue
		const value = formatValue(row, col)
		if (value === '—') continue
		lines.push(`${col.label}: ${value}`)
	}

	return lines.join('\n')
}

/**
 * A whole list as one message.
 *
 * Capped, and it says so when it caps. A silently truncated list reads as the
 * complete answer, which is how somebody ends up chasing nine of eleven
 * overdue invoices believing they are done.
 */
/**
 * A fixed-width table inside a WhatsApp code block.
 *
 * Triple backticks are the only way to get columns that line up on a phone —
 * WhatsApp renders them monospace, and in proportional text any amount of
 * padding comes out ragged. Mirrors `notifications._table` on the server so a
 * shared list and a stock request look like the same application.
 */
function asTable(headers, rows) {
	const widths = headers.map((h, i) =>
		Math.max(h.length, ...rows.map((r) => String(r[i] ?? '').length)),
	)
	const line = (cells) =>
		cells
			.map((c, i) => (i === cells.length - 1 ? String(c) : String(c).padEnd(widths[i])))
			.join('  ')
			.trimEnd()

	return [
		'```',
		line(headers),
		line(widths.map((w) => '-'.repeat(w))),
		...rows.map(line),
		'```',
	].join('\n')
}

/**
 * A whole list as one message.
 *
 * Capped, and it says so when it caps. A silently truncated list reads as the
 * complete answer, which is how somebody ends up chasing nine of eleven
 * overdue invoices believing they are done.
 *
 * Rendered as a table rather than as repeated label/value blocks: a list is
 * read by comparing rows, and twenty stacked blocks make that impossible.
 * Columns are capped at four — a phone is narrow, and the fifth column is what
 * makes the whole table wrap and stop lining up.
 */
export function rowsToMessage(rows, columns, { title, limit = 20 } = {}) {
	const shown = rows.slice(0, limit)
	const cols = columns.filter((c) => c.label && c.key !== '_actions').slice(0, 4)

	const lines = title ? [`*${title}*`, ''] : []
	lines.push(
		asTable(
			cols.map((c) => c.label),
			shown.map((row) =>
				cols.map((c) => {
					const v = formatValue(row, c)
					// Long text breaks the column for every row beneath it.
					return v.length <= 18 ? v : `${v.slice(0, 17)}…`
				}),
			),
		),
	)

	if (rows.length > shown.length) {
		lines.push('')
		lines.push(`…and ${rows.length - shown.length} more not listed here.`)
	}

	return lines.join('\n').trim()
}

/**
 * Wire a list up with row actions.
 *
 * `columns` is a getter rather than a value so a list whose columns change with
 * its filters — which most of them do — shares what is on screen now rather
 * than what was there when the page loaded.
 *
 * `documentFor` maps a row to {doctype, name} where one exists, which upgrades
 * the share from text to the real PDF. Lists whose rows are not documents (a
 * stock balance, a price) simply do not pass it.
 */
export function useRowActions({ columns, title, documentFor = null, extra = null } = {}) {
	const shareOpen = ref(false)
	const sharePayload = ref(null)

	/**
	 * `message` overrides the generated summary — for actions that are asking
	 * for something rather than passing on a row, like chasing a balance.
	 * Passed in rather than patched afterwards so the payload is complete before
	 * the sheet ever sees it.
	 */
	function shareRow(row, { message = null, title: heading = null } = {}) {
		const cols = typeof columns === 'function' ? columns() : columns || []
		const label = heading || (typeof title === 'function' ? title(row) : title)
		const doc = documentFor?.(row) || {}

		sharePayload.value = {
			title: label || 'Share',
			message: message || rowToMessage(row, cols, { title: label }),
			doctype: doc.doctype || null,
			name: doc.name || null,
		}
		shareOpen.value = true
	}

	function shareList(rows, heading) {
		const cols = typeof columns === 'function' ? columns() : columns || []
		sharePayload.value = {
			title: heading || 'Share list',
			message: rowsToMessage(rows, cols, { title: heading }),
			doctype: null,
			name: null,
		}
		shareOpen.value = true
	}

	async function copyRow(row) {
		const cols = typeof columns === 'function' ? columns() : columns || []
		try {
			await navigator.clipboard.writeText(rowToMessage(row, cols))
		} catch {
			// Clipboard access is refused outside a secure context. Sharing still
			// works, so this fails quietly rather than raising an error about a
			// permission the cashier cannot grant.
		}
	}

	/** Passed straight to DataTable's `actions` prop. */
	function actionsFor(row) {
		return [
			{ label: 'Share on WhatsApp', icon: LucideSend, onClick: () => shareRow(row) },
			{ label: 'Copy', icon: LucideCopy, onClick: () => copyRow(row) },
			...(extra?.(row) || []),
		]
	}

	return { shareOpen, sharePayload, shareRow, shareList, copyRow, actionsFor }
}
