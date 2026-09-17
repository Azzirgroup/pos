import { ref } from 'vue'
import { setChartChrome } from './palette'

/**
 * Light or dark, chosen per device.
 *
 * Asked for because of eye strain: a till is stared at all day, often in a dim
 * shop, and a white screen at full brightness is what people were complaining
 * about. frappe-ui already carries a complete dark palette behind
 * `[data-theme="dark"]` — every `surface-*`, `ink-*` and `outline-*` token this
 * app is built from flips with it — so the theme is that attribute and nothing
 * more.
 *
 * Remembered in the browser rather than on the user: the same person may want
 * dark on the counter tablet and light on the office laptop. "System" follows
 * the device's own setting and is the default.
 */

const KEY = 'cosmetics:theme'
const CHOICES = ['light', 'dark', 'system']

function read() {
	try {
		const v = localStorage.getItem(KEY)
		return CHOICES.includes(v) ? v : 'system'
	} catch {
		return 'system'
	}
}

/** What the person picked. */
export const themeChoice = ref(read())
/** What is actually showing. */
export const activeTheme = ref('light')

const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null

function apply() {
	const dark = themeChoice.value === 'dark' || (themeChoice.value === 'system' && !!media?.matches)
	activeTheme.value = dark ? 'dark' : 'light'
	const root = document.documentElement
	root.setAttribute('data-theme', activeTheme.value)
	root.style.colorScheme = activeTheme.value
	document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#171717' : '#ffffff')
	setChartChrome(dark)
}

export function setTheme(choice) {
	if (!CHOICES.includes(choice)) return
	themeChoice.value = choice
	try {
		localStorage.setItem(KEY, choice)
	} catch {
		// Private window: the choice still applies for this visit.
	}
	apply()
}

/** Flip between light and dark, leaving "system" behind once touched. */
export function toggleTheme() {
	setTheme(activeTheme.value === 'dark' ? 'light' : 'dark')
}

/** Before mount, so the first paint is already in the right colours. */
export function initTheme() {
	apply()
	media?.addEventListener?.('change', () => {
		if (themeChoice.value === 'system') apply()
	})
}
