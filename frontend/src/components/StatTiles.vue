<script setup>
import { fmtMoney } from '@/utils/format'

defineProps({
	/** [{ label, value, type: 'currency'|'number'|'text', tone }] */
	stats: { type: Array, default: () => [] },
})

function render(s) {
	if (s.type === 'currency') return fmtMoney(s.value)
	if (s.type === 'number') return Number(s.value || 0).toLocaleString()
	return s.value ?? '—'
}

const TONES = {
	default: 'text-ink-gray-9',
	good: 'text-ink-green-3',
	warn: 'text-ink-amber-3',
	bad: 'text-ink-red-3',
}
</script>

<template>
	<!-- Numbers first: a manager opening a screen wants the total before the rows.
	     Tabular figures so columns of digits line up as the values change. -->
	<div class="grid shrink-0 grid-cols-2 gap-2 px-4 py-3 sm:grid-cols-3 lg:grid-cols-4">
		<div
			v-for="s in stats"
			:key="s.label"
			class="rounded-lg border border-outline-gray-2 bg-surface-white px-3 py-2.5"
		>
			<div class="truncate text-p-xs text-ink-gray-5">{{ s.label }}</div>
			<div
				class="tabular mt-0.5 truncate text-p-xl font-semibold"
				:class="TONES[s.tone || 'default']"
			>
				{{ render(s) }}
			</div>
		</div>
	</div>
</template>
