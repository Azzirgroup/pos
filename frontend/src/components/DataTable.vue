<script setup>
import { fmtMoney } from '@/utils/format'
import { Spinner, Badge } from 'frappe-ui'
import { cellTone, statusTheme, STATUS_KEYS } from '@/utils/tone'

defineProps({
	/** [{ label, key, type: 'currency'|'number'|'text' }] */
	columns: { type: Array, default: () => [] },
	rows: { type: Array, default: () => [] },
	rowKey: { type: String, default: null },
	loading: { type: Boolean, default: false },
	emptyText: { type: String, default: 'Nothing to show' },
})

function cell(row, col) {
	const v = row[col.key]
	if (v === null || v === undefined || v === '') return '—'
	if (col.type === 'currency') return fmtMoney(v)
	if (col.type === 'number') return Number(v).toLocaleString()
	return v
}

// Numbers right-aligned so magnitudes are comparable down the column; text left.
const isNumeric = (col) => col.type === 'currency' || col.type === 'number'
</script>

<template>
	<div class="min-h-0 flex-1 overflow-auto">
		<div v-if="loading" class="grid h-40 place-items-center">
			<Spinner class="h-5 w-5" />
		</div>

		<div v-else-if="!rows.length" class="grid h-40 place-items-center px-6 text-center">
			<p class="text-p-sm text-ink-gray-5">{{ emptyText }}</p>
		</div>

		<table v-else class="w-full border-collapse text-p-sm">
			<!-- Sticky header: these tables run to hundreds of rows and the column
			     meaning has to survive scrolling. -->
			<thead class="sticky top-0 z-10 bg-surface-gray-1">
				<tr>
					<th
						v-for="c in columns"
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
					class="border-b border-outline-gray-1 transition-colors hover:bg-surface-gray-1"
					:class="row.below || row.below_cost ? 'bg-surface-red-1' : ''"
				>
					<td
						v-for="c in columns"
						:key="c.key"
						class="px-3 py-2 text-ink-gray-8"
						:class="[isNumeric(c) ? 'tabular text-right' : 'text-left', cellTone(c.key, row[c.key])]"
					>
						<slot :name="`cell-${c.key}`" :row="row" :value="row[c.key]">
							<!-- Status-ish columns read better as a badge than as a word
							     coloured in place, and the label still carries the meaning. -->
							<Badge
								v-if="STATUS_KEYS.has(c.key) && row[c.key]"
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
