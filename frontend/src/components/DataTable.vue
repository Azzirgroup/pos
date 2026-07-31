<script setup>
import { computed } from 'vue'
import { fmtMoney } from '@/utils/format'
import { Spinner, Badge, Button, Dropdown } from 'frappe-ui'
import { cellTone, rowTone, statusTheme, STATUS_KEYS } from '@/utils/tone'
import LucideMore from '~icons/lucide/more-horizontal'

const props = defineProps({
	/** [{ label, key, type: 'currency'|'number'|'text' }] */
	columns: { type: Array, default: () => [] },
	rows: { type: Array, default: () => [] },
	rowKey: { type: String, default: null },
	loading: { type: Boolean, default: false },
	emptyText: { type: String, default: 'Nothing to show' },
	/**
	 * Whether the table owns its own scrolling.
	 *
	 * True suits a full-page list, where the table is the thing that scrolls.
	 * False lets it size to its content so an enclosing page can scroll instead
	 * — a table that scrolls inside a card that scrolls inside a page gives the
	 * reader three bars and no idea which one moves what.
	 */
	scroll: { type: Boolean, default: true },
	/**
	 * Row actions, as [{ label, icon, theme, onClick(row) }] or a function of the
	 * row returning that. A trailing menu column is appended when present, so a
	 * list gains row actions by passing this and changing nothing else.
	 */
	actions: { type: [Array, Function], default: null },
	/** Row currently mid-action — shows a spinner in its menu button. */
	busyRow: { type: String, default: '' },
})

const emit = defineEmits(['row-click'])

/** The declared columns plus the menu, which is ours rather than the caller's. */
const allColumns = computed(() =>
	props.actions && props.columns.length
		? [...props.columns, { label: '', key: '_actions', type: 'text' }]
		: props.columns,
)

function actionsFor(row) {
	const list = typeof props.actions === 'function' ? props.actions(row) : props.actions
	return (list || []).filter(Boolean).map((a) => ({ ...a, onClick: () => a.onClick?.(row) }))
}

function cell(row, col) {
	const v = row[col.key]
	if (v === null || v === undefined || v === '') return '—'
	if (col.type === 'currency') return fmtMoney(v)
	if (col.type === 'number') return Number(v).toLocaleString()
	return v
}

// Numbers right-aligned so magnitudes are comparable down the column; text left.
const isNumeric = (col) => col.type === 'currency' || col.type === 'number'

/**
 * Row background, resolved to a single class string rather than Tailwind's
 * `odd:`/`even:` variants.
 *
 * Two rules compete for the same property — the zebra banding and a row that
 * wants attention — and as separate utilities they would have equal specificity,
 * leaving the winner to stylesheet order. Deciding it here in one place means
 * an attention row is never quietly repainted by the stripe underneath it.
 */
const TONE_ROWS = {
	bad: 'bg-surface-red-1 hover:bg-surface-red-2',
	warn: 'bg-surface-amber-1 hover:bg-surface-amber-2',
	good: 'bg-surface-green-1 hover:bg-surface-green-2',
}

function rowClass(row, index) {
	const tone = rowTone(row)
	if (tone && TONE_ROWS[tone]) return TONE_ROWS[tone]

	// Banding, not borders, is what lets the eye track one row across a wide
	// table. The hover is a step darker than either band so it reads on both.
	return index % 2
		? 'bg-surface-gray-1 hover:bg-surface-gray-2'
		: 'bg-surface-white hover:bg-surface-gray-2'
}

/**
 * A cancelled document is still worth listing — it is what you amend from — but
 * it should not read as live. The status badge already says so; this stops the
 * row competing for attention with the ones that still matter.
 */
const isVoid = (row) => row.docstatus === 2
</script>

<template>
	<div
		class="bg-surface-white"
		:class="scroll ? 'min-h-0 flex-1 overflow-auto' : 'overflow-x-auto'"
	>
		<div v-if="loading" class="grid h-40 place-items-center">
			<Spinner class="h-5 w-5" />
		</div>

		<div v-else-if="!rows.length" class="grid h-40 place-items-center px-6 text-center">
			<p class="text-p-sm text-ink-gray-5">{{ emptyText }}</p>
		</div>

		<table v-else class="w-full border-collapse text-p-sm">
			<!-- Sticky header: these tables run to hundreds of rows and the column
			     meaning has to survive scrolling. A step darker than the zebra so it
			     stays a header rather than becoming the first stripe. -->
			<!-- Sticky only when this table is the scroller. Pinned inside a page
			     that scrolls instead, the header would sit against the top of a
			     card that has already scrolled past. -->
			<thead :class="scroll ? 'sticky top-0 z-10 bg-surface-gray-2' : 'bg-surface-gray-2'">
				<tr>
					<th
						v-for="c in allColumns"
						:key="c.key"
						class="whitespace-nowrap border-b border-outline-gray-2 px-3 py-2 text-p-xs font-medium text-ink-gray-6"
						:class="isNumeric(c) ? 'text-right' : 'text-left'"
					>
						{{ c.label }}
					</th>
				</tr>
			</thead>
			<tbody>
				<tr
					v-for="(row, i) in rows"
					:key="rowKey ? row[rowKey] : i"
					class="transition-colors"
					:class="[rowClass(row, i), isVoid(row) ? 'text-ink-gray-5' : '']"
				>
					<td
						v-for="c in allColumns"
						:key="c.key"
						class="px-3 py-2 text-ink-gray-8"
						:class="[
							isNumeric(c) ? 'tabular text-right' : 'text-left',
							isVoid(row) ? 'text-ink-gray-5' : cellTone(c.key, row[c.key], row),
						]"
					>
						<slot :name="`cell-${c.key}`" :row="row" :value="row[c.key]">
							<!-- The menu column is ours, so it is drawn here rather than
							     left to every list to reimplement. Right-aligned: it is
							     the last column, and a left-aligned popover would run off
							     the table. -->
							<div v-if="c.key === '_actions'" class="flex justify-end">
								<Dropdown :options="actionsFor(row)" placement="right">
									<Button
										variant="ghost"
										:icon-left="LucideMore"
										:loading="busyRow === row.name"
										:aria-label="`Actions for ${row.name || 'this row'}`"
									/>
								</Dropdown>
							</div>
							<!-- Status-ish columns read better as a badge than as a word
							     coloured in place, and the label still carries the meaning. -->
							<Badge
								v-else-if="STATUS_KEYS.has(c.key) && row[c.key]"
								:theme="statusTheme(row[c.key])"
								variant="subtle"
								:label="String(row[c.key])"
							/>
							<template v-else>{{ cell(row, c) }}</template>
						</slot>
					</td>
				</tr>
			</tbody>
		</table>
	</div>
</template>
