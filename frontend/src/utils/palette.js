import { reactive } from 'vue'

/**
 * Chart colours.
 *
 * Separate from `tone.js` on purpose. `tone.js` answers "is this number good or
 * bad"; this answers "which series is this". Mixing the two is how a dashboard
 * ends up with a green bar that means *growth* next to a green bar that just
 * means *the third payment mode*.
 *
 * The categorical order is fixed, not cycled: a mode of payment keeps its
 * colour when another one is filtered out, so a reader who learned "Cash is
 * blue" is never misled. Past four series the tail folds into "Other" rather
 * than growing a fifth hue.
 *
 * Validated as a set against the surface these charts actually render on
 * (`bg-surface-white`, #ffffff): lightness band, chroma floor, colour-vision
 * separation (worst adjacent ΔE 9.1, target ≥ 8) and normal-vision separation
 * (worst 22.9, floor ≥ 15) all pass. Two of the four sit below 3:1 contrast
 * against white, so every chart using them ships visible labels and a table
 * view — colour never carries a value on its own.
 *
 * The series hues are mid-tones that hold on the dark surface as well. The
 * chrome — grid, axis, muted text, the surface itself — does not, so it is
 * swapped with the theme (see `setChartChrome`, called from `utils/theme`).
 */

/** Fixed categorical order. Index 0 is also the single-series default. */
export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']

const LIGHT_CHROME = {
	grid: '#e5e5e1',
	axis: '#c3c2b7',
	muted: '#898781',
	surface: '#ffffff',
}

const DARK_CHROME = {
	grid: '#343434',
	axis: '#4c4c4c',
	muted: '#a3a3a3',
	surface: '#171717',
}

/**
 * Everything that is context rather than subject. Reactive, so a chart already
 * on screen repaints when the theme changes.
 */
export const CHROME = reactive({ ...LIGHT_CHROME })

export function setChartChrome(dark) {
	Object.assign(CHROME, dark ? DARK_CHROME : LIGHT_CHROME)
}

/** Slot for the nth series, folded to the last slot rather than cycled. */
export function seriesColor(index) {
	return SERIES[Math.min(index, SERIES.length - 1)]
}

/**
 * Nice round axis maximum, so ticks read 0 / 2,000 / 4,000 rather than
 * 0 / 1,873 / 3,746. Returns 1 for an all-zero series so the geometry still
 * divides.
 */
export function niceMax(value) {
	const v = Number(value) || 0
	if (v <= 0) return 1
	const magnitude = 10 ** Math.floor(Math.log10(v))
	const steps = [1, 2, 2.5, 5, 10]
	return magnitude * (steps.find((s) => v <= magnitude * s) ?? 10)
}
