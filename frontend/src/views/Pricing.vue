<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl, Badge, Spinner, Dialog } from 'frappe-ui'
import { fmtMoney } from '@/utils/format'
import {
	getPriceListOptions,
	getPrices,
	getPriceFilters,
	previewBulkChange,
	applyBulkChange,
} from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideCalculator from '~icons/lucide/calculator'
import LucideTriangleAlert from '~icons/lucide/triangle-alert'
import LucideUndo from '~icons/lucide/undo-2'
import LucidePencil from '~icons/lucide/pencil'

const ALL = '__all__'

const priceLists = ref([])
const priceList = ref(null)
const rows = ref([])
const filters = ref({ item_groups: [], brands: [] })
const itemGroup = ref(ALL)
const brand = ref(ALL)
const search = ref('')
const loading = ref(false)
const selected = ref(new Set())

const mode = ref('percent')
const value = ref('')
const rounding = ref('none')

const preview = ref(null)
const previewOpen = ref(false)
const applying = ref(false)
const toast = ref(null)

/**
 * The reviewed prices, editable.
 *
 * The bulk bar answers "put every one of these up 8%", which is the common case
 * but never the whole job — a supplier raises most of a brand and two lines by
 * something else, and one figure for all of them cannot say that. So the
 * preview is the working surface rather than a receipt: the arithmetic fills it
 * in, and anything that came out wrong is corrected in place before it is
 * written.
 *
 * Held separately from `preview.rows` so the server's answer stays intact —
 * "was" and "cost" have to keep meaning what they meant when the preview ran,
 * or the margin beside an edited price is measured against nothing.
 */
const draft = ref([])
/** True when the dialog was opened to type prices rather than to review a change. */
const manual = ref(false)

const MODES = [
	{ label: 'Change by %', value: 'percent' },
	{ label: 'Change by amount', value: 'amount' },
	{ label: 'Set price to', value: 'set' },
]
const ROUNDING = [
	{ label: 'No rounding', value: 'none' },
	{ label: 'Nearest whole', value: 'whole' },
	{ label: 'Nearest 10', value: 'ten' },
	{ label: 'End in 9', value: 'psych' },
]

onMounted(async () => {
	const [pl, f] = await Promise.all([
		getPriceListOptions().catch(() => ({ options: [], default: null })),
		getPriceFilters().catch(() => ({ item_groups: [], brands: [] })),
	])
	priceLists.value = pl.options || []
	priceList.value = pl.default || pl.options?.[0]?.value || null
	filters.value = f
	load()
})

