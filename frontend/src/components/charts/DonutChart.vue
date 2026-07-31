<script setup>
import { computed } from 'vue'
import { fmtMoney, fmtMoneyShort } from '@/utils/format'
import { SERIES, seriesColor } from '@/utils/palette'

/**
 * Composition, as a ring.
 *
 * For the question "what is this made of" — which account holds the cash, which
 * tender the money came through. A bar chart answers "which is biggest"; a ring
 * answers "how is the whole divided", and using one for the other makes a
 * reader work out the share themselves.
 *
 * Deliberately not used for rankings. Angles are hard to compare when several
 * slices are close, so anything where the ordering is the point stays a bar.
 *
 * The legend carries the figures, so nothing here depends on telling two
 * similar colours apart — which is the failure mode of every pie chart, and
 * worse for the roughly one in twelve men who cannot.
 */
const props = defineProps({
	/** [{ label, value }] — already sorted, largest first. */
	rows: { type: Array, default: () => [] },
	type: { type: String, default: 'currency' },
	/** Ring thickness as a fraction of the radius. */
	thickness: { type: Number, default: 0.38 },
})

const SIZE = 100
const R = 42

/**
 * At most one slice per validated palette slot, with the remainder folded into
 * a final "Other".
 *
 * `seriesColor` folds anything past the fourth into the last colour, so seven
 * slices would draw three of them identically — a chart that looks precise and
 * is not. Grouping the tail keeps every slice distinguishable and still totals
 * correctly.
 */
const usable = computed(() => {
	const rows = props.rows.filter((r) => Math.abs(Number(r.value) || 0) > 0)
	if (rows.length <= SERIES.length) return rows

	const head = rows.slice(0, SERIES.length - 1)
	const tail = rows.slice(SERIES.length - 1)
	return [
		...head,
		{
			label: `Other (${tail.length})`,
			value: tail.reduce((sum, r) => sum + (Number(r.value) || 0), 0),
		},
	]
})

const total = computed(() =>
	usable.value.reduce((sum, r) => sum + Math.abs(Number(r.value) || 0), 0),
)

/**
 * Slices as stroke-dash offsets around one circle.
 *
 * A circle with a dashed stroke draws an arc without any path arithmetic, and
 * — unlike a wedge path — degrades to a sensible shape at any size.
 */
const slices = computed(() => {
	const circumference = 2 * Math.PI * R
	let offset = 0
	return usable.value.map((row, i) => {
		const share = total.value ? Math.abs(Number(row.value) || 0) / total.value : 0
		const length = share * circumference
		const slice = {
			label: row.label,
			value: Number(row.value) || 0,
			share,
			colour: seriesColor(i),
			dash: `${length} ${circumference - length}`,
			offset: -offset,
		}
		offset += length
		return slice
	})
})

function render(value) {
	return props.type === 'currency' ? fmtMoney(value) : Number(value || 0).toLocaleString()
}
</script>

<template>
	<div v-if="!usable.length" class="grid h-32 place-items-center">
		<p class="text-p-sm text-ink-gray-5">Nothing to show.</p>
	</div>

	<div v-else class="flex flex-wrap items-center gap-4">
		<svg :viewBox="`0 0 ${SIZE} ${SIZE}`" class="h-[120px] w-[120px] shrink-0 -rotate-90">
			<circle
				v-for="s in slices"
				:key="s.label"
				:cx="SIZE / 2"
				:cy="SIZE / 2"
				:r="R"
				fill="none"
				:stroke="s.colour"
				:stroke-width="R * thickness * 2"
				:stroke-dasharray="s.dash"
				:stroke-dashoffset="s.offset"
			/>
			<!-- The total in the hole: the one number a composition chart is
			     otherwise missing, and the thing it is a composition *of*. -->
			<text
				:x="SIZE / 2"
				:y="SIZE / 2"
				class="rotate-90 fill-ink-gray-8 text-[9px] font-semibold"
				:style="{ transformOrigin: `${SIZE / 2}px ${SIZE / 2}px` }"
				text-anchor="middle"
				dominant-baseline="central"
			>
				{{ fmtMoneyShort(total) }}
			</text>
		</svg>

		<!-- Figures in the legend, so the chart never requires distinguishing two
		     similar colours to be read. -->
		<ul class="flex min-w-[140px] flex-1 flex-col gap-1">
			<li v-for="s in slices" :key="s.label" class="flex items-center gap-2 text-p-xs">
				<span class="h-2.5 w-2.5 shrink-0 rounded-sm" :style="{ background: s.colour }" />
				<span class="min-w-0 flex-1 truncate text-ink-gray-7">{{ s.label }}</span>
				<span class="tabular shrink-0 text-ink-gray-5">{{ Math.round(s.share * 100) }}%</span>
				<span class="tabular shrink-0 font-medium text-ink-gray-8">{{ render(s.value) }}</span>
			</li>
		</ul>
	</div>
</template>
