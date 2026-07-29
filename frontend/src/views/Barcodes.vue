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

	const win = window.open('', '_blank', 'noopener,width=900,height=700')
	if (!win) {
		notify('Allow pop-ups to print labels', 'bad')
		return
	}
	win.document.write(`<!doctype html><html><head><title>Barcode labels</title><style>
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
		   pattern that scanners read unreliably or not at all. */
		@media print {
			body { margin: 5mm; }
			.label { border-color: #999; }
			svg rect { fill: #000 !important; }
		}
		@page { margin: 8mm; }
	</style></head><body><div class="sheet">${labels}</div></body></html>`)
	win.document.close()
	win.focus()
	// Give the SVG a frame to lay out; printing immediately can capture an empty
	// document in some browsers.
	win.setTimeout(() => win.print(), 250)
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
				<span v-if="row.barcode" class="tabular font-medium text-ink-gray-8">
					{{ row.barcode }}
					<Badge
						v-if="row.barcode_count > 1"
						class="ml-1"
						theme="gray"
						variant="subtle"
						:label="`+${row.barcode_count - 1}`"
					/>
				</span>
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