let timer = null
watch([priceList, itemGroup, brand, search], () => {
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	if (!priceList.value) return
	loading.value = true
	try {
		const data = await getPrices({
			priceList: priceList.value,
			search: search.value,
			itemGroup: itemGroup.value === ALL ? null : itemGroup.value,
			brand: brand.value === ALL ? null : brand.value,
		})
		rows.value = data.rows || []
		// Selections refer to rows that may no longer be listed.
		selected.value = new Set()
	} catch (e) {
		notify(e.message || 'Could not load prices', 'bad')
		rows.value = []
	} finally {
		loading.value = false
	}
}

const groupOptions = computed(() => [
	{ label: 'All groups', value: ALL },
	...filters.value.item_groups.map((g) => ({ label: g, value: g })),
])
const brandOptions = computed(() => [
	{ label: 'All brands', value: ALL },
	...filters.value.brands.map((b) => ({ label: b, value: b })),
])

const allSelected = computed(() => rows.value.length > 0 && selected.value.size === rows.value.length)

function toggleAll() {
	selected.value = allSelected.value ? new Set() : new Set(rows.value.map((r) => r.item_code))
}

function toggle(code) {
	const s = new Set(selected.value)
	s.has(code) ? s.delete(code) : s.add(code)
	selected.value = s
}

/**
 * Why the preview cannot run yet, or null when it can.
 *
 * This used to be a bare `disabled` with a label that only ever mentioned the
 * selection, so an item selected but no value entered produced a button reading
 * "Preview on 3 items" that did nothing when clicked. The button now says what
 * is missing.
 *
 * The emptiness test is deliberately not `=== ''`: a cleared number input can
 * hand back null or undefined depending on the control, and any of those
 * getting through meant a change of zero was applied and reported as success.
 */
const blocker = computed(() => {
	if (!selected.value.size) return 'Select items first'
	const raw = value.value
	if (raw === '' || raw === null || raw === undefined) return 'Enter a value'
	if (Number.isNaN(Number(raw))) return 'Value must be a number'
	if (Number(raw) === 0 && mode.value !== 'set') return 'A change of zero does nothing'
	return null
})

async function openPreview() {
	if (blocker.value) return
	await openWith({ mode: mode.value, value: Number(value.value), rounding: rounding.value })
}

/**
 * Straight to the editable table, with nothing changed yet.
 *
 * A percent change of zero is exactly "the prices as they stand", so the same
 * endpoint fills the table — no second code path, and the cost and margin come
 * back resolved the same way they do for a bulk change.
 */
async function openManual() {
	if (!selected.value.size) return
	await openWith({ mode: 'percent', value: 0, rounding: 'none' }, true)
}

async function openWith({ mode: m, value: v, rounding: r }, isManual = false) {
	try {
		preview.value = await previewBulkChange({
			priceList: priceList.value,
			itemCodes: [...selected.value],
			mode: m,
			value: v,
			rounding: r,
		})
		manual.value = isManual
		draft.value = (preview.value.rows || []).map((row) => ({ ...row, new_price: row.new_price }))
		previewOpen.value = true
	} catch (e) {
		notify(e.message || 'Could not preview', 'bad')
	}
}

/**
 * One row's price, kept exactly as typed.
 *
 * Stored as the raw string rather than a number: coercing on every keystroke
 * rewrites the field under the cursor, so "12." becomes "12" and the decimal
 * can never be reached. The conversion happens once, in `priced`, where a
 * half-typed value is simply not yet valid.
 *
 * An empty field stays empty rather than becoming zero — a cleared input
 * mid-edit is not a decision to give the stock away.
 */
function setPrice(row, raw) {
	row.new_price = raw ?? ''
}

function resetPrice(row) {
	const original = (preview.value?.rows || []).find((r) => r.item_code === row.item_code)
	row.new_price = original ? original.new_price : row.old_price
}

/** Local, so a blank input reads as 0 rather than NaN in the arithmetic. */
const flt = (n) => Number(n || 0)

const priced = computed(() =>
	draft.value.map((r) => {
		const raw = String(r.new_price ?? '').trim()
		const next = raw === '' ? null : Number(raw)
		return {
			...r,
			next,
			delta: next === null ? 0 : next - flt(r.old_price),
			below_cost: next !== null && !!r.cost && next < flt(r.cost),
			invalid: next === null || Number.isNaN(next) || next < 0,
			changed: next !== null && !Number.isNaN(next) && next !== flt(r.old_price),
		}
	}),
)

const belowCostCount = computed(() => priced.value.filter((r) => r.below_cost).length)
const changedRows = computed(() => priced.value.filter((r) => r.changed && !r.invalid))
const invalidCount = computed(() => priced.value.filter((r) => r.invalid).length)

/** Why Apply cannot run, or null. Same reasoning as `blocker` — a dead button
 *  with no explanation is the thing this screen kept getting wrong. */
const applyBlocker = computed(() => {
	if (invalidCount.value) return `${invalidCount.value} price${invalidCount.value === 1 ? '' : 's'} need a number`
	if (!changedRows.value.length) return 'Nothing has changed'
	return null
})

async function apply() {
	if (applyBlocker.value) return
	applying.value = true
	try {
		// Only what actually differs. Sending the untouched rows too would have the
		// shop told "3 updated, 47 already at that price" after editing three
		// prices, which reads as though something went wrong.
		const res = await applyBulkChange({
			priceList: priceList.value,
			changes: changedRows.value.map((r) => ({
				item_code: r.item_code,
				new_price: r.next,
			})),
		})
		previewOpen.value = false
		await load()
		// "0 updated" on its own reads as a broken screen. Saying how many were
		// already at that price is the difference between "it did nothing" and
		// "there was nothing to do".
		const parts = []
		if (res.updated) parts.push(`${res.updated} updated`)
		if (res.created) parts.push(`${res.created} created`)
		if (res.unchanged) parts.push(`${res.unchanged} already at that price`)
		notify(parts.join(', ') || 'No prices needed changing', res.updated || res.created ? 'good' : 'bad')
	} catch (e) {
		notify(e.message || 'Could not apply', 'bad')
	} finally {
		applying.value = false
	}
}

let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2600)
}

