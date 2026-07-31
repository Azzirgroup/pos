<script setup>
import { computed } from 'vue'
import { SERIES } from '@/utils/palette'
import { fmtMoney } from '@/utils/format'

/**
 * Ranked magnitudes — best sellers, biggest debtors. One series, so one colour
 * for every bar: shading them light-to-dark would encode the length twice and
 * spend the only free channel on something the bar already says.
 *
 * The value sits at the tip of every bar, so this chart never needs a tooltip
 * to be readable; the hover title is for the full name when it truncates.
 */
const props = defineProps({
	/** [{ label, value, hint }] — already sorted by the caller. */
	rows: { type: Array, default: () => [] },
	type: { type: String, default: 'currency' },
})

const max = computed(() => Math.max(1, ...props.rows.map((r) => Math.abs(Number(r.value) || 0))))

function width(value) {
	return `${Math.max(1.5, (Math.abs(Number(value) || 0) / max.value) * 100)}%`
}

function render(value) {
	return props.type === 'currency' ? fmtMoney(value) : Number(value || 0).toLocaleString()
}
</script>

<template>
	<ul class="flex flex-col gap-2">
		<li v-for="row in rows" :key="row.label" class="grid grid-cols-[minmax(0,7rem)_1fr] items-center gap-3">
			<div class="min-w-0">
				<div class="truncate text-p-xs text-ink-gray-7" :title="row.label">{{ row.label }}</div>
				<div v-if="row.hint" class="truncate text-p-xs text-ink-gray-5">{{ row.hint }}</div>
			</div>

			<!-- Bar and its value share a row so the number reads as the bar's tip
			     rather than as a separate column of figures. -->
			<div class="flex min-w-0 items-center gap-2">
				<div class="min-w-0 flex-1">
					<div
						class="h-4 rounded-r"
						:style="{ width: width(row.value), backgroundColor: SERIES[0] }"
					/>
				</div>
				<span class="tabular shrink-0 text-p-xs font-medium text-ink-gray-7">
					{{ render(row.value) }}
				</span>
			</div>
		</li>
	</ul>
</template>
