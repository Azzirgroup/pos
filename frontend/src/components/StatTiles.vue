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

/**
 * Shrink the figure until it fits, rather than cutting it off.
 *
 * These tiles were fixed at one size with `truncate`, which is the right
 * treatment for a label and the wrong one for a number: a shop with millions in
 * revenue saw "KES 7,987,…", where the digits that were dropped are the ones
 * that say how much. A truncated word can still be guessed at; a truncated
 * number cannot be read at all.
 *
 * Stepping the size down keeps every tile on one line and the band of tiles on
 * one baseline. The thresholds are in characters because that is what actually
 * decides whether it fits — "KES 723,150.00" and "644" want different sizes and
 * neither is knowable from the value alone.
 */
function valueSize(text) {
	const length = String(text ?? '').length
	// Two sizes per step: the roomy one from `lg` up, a smaller one below it,
	// where four tiles share a narrow screen and there is genuinely less room.
	if (length <= 11) return 'text-p-lg lg:text-p-xl'
	if (length <= 15) return 'text-p-base lg:text-p-lg'
	if (length <= 19) return 'text-p-sm lg:text-p-base'
	return 'text-p-xs lg:text-p-sm'
}

const TONES = {
	default: 'text-ink-gray-9',
	good: 'text-ink-green-3',
	warn: 'text-ink-amber-3',
	bad: 'text-ink-red-3',
}

/**
 * A plain count reads green.
 *
 * Asked for directly by the shop, and it holds up: a count is either something
 * there is or something there is not, so green-for-some / muted-for-none says
 * at a glance which of the two a tile is. Money keeps the fuller vocabulary in
 * `tone.js` — a large number of shillings is not automatically good news, and a
 * tile that says so about money owed would be lying.
 */
function valueTone(s) {
	if (s.tone && s.tone !== 'default') return TONES[s.tone]
	if (s.type === 'number') {
		return Number(s.value || 0) > 0 ? 'text-ink-green-3' : 'text-ink-gray-5'
	}
	return TONES.default
}

/**
 * The icon sits in a tinted chip rather than floating grey against the card.
 *
 * It is still a secondary channel — it repeats what the label says and never
 * carries meaning the label does not — but a plain grey outline on a tinted
 * card read as a smudge. The chip gives it an edge, and the tone colours it in
 * agreement with the number above it rather than independently.
 */
const ICON_CHIPS = {
	default: 'bg-violet-200 text-violet-600',
	good: 'bg-surface-green-2 text-ink-green-3',
	warn: 'bg-surface-amber-2 text-ink-amber-3',
	bad: 'bg-surface-red-2 text-ink-red-3',
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
	     Tabular figures so columns of digits line up as the values change.

	     Framed in violet rather than left as grey boxes on a grey page. The band
	     of tiles is the summary of the screen, so it is worth separating from the
	     table under it — and violet is the one hue the status vocabulary does not
	     use, so tinting every tile costs nothing: a red figure inside a violet
	     card still reads as the exception. -->
	<div
		class="grid shrink-0 gap-3 px-4 py-4"
		:class="dense ? 'grid-cols-2 sm:grid-cols-4 lg:grid-cols-4' : 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4'"
	>
		<div
			v-for="s in stats"
			:key="s.key || s.label"
			class="rounded-xl border border-violet-200 bg-surface-violet-1 px-4 py-3 shadow-sm"
		>
			<div class="flex items-center gap-3">
				<!-- Sized to the value, not to the label: the figure is what the tile
				     is for, and a chip half its height read as a bullet point beside
				     it rather than as part of it. -->
				<!-- Hidden below `lg`. On a narrow screen the chip was taking a third
				     of the tile from the figure it decorates, and it only ever repeats
				     what the label already says — so the number gets the room. -->
				<span
					v-if="resolveIcon(s.icon)"
					class="hidden h-10 w-10 shrink-0 place-items-center rounded-xl lg:grid"
					:class="ICON_CHIPS[s.tone || 'default']"
					aria-hidden="true"
				>
					<component :is="resolveIcon(s.icon)" class="h-5 w-5" />
				</span>
				<div class="min-w-0 flex-1">
					<div class="truncate text-p-xs text-ink-gray-6">{{ s.label }}</div>
					<!-- `truncate` stays, but only as a guard against a figure spilling
					     out over the card next to it — `valueSize` is what makes it fit
					     at any width a shop actually reads this on. `title` covers the
					     rest: a phone in portrait can still be held to see the whole
					     number. -->
					<div
						class="tabular mt-1 truncate font-semibold leading-tight"
						:class="[valueTone(s), valueSize(render(s))]"
						:title="render(s)"
					>
						{{ render(s) }}
					</div>
					<div v-if="s.delta || s.hint" class="mt-1 flex flex-wrap items-baseline gap-x-1.5">
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