function marginTone(pct) {
	if (pct === null || pct === undefined) return 'text-ink-gray-5'
	if (pct < 0) return 'text-ink-red-3 font-semibold'
	if (pct < 15) return 'text-ink-amber-3'
	return 'text-ink-green-3'
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader
			title="Price updates"
			:subtitle="`${rows.length} items · ${selected.size} selected`"
		>
			<template #actions>
				<div class="w-[180px]">
					<FormControl type="select" v-model="priceList" :options="priceLists" />
				</div>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<!-- Filters -->
		<div class="flex shrink-0 flex-wrap items-end gap-2 border-b border-outline-gray-2 bg-surface-white px-4 py-2">
			<div class="w-[170px]">
				<FormControl type="select" v-model="itemGroup" :options="groupOptions" label="Group" />
			</div>
			<div class="w-[170px]">
				<FormControl type="select" v-model="brand" :options="brandOptions" label="Brand" />
			</div>
			<div class="w-[200px]">
				<FormControl v-model="search" type="text" label="Search" placeholder="Item name…" />
			</div>
		</div>

		<!-- Bulk change bar. Only meaningful with a selection, so it says so. -->
		<div
			class="flex shrink-0 flex-wrap items-end gap-2 border-b border-outline-gray-2 px-4 py-2"
			:class="selected.size ? 'bg-surface-blue-1' : 'bg-surface-gray-1'"
		>
			<div class="w-[160px]">
				<FormControl type="select" v-model="mode" :options="MODES" label="Bulk change" />
			</div>
			<div class="w-[120px]">
				<FormControl v-model="value" type="number" label="Value" placeholder="0" />
			</div>
			<div class="w-[150px]">
				<FormControl type="select" v-model="rounding" :options="ROUNDING" label="Rounding" />
			</div>
			<!-- Black rather than blue: this is the one button on the bar that
			     changes prices, and the shop reads black as "this is the action". -->
			<Button
				theme="gray"
				variant="solid"
				class="!font-bold"
				:icon-left="LucideCalculator"
				:disabled="!!blocker"
				:label="blocker || `Preview on ${selected.size} item${selected.size === 1 ? '' : 's'}`"
				@click="openPreview"
			/>
			<!-- The way in when there is no single figure to apply: the same
			     editable table, opened with nothing changed. -->
			<Button
				variant="subtle"
				:icon-left="LucidePencil"
				:disabled="!selected.size"
				:label="selected.size ? `Type each price (${selected.size})` : 'Type each price'"
				@click="openManual"
			/>
		</div>

		<div class="min-h-0 flex-1 overflow-auto">
			<div v-if="loading" class="grid h-40 place-items-center"><Spinner class="h-5 w-5" /></div>
			<div v-else-if="!rows.length" class="grid h-40 place-items-center px-6 text-center">
				<p class="text-p-sm text-ink-gray-5">No items match these filters.</p>
			</div>

			<table v-else class="w-full border-collapse text-p-sm">
				<thead class="sticky top-0 z-10 bg-surface-gray-2">
					<tr>
						<th class="w-10 border-b border-outline-gray-2 px-3 py-2">
							<input type="checkbox" :checked="allSelected" @change="toggleAll" />
						</th>
						<th class="border-b border-outline-gray-2 px-3 py-2 text-left text-p-xs font-medium text-ink-gray-6">Item</th>
						<th class="border-b border-outline-gray-2 px-3 py-2 text-left text-p-xs font-medium text-ink-gray-6">Group</th>
						<th class="border-b border-outline-gray-2 px-3 py-2 text-right text-p-xs font-medium text-ink-gray-6">Cost</th>
						<th class="border-b border-outline-gray-2 px-3 py-2 text-right text-p-xs font-medium text-ink-gray-6">Price</th>
						<th class="border-b border-outline-gray-2 px-3 py-2 text-right text-p-xs font-medium text-ink-gray-6">Margin</th>
					</tr>
				</thead>
				<tbody>
					<!-- Banded like every other list in the app, with the selection
					     resolved here rather than left to stylesheet order — a selected
					     row must never be repainted by the stripe underneath it. -->
					<tr
						v-for="(row, i) in rows"
						:key="row.item_code"
						class="cursor-pointer transition-colors"
						:class="
							selected.has(row.item_code)
								? 'bg-surface-blue-1 hover:bg-surface-blue-2'
								: i % 2
									? 'bg-surface-gray-1 hover:bg-surface-gray-2'
									: 'bg-surface-white hover:bg-surface-gray-2'
						"
						@click="toggle(row.item_code)"
					>
						<td class="px-3 py-1.5" @click.stop>
							<input type="checkbox" :checked="selected.has(row.item_code)" @change="toggle(row.item_code)" />
						</td>
						<td class="px-3 py-1.5">
							<div class="truncate font-medium text-ink-gray-8">{{ row.item_name }}</div>
							<div class="text-p-xs text-ink-gray-5">{{ row.item_code }}</div>
						</td>
						<td class="px-3 py-1.5">
							<Badge v-if="row.brand" theme="gray" variant="subtle" :label="row.brand" />
							<span v-else class="text-p-xs text-ink-gray-5">{{ row.item_group }}</span>
						</td>
						<td class="tabular px-3 py-1.5 text-right text-ink-gray-6">
							{{ row.cost ? fmtMoney(row.cost) : '—' }}
						</td>
						<td class="tabular px-3 py-1.5 text-right font-medium text-ink-gray-9">
							{{ row.price === null ? 'no price' : fmtMoney(row.price) }}
						</td>
						<td class="tabular px-3 py-1.5 text-right" :class="marginTone(row.margin_pct)">
							{{ row.margin_pct === null ? '—' : row.margin_pct + '%' }}
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<!-- Two-step: a live price is hard to unpick once a cashier has sold at it.
		     The second step is editable, because one figure never fits every item —
		     the bulk change gets the table 90% right and the exceptions are typed
		     over in place rather than run as three more bulk changes. -->
		<Dialog
			v-model="previewOpen"
			:options="{ title: manual ? 'Set prices' : 'Review price changes', size: '3xl' }"
		>
			<template #body-content>
				<div
					v-if="belowCostCount"
					class="mb-3 flex items-start gap-2 rounded-lg bg-surface-red-2 px-3 py-2 text-p-sm"
				>
					<LucideTriangleAlert class="mt-0.5 h-4 w-4 shrink-0 text-ink-red-3" />
					<span class="text-ink-red-3">
						{{ belowCostCount }} item{{ belowCostCount === 1 ? '' : 's' }} would sell
						below cost. Those rows are highlighted.
					</span>
				</div>

				<p class="mb-2 text-p-xs text-ink-gray-5">
					Type over any price to change just that item. Untouched rows are left
					exactly as they are.
				</p>

				<div class="max-h-[50vh] overflow-auto">
					<table class="w-full border-collapse text-p-sm">
						<thead class="sticky top-0 z-10 bg-surface-gray-1">
							<tr>
								<th class="border-b border-outline-gray-2 px-2 py-1.5 text-left text-p-xs text-ink-gray-6">Item</th>
								<th class="border-b border-outline-gray-2 px-2 py-1.5 text-right text-p-xs text-ink-gray-6">Cost</th>
								<th class="border-b border-outline-gray-2 px-2 py-1.5 text-right text-p-xs text-ink-gray-6">Was</th>
								<th class="border-b border-outline-gray-2 px-2 py-1.5 text-right text-p-xs text-ink-gray-6">Now</th>
								<th class="border-b border-outline-gray-2 px-2 py-1.5 text-right text-p-xs text-ink-gray-6">Change</th>
								<th class="w-8 border-b border-outline-gray-2"></th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="(r, i) in priced"
								:key="r.item_code"
								class="border-b border-outline-gray-1"
								:class="r.below_cost ? 'bg-surface-red-1' : r.changed ? 'bg-surface-amber-1' : ''"
							>
								<td class="px-2 py-1 text-ink-gray-8">{{ r.item_name }}</td>
								<td class="tabular px-2 py-1 text-right text-ink-gray-6">{{ fmtMoney(r.cost) }}</td>
								<td class="tabular px-2 py-1 text-right text-ink-gray-6">{{ fmtMoney(r.old_price) }}</td>
								<td class="px-2 py-1 text-right">
									<input
										:value="draft[i].new_price"
										type="text"
										inputmode="decimal"
										class="tabular h-8 w-28 rounded-md border px-2 text-right font-semibold text-ink-gray-9 focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
										:class="
											r.invalid
												? 'border-outline-red-2 bg-surface-red-1'
												: 'border-outline-gray-2 bg-surface-white'
										"
										:aria-label="`Price for ${r.item_name}`"
										@input="setPrice(draft[i], $event.target.value)"
										@focus="$event.target.select()"
									/>
								</td>
								<td
									class="tabular px-2 py-1 text-right"
									:class="r.delta > 0 ? 'text-ink-green-3' : r.delta < 0 ? 'text-ink-red-3' : 'text-ink-gray-5'"
								>
									{{ r.delta > 0 ? '+' : '' }}{{ fmtMoney(r.delta) }}
								</td>
								<td class="px-1 py-1">
									<!-- Put one row back without closing and re-running the whole
									     preview, which would discard every other edit. -->
									<button
										v-if="r.changed"
										class="grid h-7 w-7 place-items-center rounded-md text-ink-gray-5 hover:bg-surface-gray-3 hover:text-ink-gray-8"
										:aria-label="`Undo ${r.item_name}`"
										@click="resetPrice(draft[i])"
									>
										<LucideUndo class="h-3.5 w-3.5" />
									</button>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</template>
			<template #actions>
				<Button
					theme="gray"
					variant="solid"
					class="w-full !font-bold"
					:loading="applying"
					:disabled="!!applyBlocker"
					:label="
						applyBlocker ||
						`Apply to ${changedRows.length} item${changedRows.length === 1 ? '' : 's'}`
					"
					@click="apply"
				/>
			</template>
		</Dialog>

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
