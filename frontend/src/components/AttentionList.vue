<script setup>
import { computed } from 'vue'
import { fmtMoney } from '@/utils/format'
import { cellTone, rowTone } from '@/utils/tone'

/**
 * A short list in a narrow card.
 *
 * These sections sit three across, so a five-column table could not fit and
 * scrolled sideways — which hides the one column that matters, since the figure
 * a shortlist exists to show is always the last one. Reading "Overdue invoices"
 * meant dragging every row into view.
 *
 * So the same row is laid out vertically instead: what it is, what about it,
 * and the number. Nothing is dropped and nothing scrolls.
 *
 * It takes the same `{columns, rows}` contract as DataTable, so the server
 * describes its shortlist once and the front end decides how much room it has.
 */
const props = defineProps({
	columns: { type: Array, default: () => [] },
	rows: { type: Array, default: () => [] },
	emptyText: { type: String, default: 'Nothing to show' },
})

const isNumeric = (col) => col.type === 'currency' || col.type === 'number'

/**
 * The three roles a column can play here.
 *
 * The trailing figure is the last numeric column — currency if there is one,
 * because money outranks a count when both are present. The heading is the
 * first text column. Everything else becomes the meta line, in the order the
 * server declared it, which is the order it thought mattered.
 */
const layout = computed(() => {
	const cols = props.columns.filter((c) => c.key !== '_actions')
	const trailing =
		[...cols].reverse().find((c) => c.type === 'currency') ||
		[...cols].reverse().find((c) => c.type === 'number') ||
		null
	const heading = cols.find((c) => !isNumeric(c)) || cols[0] || null
	const meta = cols.filter((c) => c !== trailing && c !== heading)
	return { heading, trailing, meta }
})

function format(row, col) {
	if (!col) return ''
	const v = row[col.key]
	if (v === null || v === undefined || v === '') return '—'
	if (col.type === 'currency') return fmtMoney(v)
	if (col.type === 'number') return Number(v).toLocaleString()
	return String(v)
}

/**
 * Meta values carry their label only when the value cannot speak for itself.
 *
 * "Days late 12" needs the label; a warehouse name does not. Numbers are
 * ambiguous out of context and text usually is not, which is the whole rule.
 */
function metaText(row, col) {
	const value = format(row, col)
	if (value === '—') return null
	return isNumeric(col) ? `${col.label} ${value}` : value
}

function metaParts(row) {
	return layout.value.meta.map((c) => metaText(row, c)).filter(Boolean)
}

/** A row that already wants attention keeps its tint, as it would in a table. */
const TONE_ROWS = {
	bad: 'bg-surface-red-1',
	warn: 'bg-surface-amber-1',
	good: 'bg-surface-green-1',
}
</script>

<template>
	<div v-if="!rows.length" class="grid h-24 place-items-center px-6 text-center">
		<p class="text-p-sm text-ink-gray-5">{{ emptyText }}</p>
	</div>

	<ul v-else class="divide-y divide-outline-gray-1">
		<li
			v-for="(row, i) in rows"
			:key="row.name || i"
			class="flex items-start gap-3 px-3 py-2"
			:class="TONE_ROWS[rowTone(row)] || ''"
		>
			<div class="min-w-0 flex-1">
				<div class="truncate text-p-sm font-medium text-ink-gray-8">
					{{ format(row, layout.heading) }}
				</div>
				<!-- Wraps to a second line rather than truncating: on a shortlist the
				     meta is the reason the row is here, so losing the end of it costs
				     more than the extra height. -->
				<div v-if="metaParts(row).length" class="mt-0.5 text-p-xs leading-snug text-ink-gray-5">
					{{ metaParts(row).join(' · ') }}
				</div>
			</div>

			<div
				v-if="layout.trailing"
				class="tabular shrink-0 text-right text-p-sm font-semibold"
				:class="cellTone(layout.trailing.key, row[layout.trailing.key], row) || 'text-ink-gray-9'"
			>
				{{ format(row, layout.trailing) }}
			</div>
		</li>
	</ul>
</template>
