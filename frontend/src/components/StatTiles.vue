<script setup>
import { fmtMoney } from '@/utils/format'
import { resolveIcon } from '@/utils/icons'

defineProps({
	/**
	 * [{ label, value, type: 'currency'|'number'|'text', tone, icon, hint,
	 *    delta, delta_good: 'up'|'down' }]
	 */
	stats: { type: Array, default: () => [] },
	/** Tighter grid for a dashboard that shows eight of these at once. */
	dense: { type: Boolean, default: false },
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

// The icon is a quiet, secondary channel: it repeats what the label says so the
// tile is scannable, and it never carries meaning the label does not.
const ICON_TONES = {
	default: 'text-ink-gray-4',
	good: 'text-ink-green-2',
	warn: 'text-ink-amber-2',
	bad: 'text-ink-red-2',
}

/**
 * A delta is good or bad depending on the tile, not on its sign: revenue up is
 * good, money owed up is not. `delta_good` says which way is which, so the
 * arrow and the colour agree — and the sign is printed either way, so the
 * change is readable without the colour.
 */
function deltaTone(s) {
	if (!s.delta) return 'text-ink-gray-5'
	const rising = Number(s.delta) > 0
	const goodWayIsUp = (s.delta_good || 'up') === 'up'
	return rising === goodWayIsUp ? 'text-ink-green-3' : 'text-ink-red-3'
}

function deltaLabel(s) {
	const n = Number(s.delta)
	return `${n > 0 ? '↑' : '↓'} ${Math.abs(n).toLocaleString()}%`
}
</script>

<template>
	<!-- Numbers first: a manager opening a screen wants the total before the rows.
	     Tabular figures so columns of digits line up as the values change. -->
	<div
		class="grid shrink-0 gap-2 px-4 py-3"
		:class="dense ? 'grid-cols-2 sm:grid-cols-4 lg:grid-cols-4' : 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4'"
	>
		<div
			v-for="s in stats"
			:key="s.key || s.label"
			class="rounded-lg border border-outline-gray-2 bg-surface-white px-3 py-2.5"
		>
			<div class="flex items-start gap-2">
				<component
					:is="resolveIcon(s.icon)"
					v-if="resolveIcon(s.icon)"
					class="mt-0.5 h-4 w-4 shrink-0"
					:class="ICON_TONES[s.tone || 'default']"
					aria-hidden="true"
				/>
				<div class="min-w-0 flex-1">
					<div class="truncate text-p-xs text-ink-gray-5">{{ s.label }}</div>
					<div
						class="tabular mt-0.5 truncate text-p-xl font-semibold"
						:class="TONES[s.tone || 'default']"
					>
						{{ render(s) }}
					</div>
					<div v-if="s.delta || s.hint" class="mt-0.5 flex flex-wrap items-baseline gap-x-1.5">
						<span v-if="s.delta" class="tabular text-p-xs font-medium" :class="deltaTone(s)">
							{{ deltaLabel(s) }}
						</span>
						<span v-if="s.hint" class="truncate text-p-xs text-ink-gray-5">{{ s.hint }}</span>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
