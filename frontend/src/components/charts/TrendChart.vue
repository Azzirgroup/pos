<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CHROME, SERIES, niceMax } from '@/utils/palette'
import { fmtMoney } from '@/utils/format'

/**
 * Daily trend: one series, so one hue and no legend — the card title already
 * says what is plotted, and a legend box with a single swatch would just
 * restate it.
 *
 * Drawn at 1:1 with CSS pixels rather than scaled from a fixed viewBox, so the
 * 2px line stays 2px on a narrow screen instead of thinning to a hairline.
 */
const props = defineProps({
	/** [{ day, revenue, invoices }] — every day present, quiet ones as zero. */
	points: { type: Array, default: () => [] },
	valueKey: { type: String, default: 'revenue' },
	height: { type: Number, default: 200 },
})

const PAD = { top: 14, right: 18, bottom: 26, left: 62 }

const wrap = ref(null)
const width = ref(640)
let observer = null

onMounted(() => {
	observer = new ResizeObserver(([entry]) => {
		width.value = Math.max(240, Math.round(entry.contentRect.width))
	})
	observer.observe(wrap.value)
})
onBeforeUnmount(() => observer?.disconnect())

const plot = computed(() => ({
	w: Math.max(1, width.value - PAD.left - PAD.right),
	h: Math.max(1, props.height - PAD.top - PAD.bottom),
}))

const max = computed(() => niceMax(Math.max(0, ...props.points.map((p) => Number(p[props.valueKey]) || 0))))

/** Single point would have nothing to divide by; centre it instead. */
function xAt(i) {
	const n = props.points.length
	if (n <= 1) return PAD.left + plot.value.w / 2
	return PAD.left + (i / (n - 1)) * plot.value.w
}

function yAt(value) {
	return PAD.top + plot.value.h - (Math.max(0, Number(value) || 0) / max.value) * plot.value.h
}

const linePath = computed(() =>
	props.points.map((p, i) => `${i ? 'L' : 'M'}${xAt(i).toFixed(1)},${yAt(p[props.valueKey]).toFixed(1)}`).join(' '),
)

const areaPath = computed(() => {
	if (!props.points.length) return ''
	const baseline = PAD.top + plot.value.h
	return `${linePath.value} L${xAt(props.points.length - 1).toFixed(1)},${baseline} L${xAt(0).toFixed(1)},${baseline} Z`
})

// Three ticks carry the values that are not directly labelled. More than that
// on a card this size turns the plot into a grid.
const ticks = computed(() => [0, max.value / 2, max.value])

/**
 * Only as many date labels as fit without touching. Measured against a
 * generous width per label rather than the rendered text, because the cheap
 * over-estimate is the safe direction — a label that collides is worse than
 * one that is missing.
 */
const xLabels = computed(() => {
	const n = props.points.length
	if (!n) return []
	const fits = Math.max(2, Math.floor(plot.value.w / 70))
	const step = Math.max(1, Math.ceil(n / fits))
	const out = []
	for (let i = 0; i < n; i += step) out.push(i)
	if (out[out.length - 1] !== n - 1) out.push(n - 1)
	return out
})

const last = computed(() => props.points[props.points.length - 1] || null)

/* ---------- hover & keyboard cursor ---------- */

const cursor = ref(null)

function onMove(event) {
	if (!props.points.length) return
	const box = wrap.value.getBoundingClientRect()
	const x = event.clientX - box.left
	const n = props.points.length
	const ratio = (x - PAD.left) / plot.value.w
	cursor.value = Math.min(n - 1, Math.max(0, Math.round(ratio * (n - 1))))
}

function step(delta) {
	if (!props.points.length) return
	const next = (cursor.value ?? props.points.length - 1) + delta
	cursor.value = Math.min(props.points.length - 1, Math.max(0, next))
}

const active = computed(() => (cursor.value === null ? null : props.points[cursor.value]))

function fmt(value) {
	return props.valueKey === 'revenue' ? fmtMoney(value) : Number(value || 0).toLocaleString()
}

/** Short axis money: the currency is already established by the tooltip. */
function fmtAxis(value) {
	const n = Number(value) || 0
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 ? 1 : 0)}M`
	if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 ? 1 : 0)}K`
	return n.toLocaleString()
}

