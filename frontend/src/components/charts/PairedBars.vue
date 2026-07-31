<script setup>
import { computed } from 'vue'
import { fmtMoney } from '@/utils/format'
import { seriesColor } from '@/utils/palette'

/**
 * Two measures per row, side by side.
 *
 * For the sections where the interesting thing is a *relationship* rather than
 * a magnitude — received against issued, ordered against received. A single bar
 * of the net figure hides which way a warehouse is running: net zero looks the
 * same whether nothing moved or a hundred came in and a hundred went out.
 *
 * Both bars are scaled against one maximum, so their lengths are comparable
 * across the whole chart and not just within a row.
 */
const props = defineProps({
	/** [{ label, a, b }] */
	rows: { type: Array, default: () => [] },
	aLabel: { type: String, default: 'A' },
	bLabel: { type: String, default: 'B' },
	type: { type: String, default: 'number' },
})

const max = computed(() =>
	Math.max(
		1,
		...props.rows.flatMap((r) => [Math.abs(Number(r.a) || 0), Math.abs(Number(r.b) || 0)]),
	),
)

function width(value) {
	// A floor of 1.5% so a small non-zero value is still visibly present rather
	// than reading as nothing at all.
	return `${Math.max(1.5, (Math.abs(Number(value) || 0) / max.value) * 100)}%`
}

function render(value) {
	return props.type === 'currency' ? fmtMoney(value) : Number(value || 0).toLocaleString()
}
</script>

<template>
	<div v-if="!rows.length" class="grid h-32 place-items-center">
		<p class="text-p-sm text-ink-gray-5">Nothing to show.</p>
	</div>

	<div v-else class="flex flex-col gap-3">
		<div class="flex items-center gap-4 text-p-xs text-ink-gray-6">
			<span class="flex items-center gap-1.5">
				<span class="h-2.5 w-2.5 rounded-sm" :style="{ background: seriesColor(0) }" />
				{{ aLabel }}
			</span>
			<span class="flex items-center gap-1.5">
				<span class="h-2.5 w-2.5 rounded-sm" :style="{ background: seriesColor(1) }" />
				{{ bLabel }}
			</span>
		</div>

		<div v-for="row in rows" :key="row.label" class="flex flex-col gap-1">
			<div class="flex items-baseline justify-between gap-2">
				<span class="min-w-0 truncate text-p-xs font-medium text-ink-gray-7">
					{{ row.label }}
				</span>
				<span class="tabular shrink-0 text-p-xs text-ink-gray-5">
					{{ render(row.a) }} / {{ render(row.b) }}
				</span>
			</div>
			<div class="flex flex-col gap-0.5">
				<div class="h-2 w-full overflow-hidden rounded-sm bg-surface-gray-2">
					<div
						class="h-full rounded-sm"
						:style="{ width: width(row.a), background: seriesColor(0) }"
					/>
				</div>
				<div class="h-2 w-full overflow-hidden rounded-sm bg-surface-gray-2">
					<div
						class="h-full rounded-sm"
						:style="{ width: width(row.b), background: seriesColor(1) }"
					/>
				</div>
			</div>
		</div>
	</div>
</template>
