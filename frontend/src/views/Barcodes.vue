<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Badge, Button, FormControl } from 'frappe-ui'
import { generateBarcodes, listBarcodeItems } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
import { ean13Svg } from '@/utils/barcode'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'
import LucideBarcode from '~icons/lucide/barcode'
import LucidePrinter from '~icons/lucide/printer'

/**
 * Barcodes for the items that came without one.
 *
 * The generated codes start with 2, the range GS1 keeps for a shop's own use,
 * so nothing minted here can ever collide with a code printed on a supplier's
 * carton. They are written to the item's own `Item Barcode` table, which is
 * where the till already looks — a code generated here scans at the counter as
 * soon as the catalog reloads.
 */
const rows = ref([])
const barcodeType = ref(null)
const search = ref('')
const onlyMissing = ref(true)
const loading = ref(false)
const working = ref(false)
const selected = ref(new Set())
const lastRun = ref(null)

onMounted(load)

let timer = null
watch([search, onlyMissing], () => {
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	loading.value = true
	try {
		const data = await listBarcodeItems({ search: search.value, onlyMissing: onlyMissing.value })
		rows.value = data.rows || []
		barcodeType.value = data.barcode_type
		// Selections refer to rows that may no longer be listed.
		selected.value = new Set()
		// A code that has just been generated needs drawing, and a code that was
		// changed upstream must not keep showing the bars it used to have.
		barCache.clear()
	} catch (e) {
		notify(e.message || 'Could not load items', 'bad')
		rows.value = []
	} finally {
		loading.value = false
	}
}

const missing = computed(() => rows.value.filter((r) => !r.barcode_count))

/** Selected rows that already carry a code, i.e. ones worth reprinting. */
const printableSelected = computed(
	() => rows.value.filter((r) => selected.value.has(r.item_code) && r.barcode).length,
)
const allSelected = computed(
	() => missing.value.length > 0 && selected.value.size === missing.value.length,
)

const COLUMNS = [
	{ label: '', key: '_pick', type: 'text' },
	{ label: 'Item', key: 'item_name', type: 'text' },
	{ label: 'Code', key: 'item_code', type: 'text' },
	{ label: 'Group', key: 'item_group', type: 'text' },
	{ label: 'Barcode', key: 'barcode', type: 'text' },
]

/**
 * Sharing a barcode is how a code reaches whoever is printing labels on the
 * other machine. The pick column is dropped from the message — a checkbox is
 * not information once the row has left the screen.
 */
const { shareOpen, sharePayload, shareList, actionsFor } = useRowActions({
	columns: COLUMNS.filter((c) => c.key !== '_pick'),
	title: (row) => row.item_name || row.item_code,
})

const stats = computed(() => [
	{ key: 'listed', label: 'Items listed', value: rows.value.length, type: 'number', icon: 'boxes' },
	{
		key: 'missing',
		label: 'Without a barcode',
		value: missing.value.length,
		type: 'number',
		icon: 'alert',
		tone: missing.value.length ? 'warn' : 'good',
	},
	{
		key: 'selected',
		label: 'Selected',
		value: selected.value.size,
		type: 'number',
		icon: 'barcode',
		hint: barcodeType.value ? `will be written as ${barcodeType.value}` : null,
	},
])

function toggleAll() {
	selected.value = allSelected.value
		? new Set()
		: new Set(missing.value.map((r) => r.item_code))
}

function toggle(code) {
	const next = new Set(selected.value)
	next.has(code) ? next.delete(code) : next.add(code)
	selected.value = next
}

async function generate() {
	if (!selected.value.size) return
	working.value = true
	try {
		const res = await generateBarcodes({ itemCodes: [...selected.value] })
		lastRun.value = res
		await load()
		const parts = []
		if (res.created) parts.push(`${res.created} generated`)
		if (res.skipped) parts.push(`${res.skipped} already had one`)
		notify(parts.join(', ') || 'Nothing to generate', res.created ? 'good' : 'bad')
	} catch (e) {
		notify(e.message || 'Could not generate barcodes', 'bad')
	} finally {
		working.value = false
	}
}

/**
 * Hands the labels to the browser's own print dialog, as real bars.
 *
 * This used to print the digits only, which is why the labels would not scan —
 * a scanner reads the bar pattern, not the number under it. The bars are inline
 * SVG rather than a barcode font, because a font has to be installed on
 * whichever machine opens the print window and falls back silently to text when
 * it is not.
 *
 * Prints whatever is selected, or the codes just generated — reprinting a lost
 * label is at least as common as printing a new one.
 */
function printLabels() {
	const madeNow = (lastRun.value?.rows || []).filter((r) => r.created)
	const chosen = rows.value.filter((r) => selected.value.has(r.item_code) && r.barcode)
	const made = chosen.length ? chosen : madeNow

	if (!made.length) {
		notify('Select rows that already have a barcode, or generate some first', 'bad')
		return
	}

	const unprintable = made.filter((r) => !ean13Svg(r.barcode))
	const labels = made
		.map((r) => {
			const svg = ean13Svg(r.barcode)
			return `<div class="label">
				<div class="name">${escapeHtml(r.item_name)}</div>
				${svg || `<div class="code">${escapeHtml(r.barcode)}</div>`}
				<div class="sku">${escapeHtml(r.item_code)}</div>
			</div>`
		})
		.join('')

	// Said out loud rather than printed as a silently unscannable label: a code
	// this cannot draw is one an older import wrote in some other format.
	if (unprintable.length) {
		notify(`${unprintable.length} code${unprintable.length === 1 ? '' : 's'} are not EAN-13 — printed as text only`, 'bad')
	}

	const html = `<!doctype html><html><head><title>Barcode labels</title><style>
		body { font-family: system-ui, sans-serif; margin: 10mm; }
		.sheet { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4mm; }
		.label {
			border: 1px solid #c3c2b7; border-radius: 2px; padding: 3mm;
			text-align: center; break-inside: avoid; page-break-inside: avoid;
		}
		.name {
			font-size: 8pt; font-weight: 600; margin-bottom: 1.5mm;
			overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
		}
		.label svg { display: block; margin: 0 auto; }
		.code { font-family: ui-monospace, monospace; font-size: 12pt; letter-spacing: 1px; }
		.sku { font-size: 7pt; color: #52514e; margin-top: 1mm; }
		/* Bars must print solid black: a browser "saving ink" produces a grey
		   pattern that scanners read unreliably or not at all.

		   Scoped to .ean-bars, never to every rect in the svg. The barcode's
		   white background is a rect too, so the unscoped version painted the
		   whole label solid black — a barcode with no white space is not a
		   barcode, and every sheet came out as a row of black boxes.

		   print-color-adjust tells the browser not to lighten it back: a barcode
		   is not decoration, and a grey approximation does not scan. */
		svg .ean-bg { fill: #fff; }
		svg .ean-bars rect { fill: #000; }
		@media print {
			body { margin: 5mm; }
			.label { border-color: #999; }
			svg { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
			svg .ean-bg { fill: #fff !important; }
			svg .ean-bars rect { fill: #000 !important; }
		}
		@page { margin: 8mm; }
	</style></head><body><div class="sheet">${labels}</div></body></html>`

	printHtml(html)
}

/**
 * Print a document that is not this one.
 *
 * Through a hidden iframe rather than a popup window, because the popup did not
 * work at all: `window.open` was called with `noopener`, and per the spec that
 * makes it **return null** — there is no handle to write the labels into. So the
 * function always took the "allow pop-ups" branch and no label was ever printed,
 * whether or not pop-ups were actually blocked.
 *
 * An iframe is the better fix rather than just dropping the flag: it is not a
 * popup, so no blocker can refuse it, and nothing depends on the user having
 * allowed one for this site.
 *
 * `srcdoc` rather than `document.write` so the load event is reliable — that is
 * what tells us the SVG has laid out, which the old 250ms guess did not.
 */
function printHtml(html) {
	const frame = document.createElement('iframe')
	// Off-screen rather than display:none — a hidden frame has no layout in some
	// browsers, and a barcode with no layout prints as a blank box.
	frame.setAttribute('aria-hidden', 'true')
	frame.style.position = 'fixed'
	frame.style.right = '0'
	frame.style.bottom = '0'
	frame.style.width = '1px'
	frame.style.height = '1px'
	frame.style.opacity = '0'
	frame.style.border = '0'

	frame.onload = () => {
		try {
			frame.contentWindow.focus()
			frame.contentWindow.print()
		} catch (e) {
			notify('Could not open the print dialog', 'bad')
			console.error('[barcodes] print failed', e)
		}
		// Removed after the dialog closes rather than immediately: tearing the
		// frame down while the dialog is open cancels the print in Safari.
		setTimeout(() => frame.remove(), 1000)
	}

	frame.srcdoc = html
	document.body.appendChild(frame)
}

/**
 * The bars for one code, as an SVG string, or null if it cannot be drawn.
 *
 * Memoised because this is called once per row per render and the work is real —
 * 95 modules resolved into rects. The codes on a row never change under it, so a
 * plain Map is enough; it is cleared when the list reloads.
 *
 * Rendered a little shorter than the printed label: on screen this is a
 * recognition aid — "there are bars, and they look right" — not something a
 * scanner is going to be pointed at.
 */
const barCache = new Map()

function barsFor(code) {
	if (!code) return null
	if (!barCache.has(code)) barCache.set(code, ean13Svg(code, { moduleWidth: 0.3, height: 12 }))
	return barCache.get(code)
}

function escapeHtml(value) {
	return String(value ?? '').replace(
		/[&<>"']/g,
		(c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
	)
}

const toast = ref(null)
let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 3200)
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader
			title="Barcodes"
			subtitle="Generate scannable codes for stock that arrived without one"
		>
			<template #actions>
				<div class="w-[200px]">
					<FormControl v-model="search" type="text" placeholder="Search item…" />
				</div>
				<FormControl v-model="onlyMissing" type="checkbox" label="Only items without one" />
				<Button
					variant="subtle"
					:icon-left="LucideSend"
					:disabled="!rows.length"
					label="Share list"
					@click="shareList(rows, 'Item barcodes')"
				/>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" />

		<div
			class="flex shrink-0 flex-wrap items-center gap-2 border-y border-outline-gray-2 px-4 py-2"
			:class="selected.size ? 'bg-surface-amber-1' : 'bg-surface-gray-1'"
		>
			<Button
				variant="subtle"
				:label="allSelected ? 'Clear selection' : `Select all ${missing.length} without one`"
				:disabled="!missing.length"
				@click="toggleAll"
			/>
			<Button
				theme="gray"
				variant="solid"
				:icon-left="LucideBarcode"
				:loading="working"
				:disabled="!selected.size"
				:label="
					selected.size
						? `Generate ${selected.size} barcode${selected.size === 1 ? '' : 's'}`
						: 'Select items first'
				"
				@click="generate"
			/>
			<!-- Reprinting a lost label matters as much as printing a new one, so
			     this prints the selection when there is one. -->
			<Button
				v-if="lastRun?.created || printableSelected"
				variant="subtle"
				:icon-left="LucidePrinter"
				:label="
					printableSelected
						? `Print ${printableSelected} label${printableSelected === 1 ? '' : 's'}`
						: `Print ${lastRun.created} new label${lastRun.created === 1 ? '' : 's'}`
				"
				@click="printLabels"
			/>
			<p class="ml-auto text-p-xs text-ink-gray-5">
				Codes start with 2 — the range reserved for a shop's own items, so they can never
				clash with a supplier's.
			</p>
		</div>

		<DataTable
			:columns="COLUMNS"
			:rows="rows"
			row-key="item_code"
			:loading="loading"
			:actions="actionsFor"
			empty-text="Every item here already has a barcode."
		>
			<template #cell-_pick="{ row }">
				<!-- Rows that already have a code stay selectable: that is how a lost
				     label gets reprinted. Generating skips them server-side. -->
				<input
					type="checkbox"
					:checked="selected.has(row.item_code)"
					:aria-label="`Select ${row.item_name}`"
					@change="toggle(row.item_code)"
				/>
			</template>
			<template #cell-barcode="{ row }">
				<!-- The bars themselves, at the same scale they print at.
				     A column of digits could not answer the question this screen
				     exists for — whether the label will scan — because the digits
				     render identically whether the bars behind them are right,
				     wrong or absent. Anything this cannot draw falls back to the
				     number and says so, rather than showing a plausible-looking
				     pattern for a code in some other symbology. -->
				<div v-if="row.barcode" class="flex items-center gap-2">
					<span
						v-if="barsFor(row.barcode)"
						class="shrink-0 [&>svg]:h-[34px] [&>svg]:w-auto"
						v-html="barsFor(row.barcode)"
					/>
					<div class="min-w-0">
						<div class="tabular text-p-xs font-medium text-ink-gray-7">
							{{ row.barcode }}
						</div>
						<Badge
							v-if="!barsFor(row.barcode)"
							theme="orange"
							variant="subtle"
							label="Not EAN-13"
						/>
						<Badge
							v-else-if="row.barcode_count > 1"
							theme="gray"
							variant="subtle"
							:label="`+${row.barcode_count - 1} more`"
						/>
					</div>
				</div>
				<Badge v-else theme="orange" variant="subtle" label="None" />
			</template>
		</DataTable>

		<ShareSheet v-model="shareOpen" :payload="sharePayload" />

		<Transition
			enter-active-class="transition-all duration-200"
			leave-active-class="transition-all duration-200"
			enter-from-class="opacity-0 translate-y-2"
			leave-to-class="opacity-0"
		>
			<div
				v-if="toast"
				class="pointer-events-none pos-toast absolute bottom-5 left-1/2 -translate-x-1/2 rounded-lg px-4 py-2.5 text-p-sm font-medium text-ink-white shadow-lg"
				:class="toast.tone === 'bad' ? 'bg-surface-red-5' : 'bg-surface-green-3'"
			>
				{{ toast.message }}
			</div>
		</Transition>
	</div>
</template>