/** "12 Mar" — the year is implied by the period shown in the header. */
function fmtDay(day) {
	const d = new Date(day)
	return Number.isNaN(d.getTime()) ? day : `${d.getDate()} ${d.toLocaleString('en', { month: 'short' })}`
}

/** Keep the tooltip inside the card instead of letting it hang off the edge. */
const tooltipLeft = computed(() => {
	if (cursor.value === null) return 0
	return Math.min(Math.max(xAt(cursor.value), 70), Math.max(70, width.value - 70))
})
</script>

<template>
	<div ref="wrap" class="relative w-full">
		<svg
			:width="width"
			:height="height"
			class="block select-none"
			role="img"
			:aria-label="`Daily ${valueKey}. Switch to the table view for the figures.`"
			tabindex="0"
			@mousemove="onMove"
			@mouseleave="cursor = null"
			@focus="cursor = points.length - 1"
			@blur="cursor = null"
			@keydown.left.prevent="step(-1)"
			@keydown.right.prevent="step(1)"
		>
			<!-- Recessive chrome: solid hairlines one step off the surface. -->
			<g>
				<line
					v-for="t in ticks"
					:key="`grid-${t}`"
					:x1="PAD.left"
					:x2="PAD.left + plot.w"
					:y1="yAt(t)"
					:y2="yAt(t)"
					:stroke="t === 0 ? CHROME.axis : CHROME.grid"
					stroke-width="1"
				/>
				<text
					v-for="t in ticks"
					:key="`tick-${t}`"
					:x="PAD.left - 8"
					:y="yAt(t) + 4"
					text-anchor="end"
					class="tabular"
					:fill="CHROME.muted"
					font-size="11"
				>
					{{ fmtAxis(t) }}
				</text>
			</g>

			<path v-if="areaPath" :d="areaPath" :fill="SERIES[0]" fill-opacity="0.1" />
			<path
				v-if="linePath"
				:d="linePath"
				fill="none"
				:stroke="SERIES[0]"
				stroke-width="2"
				stroke-linejoin="round"
				stroke-linecap="round"
			/>

			<g>
				<text
					v-for="i in xLabels"
					:key="`x-${i}`"
					:x="xAt(i)"
					:y="PAD.top + plot.h + 17"
					:text-anchor="i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'"
					:fill="CHROME.muted"
					font-size="11"
				>
					{{ fmtDay(points[i].day) }}
				</text>
			</g>

			<!-- Endpoint marker, ringed in the surface colour so it stays legible
			     where it sits on the line. -->
			<template v-if="last">
				<circle
					:cx="xAt(points.length - 1)"
					:cy="yAt(last[valueKey])"
					r="4"
					:fill="SERIES[0]"
					:stroke="CHROME.surface"
					stroke-width="2"
				/>
			</template>

			<!-- Crosshair. One vertical rule and one dot: the value itself is in
			     the tooltip, and in the table view behind the toggle. -->
			<template v-if="cursor !== null && points[cursor]">
				<line
					:x1="xAt(cursor)"
					:x2="xAt(cursor)"
					:y1="PAD.top"
					:y2="PAD.top + plot.h"
					:stroke="CHROME.axis"
					stroke-width="1"
				/>
				<circle
					:cx="xAt(cursor)"
					:cy="yAt(points[cursor][valueKey])"
					r="4"
					:fill="SERIES[0]"
					:stroke="CHROME.surface"
					stroke-width="2"
				/>
			</template>
		</svg>

		<div
			v-if="active"
			class="pointer-events-none absolute z-10 -translate-x-1/2 rounded-md border border-outline-gray-2 bg-surface-white px-2 py-1 shadow-md"
			:style="{ left: `${tooltipLeft}px`, top: '0px' }"
		>
			<div class="whitespace-nowrap text-p-xs text-ink-gray-5">{{ fmtDay(active.day) }}</div>
			<div class="tabular whitespace-nowrap text-p-sm font-medium text-ink-gray-8">
				{{ fmt(active[valueKey]) }}
			</div>
			<div v-if="active.invoices !== undefined" class="whitespace-nowrap text-p-xs text-ink-gray-5">
				{{ active.invoices }} {{ active.invoices === 1 ? 'sale' : 'sales' }}
			</div>
		</div>
	</div>
</template>
