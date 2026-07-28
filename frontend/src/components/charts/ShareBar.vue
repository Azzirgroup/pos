<script setup>
import { computed } from 'vue'
import { SERIES, seriesColor } from '@/utils/palette'
import { fmtMoney } from '@/utils/format'

/**
 * Part-to-whole across a handful of named things — which tenders the money
 * came in through.
 *
 * A stacked bar rather than a pie: the segments are read against one another,
 * and a pie makes close shares indistinguishable. Colour here is *identity*,
 * so the slots are assigned in fixed order — Cash keeps its colour when Card
 * has no takings that week.
 *
 * Nothing is written inside a segment. A thin slice cannot hold its own label
 * without being clipped, so every figure lives in the legend below, which is
 * also what keeps the two lighter slots readable against white.
 */
const props = defineProps({
	/** [{ mode, amount, share }] — sorted by the caller. */
	segments: { type: Array, default: () => [] },
	/** Past this many, the tail is folded rather than given new hues. */
	maxSlots: { type: Number, default: SERIES.length },
})

const shown = computed(() => {
	const list = props.segments.filter((s) => Number(s.amount) > 0)
	if (list.length <= props.maxSlots) return list

	const head = list.slice(0, props.maxSlots - 1)
	const tail = list.slice(props.maxSlots - 1)
	return [
		...head,
		{
			mode: 'Other',
			amount: tail.reduce((sum, s) => sum + Number(s.amount || 0), 0),
			share: tail.reduce((sum, s) => sum + Number(s.share || 0), 0),
		},
	]
})

const total = computed(() => shown.value.reduce((sum, s) => sum + Number(s.amount || 0), 0))

function pct(segment) {
	return total.value ? (Number(segment.amount) / total.value) * 100 : 0
}
</script>

<template>
	<div class="flex flex-col gap-3">
		<!-- 2px of surface between segments, not a stroke: a border round each
		     fill adds ink that is not data. -->
		<div class="flex h-6 w-full gap-[2px] overflow-hidden rounded">
			<div
				v-for="(segment, i) in shown"
				:key="segment.mode"
				class="h-full first:rounded-l last:rounded-r"
				:style="{ width: `${pct(segment)}%`, backgroundColor: seriesColor(i) }"
				:title="`${segment.mode}: ${fmtMoney(segment.amount)}`"
			/>
		</div>

		<ul class="flex flex-col gap-1">
			<li v-for="(segment, i) in shown" :key="segment.mode" class="flex items-baseline gap-2">
				<span
					class="mt-1 h-2.5 w-2.5 shrink-0 rounded-sm"
					:style="{ backgroundColor: seriesColor(i) }"
					aria-hidden="true"
				/>
				<span class="min-w-0 flex-1 truncate text-p-xs text-ink-gray-7">{{ segment.mode }}</span>
				<span class="tabular shrink-0 text-p-xs text-ink-gray-5">{{ pct(segment).toFixed(1) }}%</span>
				<span class="tabular w-24 shrink-0 text-right text-p-xs font-medium text-ink-gray-8">
					{{ fmtMoney(segment.amount) }}
				</span>
			</li>
		</ul>
	</div>
</template>
